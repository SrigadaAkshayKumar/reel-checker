"""YouTube Data API v3: earlier uploads of the same footage.

Searches describe what is visibly happening (not the claimed place/date) and
are limited to videos published before the claim. For each result we hash the
custom thumbnail plus YouTube's three automatic frame grabs (1/2/3.jpg, taken
from the video itself) and compare them with the reel's keyframes. Only images
are downloaded, never videos."""
from __future__ import annotations

from datetime import date, timedelta

from ...core.http import HttpError
from .. import fingerprint as fp
from ..context import Context, SkipCheck, claim_cutoff
from ..models import Claim, Evidence, Keyframe

SEARCH = "https://www.googleapis.com/youtube/v3/search"
FRAME_URLS = ("https://i.ytimg.com/vi/{id}/hqdefault.jpg", "https://i.ytimg.com/vi/{id}/1.jpg",
              "https://i.ytimg.com/vi/{id}/2.jpg", "https://i.ytimg.com/vi/{id}/3.jpg")
SEARCH_COST = 100  # quota units per search.list call


def _search(ctx: Context, q: str, before: date) -> dict:
    key = f"yt:{q.casefold()}|{before.isoformat()}"
    cached = ctx.store.cache_get(key, ctx.settings.cache_ttl_days)
    if cached is not None:
        return cached
    if not ctx.store.quota_take("youtube", SEARCH_COST, ctx.settings.youtube_daily_units):
        raise SkipCheck("quota", "daily YouTube quota used up")
    data = ctx.http.get_json(SEARCH, params={
        "part": "snippet", "type": "video", "q": q, "maxResults": 15, "order": "relevance",
        "publishedBefore": f"{before.isoformat()}T00:00:00Z", "key": ctx.settings.youtube_key,
    })
    ctx.store.cache_put(key, data)
    return data


def _video_hashes(ctx: Context, video_id: str) -> list[str]:
    """Variant hashes of the thumbnail + frame grabs, cached per video."""
    key = f"ythash:{video_id}"
    cached = ctx.store.cache_get(key, 365)
    if cached is not None:
        return cached["hashes"]
    hashes: list[str] = []
    for tmpl in FRAME_URLS:
        try:
            hashes += fp.variants(fp.open_image(ctx.http.get_bytes(tmpl.format(id=video_id))))
        except (HttpError, OSError):
            continue
    if hashes:
        ctx.store.cache_put(key, {"hashes": hashes})
    return hashes


def search(ctx: Context, claim: Claim, frames: list[Keyframe]) -> list[Evidence]:
    if not ctx.settings.youtube_key:
        raise SkipCheck("skipped", "no GOOGLE_API_KEY (YouTube Data API v3)")
    if not claim.search_queries:
        raise SkipCheck("skipped", "no search queries")
    cutoff = claim_cutoff(ctx, claim)
    before = cutoff - timedelta(days=ctx.settings.date_tolerance_days)
    usable = [k for k in frames if k.usable] or frames
    frame_variants = [k.variants for k in usable]

    videos: dict[str, dict] = {}
    errors = []
    for q in claim.search_queries[:2]:
        try:
            data = _search(ctx, q, before)
        except HttpError as exc:
            errors.append(str(exc))
            continue
        for item in data.get("items", []):
            vid = item.get("id", {}).get("videoId")
            if vid and vid not in videos:
                videos[vid] = item.get("snippet", {})
    if errors and not videos:
        raise SkipCheck("failed", errors[0])

    out: list[Evidence] = []
    for vid, snip in videos.items():
        hashes = _video_hashes(ctx, vid)
        sim, pos = fp.best_match(frame_variants, hashes) if hashes else (0.0, None)
        published = (snip.get("publishedAt") or "")[:10] or None
        earlier = bool(published and published < before.isoformat())
        n_frames = fp.frames_matching(frame_variants, hashes, ctx.settings.weak_similarity) if hashes else 0
        out.append(Evidence(
            source="youtube",
            title=snip.get("title", ""),
            url=f"https://www.youtube.com/watch?v={vid}",
            date=published,
            similarity=round(sim, 3) if hashes else None,
            matched_frame=usable[pos].index if pos is not None else None,
            publisher=snip.get("channelTitle", ""),
            thumbnail_url=FRAME_URLS[0].format(id=vid),
            notes=f"{n_frames} reel keyframe(s) match" if n_frames else "",
            supports="earlier_footage" if earlier and sim >= ctx.settings.weak_similarity else "lead",
        ))
    out.sort(key=lambda e: e.similarity or 0, reverse=True)
    if ctx.settings.use_clip:
        _clip_rescore(ctx, out[:5], usable, before)
        out.sort(key=lambda e: max(e.similarity or 0, e.clip_similarity or 0), reverse=True)
    return out[:6]


def _clip_rescore(ctx: Context, candidates: list[Evidence], frames: list[Keyframe], before: date) -> None:
    """Re-score pHash near-misses (0.6 to the weak threshold) with CLIP."""
    from .. import clip
    near = [e for e in candidates if e.similarity is not None
            and 0.6 <= e.similarity < ctx.settings.weak_similarity]
    if not near or not clip.available():
        return
    reel = clip.embed([fp.content_box(fp.open_image(k.path)) for k in frames])
    for e in near:
        vid = e.url.rsplit("=", 1)[-1]
        imgs = []
        for tmpl in FRAME_URLS:
            try:
                imgs.append(fp.content_box(fp.open_image(ctx.http.get_bytes(tmpl.format(id=vid)))))
            except (HttpError, OSError):
                continue
        if imgs:
            e.clip_similarity = round(clip.best_cosine(reel, clip.embed(imgs)), 3)
            if e.clip_similarity >= ctx.settings.clip_strong and e.date and e.date < before.isoformat():
                e.supports = "earlier_footage"
