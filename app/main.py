"""HTTP surface.

This module is the seam the tests drive. Everything the user can do is
reachable from here; nothing below it is reached into directly by tests.
"""

from __future__ import annotations

import asyncio
import re
import time as _time
from contextlib import asynccontextmanager
from dataclasses import asdict
from pathlib import Path

import anthropic
from fastapi import Depends, FastAPI, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse

from app import auth, backup, budget, db, generation, identity, ingestion
from app import jobs, ledger, packaging, planning, progress, providers, social, study
from app import worker as worker_module


def create_app(
    database_url: str,
    data_dir: Path,
    anthropic_client: anthropic.Anthropic | None = None,
    provider=None,
    *,
    resume_backoff_seconds: float = jobs.MIN_RESUME_BACKOFF_SECONDS,
    drain_deadline_seconds: float = worker_module.DRAIN_DEADLINE_SECONDS,
    heartbeat_seconds: float = progress.HEARTBEAT_SECONDS,
    event_stream_seconds: float = progress.MAX_STREAM_SECONDS,
    per_job_token_ceiling: int = budget.PER_JOB_TOKEN_CEILING,
    daily_budget_usd: float = budget.DAILY_BUDGET_USD,
    global_daily_budget_usd: float = budget.GLOBAL_DAILY_BUDGET_USD,
    # Who is allowed in. Injected rather than built from the environment here,
    # so tests exercise the real verification against their own signing key.
    verifier: identity.Verifier | None = None,
    # None means no off-platform copies. Tests pass one explicitly rather
    # than reaching for the environment.
    backup_destination: backup.Destination | None = None,
) -> FastAPI:
    data_dir = Path(data_dir)
    backup_destination = backup_destination or backup.destination_from_env()
    verifier = verifier or identity.from_env()
    # One vendor, chosen by configuration. Everything vendor-specific lives behind
    # this object; nothing below it knows which one is serving the job.
    provider = provider or providers.build(client=anthropic_client)
    refusals = providers.check_usable(provider)
    if refusals:
        raise ValueError(
            f"{provider.name}/{provider.model} cannot serve this workload: "
            + "; ".join(refusals)
        )
    worker = worker_module.Worker(database_url, provider, drain_deadline_seconds=drain_deadline_seconds)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # Idempotent, and not how production gets its schema -- Fly runs
        # `alembic upgrade head` as a release command, once per deploy, before
        # any machine starts. This is what makes a local run and a test work
        # without a migration step, and a test asserts the two agree.
        db.initialise(database_url)
        data_dir.mkdir(parents=True, exist_ok=True)
        conn = db.connect(database_url)
        try:
            # Whatever the last machine was doing when it went, it is not doing
            # it now.
            jobs.recover_orphans(conn, worker.id)
        finally:
            conn.close()

        # Nightly off-platform copies, if a bucket is configured. Absent
        # configuration is a supported state: local development and a first
        # deploy both run without one, and a task that raises every night is a
        # task whose alarms get muted.
        backups = None
        if backup_destination is not None:
            backups = asyncio.create_task(
                backup.nightly(database_url, data_dir / "tmp", backup_destination)
            )

        yield
        if backups is not None:
            backups.cancel()
        # The platform turns SIGTERM into a graceful shutdown, which arrives
        # here. Everything the drain does is bounded, because the kill that
        # follows is not negotiable.
        await worker.drain()

    app = FastAPI(title="ai-anki", lifespan=lifespan)
    app.add_middleware(auth.Guard, database_url=database_url, verifier=verifier)

    async def get_conn():
        # Async so the connection is created and used on the same thread. A sync
        # dependency would be resolved in a threadpool and then handed to the
        # event loop, which SQLite refuses. Statements here are sub-millisecond;
        # long-running work belongs in the worker, not in a request.
        conn = db.connect(database_url)
        try:
            yield conn
        finally:
            conn.close()

    def guard_spend(conn, account_id):
        """Refuse work we already know we should not pay for."""
        try:
            budget.check(
                conn,
                account_id,
                daily_budget_usd=daily_budget_usd,
                global_daily_budget_usd=global_daily_budget_usd,
            )
        except budget.GenerationDisabled as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except budget.BudgetExceeded as exc:
            raise HTTPException(status_code=429, detail=str(exc)) from exc

    def guard_size(conn, job_id: str, request: dict) -> int:
        measured = ingestion.count_input_tokens(provider, request)
        jobs.record_input_tokens(conn, job_id, measured)
        if measured > per_job_token_ceiling:
            too_large = ingestion.TooLarge(measured)
            jobs.fail_job(conn, job_id, str(too_large))
            raise HTTPException(status_code=413, detail=str(too_large))
        return measured

    async def account_of(request: Request) -> identity.Account:
        """Whose request this is, as the guard established it."""
        return request.state.account

    def owned_job(conn, job_id: str, account_id: str) -> jobs.Job:
        """Load a job, but only for the person whose job it is.

        Somebody else's job is answered as missing rather than as forbidden:
        which job ids exist is not something a signed-in stranger should be
        able to enumerate.
        """
        job = jobs.load_job(conn, job_id)
        if job is None or str(job.account_id) != str(account_id):
            raise HTTPException(status_code=404, detail="job not found")
        return job

    @app.post("/api/jobs", status_code=201)
    async def create_job(
        file: UploadFile,
        deck_id: str | None = Form(default=None),
        conn=Depends(get_conn),
        account: identity.Account = Depends(account_of),
    ):
        """Start a Job. Naming a Deck continues it; naming none begins one."""
        if deck_id and not ledger.deck_exists(conn, deck_id, account.id):
            raise HTTPException(status_code=404, detail="no such deck")
        content = await file.read()
        job_id = jobs.create_job(
            conn,
            data_dir,
            file.filename or "upload",
            content,
            account_id=account.id,
            deck_id=deck_id,
        )
        return JSONResponse({"job_id": job_id}, status_code=201)

    def plan_request_for(conn, job_id: str, job=None):
        """The pass-1 request for a job, including what its deck already holds.

        Shared by the three places that build it — the call itself, the size
        guard, and the estimate — because a guard that measures a different
        request from the one sent is not a guard.
        """
        job = job or jobs.load_job(conn, job_id)
        existing = ledger.deck_topics(conn, job.deck_id) if job and job.deck_id else []
        return planning.build_plan_request(
            jobs.documents_for(conn, job_id, provider), provider, existing
        )

    @app.get("/api/jobs")
    async def list_jobs(conn=Depends(get_conn), account: identity.Account = Depends(account_of)):
        """Everything this person has started. The way back to a run."""
        return {"jobs": jobs.list_jobs(conn, account.id)}

    @app.get("/api/decks")
    async def list_decks(conn=Depends(get_conn), account: identity.Account = Depends(account_of)):
        return {"decks": ledger.list_decks(conn, account.id)}

    @app.patch("/api/decks/{deck_id}")
    async def rename_deck(
        deck_id: str,
        body: dict,
        conn=Depends(get_conn),
        account: identity.Account = Depends(account_of),
    ):
        if not ledger.deck_exists(conn, deck_id, account.id):
            raise HTTPException(status_code=404, detail="no such deck")
        try:
            with db.transaction(conn):
                ledger.rename_deck(conn, deck_id, account.id, str(body.get("name", "")))
        except ledger.DeckNameRejected as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return {"deck_id": deck_id}

    @app.get("/api/jobs/{job_id}")
    async def read_job(
        job_id: str, conn=Depends(get_conn), account: identity.Account = Depends(account_of)
    ):
        job = owned_job(conn, job_id, account.id)
        return {
            "job_id": job.id,
            "account_id": job.account_id,
            "deck_id": job.deck_id,
            "state": job.state,
            "error": job.error,
            "plan": job.plan,
            "attempt_count": job.attempt_count,
            "source_filename": job.source_filenames[0] if job.source_filenames else None,
            "source_filenames": job.source_filenames,
        }

    @app.get("/api/jobs/{job_id}/topics")
    async def read_topics(job_id: str, conn=Depends(get_conn)):
        if jobs.load_job(conn, job_id) is None:
            raise HTTPException(status_code=404, detail="job not found")
        return {
            "topics": [
                {
                    "topic_id": topic.topic_id,
                    "path": topic.topic["path"],
                    "status": topic.status,
                    "attempt_count": topic.attempt_count,
                    "error": topic.error,
                    "card_count": topic.card_count,
                }
                for topic in jobs.load_topics(conn, job_id)
            ]
        }

    @app.get("/api/jobs/{job_id}/events")
    async def watch_job(job_id: str, request: Request, conn=Depends(get_conn)):
        """Progress for one job, as a stream a browser can be dropped from.

        What is streamed is the job's persisted event log and nothing else, so
        this says the same thing whether the worker is in this process, in a
        process that has since been killed, or was never running at all.
        """
        if jobs.load_job(conn, job_id) is None:
            raise HTTPException(status_code=404, detail="job not found")
        return StreamingResponse(
            progress.stream(
                database_url,
                job_id,
                after_id=progress.last_event_id(request.headers.get("last-event-id")),
                is_disconnected=request.is_disconnected,
                heartbeat_seconds=heartbeat_seconds,
                max_seconds=event_stream_seconds,
            ),
            media_type="text/event-stream",
            headers=progress.STREAM_HEADERS,
        )

    @app.post("/api/jobs/{job_id}/plan")
    async def plan_job(job_id: str, conn=Depends(get_conn)):
        job = jobs.load_job(conn, job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="job not found")
        guard_spend(conn, job.account_id)
        _claim(conn, job_id, jobs.PLANNING)

        try:
            request = plan_request_for(conn, job_id, job)
            # Measured before anything is generated, over the request that is
            # about to be sent rather than an approximation of it. A job that is
            # too large must cost nothing beyond this count.
            guard_size(conn, job_id, request)

            reply = provider.send(request)
            jobs.record_usage(conn, job_id, "plan", reply.usage, model=provider.model)
            plan = reply.data
        except providers.Unusable as exc:
            jobs.fail_job(conn, job_id, str(exc))
            raise HTTPException(status_code=422, detail=str(exc)) from exc

        jobs.save_plan(conn, job_id, plan)
        return {"job_id": job_id, "plan": plan}

    @app.get("/api/decks/{deck_id}/ledger")
    async def read_ledger(
        deck_id: str, conn=Depends(get_conn), account: identity.Account = Depends(account_of)
    ):
        """What this Deck knows about its own cards. Never purged."""
        if not ledger.deck_exists(conn, deck_id, account.id):
            raise HTTPException(status_code=404, detail="no such deck")
        return {"deck_id": deck_id, "cards": ledger.entries(conn, deck_id)}

    @app.get("/api/spend")
    async def read_spend(conn=Depends(get_conn)):
        """Who has spent what. The owner's view."""
        return {
            "people": budget.spend_by_person(conn),
            "last_24h_usd": budget.spend_since(conn, _time.time() - 86400),
            "global_daily_budget_usd": global_daily_budget_usd,
        }

    @app.post("/api/maintenance/purge")
    async def purge(body: dict, conn=Depends(get_conn)):
        """Drop old uploads and packages. The ledger is never touched.

        Retention is split by data class deliberately: sources are the bulk and
        the actual disk pressure, while the ledger is a few hundred bytes a card
        and losing it would duplicate every user's deck on their next run.
        """
        removed = jobs.purge_sources(conn, data_dir, older_than_days=body.get("older_than_days", 30))
        return {"sources_removed": removed}

    @app.post("/api/maintenance/backup")
    async def take_backup(conn=Depends(get_conn)):
        """Take a consistent copy while the application keeps running.

        Off the platform when a bucket is configured. Onto local disk otherwise,
        so the endpoint still does something useful before object storage is set
        up — and says plainly that a copy sitting next to the machine that made
        it is not a backup.

        The managed database takes its own point-in-time backups. This one is
        vendor independence rather than redundancy: it is the copy that can
        leave.
        """
        if backup_destination is not None:
            result = await asyncio.to_thread(
                backup.run, database_url, data_dir / "tmp", backup_destination
            )
            return {"destination": backup_destination.bucket, **result}
        local = data_dir / "backup.dump"
        await asyncio.to_thread(backup.snapshot, database_url, local)
        return {
            "path": str(local),
            "bytes": local.stat().st_size,
            "warning": (
                "written to local disk, not off-platform; set "
                "AI_ANKI_BACKUP_BUCKET for a copy that survives losing this machine"
            ),
        }

    @app.get("/api/jobs/{job_id}/usage")
    async def read_usage(
        job_id: str, conn=Depends(get_conn), account: identity.Account = Depends(account_of)
    ):
        """What this job actually cost, derived from what the API reported."""
        owned_job(conn, job_id, account.id)
        calls = jobs.load_usage(conn, job_id)
        priced = [{**call, "cost_usd": ingestion.cost_of(call, provider.prices)} for call in calls]
        return {
            "job_id": job_id,
            "calls": priced,
            "total_cost_usd": round(sum(call["cost_usd"] for call in priced), 6),
        }

    @app.get("/api/jobs/{job_id}/estimate")
    async def read_estimate(
        job_id: str, conn=Depends(get_conn), account: identity.Account = Depends(account_of)
    ):
        """What this job measures and what it is expected to cost.

        Reported in tokens and money. Page count is deliberately absent: it is
        not the limit, and showing it as one would be a promise the pipeline
        cannot keep.
        """
        job = owned_job(conn, job_id, account.id)
        input_tokens = ingestion.count_input_tokens(
            provider, plan_request_for(conn, job_id, job)
        )
        jobs.record_input_tokens(conn, job_id, input_tokens)

        # Once a plan exists, price the plan the user is actually looking at.
        # The fixed assumption is only for the window before pass 1 has run —
        # and a plan that came back with three times as many topics as assumed
        # would otherwise quote half the real cost at the exact moment the user
        # is deciding whether to spend it.
        topics = len((job.plan or {}).get("topics") or []) or ingestion.ASSUMED_TOPICS
        return {
            "job_id": job_id,
            "input_tokens": input_tokens,
            "topics": topics,
            "token_ceiling": ingestion.TOKEN_CEILING,
            "within_limit": input_tokens <= ingestion.TOKEN_CEILING,
            "estimated_cost_usd": ingestion.estimate_cost(input_tokens, topics=topics),
        }

    @app.put("/api/jobs/{job_id}/plan")
    async def edit_plan(
        job_id: str, body: dict, conn=Depends(get_conn), account: identity.Account = Depends(account_of)
    ):
        """Replace the plan with the user's edited version.

        Validated here, not in the browser: the UI is a convenience, not a
        trusted client, and the response schema could not express these bounds
        in the first place.
        """
        owned_job(conn, job_id, account.id)
        try:
            plan = planning.validate(body)
        except planning.InvalidPlan as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        jobs.replace_plan(conn, job_id, plan)
        return {"job_id": job_id, "plan": plan}

    @app.patch("/api/cards/{card_uuid}")
    async def edit_card(card_uuid: str, body: dict, conn=Depends(get_conn)):
        if not jobs.update_card(conn, card_uuid, body.get("front", ""), body.get("back", "")):
            raise HTTPException(status_code=404, detail="no such card")
        return {"card_uuid": card_uuid}

    @app.delete("/api/cards/{card_uuid}")
    async def reject_card(card_uuid: str, conn=Depends(get_conn)):
        if not jobs.delete_card(conn, card_uuid):
            raise HTTPException(status_code=404, detail="no such card")
        return {"card_uuid": card_uuid, "rejected": True}

    @app.delete("/api/jobs/{job_id}/topics/{topic_id}/cards")
    async def reject_topic(
        job_id: str, topic_id: str, conn=Depends(get_conn), account: identity.Account = Depends(account_of)
    ):
        owned_job(conn, job_id, account.id)
        return {"rejected": jobs.delete_topic_cards(conn, job_id, topic_id)}

    @app.post("/api/cards/{card_uuid}/reroll")
    async def reroll_card(card_uuid: str, conn=Depends(get_conn)):
        """Ask again for one card, not the whole topic."""
        existing = jobs.find_card(conn, card_uuid)
        if existing is None:
            raise HTTPException(status_code=404, detail="no such card")
        job = jobs.load_job(conn, existing["job_id"])
        guard_spend(conn, job.account_id if job else None)

        topic = jobs.topic_of(conn, existing["job_id"], existing["topic_id"])
        documents = jobs.documents_for(conn, existing["job_id"], provider)
        request = generation.build_cards_request(documents, {**topic, "proposed_card_count": 1}, provider)
        request["messages"][0]["content"][-1]["text"] += (
            "\n\nWrite ONE replacement for this card, asking the same thing a different "
            f"way:\n{existing['front']}\n"
        )
        try:
            reply = provider.send(request)
        except providers.Unusable as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

        jobs.record_usage(
            conn, existing["job_id"], "reroll", reply.usage,
            topic_id=existing["topic_id"], model=provider.model,
        )
        replacement = (reply.data.get("cards") or [{}])[0]
        jobs.update_card(
            conn,
            card_uuid,
            replacement.get("front", existing["front"]),
            replacement.get("back", existing["back"]),
        )
        return {"card_uuid": card_uuid}

    @app.get("/api/jobs/{job_id}/download-info")
    async def download_info(
        job_id: str, conn=Depends(get_conn), account: identity.Account = Depends(account_of)
    ):
        """What to tell the user at the moment they import."""
        owned_job(conn, job_id, account.id)
        return {
            "anki_search": f"tag:aianki::job::{job_id}",
            "import_advice": (
                "Anki's import defaults are already correct — click Import and leave "
                "the settings alone. Changing 'Update notes' breaks in-place updates."
            ),
            "duplicate_advice": (
                "We can only see inside this job. After importing, run "
                "Notes > Find Duplicates in Anki to catch overlap with cards you "
                "already had."
            ),
            "undo_advice": (
                "If this batch turns out badly, search the tag above in the Browse "
                "screen and delete the notes it finds."
            ),
        }

    @app.post("/api/jobs/{job_id}/generate")
    async def generate_cards(job_id: str, conn=Depends(get_conn)):
        job = jobs.load_job(conn, job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="job not found")
        if job.plan is None:
            raise HTTPException(status_code=409, detail="job has no approved plan yet")
        guard_spend(conn, job.account_id)
        # Re-checked here, not only at admission: a plan multiplies the work and
        # the sources may have grown between the two passes.
        guard_size(
            conn,
            job_id,
            plan_request_for(conn, job_id, job),
        )
        if worker.draining:
            # Claiming an attempt we cannot run would spend one of the three
            # this job is allowed.
            raise HTTPException(status_code=503, detail="the machine is shutting down")
        _claim(conn, job_id, jobs.GENERATING)

        try:
            state = await worker.generate(job_id)
        except worker_module.WorkerDraining as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        return {
            "job_id": job_id,
            "state": state,
            "card_count": len(jobs.load_cards(conn, job_id)),
        }

    @app.post("/api/jobs/{job_id}/clear")
    async def clear_job(job_id: str, conn=Depends(get_conn)):
        """The manual intervention a dead job requires before it runs again."""
        if jobs.load_job(conn, job_id) is None:
            raise HTTPException(status_code=404, detail="job not found")
        try:
            jobs.clear_dead_job(conn, job_id)
        except jobs.IllegalTransition as exc:
            raise HTTPException(
                status_code=409, detail=f"only a dead job can be cleared: {exc}"
            ) from exc
        return {"job_id": job_id, "state": jobs.load_job(conn, job_id).state}

    def _claim(conn, job_id: str, state: str) -> None:
        """Take ownership of a job for a run that is about to cost money."""
        try:
            jobs.begin_attempt(
                conn,
                job_id,
                state,
                worker_id=worker.id,
                backoff_seconds=resume_backoff_seconds,
            )
        except jobs.IllegalTransition as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except jobs.ResumeRefused as exc:
            if exc.retry_after is None:
                raise HTTPException(status_code=409, detail=str(exc)) from exc
            raise HTTPException(
                status_code=429,
                detail=str(exc),
                headers={"retry-after": str(int(exc.retry_after) + 1)},
            ) from exc

    # --- studying --------------------------------------------------------

    def _at(value: str | None):
        """A moment named by the caller, so tests and clients can ask about a
        future the server has not reached yet."""
        if not value:
            return None
        from datetime import datetime, timezone

        # A `+` in a query value decodes to a space, which is what form
        # encoding says it means -- so an ISO timestamp sent without escaping
        # arrives as "...T10:00:00 00:00". Repairing it beats a 500 for a
        # mistake every client makes once.
        repaired = re.sub(r" (\d{2}:\d{2})$", r"+\1", value)
        try:
            moment = datetime.fromisoformat(repaired)
        except ValueError as exc:
            raise HTTPException(
                status_code=422, detail=f"'{value}' is not a time"
            ) from exc
        return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)

    def owned_deck(conn, deck_id: str, account_id: str) -> str:
        if not ledger.deck_exists(conn, deck_id, account_id):
            raise HTTPException(status_code=404, detail="no such deck")
        return deck_id

    @app.post("/api/decks/{deck_id}/study")
    async def start_studying(
        deck_id: str,
        conn=Depends(get_conn),
        account: identity.Account = Depends(account_of),
    ):
        """Make a deck's cards studiable. Safe to call again as it grows."""
        owned_deck(conn, deck_id, account.id)
        with db.transaction(conn):
            added = study.enrol(conn, account.id, deck_id)
        return {"deck_id": deck_id, "added": added}

    @app.get("/api/decks/{deck_id}/due")
    async def read_due(
        deck_id: str,
        at: str | None = None,
        conn=Depends(get_conn),
        account: identity.Account = Depends(account_of),
    ):
        owned_deck(conn, deck_id, account.id)
        return {"cards": study.due_cards(conn, account.id, deck_id, _at(at))}

    @app.get("/api/decks/{deck_id}/cards")
    async def read_deck_cards(
        deck_id: str,
        conn=Depends(get_conn),
        account: identity.Account = Depends(account_of),
    ):
        owned_deck(conn, deck_id, account.id)
        return {"cards": study.deck_cards(conn, account.id, deck_id)}

    @app.get("/api/decks/{deck_id}/mastery")
    async def read_mastery(
        deck_id: str,
        at: str | None = None,
        conn=Depends(get_conn),
        account: identity.Account = Depends(account_of),
    ):
        owned_deck(conn, deck_id, account.id)
        return study.mastery(conn, account.id, deck_id, _at(at))

    @app.post("/api/reviews")
    async def record_reviews(
        body: dict,
        conn=Depends(get_conn),
        account: identity.Account = Depends(account_of),
    ):
        """Append answers. Idempotent, in batches, and safe to retry.

        A whole batch is one transaction: a client that pushed twenty reviews
        and got a network error should find either all of them or none, not a
        prefix it has to work out the length of.
        """
        reviews = list(body.get("reviews") or [])
        for review in reviews:
            if not study.studiable(conn, account.id, review.get("card_uuid")):
                raise HTTPException(status_code=404, detail="no such card to review")
        try:
            with db.transaction(conn):
                accepted = study.record(conn, account.id, reviews)
        except study.UnknownRating as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return {"accepted": accepted, "submitted": len(reviews)}

    @app.get("/api/cards/{card_uuid}/reviews")
    async def read_card_history(
        card_uuid: str,
        conn=Depends(get_conn),
        account: identity.Account = Depends(account_of),
    ):
        if not study.studiable(conn, account.id, card_uuid):
            raise HTTPException(status_code=404, detail="no such card")
        return {"card_uuid": card_uuid, "reviews": study.history(conn, account.id, card_uuid)}

    # --- friends, and competing with them --------------------------------

    @app.get("/api/me")
    async def read_me(
        conn=Depends(get_conn), account: identity.Account = Depends(account_of)
    ):
        with db.transaction(conn):
            code = social.friend_code(conn, account.id)
        return {
            "account_id": account.id,
            "display_name": account.display_name,
            "email": account.email,
            "is_admin": account.is_admin,
            "friend_code": code,
        }

    @app.get("/api/friends")
    async def read_friends(
        conn=Depends(get_conn), account: identity.Account = Depends(account_of)
    ):
        return social.listing(conn, account.id)

    @app.post("/api/friends")
    async def add_friend(
        body: dict,
        conn=Depends(get_conn),
        account: identity.Account = Depends(account_of),
    ):
        """Ask by the code somebody gave you."""
        try:
            with db.transaction(conn):
                other = social.request(conn, account.id, str(body.get("code", "")))
        except social.NotFriendable as exc:
            # "No such code" is a 404; "that code is yours" is a 422. The
            # difference is real: one is a typo, the other is a misunderstanding.
            status = 404 if "no such code" in str(exc) else 422
            raise HTTPException(status_code=status, detail=str(exc)) from exc
        return {"account_id": other, "state": social.PENDING}

    @app.post("/api/friends/{other}/accept")
    async def accept_friend(
        other: str,
        conn=Depends(get_conn),
        account: identity.Account = Depends(account_of),
    ):
        with db.transaction(conn):
            done = social.accept(conn, account.id, other)
        if not done:
            raise HTTPException(status_code=404, detail="no request from that person")
        return {"account_id": other, "state": social.ACCEPTED}

    @app.delete("/api/friends/{other}")
    async def remove_friend(
        other: str,
        conn=Depends(get_conn),
        account: identity.Account = Depends(account_of),
    ):
        with db.transaction(conn):
            social.remove(conn, account.id, other)
        return {"account_id": other, "state": "none"}

    @app.get("/api/leaderboard")
    async def read_leaderboard(
        days: int = social.DEFAULT_WINDOW_DAYS,
        at: str | None = None,
        conn=Depends(get_conn),
        account: identity.Account = Depends(account_of),
    ):
        return social.leaderboard(conn, account.id, days=max(1, days), at=_at(at))

    @app.get("/api/decks/{deck_id}/compare")
    async def compare_deck(
        deck_id: str,
        conn=Depends(get_conn),
        account: identity.Account = Depends(account_of),
    ):
        owned_deck(conn, deck_id, account.id)
        return social.compare(conn, account.id, deck_id)

    @app.get("/api/me/activity")
    async def read_activity(
        conn=Depends(get_conn), account: identity.Account = Depends(account_of)
    ):
        return study.activity(conn, account.id)

    @app.get("/api/jobs/{job_id}/lessons")
    async def read_lessons(
        job_id: str, conn=Depends(get_conn), account: identity.Account = Depends(account_of)
    ):
        """Everything this job taught, in the order the plan put its topics."""
        owned_job(conn, job_id, account.id)
        return {"job_id": job_id, "lessons": jobs.load_lessons(conn, job_id)}

    @app.get("/api/jobs/{job_id}/topics/{topic_id}/lesson")
    async def read_lesson(
        job_id: str,
        topic_id: str,
        conn=Depends(get_conn),
        account: identity.Account = Depends(account_of),
    ):
        owned_job(conn, job_id, account.id)
        lesson = jobs.load_lesson(conn, job_id, topic_id)
        if lesson is None:
            raise HTTPException(status_code=404, detail="this topic has not been taught yet")
        return lesson

    @app.get("/api/jobs/{job_id}/cards")
    async def read_cards(job_id: str, conn=Depends(get_conn)):
        if jobs.load_job(conn, job_id) is None:
            raise HTTPException(status_code=404, detail="job not found")
        cards = jobs.load_cards(conn, job_id)
        return {
            "cards": [
                {
                    **asdict(card),
                    "tags": card.tags,
                    "rendered_front": planning.render_cloze(card.front)
                    if card.note_type == "cloze"
                    else card.front,
                }
                for card in cards
            ],
            "total": len(cards),
            # How far through the read is, so a review of 164 cards can be put
            # down and picked up rather than restarted.
            "reviewed_count": sum(1 for card in cards if card.reviewed),
        }

    @app.post("/api/jobs/{job_id}/cards/reject")
    async def reject_cards(
        job_id: str,
        body: dict,
        conn=Depends(get_conn),
        account: identity.Account = Depends(account_of),
    ):
        """Drop a selection in one call rather than one round trip per card."""
        owned_job(conn, job_id, account.id)
        with db.transaction(conn):
            dropped = jobs.reject_cards(conn, job_id, list(body.get("card_uuids") or []))
        return {"job_id": job_id, "rejected": dropped}

    @app.post("/api/jobs/{job_id}/cards/accept")
    async def accept_cards(
        job_id: str,
        body: dict,
        conn=Depends(get_conn),
        account: identity.Account = Depends(account_of),
    ):
        """Mark a selection read. Accepting is what makes progress visible."""
        owned_job(conn, job_id, account.id)
        with db.transaction(conn):
            marked = jobs.accept_cards(conn, job_id, list(body.get("card_uuids") or []))
        return {"job_id": job_id, "accepted": marked}

    @app.get("/api/jobs/{job_id}/diff")
    async def read_diff(
        job_id: str, conn=Depends(get_conn), account: identity.Account = Depends(account_of)
    ):
        """What downloading now would do to the user's collection."""
        job = owned_job(conn, job_id, account.id)
        if not job.deck_id:
            raise HTTPException(status_code=409, detail="job has no deck")
        split = ledger.classify(conn, job.deck_id, job_id)
        return {
            "job_id": job_id,
            "counts": {
                "update": len(split["updates"]),
                "add": len(split["additions"]),
                "unchanged": len(split["unchanged"]),
            },
            "updates": split["updates"],
            "warning": ledger.TAG_WARNING,
        }

    @app.get("/api/jobs/{job_id}/deck.apkg")
    async def download_deck(
        job_id: str,
        update: bool = False,
        skip: list[str] = Query(default=[]),
        conn=Depends(get_conn),
    ):
        job = jobs.load_job(conn, job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="job not found")
        cards = jobs.load_cards(conn, job_id)
        if not cards:
            raise HTTPException(status_code=409, detail="job has no cards to package")

        deck_id = job.deck_id
        if not deck_id:
            outgoing, updating, unchanged = cards, [], []
        else:
            split = ledger.classify(conn, deck_id, job_id)
            unchanged = split["unchanged"]
            skipped = {value for value in skip if value}
            # Updating is opt-in and skips are honoured by omission. An omitted
            # note is one Anki never sees, so the user's own edits, hand tags,
            # leech state and scheduling all survive untouched — no merge logic
            # has to exist for that to be true.
            updating = (
                [u["card_uuid"] for u in split["updates"] if u["card_uuid"] not in skipped]
                if update
                else []
            )
            included = set(split["additions"]) | set(updating)
            outgoing = [card for card in cards if card.card_uuid in included]

        if not outgoing:
            raise HTTPException(
                status_code=409, detail="nothing new to download for this deck"
            )

        stamp = ledger.next_export_timestamp(conn, deck_id) if deck_id else None
        package = packaging.build_package(outgoing, deck_name="AI Anki", timestamp=stamp)
        if deck_id:
            ledger.mark_exported(conn, deck_id, outgoing, stamp)

        return Response(
            content=package,
            media_type="application/octet-stream",
            headers={
                "content-disposition": f'attachment; filename="{job_id[:8]}.apkg"',
                "x-notes-added": str(len(outgoing) - len(updating)),
                "x-notes-updated": str(len(updating)),
                "x-notes-omitted-unchanged": str(len(unchanged)),
                "x-export-timestamp": str(stamp or 0),
            },
        )

    # The built single-page app, served by the same process. Mounted last so it
    # never shadows an API route, and outside the guard so the sign-in screen is
    # reachable by someone who does not have a session yet.
    frontend = Path(__file__).resolve().parent.parent / "frontend" / "dist"
    if frontend.is_dir():

        @app.get("/{path:path}", include_in_schema=False)
        async def serve_frontend(path: str):
            candidate = frontend / path
            if path and candidate.is_file():
                return FileResponse(candidate)
            # Any other path is a client-side route, so the shell is returned and
            # the app works out what to show — including a job link opened cold.
            return FileResponse(frontend / "index.html")

    return app
