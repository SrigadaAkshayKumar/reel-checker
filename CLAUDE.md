# Reel Fact-Checker

Checks whether an Instagram reel (a user-supplied file) shows old footage passed off as new. Product brief:
`docs/project-overview.md`; build plan and phases: `docs/workflow.md`. Done: Phases 1-3 (pipeline + CLI), 4 (FastAPI +
job queue), 6 (own index + seeding) and 7 (eval / bench / review, `data/eval/README.md`) in `backend/`; 5 (Next.js) in
`frontend/`. Next: Phase 8, deployment.

## Rules that define the product

- Verdicts are `DEBUNKED`, `LIKELY_OLD_FOOTAGE`, `NO_CONTRADICTION_FOUND`, `UNVERIFIED`. Never "real" / "100% true".
- The verdict is decided by rules in `backend/app/pipeline/verdict.py`. The LLM only extracts the claim and explains;
  it never decides, and its summary may only use retrieved evidence.
- Report what the evidence shows about the footage; never accuse a person or account.
- No Instagram scraping: input is always a file the user provides. Delete work files after analysis; keep only
  hashes and results. Never commit media, `.env`, databases or reports.
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
