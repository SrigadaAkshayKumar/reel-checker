# Reel Fact-Checker: End-to-End Project Workflow (100% Free Stack)

A web app where a user submits an Instagram reel (uploaded file or screen recording) and gets back an evidence-based report: **does the footage match what the reel claims, and where did it first appear?**

> Core principle: the product never says "this is 100% real". It says "this footage appeared earlier at X, which contradicts the claim", or "no contradicting evidence found". Honest uncertainty builds trust.

---

## 1. Product Definition

### 1.1 Problem
Old or unrelated videos are re-shared as breaking news (e.g. a 10-year-old plane crash captioned "today in Hyderabad", old test footage shown as a war event).

### 1.2 What the app does
1. User uploads a reel (MP4) or a screen recording.
2. App extracts the claim (caption, on-screen text, spoken words).
3. App searches for earlier appearances of the footage and for existing fact-checks.
4. App compares the claim with the evidence and produces a verdict report with sources.

### 1.3 Verdict categories
| Verdict | Meaning |
|---|---|
| `DEBUNKED` | A fact-checker has already reviewed this claim or video |
| `LIKELY_OLD_FOOTAGE` | Same or very similar footage found with an earlier date |
| `NO_CONTRADICTION_FOUND` | Nothing earlier found; this is NOT proof it is real |
| `UNVERIFIED` | Not enough data (too short, too dark, no speech or text) |

### 1.4 Out of scope for the MVP
- Auto-scanning Instagram (no public API; scraping breaks their terms)
- Deepfake and AI-generated detection (add later)
- Live "real-time" monitoring of all reels (use on-demand analysis, 30-60 s)

---

## 2. Architecture

```
[Next.js UI] --upload--> [FastAPI]
                            |
                            v
                      [Job queue] --> [Worker]
                                         |
     +-----------+-----------+-----------+-----------+
     v           v           v           v           v
  ffmpeg      Whisper     OCR        pHash+CLIP   Claim LLM
  (frames,   (speech)   (on-screen   (fingerprint) (Gemini free /
   audio)                  text)                     Ollama)
                                         |
                                         v
                     +-------- Evidence gathering --------+
                     | 1. Own index lookup (FAISS)        |
                     | 2. Google Fact Check Tools API     |
                     | 3. YouTube Data API keyword search |
                     | 4. Google Vision Web Detection     |
                     |    (best 2-3 frames, last resort)  |
                     +------------------------------------+
                                         |
                                         v
                              [Verdict engine + LLM summary]
                                         |
                                         v
                       [Postgres: results + cache] --> [Report page]
```

---

## 3. Free Tech Stack

| Layer | Tool | Notes |
|---|---|---|
| Frontend | Next.js on Vercel / Cloudflare Pages | Free tier |
| Backend API | FastAPI (Python) | |
| Queue | Postgres job table (simplest) or Upstash Redis free | Start with Postgres |
| Database | Supabase or Neon free Postgres (+ pgvector) | |
| File storage | Local disk on VM; delete uploads after processing | Saves quota and protects privacy |
| Video / audio | ffmpeg, OpenCV, PySceneDetect | |
| Speech to text | faster-whisper (`base` or `small`) | Runs locally |
| OCR | EasyOCR or Tesseract | |
| Fingerprints | `imagehash` (pHash/dHash), CLIP via `open_clip` or `sentence-transformers` | |
| Vector search | FAISS or pgvector | |
| Claim database | Google Fact Check Tools API | Free API key |
| Earlier uploads | YouTube Data API v3, Internet Archive | Daily quota; cache everything |
| Reverse image search | Google Cloud Vision Web Detection | Small free monthly quota; use sparingly |
| LLM | Gemini API free tier, Groq free tier, or Ollama (local) | |
| Hosting | Oracle Cloud Always Free VM (best for heavy work), Hugging Face Spaces (alternative) | |

Check each provider's current free limits before building; they change.

---

## 4. Repository Structure

```
reel-checker/
├── backend/
│   ├── app/
│   │   ├── main.py              # FastAPI app
│   │   ├── api/                 # routes: upload, status, report
│   │   ├── core/config.py       # env vars, limits
│   │   ├── db/                  # models, session, migrations
│   │   ├── pipeline/
│   │   │   ├── extract.py       # ffmpeg frames + audio
│   │   │   ├── transcribe.py    # Whisper
│   │   │   ├── ocr.py
│   │   │   ├── claims.py        # LLM claim extraction
│   │   │   ├── fingerprint.py   # pHash + CLIP
│   │   │   ├── evidence/
│   │   │   │   ├── own_index.py
│   │   │   │   ├── factcheck_api.py
│   │   │   │   ├── youtube.py
│   │   │   │   └── vision_web.py
│   │   │   ├── verdict.py       # scoring logic
│   │   │   └── report.py        # LLM summary
│   │   └── worker.py            # job runner
│   ├── tests/
│   └── requirements.txt
├── frontend/                    # Next.js app
├── data/
│   └── seed/                    # debunked videos list, sample reels
├── docs/
├── .env.example
└── README.md
```

---

## 5. Build Phases

### Phase 0: Setup (Day 1-2)
- [ ] Create GitHub repo and project skeleton
- [ ] Install ffmpeg, Python 3.11+, Node 20+
- [ ] Get API keys: Google Cloud (Fact Check Tools, YouTube Data v3, Vision), Gemini
- [ ] Create `.env.example`; never commit real keys
- [ ] Collect 15-20 test reels: some genuine, some known recycled footage (use known debunked examples as ground truth)

### Phase 1: Core script, no web (Week 1)
Goal: `python run.py sample.mp4` prints a basic report.
1. **Extract** with ffmpeg:
   ```bash
   ffmpeg -i in.mp4 -vf "fps=1" frames/%03d.jpg
   ffmpeg -i in.mp4 -vn -ac 1 -ar 16000 audio.wav
   ```
   Use PySceneDetect to keep only scene-change frames (cap at ~10-15).
2. **Transcribe** audio with faster-whisper (auto language detection; reels in Telugu, Hindi and English are common).
3. **OCR** every key frame; dedupe text.
4. **Extract claim** with an LLM. Prompt for strict JSON:
   ```json
   {"event": "", "location": "", "claimed_date": "", "keywords": [], "language": ""}
   ```
5. **Print** everything to the console.

### Phase 2: Evidence gathering (Week 2-3)
1. **Fact Check API:** query with the claim text and keywords; store matching `claimReview` entries (publisher, rating, URL, date).
2. **YouTube search:** build 2-3 queries from keywords (e.g. "plane crash runway video"), filter by `publishedBefore` the claimed date; keep top results and their upload dates.
3. **Frame similarity check** on candidates: download only thumbnails (not videos) from YouTube results, compute pHash/CLIP similarity against your key frames. High similarity with an earlier date is strong evidence.
4. **Vision Web Detection** on the best 2-3 frames only when steps 1-3 found nothing; use `pagesWithMatchingImages` and `visuallySimilarImages`.
5. **Cache** every external call in Postgres keyed by query or frame hash.

### Phase 3: Verdict engine (Week 3)
Rule-based first, LLM only to explain.

```
if fact_check_hit:                          DEBUNKED
elif earlier_match.similarity >= 0.90
     and earlier_match.date < claimed_date: LIKELY_OLD_FOOTAGE (confidence by similarity + source count)
elif earlier_match.similarity >= 0.80:      LIKELY_OLD_FOOTAGE (low confidence)
elif input_too_poor:                        UNVERIFIED
else:                                       NO_CONTRADICTION_FOUND
```
Then the LLM writes a 4-6 line plain-language summary using only the retrieved evidence. Instruct it not to invent sources or dates.

### Phase 4: Backend API (Week 4)
Endpoints:
| Method | Path | Purpose |
|---|---|---|
| POST | `/api/analyze` | Upload file, returns `job_id` |
| GET | `/api/jobs/{id}` | Status: queued / running / done / failed |
| GET | `/api/reports/{id}` | Final report JSON |
| GET | `/r/{id}` | Public shareable report page |

Limits: max 60 s video, max 50 MB, 10 analyses per IP per day, delete the uploaded file after processing.

### Phase 5: Frontend (Week 4-5)
- Landing page with a one-line pitch and upload box
- Progress screen (steps: extracting, transcribing, searching, comparing)
- Report page: verdict badge, claim extracted, evidence cards (source, date, similarity, link), side-by-side frames, share button
- Mobile-first layout; most users will be on phones
- "Open in Google Lens / Yandex" helper button for manual checks

### Phase 6: Own index (Week 5-6)
- Seed with videos already debunked by fact-checkers (store URL, date, claim, frame hashes and CLIP embeddings, not the videos)
- Add every analysed reel's fingerprints to the index
- Match new uploads against the index before any external API call

### Phase 7: Test and measure (Week 6)
- Run all test reels; record precision on recycled-footage cases and false-positive rate on genuine ones
- Manually review every `LIKELY_OLD_FOOTAGE` result in the first month
- Tune similarity thresholds on your test set, not by guessing

### Phase 8: Deploy (Week 7)
1. Frontend to Vercel or Cloudflare Pages
2. Backend + worker on an Oracle Always Free VM (systemd or Docker Compose)
3. HTTPS via Caddy or Cloudflare
4. Env vars in the host's secret store
5. Basic uptime check (UptimeRobot free) and error logs

### Phase 9: Launch and learn (Week 8+)
- Share with journalism students, fact-checking volunteers and local news creators
- Add a "Was this correct?" button on each report; store feedback to improve thresholds
- Post example reports (with permission) on social media; shareable reports are your growth loop

---

## 6. Database Schema (starter)

```sql
create table jobs (
  id uuid primary key default gen_random_uuid(),
  status text not null default 'queued',
  video_hash text,
  created_at timestamptz default now()
);

create table reports (
  job_id uuid references jobs(id),
  claim jsonb,
  verdict text,
  confidence real,
  evidence jsonb,       -- list of {source, url, date, similarity}
  summary text,
  created_at timestamptz default now()
);

create table known_footage (
  id serial primary key,
  source_url text,
  first_seen date,
  claim_note text,
  phash text,
  embedding vector(512)
);

create table api_cache (
  key text primary key,   -- e.g. "yt:plane crash runway"
  response jsonb,
  fetched_at timestamptz default now()
);
```

---

## 7. Managing Free-Tier Limits

- Cache every API response; hash each video so the same reel is never re-analysed
- Order of checks: own index, then Fact Check API, then YouTube, then Vision (last resort)
- Track daily quota usage in a table; if exhausted, return a partial report with the manual-check links
- Run Whisper `base` first; move to `small` only if confidence is low
- Process only scene-change frames, not every frame

---

## 8. Legal, Privacy and Ethics

- Do not scrape or bulk-download from Instagram; accept user-provided files only
- Delete uploaded videos after analysis; keep only hashes and results
- Add a privacy note and terms page before launch
- Show sources for every claim; never accuse a person or account of lying, only that the footage predates the claim
- Label the result as automated and possibly wrong; include a way to report errors
- Avoid storing personal data; do not log uploader identity beyond rate limiting

---

## 9. Testing Checklist

- [ ] Reel with burned-in text but no speech
- [ ] Speech-only reel in Telugu, Hindi and English
- [ ] Heavily cropped, mirrored or re-encoded copy of old footage
- [ ] Reel with a watermark or overlay on top of old footage
- [ ] Genuine recent footage (must NOT be flagged)
- [ ] Very short or very dark video (should return `UNVERIFIED`)
- [ ] Quota exhausted (graceful partial report)
- [ ] Corrupt or oversized upload

---

## 10. Roadmap After MVP

1. Browser extension and a WhatsApp or Telegram bot ("forward a reel, get a report")
2. Audio fingerprinting to match reused soundtracks
3. Geolocation clues (signs, landmarks) and weather and date consistency checks
4. AI-generated video detection
5. Public API and dashboard for newsrooms
6. Paid tier for heavy users, once free quotas become the bottleneck

---

## 11. Weekly Plan Summary

| Week | Deliverable |
|---|---|
| 1 | Local script: frames, transcript, OCR, claim JSON |
| 2-3 | Evidence gathering with caching |
| 3 | Verdict engine + LLM summary |
| 4 | FastAPI backend with job queue |
| 4-5 | Next.js frontend and report page |
| 5-6 | Own index of known footage |
| 6 | Evaluation on test set |
| 7 | Deployment |
| 8+ | Launch, feedback, iterate |
