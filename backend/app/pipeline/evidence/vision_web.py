"""Google Cloud Vision Web Detection, the last resort: only for the best 2
frames and only when nothing else found earlier footage. Results carry no
upload date, so they are leads for a human, never proof on their own.
(Vision needs billing enabled on the Cloud project even inside the free
1,000 units/month.)"""
from __future__ import annotations

import base64
import re

from ...core.http import HttpError
from ..context import Context, SkipCheck
from ..extract import jpeg_bytes, pick_frames
from ..models import Evidence, Keyframe

URL = "https://vision.googleapis.com/v1/images:annotate"


def search(ctx: Context, frames: list[Keyframe]) -> list[Evidence]:
    if not ctx.settings.vision_enabled:
        raise SkipCheck("skipped", "disabled (VISION_ENABLED=false)")
    if not ctx.settings.vision_key:
        raise SkipCheck("skipped", "no GOOGLE_API_KEY (Cloud Vision)")
    best = pick_frames(frames, 2)
    key = "vision:" + ",".join(k.phash for k in best)
    data = ctx.store.cache_get(key, ctx.settings.cache_ttl_days)
    if data is None:
        if not ctx.store.quota_take("vision", len(best), ctx.settings.vision_monthly_units, monthly=True):
            raise SkipCheck("quota", "monthly Vision budget used up")
        body = {"requests": [{
            "image": {"content": base64.b64encode(jpeg_bytes(k.path, 1024)).decode()},
            "features": [{"type": "WEB_DETECTION", "maxResults": 10}],
        } for k in best]}
        try:
            data = ctx.http.post_json(URL, body, params={"key": ctx.settings.vision_key})
        except HttpError as exc:
            raise SkipCheck("failed", str(exc)) from None
        ctx.store.cache_put(key, data)

    out: dict[str, Evidence] = {}
    for frame, resp in zip(best, data.get("responses", []), strict=False):
        web = resp.get("webDetection", {})
        for page in web.get("pagesWithMatchingImages", []):
            url = page.get("url")
            if not url or url in out:
                continue
            full = bool(page.get("fullMatchingImages"))
            out[url] = Evidence(
                source="vision_web", title=_strip_tags(page.get("pageTitle", "")) or url, url=url,
                matched_frame=frame.index,
                notes=("Full image match" if full else "Partial image match")
                + "; open the page to see when it was published.",
                supports="lead",
            )
    ranked = sorted(out.values(), key=lambda e: e.notes.startswith("Full"), reverse=True)
    return ranked[:6]


def _strip_tags(s: str) -> str:
    return re.sub(r"<[^>]+>", "", s).strip()
