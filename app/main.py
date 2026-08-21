"""HTTP surface.

This module is the seam the tests drive. Everything the user can do is
reachable from here; nothing below it is reached into directly by tests.
"""

from __future__ import annotations

import asyncio
import os
import time as _time
from contextlib import asynccontextmanager
from dataclasses import asdict
from pathlib import Path

import anthropic
from fastapi import Depends, FastAPI, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from pydantic import BaseModel

from app import auth
from app import budget, db, generation, ingestion, jobs, ledger, packaging, planning, progress, providers
from app import worker as worker_module


class InviteRequest(BaseModel):
    person: str


class SessionRequest(BaseModel):
    token: str


def create_app(
    db_path: Path,
    data_dir: Path,
    anthropic_client: anthropic.Anthropic | None = None,
    provider=None,
    *,
    resume_backoff_seconds: float = jobs.MIN_RESUME_BACKOFF_SECONDS,
    drain_deadline_seconds: float = worker_module.DRAIN_DEADLINE_SECONDS,
    heartbeat_seconds: float = progress.HEARTBEAT_SECONDS,
    event_stream_seconds: float = progress.MAX_STREAM_SECONDS,
    owner_token: str | None = None,
    session_ttl_seconds: float = auth.SESSION_TTL_SECONDS,
    per_job_token_ceiling: int = budget.PER_JOB_TOKEN_CEILING,
    daily_budget_usd: float = budget.DAILY_BUDGET_USD,
    global_daily_budget_usd: float = budget.GLOBAL_DAILY_BUDGET_USD,
    login_delay_seconds: float = auth.FAILED_LOGIN_DELAY_SECONDS,
    lockout_seconds: float = auth.LOCKOUT_SECONDS,
) -> FastAPI:
    db_path = Path(db_path)
    data_dir = Path(data_dir)
    # A runtime secret, never baked in. Unset means nobody is the owner, which
    # shuts minting rather than opening it.
    owner_token = owner_token or os.environ.get("AI_ANKI_OWNER_TOKEN")
    # One vendor, chosen by configuration. Everything vendor-specific lives behind
    # this object; nothing below it knows which one is serving the job.
    provider = provider or providers.build(client=anthropic_client)
    refusals = providers.check_usable(provider)
    if refusals:
        raise ValueError(
            f"{provider.name}/{provider.model} cannot serve this workload: "
            + "; ".join(refusals)
        )
    worker = worker_module.Worker(db_path, provider, drain_deadline_seconds=drain_deadline_seconds)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        db.initialise(db_path)
        data_dir.mkdir(parents=True, exist_ok=True)
        conn = db.connect(db_path)
        try:
            # Whatever the last machine was doing when it went, it is not doing
            # it now.
            jobs.recover_orphans(conn, worker.id)
        finally:
            conn.close()
        yield
        # The platform turns SIGTERM into a graceful shutdown, which arrives
        # here. Everything the drain does is bounded, because the kill that
        # follows is not negotiable.
        await worker.drain()

    app = FastAPI(title="ai-anki", lifespan=lifespan)
    app.add_middleware(auth.Guard, db_path=db_path, owner_token=owner_token)

    async def get_conn():
        # Async so the connection is created and used on the same thread. A sync
        # dependency would be resolved in a threadpool and then handed to the
        # event loop, which SQLite refuses. Statements here are sub-millisecond;
        # long-running work belongs in the worker, not in a request.
        conn = db.connect(db_path)
        try:
            yield conn
        finally:
            conn.close()

    def guard_spend(conn, invite_id):
        """Refuse work we already know we should not pay for."""
        try:
            budget.check(
                conn,
                invite_id,
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

    async def invite_of(request: Request) -> str:
        """The Invite Token this request arrived with, as the guard established it."""
        return request.state.invite_id

    def owned_job(conn, job_id: str, invite_id: str) -> jobs.Job:
        """Load a job, but only for the person whose job it is.

        Somebody else's job is answered as missing rather than as forbidden:
        which job ids exist is not something an invited stranger should be able
        to enumerate.
        """
        job = jobs.load_job(conn, job_id)
        if job is None or job.invite_id != invite_id:
            raise HTTPException(status_code=404, detail="job not found")
        return job

    @app.post("/api/invites", status_code=201)
    async def mint_invite(request: InviteRequest, conn=Depends(get_conn)):
        """Mint one person's Invite Token. The only time the token exists."""
        token = auth.mint_invite(conn, request.person)
        return JSONResponse({"person": request.person, "token": token}, status_code=201)

    @app.get("/api/invites")
    async def read_invites(conn=Depends(get_conn)):
        return {"invites": [asdict(invite) for invite in auth.list_invites(conn)]}

    @app.post("/api/invites/{invite_id}/revoke")
    async def revoke_invite(invite_id: str, conn=Depends(get_conn)):
        if not auth.revoke_invite(conn, invite_id):
            raise HTTPException(status_code=404, detail="no such invite")
        return {"invite_id": invite_id, "revoked": True}

    @app.post("/api/session")
    async def sign_in(body: SessionRequest, request: Request, conn=Depends(get_conn)):
        """Redeem an Invite Token for a session."""
        address = request.client.host if request.client else "unknown"
        waiting = auth.lockout_remaining(conn, address, lockout_seconds=lockout_seconds)
        if waiting > 0:
            raise HTTPException(
                status_code=429,
                detail="too many failed sign-ins from this address",
                headers={"retry-after": str(int(waiting) + 1)},
            )
        try:
            session_id, person = auth.redeem(
                conn, body.token, ttl_seconds=session_ttl_seconds
            )
        except auth.InvalidToken as exc:
            auth.record_failure(conn, address)
            # Every failure costs the same fixed wait, so the answer arrives no
            # sooner for a token that got closer, and guessing runs at the rate
            # we choose rather than the rate the network allows.
            await asyncio.sleep(login_delay_seconds)
            raise HTTPException(status_code=401, detail=str(exc)) from exc

        auth.clear_failures(conn, address)
        response = JSONResponse({"person": person})
        # No expiry on the cookie itself: the session's absolute expiry lives in
        # the database, where it cannot be edited by the holder, and one source
        # of truth is better than two that can disagree.
        response.set_cookie(
            auth.SESSION_COOKIE,
            session_id,
            httponly=True,
            secure=True,
            samesite="lax",
            path="/",
        )
        return response

    @app.post("/api/jobs", status_code=201)
    async def create_job(
        file: UploadFile,
        deck_id: str | None = Form(default=None),
        conn=Depends(get_conn),
        invite_id: str = Depends(invite_of),
    ):
        """Start a Job. Naming a Deck continues it; naming none begins one."""
        if deck_id and not ledger.deck_exists(conn, deck_id, invite_id):
            raise HTTPException(status_code=404, detail="no such deck")
        content = await file.read()
        job_id = jobs.create_job(
            conn,
            data_dir,
            file.filename or "upload",
            content,
            invite_id=invite_id,
            deck_id=deck_id,
        )
        return JSONResponse({"job_id": job_id}, status_code=201)

    @app.get("/api/jobs/{job_id}")
    async def read_job(
        job_id: str, conn=Depends(get_conn), invite_id: str = Depends(invite_of)
    ):
        job = owned_job(conn, job_id, invite_id)
        return {
            "job_id": job.id,
            "invite_id": job.invite_id,
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
                db_path,
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
        guard_spend(conn, job.invite_id)
        _claim(conn, job_id, jobs.PLANNING)

        try:
            documents = jobs.documents_for(conn, job_id, provider)
            request = planning.build_plan_request(documents, provider)
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
        deck_id: str, conn=Depends(get_conn), invite_id: str = Depends(invite_of)
    ):
        """What this Deck knows about its own cards. Never purged."""
        if not ledger.deck_exists(conn, deck_id, invite_id):
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
    async def backup(conn=Depends(get_conn)):
        """Take a consistent copy while the application keeps running.

        Platform volume snapshots are documented as not being a backup, and this
        database is the one thing whose loss cannot be recovered by re-running
        anything.
        """
        destination = data_dir / "backup.db"
        written = db.backup_to(db_path, destination)
        return {"path": str(destination), "bytes": written}

    @app.get("/api/jobs/{job_id}/usage")
    async def read_usage(
        job_id: str, conn=Depends(get_conn), invite_id: str = Depends(invite_of)
    ):
        """What this job actually cost, derived from what the API reported."""
        owned_job(conn, job_id, invite_id)
        calls = jobs.load_usage(conn, job_id)
        priced = [{**call, "cost_usd": ingestion.cost_of(call, provider.prices)} for call in calls]
        return {
            "job_id": job_id,
            "calls": priced,
            "total_cost_usd": round(sum(call["cost_usd"] for call in priced), 6),
        }

    @app.get("/api/jobs/{job_id}/estimate")
    async def read_estimate(
        job_id: str, conn=Depends(get_conn), invite_id: str = Depends(invite_of)
    ):
        """What this job measures and what it is expected to cost.

        Reported in tokens and money. Page count is deliberately absent: it is
        not the limit, and showing it as one would be a promise the pipeline
        cannot keep.
        """
        job = owned_job(conn, job_id, invite_id)
        documents = jobs.documents_for(conn, job_id, provider)
        input_tokens = ingestion.count_input_tokens(
            provider, planning.build_plan_request(documents, provider)
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
        job_id: str, body: dict, conn=Depends(get_conn), invite_id: str = Depends(invite_of)
    ):
        """Replace the plan with the user's edited version.

        Validated here, not in the browser: the UI is a convenience, not a
        trusted client, and the response schema could not express these bounds
        in the first place.
        """
        owned_job(conn, job_id, invite_id)
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
        job_id: str, topic_id: str, conn=Depends(get_conn), invite_id: str = Depends(invite_of)
    ):
        owned_job(conn, job_id, invite_id)
        return {"rejected": jobs.delete_topic_cards(conn, job_id, topic_id)}

    @app.post("/api/cards/{card_uuid}/reroll")
    async def reroll_card(card_uuid: str, conn=Depends(get_conn)):
        """Ask again for one card, not the whole topic."""
        existing = jobs.find_card(conn, card_uuid)
        if existing is None:
            raise HTTPException(status_code=404, detail="no such card")
        job = jobs.load_job(conn, existing["job_id"])
        guard_spend(conn, job.invite_id if job else None)

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
        job_id: str, conn=Depends(get_conn), invite_id: str = Depends(invite_of)
    ):
        """What to tell the user at the moment they import."""
        owned_job(conn, job_id, invite_id)
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
        guard_spend(conn, job.invite_id)
        # Re-checked here, not only at admission: a plan multiplies the work and
        # the sources may have grown between the two passes.
        guard_size(
            conn,
            job_id,
            planning.build_plan_request(jobs.documents_for(conn, job_id, provider), provider),
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

    @app.get("/api/jobs/{job_id}/cards")
    async def read_cards(job_id: str, conn=Depends(get_conn)):
        if jobs.load_job(conn, job_id) is None:
            raise HTTPException(status_code=404, detail="job not found")
        return {
            "cards": [
                {
                    **asdict(card),
                    "tags": card.tags,
                    "rendered_front": planning.render_cloze(card.front)
                    if card.note_type == "cloze"
                    else card.front,
                }
                for card in jobs.load_cards(conn, job_id)
            ]
        }

    @app.get("/api/jobs/{job_id}/diff")
    async def read_diff(
        job_id: str, conn=Depends(get_conn), invite_id: str = Depends(invite_of)
    ):
        """What downloading now would do to the user's collection."""
        job = owned_job(conn, job_id, invite_id)
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
