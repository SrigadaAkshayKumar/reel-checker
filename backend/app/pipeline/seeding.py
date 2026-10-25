"""Building the known-footage index (docs/workflow.md, Phase 6).

An entry needs: where the footage first appeared (source_url, first_seen),
what it really shows (claim_note), optionally the fact-check URL, and the
footage itself as one of
  phashes   ready-made 16-hex-digit pHashes (exported packs)
  youtube   a video URL or id: its public thumbnail + 3 auto frame grabs are
            hashed; the video is never downloaded. first_seen defaults to the
            upload date from the YouTube Data API (1 quota unit).
  images    image files or URLs (e.g. stills from a fact-check article)
  video     a local video file you are allowed to use
Only hashes (and optional CLIP embeddings) are stored, never media, so an
exported pack can be committed to the public repo.

`harvest` turns Fact Check API results rated false into a CSV of candidates:
fill in the footage column for the ones worth keeping, then import the CSV.
"""
from __future__ import annotations

import csv
import json
import re
import tempfile
from datetime import date
from pathlib import Path

import numpy as np

from ..core.http import HttpError
from . import extract
from . import fingerprint as fp
from .context import Context, SkipCheck
from .evidence import factcheck_api
from .evidence.own_index import encode_embeddings
from .evidence.youtube import FRAME_URLS

YOUTUBE_VIDEOS = "https://www.googleapis.com/youtube/v3/videos"
CSV_FIELDS = ["claim_note", "first_seen", "source_url", "youtube", "video", "images", "phashes", "fact_check_url",
              "rating", "publisher", "review_date", "claim_text"]
_YT_ID = re.compile(r"(?:v=|youtu\.be/|/shorts/|/embed/|/live/)([A-Za-z0-9_-]{11})|^([A-Za-z0-9_-]{11})$")
_HEX = re.compile(r"^[0-9a-f]{16}$")


class SeedError(Exception):
    pass


def youtube_id(value: str) -> str:
    m = _YT_ID.search(value.strip())
    if not m:
        raise SeedError(f"not a YouTube URL or id: {value}")
    return m.group(1) or m.group(2)


def _date(value: str | None) -> str | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value.strip()[:10]).isoformat()
    except ValueError:
        raise SeedError(f"first_seen must be YYYY-MM-DD, got {value!r}") from None


def _embed(ctx: Context, images: list) -> bytes | None:
    if not ctx.settings.use_clip or not images:
        return None
    from . import clip
    if not clip.available():
        return None
    emb = clip.embed([fp.content_box(im) for im in images])
    return encode_embeddings(emb / np.maximum(np.linalg.norm(emb, axis=1, keepdims=True), 1e-6))


def from_images(ctx: Context, sources: list[str]) -> tuple[list[str], list]:
    """(hashes, PIL images) from local paths or http(s) URLs."""
    images = []
    for src in sources:
        try:
            data = ctx.http.get_bytes(src) if re.match(r"^https?://", src) else Path(src).read_bytes()
            images.append(fp.open_image(data))
        except (HttpError, OSError) as exc:
            raise SeedError(f"cannot read image {src}: {exc}") from None
    usable = [im for im in images if fp.image_stats(im)[1] >= 8.0]
    return [h for im in usable for h in fp.stored_hashes(im)], usable


def from_youtube(ctx: Context, video_id: str) -> tuple[list[str], list, str | None, str]:
    """(hashes, images, upload date or None, title) for a YouTube video."""
    images = []
    for tmpl in FRAME_URLS:
        try:
            images.append(fp.open_image(ctx.http.get_bytes(tmpl.format(id=video_id))))
        except (HttpError, OSError):
            continue
    usable = [im for im in images if fp.image_stats(im)[1] >= 8.0]
    if not usable:
        raise SeedError(f"no thumbnails found for YouTube video {video_id} (removed or private?)")
    published, title = None, ""
    if ctx.settings.youtube_key and ctx.store.quota_take("youtube", 1, ctx.settings.youtube_daily_units):
        try:
            data = ctx.http.get_json(YOUTUBE_VIDEOS, params={"part": "snippet", "id": video_id,
                                                             "key": ctx.settings.youtube_key})
            items = data.get("items") or []
            if items:
                published = (items[0]["snippet"].get("publishedAt") or "")[:10] or None
                title = items[0]["snippet"].get("title", "")
        except HttpError:
            pass
    return [h for im in usable for h in fp.stored_hashes(im)], usable, published, title


def from_video(ctx: Context, path: Path) -> tuple[list[str], list]:
    s = ctx.settings
    try:
        info = extract.probe(path, s.max_video_seconds * 40, s.max_upload_mb * 40)
    except extract.InputError as exc:
        raise SeedError(f"cannot read video {path}: {exc}") from None
    with tempfile.TemporaryDirectory() as tmp:
        frames = extract.keyframes(path, info, Path(tmp), max_frames=24, scene_threshold=s.scene_threshold)
        usable = [k for k in frames if k.usable]
        images = [fp.open_image(k.path) for k in usable] if s.use_clip else []
    return [h for k in usable for h in fp.stored_from_variants(k.variants)], images


def add_entry(ctx: Context, entry: dict, base_dir: Path | None = None) -> tuple[int | None, str]:
    """Add one seed entry. Returns (row id or None if skipped, message)."""
    def local(p: str) -> str:
        return p if re.match(r"^https?://", p) or Path(p).is_absolute() or not base_dir else str(base_dir / p)

    hashes: list[str] = []
    images: list = []
    source_url = (entry.get("source_url") or "").strip()
    first_seen = _date(entry.get("first_seen"))
    note = (entry.get("claim_note") or "").strip()

    phashes = entry.get("phashes") or []
    if isinstance(phashes, str):  # CSV cell
        phashes = [h for h in re.split(r"[\s,|]+", phashes) if h]
    for h in phashes:
        if not _HEX.match(str(h)):
            raise SeedError(f"bad phash {h!r} (expected 16 hex digits)")
        hashes.append(str(h))
    if entry.get("video"):
        h, ims = from_video(ctx, Path(local(entry["video"])))
        hashes += h
        images += ims
    if entry.get("youtube"):
        vid = youtube_id(entry["youtube"])
        h, ims, published, title = from_youtube(ctx, vid)
        hashes += h
        images += ims
        source_url = source_url or f"https://www.youtube.com/watch?v={vid}"
        first_seen = first_seen or published
        note = note or title
    image_list = entry.get("images") or []
    if isinstance(image_list, str):
        image_list = [s for s in re.split(r"[\s|]+", image_list) if s]
    if image_list:
        h, ims = from_images(ctx, [local(s) for s in image_list])
        hashes += h
        images += ims

    hashes = list(dict.fromkeys(hashes))
    if not hashes:
        raise SeedError("no footage given (phashes, youtube, images or video)")
    if not first_seen:
        raise SeedError("first_seen is required (the earliest date the footage is known online)")
    if source_url and ctx.store.footage_by_source(source_url):
        return None, f"already indexed: {source_url}"
    row = ctx.store.footage_add(kind="debunked", phashes=hashes, source_url=source_url, first_seen=first_seen,
                                claim_note=note, fact_check_url=(entry.get("fact_check_url") or "").strip(),
                                embeddings=_embed(ctx, images))
    return row, f"added #{row}: {len(hashes)} fingerprints, first seen {first_seen}"


def read_entries(path: Path) -> list[dict]:
    if path.suffix.lower() == ".csv":
        with open(path, newline="", encoding="utf-8-sig") as f:
            return [{k: (v or "").strip() for k, v in row.items() if k} for row in csv.DictReader(f)]
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise SeedError("a seed JSON file must contain a list of entries")
    return data


def import_file(ctx: Context, path: Path) -> dict:
    """Import a JSON or CSV seed file. CSV rows with no footage column are skipped (candidates not filled in)."""
    added, skipped, failed = [], [], []
    for n, entry in enumerate(read_entries(path), start=1):
        if path.suffix.lower() == ".csv" and not any(entry.get(k) for k in ("youtube", "video", "images", "phashes")):
            skipped.append(f"row {n}: no footage given yet")
            continue
        try:
            row, msg = add_entry(ctx, entry, base_dir=path.parent)
        except SeedError as exc:
            failed.append(f"{'row' if path.suffix == '.csv' else 'entry'} {n}: {exc}")
            continue
        (added if row else skipped).append(f"{n}: {msg}")
    return {"added": added, "skipped": skipped, "failed": failed}


def export_entries(ctx: Context, kind: str | None = "debunked") -> list[dict]:
    """Seed-format entries (hashes only) for sharing or committing a curated pack."""
    out = []
    for r in ctx.store.footage_all(kind=kind):
        entry = {"source_url": r["source_url"] or "", "first_seen": r["first_seen"],
                 "claim_note": r["claim_note"] or "", "fact_check_url": r["fact_check_url"] or "",
                 "phashes": r["phashes"]}
        if kind is None:
            entry["kind"] = r["kind"]
        out.append(entry)
    return out


def harvest(ctx: Context, queries: list[str], out: Path, append: bool = True) -> tuple[int, list[str]]:
    """Write Fact Check API claims rated false to a candidates CSV. Returns (new rows, errors)."""
    existing: set[str] = set()
    if append and out.is_file():
        existing = {r.get("fact_check_url", "") for r in read_entries(out)}
    rows, errors = [], []
    for q in queries:
        try:
            data = factcheck_api.query(ctx, q)
        except SkipCheck as exc:
            errors.append(f"{q}: {exc.detail}")
            break
        except HttpError as exc:
            errors.append(f"{q}: {exc}")
            continue
        for c in data.get("claims", []):
            for review in c.get("claimReview", []):
                url = review.get("url", "")
                if not url or url in existing or not factcheck_api.rating_is_false(review.get("textualRating", "")):
                    continue
                existing.add(url)
                rows.append({
                    "claim_note": (review.get("title") or c.get("text", ""))[:200], "first_seen": "",
                    "source_url": "", "youtube": "", "video": "", "images": "", "phashes": "", "fact_check_url": url,
                    "rating": review.get("textualRating", ""),
                    "publisher": (review.get("publisher") or {}).get("name", ""),
                    "review_date": (review.get("reviewDate") or "")[:10], "claim_text": c.get("text", "")[:300],
                })
    new_file = not (append and out.is_file())
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "a" if not new_file else "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        if new_file:
            w.writeheader()
        w.writerows(rows)
    return len(rows), errors
