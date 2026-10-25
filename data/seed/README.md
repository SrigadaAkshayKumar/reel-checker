# Seeding the known-footage index

The own index is checked before any external API. When a reel matches known old footage strongly,
the YouTube and Vision searches are skipped entirely, which saves the scarce free quota. Seed it with
footage that fact-checkers have already debunked.

**Only fingerprints are stored, never media.** An entry is a list of 64-bit pHashes (plus optional CLIP
embeddings) with the source URL, the date the footage first appeared, what it really shows, and the
fact-check link. Exported packs are safe to commit to this public repo.

All commands run from `backend/`.

## The workflow

1. **Collect candidates.** This collects fact-checks rated false or misleading from the Google Fact Check API into a CSV:

   ```bash
   python run.py index harvest                     # queries from harvest_queries.txt
   python run.py index harvest --query "పాత వీడియో" --query "old video Hyderabad"
   ```

   Needs `GOOGLE_API_KEY` with the Fact Check Tools API enabled. Re-running appends only new fact-checks.

2. **Fill in the footage.** For each row worth keeping in `candidates.csv`, open the fact-check and find
   the original footage it cites. Then fill in:
   - `youtube`: the original video's URL (most fact-checks link it). Only its public thumbnail and YouTube's
     three automatic frame grabs are fingerprinted; the video is never downloaded. `first_seen` and
     `source_url` fill themselves from the YouTube API when left empty.
   - or `images`: stills from the article (file paths or URLs, separated by spaces or `|`)
   - or `video`: a local copy of the original, if you have one you may use
   - `first_seen`: the earliest date the footage is known online (YYYY-MM-DD), unless YouTube fills it
   - `claim_note`: prefilled with the fact-check title; edit it to say what the footage really shows

   Leave rows you don't want empty: import skips rows with no footage.

3. **Import.**

   ```bash
   python run.py index import ../data/seed/candidates.csv
   ```

4. **Share or commit a pack** (hashes only):

   ```bash
   python run.py index export ../data/seed/known_footage.json
   python run.py index import ../data/seed/known_footage.json     # on another server
   ```

## One-off additions

```bash
python run.py index add-youtube "https://youtu.be/XXXXXXXXXXX" --note "2015 cargo crash, Brazil" --fact-check URL
python run.py index add-images still1.jpg https://example.org/still2.jpg --first-seen 2019-08-01 \
  --source-url URL --note "..." [--fact-check URL]
python run.py index add original.mp4 --first-seen 2016-07-01 --source-url URL --note "..."
```

## Looking after it

```bash
python run.py index list          # every entry: kind, first seen, fingerprints, sightings
python run.py index stats         # counts, and the footage that resurfaces most
python run.py index remove 12
```

Every analysed reel is added automatically as a `seen` entry, with a link to its report. When the same
footage turns up again it adds a sighting to that entry instead of a duplicate, so `stats` shows which old
clips keep coming back. A later reel matching it links to the earlier report.

## File formats

**JSON pack**: a list of entries:

```json
[{"source_url": "https://www.youtube.com/watch?v=XXXXXXXXXXX", "first_seen": "2015-03-02",
  "claim_note": "2015 cargo plane crash, Brazil; shared as Hyderabad 2026",
  "fact_check_url": "https://example.org/fact-check", "phashes": ["c3d1a4b2e5f60718", "..."]}]
```

Instead of `phashes`, an entry may give `youtube`, `images` (a list) or `video`, as in the CSV.

**CSV**: columns `claim_note, first_seen, source_url, youtube, video, images, phashes, fact_check_url`
(+ `rating, publisher, review_date, claim_text`, for reference only).

## Matching rules

An entry matches a reel when one keyframe is at least 90% similar (`STRONG_SIMILARITY`), or when at least
two different keyframes are at least 80% similar (`WEAK_SIMILARITY`). The two-frame rule is what keeps
a large index honest. With a million stored fingerprints, a reel makes about 100 million comparisons,
and chance alone puts a few dozen unrelated entries above 80% on a single frame. Two frames of the same
entry at that level essentially never happen by chance.

Matching is vectorised with numpy (about 0.8 s for 1.2 million fingerprints on one CPU core), so the index can
grow a long way before it needs FAISS or pgvector.
