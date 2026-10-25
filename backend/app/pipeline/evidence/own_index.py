"""Our own index of known footage, checked before any external API.

Two kinds of rows:
- debunked: seeded from fact-checks (source URL, first-seen date, the false
  claim, the fact-check link) with keyframe hashes, never the video itself.
  See seeding.py and data/seed/README.md.
- seen: fingerprints of every reel analysed, so footage seen by this system
  before is caught when it resurfaces with a new caption. A re-upload of
  footage already in the index adds a sighting to that row instead of a
  near-duplicate row.

Matching is vectorised: all stored 64-bit hashes sit in one numpy array and
each keyframe variant is compared with a popcount over the whole array, which
stays fast into the millions of hashes (the same thing a FAISS binary index
does). The array is cached per database and rebuilt when rows change.
"""
from __future__ import annotations

import io
import threading
from dataclasses import dataclass
from datetime import date
from math import comb

import numpy as np

from .. import fingerprint as fp
from ..context import Context, claim_cutoff
from ..models import Claim, Evidence, Keyframe
from ..scoring import DEBUNKED_FOOTAGE, Thresholds, classify


@dataclass
class FootageIndex:
    version: tuple[int, int]
    rows: list[dict]            # rows that have hashes, in array order (no phashes / embeddings)
    hashes: np.ndarray          # uint64, all rows' hashes concatenated
    starts: np.ndarray          # index into `hashes` where each row begins
    embeddings: dict[int, np.ndarray]  # row position → (n, d) float32, unit length


@dataclass
class Match:
    row: dict
    similarity: float           # best pHash similarity over keyframes × variants × row hashes
    frame: int | None           # position in the usable-frame list
    frames_matching: int        # keyframes at or above the weak threshold
    clip_similarity: float | None = None


_cache: dict[str, FootageIndex] = {}
_lock = threading.Lock()


def _u64(hexes: list[str]) -> np.ndarray:
    return np.array([int(h, 16) for h in hexes], dtype=np.uint64)


def encode_embeddings(emb: np.ndarray) -> bytes:
    buf = io.BytesIO()
    np.save(buf, emb.astype(np.float16), allow_pickle=False)
    return buf.getvalue()


def decode_embeddings(blob: bytes) -> np.ndarray:
    emb = np.load(io.BytesIO(blob), allow_pickle=False).astype(np.float32)
    return emb / np.maximum(np.linalg.norm(emb, axis=1, keepdims=True), 1e-6)


def load_index(ctx: Context) -> FootageIndex:
    key = str(ctx.store.path)
    version = ctx.store.footage_version()
    with _lock:
        cached = _cache.get(key)
        if cached and cached.version == version:
            return cached
        rows, chunks, starts, embeddings, offset = [], [], [], {}, 0
        for r in ctx.store.footage_all(with_embeddings=True):
            hashes = r.pop("phashes")
            blob = r.pop("embeddings", None)
            if not hashes:
                continue
            if blob:
                embeddings[len(rows)] = decode_embeddings(blob)
            starts.append(offset)
            chunks.append(_u64(hashes))
            offset += len(hashes)
            rows.append(r)
        index = FootageIndex(version, rows,
                             np.concatenate(chunks) if chunks else np.zeros(0, dtype=np.uint64),
                             np.array(starts, dtype=np.int64), embeddings)
        _cache[key] = index
        return index


def match(index: FootageIndex, frame_variants: list[list[str]], weak: float, strong: float,
          reel_embeddings: np.ndarray | None = None, clip_strong: float = 1.1) -> list[Match]:
    """Rows that match: best similarity >= strong, or >= weak on at least two different keyframes,
    or a CLIP score >= clip_strong.

    The two-frame rule matters at scale: against 1M stored hashes a reel makes ~1e8 comparisons,
    and chance alone puts ~20 random rows above 0.80 on a single frame. Two independent frames
    of the same row at that level essentially never happen by chance (~0.002 per reel)."""
    n = len(index.rows)
    if n == 0 or not frame_variants:
        return []
    best = np.zeros(n)
    best_frame = np.full(n, -1)
    counts = np.zeros(n, dtype=np.int64)
    for fi, variants in enumerate(frame_variants):
        dist = np.bitwise_count(_u64(variants)[:, None] ^ index.hashes[None, :]).min(axis=0)
        sim = 1.0 - np.minimum.reduceat(dist, index.starts) / fp.HASH_BITS
        better = sim > best
        best[better] = sim[better]
        best_frame[better] = fi
        counts += sim >= weak
    clip_scores: dict[int, float] = {}
    if reel_embeddings is not None and len(reel_embeddings):
        for pos, emb in index.embeddings.items():
            clip_scores[pos] = float((reel_embeddings @ emb.T).max())
    out = []
    for pos in range(n):
        clip_sim = clip_scores.get(pos)
        if (best[pos] >= strong or (best[pos] >= weak and counts[pos] >= 2)
                or (clip_sim is not None and clip_sim >= clip_strong)):
            out.append(Match(index.rows[pos], float(best[pos]),
                             int(best_frame[pos]) if best_frame[pos] >= 0 else None,
                             int(counts[pos]), clip_sim))
    out.sort(key=lambda m: max(m.similarity, m.clip_similarity or 0), reverse=True)
    return out


def chance_matches(strong: float, weak: float, index_fingerprints: int = 1_000_000, frames: int = 12,
                   variants: int = 7, per_row: int = 24) -> float:
    """Expected unrelated rows matched per reel *by chance* under the match rule, if fingerprints were
    random 64-bit strings. Real images are less random than that, so treat it as a lower bound: keep it
    far below 1. With the defaults (1M fingerprints, 12 frames x 7 variants, 24 hashes per row):
    strong 0.90 / weak 0.80 gives ~0.004 per reel; weak 0.78 gives ~0.8; weak 0.74 over 100."""
    def tail(w: float) -> float:  # P(similarity >= w) for one random pair
        d = int(np.floor((1 - w) * fp.HASH_BITS + 1e-9))
        return sum(comb(fp.HASH_BITS, k) for k in range(d + 1)) / 2 ** fp.HASH_BITS

    def per_frame(w: float) -> float:  # P(a keyframe reaches w against some hash of one row)
        return 1 - (1 - tail(w)) ** (variants * per_row)

    rows = index_fingerprints / per_row
    return rows * (frames * per_frame(strong) + comb(frames, 2) * per_frame(weak) ** 2)


def reel_embeddings(ctx: Context, frames: list[Keyframe]) -> np.ndarray | None:
    """CLIP embeddings of the reel's frames, when USE_CLIP is on and CLIP is installed."""
    if not ctx.settings.use_clip:
        return None
    from .. import clip
    if not clip.available():
        return None
    emb = clip.embed([fp.content_box(fp.open_image(k.path)) for k in frames])
    return emb / np.maximum(np.linalg.norm(emb, axis=1, keepdims=True), 1e-6)


def _usable(frames: list[Keyframe]) -> list[Keyframe]:
    return [k for k in frames if k.usable] or frames


def find(ctx: Context, frames: list[Keyframe], video_hash: str = "") -> list[Match]:
    usable = _usable(frames)
    matches = match(load_index(ctx), [k.variants for k in usable], ctx.settings.weak_similarity,
                    ctx.settings.strong_similarity, reel_embeddings(ctx, usable), ctx.settings.clip_strong)
    # The same upload analysed before is not independent evidence.
    return [m for m in matches if not (video_hash and m.row["video_hash"] == video_hash)]


def report_link(ctx: Context, report_id: str | None) -> str:
    return f"{ctx.settings.public_base_url.rstrip('/')}/r/{report_id}" if report_id else ""


def lookup(ctx: Context, claim: Claim, frames: list[Keyframe], video_hash: str) -> list[Evidence]:
    usable = _usable(frames)
    cutoff = claim_cutoff(ctx, claim)
    t = Thresholds.of(ctx.settings)
    out: list[Evidence] = []
    for m in find(ctx, frames, video_hash):
        row = m.row
        seen = row["kind"] == "seen"
        sightings = row.get("times_seen") or 1
        notes = [f"{m.frames_matching} reel keyframe(s) match."]
        if sightings > 1:
            notes.append(f"Seen {sightings} times since {row['first_seen']}.")
        notes.append("Recorded by an earlier check here." if seen else "Seeded from a fact-check.")
        common = dict(source="own_index", date=row["first_seen"], similarity=round(m.similarity, 3),
                      clip_similarity=round(m.clip_similarity, 3) if m.clip_similarity is not None else None,
                      frames_matching=m.frames_matching,
                      matched_frame=usable[m.frame].index if m.frame is not None else None)
        out.append(Evidence(
            title=row["claim_note"] or (f"Checked here on {row['first_seen']}" if seen else "Known recycled footage"),
            url=row["source_url"] or report_link(ctx, row.get("report_id")), notes=" ".join(notes), **common))
        if row["kind"] == "debunked" and row["fact_check_url"]:
            out.append(Evidence(title=f"Fact-check of this footage: {row['claim_note']}", url=row["fact_check_url"],
                                rating=DEBUNKED_FOOTAGE, relevance=1.0,
                                notes="The same footage is in our index of debunked videos.", **common))
    for e in out:
        e.supports = classify(e, cutoff, t)
    return out[:6]


def remember(ctx: Context, frames: list[Keyframe], video_hash: str, report_id: str = "") -> str:
    """Record an analysed reel (hashes only, no identity). Returns added | merged | exists | none."""
    if ctx.store.footage_has_video(video_hash):
        return "exists"
    usable = [k for k in frames if k.usable]
    if not usable:
        return "none"
    today = date.today().isoformat()
    # Mostly the same footage as a row we have: count a sighting rather than store a near-duplicate.
    need = max(1, (len(usable) + 1) // 2)
    for m in find(ctx, usable):
        if m.similarity >= ctx.settings.strong_similarity and m.frames_matching >= need:
            ctx.store.footage_touch(m.row["id"], today)
            return "merged"
    emb = reel_embeddings(ctx, usable)
    ctx.store.footage_add(kind="seen", phashes=[h for k in usable for h in fp.stored_from_variants(k.variants)],
                          first_seen=today,
                          video_hash=video_hash, report_id=report_id,
                          embeddings=encode_embeddings(emb) if emb is not None else None)
    return "added"
