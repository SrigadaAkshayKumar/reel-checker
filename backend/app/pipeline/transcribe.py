"""Speech to text with faster-whisper (optional dependency). `base` first, then
`small` when confidence is low. Returns None when Whisper is unavailable or
still unsure, so the claim step can hand the audio to Gemini instead (which
is much better on Telugu)."""
from __future__ import annotations

import math
from functools import lru_cache
from pathlib import Path

from ..core.config import Settings
from .models import Transcript


@lru_cache(maxsize=2)
def _model(name: str):
    from faster_whisper import WhisperModel  # optional dependency
    return WhisperModel(name, device="cpu", compute_type="int8")


def _run(model_name: str, audio: Path) -> Transcript:
    segments, info = _model(model_name).transcribe(str(audio), beam_size=5, vad_filter=True)
    texts, weights, logprobs = [], [], []
    for seg in segments:
        texts.append(seg.text.strip())
        dur = max(seg.end - seg.start, 0.1)
        weights.append(dur)
        logprobs.append(seg.avg_logprob * dur)
    text = " ".join(t for t in texts if t)
    if not text:
        return Transcript(text="", language=info.language, confidence=0.0, engine=f"whisper-{model_name}")
    speech_conf = math.exp(sum(logprobs) / sum(weights))
    confidence = min(speech_conf, info.language_probability)
    return Transcript(text=text, language=info.language, confidence=round(confidence, 3),
                      engine=f"whisper-{model_name}")


def transcribe(audio: Path | None, settings: Settings) -> tuple[Transcript | None, str]:
    """Returns (transcript or None, status detail)."""
    if audio is None:
        return None, "no audio track"
    try:
        import faster_whisper  # noqa: F401
    except ImportError:
        return None, "faster-whisper not installed (pip install -r requirements-ml.txt)"
    best: Transcript | None = None
    for name in dict.fromkeys([settings.whisper_model, settings.whisper_fallback_model]):
        try:
            result = _run(name, audio)
        except Exception as exc:  # model download / load problems
            return best, f"whisper-{name} failed: {exc.__class__.__name__}: {str(exc)[:120]}"
        if best is None or result.confidence > best.confidence:
            best = result
        if best.confidence >= settings.whisper_min_confidence or not best.text:
            break
    if best and not best.text:
        return best, "no speech detected"
    if best and best.confidence < settings.whisper_min_confidence:
        return best, f"low confidence {best.confidence:.2f} ({best.language}); Gemini will listen too"
    return best, f"{best.engine}, {best.language}, confidence {best.confidence:.2f}"
