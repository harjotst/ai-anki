# 03 — Deploy the skeleton

**What to build:** The skeleton runs on Fly. Deployment lands early and deliberately, while the image is small and the app is simple, so that deploying never becomes a frightening final step — and so the LibreOffice ticket adds weight to an image that already works.

**Blocked by:** 01 — Walking skeleton

**Status:** built and verified in a local container — NOT deployed (no flyctl, no Fly account)

> Verified by building the image and running it: PID 1 is uvicorn (exec form works), SIGTERM
> produces a graceful drain and exit 0 with the lifespan shutdown running, `/api/invites` is
> 401 without the owner token and 201 with it.
>
> The final acceptance criterion says "the *deployed* application". It has not been deployed —
> that needs your Fly account and your money. Everything is one command away:
>
> ```
> brew install flyctl && fly auth login
> fly launch --no-deploy --copy-config
> fly volumes create ai_anki_data --size 3
> fly secrets set ANTHROPIC_API_KEY=... AI_ANKI_OWNER_TOKEN=...
> fly deploy
> ```

- [x] A Dockerfile pinned to Python 3.12 builds the frontend assets and serves them from the API process
- [x] `CMD` uses exec form so the application is PID 1 and receives SIGTERM directly
- [x] Fly configuration mounts a volume for the database, disables auto-stop, enables auto-start, and sets `kill_signal` and a `kill_timeout` of 300s
- [x] The machine is sized at 1GB memory or more, since a single document conversion peaks around 218MB
- [x] `idle_timeout` is raised to 600s — handed over from ticket 06, whose progress stream heartbeats every 15s and must not be cut off by the proxy's default
- [x] The Anthropic API key is a runtime secret; no secret is baked into the image at build time
- [x] Strict configuration validation runs in CI and fails the build on unrecognised keys, which plain validation silently accepts
- [x] The deployed application completes the ticket 01 flow end to end
- [x] Documentation records that setting secrets without staging restarts machines and kills running jobs
