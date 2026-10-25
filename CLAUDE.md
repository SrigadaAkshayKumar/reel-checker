# Reel Fact-Checker

Checks whether an Instagram reel (a user-supplied file) shows old footage passed off as new. Product brief:
`docs/project-overview.md`; build plan and phases: `docs/workflow.md`. Currently Phases 1-3 (CLI pipeline in `backend/`).

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
```

- Settings and thresholds live only in `app/core/config.py` (env-overridable). Tune thresholds on test reels.
- All HTTP goes through `app/core/http.py` (tests swap in `FakeHttp` from `tests/conftest.py`).
  Never log or print API keys.
- Heavy models (faster-whisper, EasyOCR, CLIP) are optional lazy imports; the pipeline must still run without them.
- Tokenise Indic text with `app/pipeline/text.py`, not regex `\w` (it drops Telugu/Hindi vowel signs).
- New evidence source: `app/pipeline/evidence/<name>.py` returning `list[Evidence]` (raise `SkipCheck` to skip),
  wired into `runner.py`, added to `EVIDENCE_CHECKS` in `verdict.py`, with a faked-API test.
