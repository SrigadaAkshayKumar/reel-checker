"""Claim extraction. One Gemini call sees the caption, the local transcript and
OCR (when we have them) and a few keyframes, plus the audio when Whisper was
missing or unsure, and returns what the reel claims and how to search for
the footage. Without Gemini, a keyword heuristic keeps the pipeline going."""
from __future__ import annotations

import re
from collections import Counter
from datetime import date

from .llm import Gemini, LLMError
from .models import Claim, Transcript
from .text import has_recency_marker, terms, tokens

SYSTEM = """You help a fact-checking tool that detects old or unrelated footage shared as new.
You extract what a short social-media video CLAIMS. You never judge whether it is true.
Use only what is in the inputs. Leave a field empty when the inputs do not say it."""

PROMPT = """Reference date (when the reel was posted or is being checked): {ref}

Caption supplied by the user:
{caption}

Speech transcript ({t_engine}):
{transcript}

On-screen text read by OCR:
{ocr}

{attached}

Return JSON:
- claim_text: one sentence in English stating what the reel says is shown (event, place, time).
- event, location: short English phrases from the claim.
- claimed_date: YYYY-MM-DD of the event as the reel presents it. Resolve "today", "yesterday",
  "आज", "ఈరోజు", "నిన్న" etc. against the reference date. Empty if the reel gives no time at all.
- recency: "current" if the reel presents it as happening now / recently / breaking,
  "dated" if it names a specific past date, "none" if it says nothing about time.
- keywords: 3-8 short English keywords for the event and place.
- search_queries: 2-3 short English YouTube queries that describe what is VISIBLY happening in the
  footage (objects, action, setting), WITHOUT the claimed place or date, because those may be false.
  Example: "plane crash runway fire" not "Hyderabad plane crash today".
- factcheck_queries: 2-3 short queries for a fact-check database: the claim in English, plus one
  in the reel's own language if it is not English.
- language: main language code of the reel (te, hi, en, ...).
- visual_description: one sentence describing what the frames show.
- transcript: verbatim speech in its original script, only if audio is attached; else empty.
- onscreen_text: text visible in the frames, in its original script, only if frames are attached
  and no OCR text was given above; else empty."""

SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "claim_text": {"type": "STRING"},
        "event": {"type": "STRING"},
        "location": {"type": "STRING"},
        "claimed_date": {"type": "STRING"},
        "recency": {"type": "STRING", "enum": ["current", "dated", "none"]},
        "keywords": {"type": "ARRAY", "items": {"type": "STRING"}},
        "search_queries": {"type": "ARRAY", "items": {"type": "STRING"}},
        "factcheck_queries": {"type": "ARRAY", "items": {"type": "STRING"}},
        "language": {"type": "STRING"},
        "visual_description": {"type": "STRING"},
        "transcript": {"type": "STRING"},
        "onscreen_text": {"type": "STRING"},
    },
    "required": ["claim_text", "recency", "keywords", "search_queries", "factcheck_queries"],
}

_ISO = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _clean_date(value: str | None) -> str | None:
    if not value or not _ISO.match(value.strip()):
        return None
    try:
        return date.fromisoformat(value.strip()).isoformat()
    except ValueError:
        return None


def _strs(items, limit: int) -> list[str]:
    out = []
    for item in items or []:
        s = " ".join(str(item).split())
        if s and s.casefold() not in {o.casefold() for o in out}:
            out.append(s[:120])
    return out[:limit]


def extract_with_gemini(llm: Gemini, *, caption: str, transcript: Transcript | None,
                        ocr_lines: list[str] | None, frames: list[bytes], audio: bytes | None,
                        reference: date) -> tuple[Claim, str, str]:
    """Returns (claim, transcript text from Gemini, on-screen text from Gemini)."""
    attached = []
    parts: list = []
    if frames:
        attached.append(f"{len(frames)} keyframes from the reel are attached as images.")
    if audio:
        attached.append("The reel's audio is attached; transcribe it.")
    parts.append(PROMPT.format(
        ref=reference.isoformat(),
        caption=caption or "(none)",
        t_engine=transcript.engine if transcript else "none",
        transcript=(transcript.text if transcript and transcript.text else "(none)")[:4000],
        ocr="\n".join(ocr_lines)[:2000] if ocr_lines else "(none)",
        attached="\n".join(attached),
    ))
    parts += [("image/jpeg", f) for f in frames]
    if audio:
        parts.append(("audio/wav", audio))
    data = llm.generate_json(parts, SCHEMA, system=SYSTEM)
    claim = Claim(
        claim_text=str(data.get("claim_text", "")).strip(),
        event=str(data.get("event", "")).strip(),
        location=str(data.get("location", "")).strip(),
        claimed_date=_clean_date(data.get("claimed_date")),
        recency=data.get("recency") if data.get("recency") in ("current", "dated", "none") else "none",
        keywords=_strs(data.get("keywords"), 8),
        search_queries=_strs(data.get("search_queries"), 3),
        factcheck_queries=_strs(data.get("factcheck_queries"), 3),
        language=str(data.get("language", "")).strip()[:8],
        visual_description=str(data.get("visual_description", "")).strip(),
        engine="gemini",
    )
    if claim.claimed_date and claim.claimed_date > reference.isoformat():
        claim.claimed_date = reference.isoformat()
    return claim, str(data.get("transcript") or "").strip(), str(data.get("onscreen_text") or "").strip()


def extract_heuristic(*, caption: str, transcript: Transcript | None, ocr_lines: list[str] | None) -> Claim:
    """No-LLM fallback: frequent content words become keywords and queries."""
    text = " ".join(filter(None, [caption, transcript.text if transcript else "", *(ocr_lines or [])]))
    content = terms(text)
    words = [t for t in tokens(text) if t in content]
    common = [w for w, _ in Counter(words).most_common(8)]
    claim_text = (caption or (ocr_lines[0] if ocr_lines else "") or (transcript.text if transcript else ""))[:200]
    query = " ".join(common[:5])
    return Claim(
        claim_text=claim_text.strip(),
        recency="current" if has_recency_marker(text) else "none",
        keywords=common,
        search_queries=[query] if query else [],
        factcheck_queries=_strs([caption[:100] if caption else "", query], 2),
        language=transcript.language if transcript else "",
        engine="heuristic",
    )


def extract_claim(llm: Gemini | None, **kwargs) -> tuple[Claim, str, str, str]:
    """Returns (claim, gemini transcript, gemini on-screen text, status detail)."""
    reference: date = kwargs["reference"]
    if llm and llm.available:
        try:
            claim, g_transcript, g_onscreen = extract_with_gemini(llm, **kwargs)
            return claim, g_transcript, g_onscreen, "gemini"
        except LLMError as exc:
            detail = f"Gemini unavailable ({exc}); used keyword heuristic"
    else:
        detail = "no GEMINI_API_KEY; used keyword heuristic"
    claim = extract_heuristic(caption=kwargs["caption"], transcript=kwargs["transcript"],
                              ocr_lines=kwargs["ocr_lines"])
    if claim.recency == "current":
        claim.claimed_date = reference.isoformat()
    return claim, "", "", detail
