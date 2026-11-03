# Reel Fact-Checker

Checks whether an Instagram reel (a user-supplied file) shows old footage passed off as new. Product brief:
`docs/project-overview.md`; build plan and phases: `docs/workflow.md`. Done: Phases 1-8 (pipeline + CLI, FastAPI + queue,
Next.js in `frontend/`, own index, eval / bench / review, deployment: `compose.yaml`, `deploy/`, `docs/deploy.md`).
Android app in `android/` (plan: `docs/android-build-guide.md`, API: `docs/mobile-api.md`, build: `android/README.md`):
share target, floating button over Instagram, rewarded ads. Backend side: `app/api/mobile.py` (anonymous accounts, one
free check a day, AdMob SSV credits, pasted links, refunds).

## Rules that define the product

- Verdicts are `DEBUNKED`, `LIKELY_OLD_FOOTAGE`, `NO_CONTRADICTION_FOUND`, `UNVERIFIED`. Never "real" / "100% true".
- The verdict is decided by rules in `backend/app/pipeline/verdict.py`. The LLM only extracts the claim and explains;
  it never decides, and its summary may only use retrieved evidence.
- Report what the evidence shows about the footage; never accuse a person or account.
- Input is a file the user provides, or (app only) one Instagram reel link the user pasted, fetched once by the
  worker with yt-dlp (`pipeline/fetch.py`: canonical Instagram links only, Instagram extractor only, no login or
  cookies). No crawling, no accounts. Delete work files and the link after analysis; keep only hashes and
  results. Never commit media, `.env`, databases or reports.
- The server counts app checks (`app_spend`), never the app. Ad credits come only from a verified AdMob callback
  for our own ad units (`api/admob.py`). Failed or partial jobs are refunded once (`charge_refund`); cached answers
  are free.
- Free stack only. Check order: own index → Fact Check API → YouTube → Vision (last resort). Cache every external
  call (`api_cache`) and charge every call to a budget (`quota`). When a check can't run, mark the report partial
  rather than failing.

## Working here

```
cd backend
pytest -q && ruff check .     # must pass before every commit; no network or keys needed
python run.py <video> [--caption ...] [--posted YYYY-MM-DD]
uvicorn app.main:app --port 8000   # API + share page + upload page, embedded worker

cd ../frontend
npm run lint && npm run typecheck && npm test && npm run build    # before every frontend commit
npm run e2e:build && E2E_PYTHON=../.venv/bin/python npm run e2e   # Playwright against the real backend
```

- Settings and thresholds live only in `app/core/config.py` (env-overridable). Tune thresholds on test reels.
- All HTTP goes through `app/core/http.py` (tests swap in `FakeHttp` from `tests/conftest.py`).
  Never log or print API keys.
- Heavy models (faster-whisper, EasyOCR, CLIP) are optional lazy imports; the pipeline must still run without them.
- Tokenise Indic text with `app/pipeline/text.py`, not regex `\w` (it drops Telugu/Hindi vowel signs).
- New evidence source: `app/pipeline/evidence/<name>.py` returning `list[Evidence]` (raise `SkipCheck` to skip),
  wired into `runner.py`, added to `EVIDENCE_CHECKS` in `verdict.py`, with a faked-API test.
- API: routes in `app/api/routes.py` return `views.public_*` shapes (no server paths). Errors are
  `HTTPException(status, {"code", "message"})` with a user-facing message. Report ids are the job ids (12 hex).
- The worker must always delete the upload (`finally`) and must never put exception text in a job's `error`.
- Share-page text is public: no internal check names, env vars or stack details. Those stay in `checks`.
- Frontend: Next.js 16 with Cache Components. Read `frontend/AGENTS.md` and the bundled docs before using a Next
  API. Runtime values (dates, `navigator`) must not be read during prerender: use `useSyncExternalStore` with a
  server snapshot. The browser talks to the backend directly (`NEXT_PUBLIC_API_URL`); types in `frontend/lib/api.ts`
  mirror the backend JSON, so change both together. Same wording rules as the share page: plain, public, no internals.
- Own index (`evidence/own_index.py`): a match needs one frame >= STRONG or two frames >= WEAK; the two-frame rule
  stops chance matches in a large index. Never loosen it without re-running `test_large_index_does_not_match_by_chance`.
  Seeds store hashes only (`pipeline/seeding.py`); never download videos from YouTube or Instagram.
- Evidence is classified only in `pipeline/scoring.py` (sources and `run.py eval` both call it). Never decide
  `supports` inline in a source module, or the threshold sweep stops matching production. Threshold changes go in
  `.env` and should come from an eval run, not a guess.
- Android: logic that needs no Android API (HTTP, polling, link parsing, wording) goes in `android/core` (plain Kotlin,
  `./gradlew -p core test`, runs without the SDK); `android/app` is UI only. `core/…/Models.kt` mirrors the backend
  JSON like `frontend/lib/api.ts`: change them together. Wording in `core/…/Wording.kt` follows `frontend/lib/present.ts`.
  The app never counts checks or grants credits; it shows what the server says. Overlay windows are classic Views.
  CI builds the APK on every push (`android` in `ci.yml`); `android-emulator.yml` drives it on an emulator against
  the real backend (`android/ci/emulator_smoke.py`) only when the app or the backend code it uses changes; keep both green. Keep Google's test AdMob ids in the repo; real ids come from `-P`.
- Deployment: `compose.yaml` is the production stack and CI's `docker` job runs it with `deploy/smoke-test.sh`; keep
  both green. Nothing may log request lines or client IPs (uvicorn runs with `--no-access-log`, Caddy has no `log`).
  New settings need a line in `.env.example`; data lives in the `data` volume (`/var/lib/reel-checker`).
