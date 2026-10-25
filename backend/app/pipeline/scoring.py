"""What a piece of evidence supports (debunk / earlier_footage / lead), given thresholds.

Every evidence source classifies through `classify`, and so does the evaluator
when it re-scores saved evidence at other thresholds (`run.py eval`). Keeping
it in one place means the numbers measured in Phase 7 are the numbers
production gets.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from ..core.config import Settings
from .models import Evidence
from .text import normalize

# Fact-check ratings that mean "the claim is not what it says". Matched as substrings.
FALSE_RATINGS = (
    "false", "fake", "untrue", "misleading", "mislead", "altered", "doctored", "edited", "manipulated",
    "out of context", "missing context", "lacks context", "old video", "old image", "old footage",
    "recycled", "unrelated", "incorrect", "wrong", "hoax", "scam", "satire", "no evidence",
    "unproven", "distorted", "exaggerat", "pants on fire", "four pinocchios", "baseless", "fabricated",
    "फर्जी", "झूठ", "भ्रामक", "गलत", "फेक", "पुराना", "भ्रम",
    "తప్పు", "ఫేక్", "అబద్ధ", "పాత", "తప్పుదోవ", "నకిలీ",
)

DEBUNKED_FOOTAGE = "debunked footage"  # rating on own-index evidence that points at a fact-check


def rating_is_false(rating: str) -> bool:
    r = normalize(rating)
    return any(word in r for word in FALSE_RATINGS)


@dataclass(frozen=True)
class Thresholds:
    strong: float
    weak: float
    clip_strong: float
    factcheck_min_relevance: float
    date_tolerance_days: int

    @classmethod
    def of(cls, s: Settings) -> Thresholds:
        return cls(s.strong_similarity, s.weak_similarity, s.clip_strong, s.factcheck_min_relevance,
                   s.date_tolerance_days)


def before_date(cutoff: date, t: Thresholds) -> str:
    """Footage published before this ISO date predates the claim."""
    return (cutoff - timedelta(days=t.date_tolerance_days)).isoformat()


def footage_match(e: Evidence, t: Thresholds) -> bool:
    """Is this the same footage? The own index needs one strong frame or two weak ones (chance
    matches in a large index, see own_index.match); a YouTube result's handful of images can't
    produce those, so one weak frame is enough there."""
    sim = e.similarity or 0.0
    if (e.clip_similarity or 0.0) >= t.clip_strong:
        return True
    if e.source == "own_index":
        return sim >= t.strong or (sim >= t.weak and (e.frames_matching or 0) >= 2)
    return sim >= t.weak


def classify(e: Evidence, cutoff: date, t: Thresholds) -> str:
    if e.source == "fact_check":
        relevant = (e.relevance or 0.0) >= t.factcheck_min_relevance
        return "debunk" if relevant and rating_is_false(e.rating) else "lead"
    if e.source == "own_index" and e.rating == DEBUNKED_FOOTAGE:
        return "debunk" if (e.similarity or 0.0) >= t.strong else "lead"
    if e.source in ("youtube", "own_index"):
        earlier = bool(e.date and e.date < before_date(cutoff, t))
        return "earlier_footage" if earlier and footage_match(e, t) else "lead"
    return "lead"  # vision_web: no dates, so never proof on its own


def reclassify(evidence: list[Evidence], cutoff: date, t: Thresholds) -> list[Evidence]:
    for e in evidence:
        e.supports = classify(e, cutoff, t)
    return evidence
