"""Small multilingual text helpers. Splits on whitespace and punctuation only,
because regex \\w drops Indic vowel signs and breaks Telugu/Hindi words."""
from __future__ import annotations

import re
import unicodedata

_SPLIT = re.compile(r"[\s.,;:!?\"'“”‘’()\[\]{}<>/\\|\-–—…#@*+=~`^_।॥]+")

STOPWORDS = {
    "a", "an", "the", "and", "or", "of", "in", "on", "at", "to", "for", "from", "by", "with", "is",
    "are", "was", "were", "be", "been", "this", "that", "these", "those", "it", "its", "as", "video",
    "viral", "shows", "showing", "shown", "claim", "claims", "claimed", "today", "yesterday", "new",
    "news", "breaking", "live", "watch", "after", "before", "during", "into", "over", "not", "no",
    "has", "have", "had", "will", "can", "says", "said", "how", "what", "who", "when", "where",
    "photo", "image", "footage", "clip", "reel", "post", "posts", "shared", "social", "media",
    "है", "के", "की", "का", "में", "से", "को", "और", "यह", "वीडियो", "ఈ", "లో", "మరియు", "వీడియో",
}

# Words that make a reel present itself as happening now.
RECENCY_MARKERS = (
    "today", "just now", "right now", "breaking", "live", "tonight", "this morning", "yesterday",
    "आज", "अभी", "ब्रेकिंग", "कल रात", "ఈరోజు", "నేడు", "ఇప్పుడే", "బ్రేకింగ్", "నిన్న",
)


def normalize(s: str) -> str:
    return unicodedata.normalize("NFC", s).casefold()


def tokens(s: str) -> list[str]:
    return [t for t in _SPLIT.split(normalize(s)) if t and len(t) > 1 and not t.isdigit()]


def terms(s: str) -> set[str]:
    return {t for t in tokens(s) if t not in STOPWORDS}


def has_recency_marker(s: str) -> bool:
    low = normalize(s)
    return any(m in low for m in RECENCY_MARKERS)


def overlap(query_terms: set[str], doc: str) -> float:
    """Share of the query terms (up to 6 counted) found in doc."""
    if not query_terms:
        return 0.0
    doc_terms = terms(doc)
    # Allow simple plural / inflection differences by prefix match on longer words.
    hits = sum(1 for q in query_terms
               if q in doc_terms or (len(q) >= 5 and any(d.startswith(q[:5]) for d in doc_terms)))
    return min(1.0, hits / min(len(query_terms), 6))
