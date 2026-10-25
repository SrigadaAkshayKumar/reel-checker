"""On-screen text from keyframes. EasyOCR (Telugu, Hindi, English) or the
tesseract binary when installed; otherwise None, and the claim step asks
Gemini to read the frames it already receives."""
from __future__ import annotations

import shutil
import subprocess
import unicodedata
from functools import lru_cache

from ..core.config import Settings
from .models import Keyframe


@lru_cache(maxsize=4)
def _easyocr_reader(langs: tuple[str, ...]):
    import easyocr  # optional dependency
    return easyocr.Reader(list(langs), gpu=False, verbose=False)


def _easyocr(paths: list[str]) -> list[str]:
    # EasyOCR can't mix Devanagari and Telugu in one reader; run both.
    lines: list[str] = []
    for langs in (("en", "hi"), ("en", "te")):
        reader = _easyocr_reader(langs)
        for p in paths:
            for _box, text, conf in reader.readtext(p):
                if conf >= 0.4:
                    lines.append(text)
    return lines


def _tesseract(paths: list[str]) -> list[str]:
    lines: list[str] = []
    for p in paths:
        res = subprocess.run(["tesseract", p, "-", "-l", "eng+hin+tel"], capture_output=True,
                             text=True, timeout=60)
        if res.returncode != 0:  # language packs missing: English only
            res = subprocess.run(["tesseract", p, "-"], capture_output=True, text=True, timeout=60)
        lines += res.stdout.splitlines()
    return lines


def _norm(s: str) -> str:
    return " ".join(unicodedata.normalize("NFC", s).split()).strip()


def dedupe_lines(lines: list[str]) -> list[str]:
    seen, out = set(), []
    for line in map(_norm, lines):
        key = line.casefold()
        if len(key) < 2 or key in seen:
            continue
        seen.add(key)
        out.append(line)
    return out


def _engine(settings: Settings) -> str:
    choice = settings.ocr_engine
    if choice != "auto":
        return choice
    try:
        import easyocr  # noqa: F401
        return "easyocr"
    except ImportError:
        pass
    if shutil.which("tesseract"):
        return "tesseract"
    return "gemini"


def read_text(frames: list[Keyframe], settings: Settings) -> tuple[list[str] | None, str, str]:
    """Returns (lines or None if not done locally, engine, status detail)."""
    engine = _engine(settings)
    if engine in ("gemini", "none"):
        return None, engine, "handled by Gemini with the claim" if engine == "gemini" else "disabled"
    paths = [k.path for k in frames if k.brightness >= 15][:8]
    try:
        raw = _easyocr(paths) if engine == "easyocr" else _tesseract(paths)
    except Exception as exc:
        return None, "gemini", f"{engine} failed ({exc.__class__.__name__}); Gemini will read the frames"
    lines = dedupe_lines(raw)
    return lines, engine, f"{engine}: {len(lines)} lines"
