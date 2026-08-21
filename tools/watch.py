"""Emit one line per meaningful change while a job runs.

Coverage matters more than tidiness here: it emits on every terminal state and
on every error, not just the happy path, because a monitor that only prints good
news is indistinguishable from a monitor watching a crashed process.
"""
import os, re, sqlite3, sys, time
from pathlib import Path

DB = Path(os.environ.get("AI_ANKI_DB_PATH", ".local/ai-anki.db"))
LOG = Path(sys.argv[1])

def say(msg):
    print(msg, flush=True)

def snapshot():
    if not DB.exists():
        return {}
    try:
        c = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
        c.row_factory = sqlite3.Row
        out = {}
        for j in c.execute("SELECT id, state, error, input_tokens FROM job"):
            topics = c.execute(
                "SELECT status, COUNT(*) n FROM topic WHERE job_id=? GROUP BY status",
                (j["id"],)).fetchall()
            cards = c.execute("SELECT COUNT(*) n FROM card WHERE job_id=?", (j["id"],)).fetchone()["n"]
            cost = c.execute(
                "SELECT COALESCE(SUM(input_tokens*5.0/1e6 + cache_creation_input_tokens*10.0/1e6"
                " + cache_read_input_tokens*0.5/1e6 + output_tokens*25.0/1e6),0) c"
                " FROM api_call WHERE job_id=?", (j["id"],)).fetchone()["c"]
            out[j["id"]] = {
                "state": j["state"], "error": j["error"], "tokens": j["input_tokens"],
                "topics": {t["status"]: t["n"] for t in topics}, "cards": cards, "cost": cost,
            }
        c.close()
        return out
    except Exception:
        return {}

seen = snapshot()
pos = LOG.stat().st_size if LOG.exists() else 0
say("watching — upload something and I will report as it moves")

while True:
    time.sleep(1.5)

    now = snapshot()
    for job_id, s in now.items():
        short = job_id[:8]
        was = seen.get(job_id)
        if was is None:
            say(f"[{short}] new job · state={s['state']}")
        else:
            if s["state"] != was["state"]:
                extra = f" · {s['tokens']:,} tokens" if s["tokens"] and s["state"] == "plan_ready" else ""
                say(f"[{short}] {was['state']} -> {s['state']}{extra}")
            if s["topics"] != was["topics"]:
                done = s["topics"].get("done", 0)
                total = sum(s["topics"].values())
                failed = s["topics"].get("failed", 0)
                flag = f" · {failed} FAILED" if failed else ""
                say(f"[{short}] topics {done}/{total} done · {s['cards']} cards · ${s['cost']:.3f}{flag}")
            if s["error"] and s["error"] != (was["error"] or ""):
                say(f"[{short}] ERROR: {s['error'][:200]}")
        if s["state"] in ("complete", "failed", "dead", "interrupted") and (
            was is None or was["state"] != s["state"]
        ):
            say(f"[{short}] FINISHED in state '{s['state']}' · {s['cards']} cards · ${s['cost']:.3f}")
    seen = now

    # Anything the server itself complains about: exceptions, and any non-2xx.
    try:
        if LOG.exists() and LOG.stat().st_size > pos:
            with LOG.open() as f:
                f.seek(pos)
                chunk = f.read()
                pos = f.tell()
            for line in chunk.splitlines():
                if re.search(r"Traceback|Exception|Error|CRITICAL", line):
                    say(f"SERVER: {line[:220]}")
                elif re.search(r'HTTP/1\.1" (4\d\d|5\d\d)', line) and "401 Unauthorized" not in line:
                    say(f"SERVER: {line.split(' - ')[-1][:200]}")
    except Exception:
        pass
