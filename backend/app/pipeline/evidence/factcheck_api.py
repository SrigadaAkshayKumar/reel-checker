"""Google Fact Check Tools API: has a fact-checker already reviewed this claim?"""
from __future__ import annotations

from ...core.http import HttpError
from ..context import Context, SkipCheck
from ..models import Claim, Evidence
from ..text import normalize, overlap, terms

URL = "https://factchecktools.googleapis.com/v1alpha1/claims:search"

# Ratings that mean "the claim is not what it says". Matched as substrings.
FALSE_RATINGS = (
    "false", "fake", "untrue", "misleading", "mislead", "altered", "doctored", "edited", "manipulated",
    "out of context", "missing context", "lacks context", "old video", "old image", "old footage",
    "recycled", "unrelated", "incorrect", "wrong", "hoax", "scam", "satire", "no evidence",
    "unproven", "distorted", "exaggerat", "pants on fire", "four pinocchios", "baseless", "fabricated",
    "फर्जी", "झूठ", "भ्रामक", "गलत", "फेक", "पुराना", "भ्रम",
    "తప్పు", "ఫేక్", "అబద్ధ", "పాత", "తప్పుదోవ", "నకిలీ",
)


def rating_is_false(rating: str) -> bool:
    r = normalize(rating)
    return any(word in r for word in FALSE_RATINGS)


def claim_terms(claim: Claim) -> set[str]:
    return terms(" ".join([*claim.keywords, claim.event, claim.location]))


def _query(ctx: Context, q: str) -> dict:
    key = f"fc:{normalize(q)}"
    cached = ctx.store.cache_get(key, ctx.settings.cache_ttl_days)
    if cached is not None:
        return cached
    if not ctx.store.quota_take("factcheck", 1, ctx.settings.factcheck_daily_limit):
        raise SkipCheck("quota", "daily Fact Check budget used up")
    data = ctx.http.get_json(URL, params={"query": q, "pageSize": 10, "key": ctx.settings.factcheck_key})
    ctx.store.cache_put(key, data)
    return data


def search(ctx: Context, claim: Claim) -> list[Evidence]:
    if not ctx.settings.factcheck_key:
        raise SkipCheck("skipped", "no GOOGLE_API_KEY (Fact Check Tools API)")
    queries = claim.factcheck_queries or ([claim.claim_text] if claim.claim_text else [])
    if not queries:
        raise SkipCheck("skipped", "no claim text to search")
    wanted = claim_terms(claim)
    found: dict[str, Evidence] = {}
    errors = []
    for q in queries[:3]:
        try:
            data = _query(ctx, q)
        except HttpError as exc:
            errors.append(str(exc))
            continue
        for c in data.get("claims", []):
            for review in c.get("claimReview", []):
                url = review.get("url", "")
                if not url or url in found:
                    continue
                rating = review.get("textualRating", "")
                doc = " ".join([c.get("text", ""), review.get("title", "")])
                relevance = overlap(wanted, doc) if wanted else 0.0
                is_false = rating_is_false(rating)
                found[url] = Evidence(
                    source="fact_check",
                    title=review.get("title") or c.get("text", "")[:140],
                    url=url,
                    date=(review.get("reviewDate") or c.get("claimDate") or "")[:10] or None,
                    publisher=review.get("publisher", {}).get("name") or review.get("publisher", {}).get("site", ""),
                    rating=rating,
                    relevance=round(relevance, 2),
                    notes=f"Reviewed claim: {c.get('text', '')[:200]}",
                    supports="debunk" if is_false and relevance >= ctx.settings.factcheck_min_relevance else "lead",
                )
    if errors and not found:
        raise SkipCheck("failed", errors[0])
    ranked = sorted(found.values(), key=lambda e: (e.supports == "debunk", e.relevance or 0), reverse=True)
    return [e for e in ranked if (e.relevance or 0) >= 0.2][:8]
