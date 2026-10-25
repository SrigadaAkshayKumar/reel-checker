"""Data passed between pipeline stages; everything serialises to the report JSON."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field

DEBUNKED = "DEBUNKED"
LIKELY_OLD_FOOTAGE = "LIKELY_OLD_FOOTAGE"
NO_CONTRADICTION_FOUND = "NO_CONTRADICTION_FOUND"
UNVERIFIED = "UNVERIFIED"

VERDICT_LABELS = {
    DEBUNKED: "Debunked",
    LIKELY_OLD_FOOTAGE: "Likely old footage",
    NO_CONTRADICTION_FOUND: "No contradiction found",
    UNVERIFIED: "Unverified",
}


@dataclass
class MediaInfo:
    path: str
    sha256: str
    duration: float
    width: int
    height: int
    has_audio: bool
    size_bytes: int


@dataclass
class Keyframe:
    index: int
    time: float
    path: str
    brightness: float  # mean luma 0-255
    detail: float      # luma std-dev; near 0 means a flat frame that hashes poorly
    phash: str = ""                                    # hash of the content box
    variants: list[str] = field(default_factory=list)  # content box, mirrored, centre crop

    @property
    def usable(self) -> bool:
        return self.detail >= 8.0 and self.brightness >= 20.0


@dataclass
class Transcript:
    text: str
    language: str
    confidence: float | None  # None when the engine gives no score (Gemini)
    engine: str


@dataclass
class Claim:
    claim_text: str = ""
    event: str = ""
    location: str = ""
    claimed_date: str | None = None  # ISO date the reel says the event happened
    recency: str = "none"            # current | dated | none
    keywords: list[str] = field(default_factory=list)
    search_queries: list[str] = field(default_factory=list)     # describe the visible footage
    factcheck_queries: list[str] = field(default_factory=list)  # describe the claim
    language: str = ""
    visual_description: str = ""
    engine: str = ""

    @property
    def has_content(self) -> bool:
        return bool(self.claim_text or self.event or self.keywords)


@dataclass
class Evidence:
    source: str             # fact_check | youtube | own_index | vision_web
    title: str
    url: str
    date: str | None = None          # ISO date the item was published / first seen
    similarity: float | None = None  # best pHash similarity to a reel keyframe
    clip_similarity: float | None = None
    matched_frame: int | None = None
    publisher: str = ""
    rating: str = ""
    relevance: float | None = None
    thumbnail_url: str = ""
    notes: str = ""
    supports: str = "lead"  # debunk | earlier_footage | lead

    def to_dict(self) -> dict:
        d = asdict(self)
        return {k: v for k, v in d.items() if v not in (None, "")}


@dataclass
class Check:
    name: str
    status: str  # ok | skipped | failed | quota
    detail: str = ""
    seconds: float = 0.0


def to_jsonable(obj):
    if hasattr(obj, "to_dict"):
        return obj.to_dict()
    if hasattr(obj, "__dataclass_fields__"):
        return asdict(obj)
    return obj
