# Seeding the known-footage index

The own index is checked before any external API. Seed it with footage that
fact-checkers have already debunked. Store **fingerprints only**, never the video.

## From a video you have locally

```bash
cd backend
python run.py index add /path/to/original.mp4 \
  --source-url "https://www.youtube.com/watch?v=..." \
  --first-seen 2016-07-01 \
  --note "2016 cargo plane crash, Brazil; shared as Hyderabad 2026" \
  --fact-check "https://factly.in/..."
```

The video is read, its keyframes are hashed, and only the hashes are saved.

## From a JSON file

`python run.py index import ../data/seed/known_footage.json` loads a list of
entries shaped like `known_footage.example.json`. `phashes` are 16-character hex
pHashes of keyframes (the first value of `fingerprint.variants()` for a frame).

Every analysed reel is also added automatically as a `seen` entry, so footage
that resurfaces later with a new caption is caught. `python run.py index list` shows it all.
