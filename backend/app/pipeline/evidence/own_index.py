"""Our own index of known footage, checked before any external API.

Two kinds of rows:
- debunked: seeded from fact-checks (source URL, first-seen date, the false
  claim, the fact-check link) with keyframe hashes, never the video itself.
- seen: fingerprints of every reel analysed, so a clip seen by this system
  months ago is caught when it resurfaces with a new caption.
Linear scan over 64-bit hashes is fast for tens of thousands of rows; move
to FAISS / pgvector when the index outgrows that."""
from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

from .. import fingerprint as fp
from ..context import Context, claim_cutoff
from ..models import Claim, Evidence, Keyframe


def lookup(ctx: Context, claim: Claim, frames: list[Keyframe], video_hash: str) -> list[Evidence]:
    usable = [k for k in frames if k.usable] or frames
    frame_variants = [k.variants for k in usable]
    weak = ctx.settings.weak_similarity
    before = (claim_cutoff(ctx, claim) - timedelta(days=ctx.settings.date_tolerance_days)).isoformat()
    out: list[Evidence] = []
    for row in ctx.store.footage_all():
        if row["video_hash"] and row["video_hash"] == video_hash:
            continue  # the same upload analysed before is not independent evidence
        sim, pos = fp.best_match(frame_variants, row["phashes"])
        if sim < weak:
            continue
        n = fp.frames_matching(frame_variants, row["phashes"], weak)
        earlier = bool(row["first_seen"] and row["first_seen"] < before)
        seen = row["kind"] == "seen"
        out.append(Evidence(
            source="own_index",
            title=row["claim_note"] or ("Seen in an earlier check" if seen else "Known recycled footage"),
            url=row["source_url"] or "",
            date=row["first_seen"],
            similarity=round(sim, 3),
            matched_frame=usable[pos].index if pos is not None else None,
            notes=(f"{n} reel keyframe(s) match. "
                   + ("Fingerprint from an earlier reel checked here." if seen else "Seeded from a fact-check.")
                   + (f" Fact-check: {row['fact_check_url']}" if row["fact_check_url"] else "")),
            supports="earlier_footage" if earlier else "lead",
        ))
        if row["kind"] == "debunked" and row["fact_check_url"] and sim >= ctx.settings.strong_similarity:
            out.append(Evidence(source="own_index", title=f"Fact-check of this footage: {row['claim_note']}",
                                url=row["fact_check_url"], date=row["first_seen"], similarity=round(sim, 3),
                                rating="debunked footage", relevance=1.0, supports="debunk",
                                notes="The same footage is in our index of debunked videos."))
    out.sort(key=lambda e: e.similarity or 0, reverse=True)
    return out[:6]


def remember(ctx: Context, frames: list[Keyframe], video_hash: str) -> bool:
    """Add an analysed reel's fingerprints (hashes only, no identity)."""
    if ctx.store.footage_has_video(video_hash):
        return False
    hashes = [k.phash for k in frames if k.usable]
    if not hashes:
        return False
    ctx.store.footage_add(kind="seen", phashes=hashes, first_seen=date.today().isoformat(),
                          video_hash=video_hash)
    return True


def import_seed(ctx: Context, path: Path) -> int:
    """Load debunked-footage entries from a seed JSON list (see data/seed/README.md)."""
    entries = json.loads(path.read_text(encoding="utf-8"))
    n = 0
    for e in entries:
        hashes = e.get("phashes") or []
        if not hashes:
            continue
        ctx.store.footage_add(kind="debunked", phashes=hashes, source_url=e.get("source_url", ""),
                              first_seen=e.get("first_seen"), claim_note=e.get("claim_note", ""),
                              fact_check_url=e.get("fact_check_url", ""))
        n += 1
    return n
