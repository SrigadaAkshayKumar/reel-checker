# Reel Fact-Checker

Tells you whether a reel shows what it claims, or old footage passed off as news.
You give it the video file; it gives back an evidence report:

1. **What the reel claims**: event, place and date, from the caption, speech (Telugu / Hindi / English) and on-screen text.
2. **Where the footage really comes from**: earlier copies, existing fact-checks.
3. **A verdict** with confidence, sources and side-by-side frames.

| Verdict | Meaning |
|---|---|
| `DEBUNKED` | A fact-checker has already rated this claim false or misleading |
| `LIKELY_OLD_FOOTAGE` | The same or very similar footage was published before the claimed date |
| `NO_CONTRADICTION_FOUND` | Nothing earlier found. **Not** proof it is real |
| `UNVERIFIED` | Not enough to judge (too short/dark, no claim, or no evidence search could run) |

It never says a reel is "100% real", and it never accuses a person. Background: [`docs/project-overview.md`](docs/project-overview.md),
full plan: [`docs/workflow.md`](docs/workflow.md).

## Status

Phases 1-6 of the plan: the analysis pipeline (CLI), the FastAPI backend with a job queue, the Next.js
web app (`frontend/`, see [`frontend/README.md`](frontend/README.md)), and the own index of known footage with
seeding tools ([`data/seed/README.md`](data/seed/README.md)), and the measurement tools to test on real reels
and tune thresholds ([`data/eval/README.md`](data/eval/README.md)). Next: deployment (Phase 8).

## Quick start

Needs Python 3.11+ and ffmpeg.

```bash
cd backend
python -m venv ../.venv && source ../.venv/bin/activate
pip install -r requirements-dev.txt          # requests, numpy, pillow, fastapi (+ pytest, ruff)
cp ../.env.example ../.env                   # then add your keys

python run.py reel.mp4 --caption "Plane crash today at Hyderabad" --posted 2026-10-24
```

Output goes to `output/<job_id>/`: `report.md`, `report.json`, `compare_*.jpg` (reel frame next to the
earlier match) and `frames/` (keyframes to upload to Google Lens / Yandex by hand).

Other commands:

```bash
python run.py reel.mp4 --json            # full report JSON on stdout
python run.py reel.mp4 --fresh           # ignore the cached report for this exact file
python run.py index harvest              # fact-checks rated false → candidates CSV to fill in
python run.py index import ../data/seed/candidates.csv
python run.py index add-youtube URL --note "..." [--fact-check URL]   # thumbnails only, nothing downloaded
python run.py index list | stats | export pack.json | remove ID
python run.py eval ../data/eval/cases.csv   # measure on labelled reels + recommend thresholds
python run.py bench ~/Videos/*.mp4       # fingerprint robustness under 17 common edits (no keys)
python run.py review                     # flagged production results awaiting human review
python run.py quota                      # today's free-tier usage
pytest -q && ruff check .                # tests (no network, no keys needed)
```

## API server

```bash
cd backend
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

For the full web app, run the Next.js frontend too (`cd frontend && npm install && npm run dev`, then open
http://localhost:3000; start the backend with `CORS_ORIGINS=http://localhost:3000 PUBLIC_BASE_URL=http://localhost:3000`).
The backend's own minimal upload page at http://localhost:8000 and `/r/{id}` page still work without it.
Interactive API docs are at `/docs`. One worker thread runs
inside the server (`EMBEDDED_WORKER=true`), which is enough for a single free VM. To scale, set it to `false`
and run one or more `python -m app.worker` processes against the same database. Claiming a job is atomic.

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/analyze` | multipart `file` (+ optional `caption`, `posted_date` YYYY-MM-DD). `202` with a queued job, or `200` with `cached: true` when this exact file was already checked |
| GET | `/api/jobs/{id}` | `queued` (with `queue_position`) → `running` (with `step`: extracting, transcribing, understanding, searching, comparing) → `done` / `failed` (with a user-facing `error`) |
| GET | `/api/reports/{id}` | report JSON, with `share_url` and image URLs |
| GET | `/api/reports/{id}/files/{name}` | side-by-side comparison images and keyframes |
| POST | `/api/reports/{id}/feedback` | `{"correct": true/false, "note": "..."}`: "Was this correct?" / report an error |
| GET | `/r/{id}` | public share page, mobile-first, with WhatsApp preview tags and a share button |
| GET | `/api/health` | status, queue length, which keys are configured (never their values) |

Errors come back as `{"detail": {"code": "...", "message": "..."}}`: `not_video` 415, `too_large` 413,
`bad_video` 400 (corrupt, or over `MAX_VIDEO_SECONDS`), `bad_date` / `caption_too_long` 422, `rate_limited` 429.

Limits and privacy:
- Uploads up to `MAX_UPLOAD_MB` (50) and `MAX_VIDEO_SECONDS` (90), checked before queueing.
- `RATE_LIMIT_PER_DAY` (10) new analyses per client. Cached answers don't count.
- Client IPs are stored only as salted hashes. Behind Caddy or Cloudflare, set `TRUST_PROXY=true`.
- The uploaded video is deleted as soon as its analysis finishes or fails. Kept: fingerprints, the report,
  and the small keyframe and comparison images the share page shows.
- A job left `running` by a crashed worker is requeued once, then failed with a "try again" message.

## Keys

| Key | Used for | Without it |
|---|---|---|
| `GEMINI_API_KEY` ([AI Studio](https://aistudio.google.com/apikey)) | Claim extraction, transcription when Whisper is missing or unsure, on-screen text, summary | Keyword heuristic from the caption; no speech/OCR unless local models are installed |
| `GOOGLE_API_KEY` (Cloud Console) with **Fact Check Tools API**, **YouTube Data API v3**, **Cloud Vision API** enabled | Existing fact-checks, earlier uploads, reverse image search | Those checks are skipped and the report is marked partial |

Cloud Vision needs billing enabled on the project, even within its 1,000 free units a month. Leave it off with
`VISION_ENABLED=false` if you prefer. Free-tier limits change, so check current quotas in AI Studio and the Cloud Console.
The app enforces its own budgets (`GEMINI_DAILY_LIMIT`, `YOUTUBE_DAILY_UNITS`, ...) and caches every response.

**Privacy:** Gemini's free tier may use prompts to improve Google's models, so keyframes and audio sent for
claim extraction fall under that. For sensitive material, use a paid key or local models.

## Optional local models

```bash
pip install -r requirements-ml.txt       # faster-whisper, EasyOCR, open_clip (+ torch)
```

- **faster-whisper** `base`, then `small` when confidence is low. If it's still unsure (common on Telugu), the audio goes to Gemini.
- **EasyOCR** reads English + Hindi + Telugu on-screen text. `tesseract` is used if it's installed instead.
- **CLIP** (`USE_CLIP=true`) re-scores near-miss frame matches that pHash misses (heavy crops, overlays).

## How it works

```
reel.mp4 ─ ffprobe/ffmpeg ─ keyframes (even sweep + scene changes, de-duplicated, ≤12) + 16 kHz audio
        ─ faster-whisper / EasyOCR (if installed)
        ─ Gemini: one call with caption + transcript + OCR + 5 frames (+ audio if needed)
                  → claim, claimed date, YouTube queries describing the VISIBLE footage, fact-check queries
        ─ evidence, cheapest first:
            1. own index      known debunked footage + every reel checked before (vectorised pHash,
                              optional CLIP); a strong match skips the YouTube / Vision quota
            2. Fact Check     Google Fact Check Tools claims:search, rating + relevance gate
            3. YouTube        search.list with publishedBefore = claimed date; hash each result's thumbnail
                              and its 3 auto frame grabs against the reel's keyframes (images only, no video)
            4. Vision Web     only when 1-3 found nothing: pages with matching images (leads, no dates)
        ─ what each piece of evidence supports: one shared rule set (backend/app/pipeline/scoring.py), so
          `run.py eval` can re-score saved evidence at any threshold exactly as production would
        ─ verdict rules (backend/app/pipeline/verdict.py), then a Gemini summary grounded in that evidence
        ─ report.json / report.md / side-by-side images; the work dir is deleted, fingerprints are kept
```

Fingerprints are 64-bit pHashes of each frame's *content box* (letterbox bars trimmed), plus mirrored,
centre-crop and middle-16:9-band variants. So a landscape clip inside a 9:16 reel with caption strips still
matches the original upload's thumbnail. Thresholds: ≥ 0.90 strong, ≥ 0.80 weak (low confidence). Tune them
on real test reels.

## Layout

```
backend/
  run.py                    CLI
  app/main.py               FastAPI app (uvicorn app.main:app)
  app/api/                  routes (JSON API), pages (share page + upload page), views, deps
  app/worker.py             job runner (embedded thread or `python -m app.worker`)
  app/core/                 config (.env), HTTP client (keys redacted from errors)
  app/db/store.py           SQLite: api_cache, quota, reports, known_footage, jobs, rate_limit, feedback
                            (mirrors the Postgres schema)
  app/pipeline/             extract, transcribe, ocr, llm (Gemini), claims, fingerprint, clip,
                            evidence/{own_index,factcheck_api,youtube,vision_web}, verdict, report, runner
  app/eval/                 evaluate (labelled reels → metrics + threshold sweep), bench, review queue
  tests/                    synthetic reels via ffmpeg; every external API faked; API via TestClient
  tests/e2e_server.py       real API + worker with faked external services, for the frontend's Playwright tests
frontend/                   Next.js 16 web app: upload, live progress, report page, privacy page
data/seed/                  how to seed known debunked footage
data/eval/                  how to build the evaluation set (cases.csv); reels themselves are never committed
docs/                       project overview + full workflow
```
