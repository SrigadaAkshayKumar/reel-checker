# Evaluation set (Phase 7)

The plan's success measures are: correctly flag known recycled footage, very few genuine reels
wrongly flagged, and reports in under 60 seconds. `run.py eval` measures all three on a labelled set
of reels, and tunes the thresholds on that set rather than by guessing.

**Never commit the videos** (they are git-ignored). Commit `cases.csv` if the reels are shareable.

## Build the set

Put reels in `data/eval/reels/` and list them in `cases.csv` (start from `cases.example.csv`):

| Column | |
|---|---|
| `file` | path relative to the CSV |
| `expected` | `recycled` (old or unrelated footage passed off as new), `genuine` (really from when and where it says), `poor` (too short, dark, no claim: should be UNVERIFIED), `error` (corrupt or oversized: should be rejected) |
| `caption`, `posted_date` | what a user would give (the post's caption, the date it was posted) |
| `original_url` | for `recycled`: where the footage really comes from. Measures whether the evidence found the true source |
| `tags` | anything to break results down by, comma-separated. Suggested, from the plan's testing checklist: `te`, `hi`, `en`, `speech`, `text-only`, `no-speech`, `cropped`, `mirrored`, `reencoded`, `letterbox`, `caption`, `watermark`, `short`, `dark` |
| `notes` | free text |

Aim for 15-20 reels to start: known debunked examples (fact-checkers' archives are the ground truth) and
**genuine recent footage**. Without genuine reels, false positives can't be measured, and a "recommended"
threshold means nothing.

## Run it

```bash
cd backend
python run.py eval ../data/eval/cases.csv              # needs the API keys; uses real quota
python run.py eval --rescore ../output/eval/<run>/results.json --max-fpr 0.05   # re-score, no API calls
```

- Cases run against a copy of the database. Seeded footage and the API cache are used, but test reels never
  enter the live index and can't match each other. New cache entries and the quota spent are merged back,
  so re-runs are nearly free and the daily budgets stay accurate.
- Vision and the LLM summary are skipped during evaluation: they never change a verdict.
- Each run writes `output/eval/<timestamp>/`:
  - `report.md`: recall, precision, false-positive rate, poor-input and bad-upload handling, source found,
    per-tag accuracy, confusion table, timings against the 60 s goal, the threshold sweep, every case
  - `results.json`: everything needed to re-score
  - `sweep.csv`: every threshold combination

## Tuning

Evidence is captured with permissive thresholds and re-scored with the same rules production uses
(`backend/app/pipeline/scoring.py`), so the sweep shows exactly what each setting would have decided. The
recommendation is the setting that catches the most recycled footage while keeping false positives within
`--max-fpr` (default 0). Ties go to the stricter setting. Copy it into `.env`, then confirm on reels that
weren't in the set: small sets overfit.

## Fingerprints only: `run.py bench`

```bash
python run.py bench ~/Videos/*.mp4          # any footage, no keys
python run.py bench --synthetic 6           # generated footage, a self-check of the method
```

This runs each source video through 17 common edits (re-encoding, crops, mirroring, 9:16 letterboxing,
captions, watermarks, colour, blur, speed, rotation, picture-in-picture, screen recording, excerpt,
everything combined). It reports how often the index still finds the original (recall) and how often it
matches a different video (false matches), at every threshold pair.

## In production: `run.py review`

The first month, review every flagged result: `python run.py review`, then
`python run.py review mark ID correct|wrong|unsure --note "..."`. `review stats` gives precision measured
on real traffic, and reports that users marked wrong come first in the queue.
