"""Perceptual fingerprints: pHash on the frame's content box, plus variants
that survive the edits recycled footage usually gets (letterbox bars, mirroring,
zoom/crop). Pure numpy + Pillow; optional CLIP lives in clip.py.
"""
from __future__ import annotations

import io
from functools import lru_cache

import numpy as np
from PIL import Image, ImageOps

HASH_BITS = 64


@lru_cache(maxsize=1)
def _dct_matrix(n: int = 32) -> np.ndarray:
    k = np.arange(n)
    m = np.cos(np.pi * (2 * k[None, :] + 1) * k[:, None] / (2 * n))
    m[0] *= 1 / np.sqrt(2)
    return m * np.sqrt(2 / n)


def open_image(src) -> Image.Image:
    if isinstance(src, (bytes, bytearray)):
        src = io.BytesIO(src)
    img = Image.open(src)
    img.load()
    return img.convert("RGB")


def _is_content(lines_std: np.ndarray, lines_mean: np.ndarray) -> np.ndarray:
    # A bar is a near-constant line, or a dark one with a little encoder noise.
    return ~((lines_std < 3.0) | ((lines_mean < 20.0) & (lines_std < 8.0)))


def content_box(img: Image.Image) -> Image.Image:
    """Trim flat bars from the edges: black letterboxing on 16:9 footage inside
    a 9:16 reel, YouTube's black hqdefault bars, plain colour strips."""
    gray = np.asarray(img.convert("L"), dtype=np.float32)
    h, w = gray.shape
    rows = _is_content(gray.std(axis=1), gray.mean(axis=1))
    cols = _is_content(gray.std(axis=0), gray.mean(axis=0))
    if not rows.any() or not cols.any():
        return img
    top, bottom = np.argmax(rows), h - np.argmax(rows[::-1])
    left, right = np.argmax(cols), w - np.argmax(cols[::-1])
    if (bottom - top) < 0.2 * h or (right - left) < 0.2 * w:
        return img
    return img.crop((int(left), int(top), int(right), int(bottom)))


def phash(img: Image.Image) -> str:
    gray = img.convert("L").resize((32, 32), Image.LANCZOS)
    pixels = np.asarray(gray, dtype=np.float64)
    m = _dct_matrix(32)
    dct = m @ pixels @ m.T
    low = dct[:8, :8].flatten()
    median = np.median(low[1:])
    bits = low > median
    return f"{int(''.join('1' if b else '0' for b in bits), 2):016x}"


def center_crop(img: Image.Image, keep: float = 0.8) -> Image.Image:
    w, h = img.size
    dw, dh = int(w * (1 - keep) / 2), int(h * (1 - keep) / 2)
    return img.crop((dw, dh, w - dw, h - dh))


def center_band(img: Image.Image) -> Image.Image:
    """Middle 16:9 band of a portrait frame: where reels put landscape footage
    between caption strips or over a blurred copy of itself."""
    w, h = img.size
    band = int(w * 9 / 16)
    top = (h - band) // 2
    return img.crop((0, top, w, top + band))


def variants(img: Image.Image) -> list[str]:
    """Hashes compared pairwise against a candidate's variants. The first one
    (content box) is what gets stored in the index."""
    box = content_box(img)
    out = [phash(box), phash(ImageOps.mirror(box)), phash(center_crop(box)), phash(img)]
    for src in (img, box):
        if src.size[1] > 1.3 * src.size[0]:
            band = center_band(src)
            out += [phash(band), phash(ImageOps.mirror(band))]
    return list(dict.fromkeys(out))


def stored_hashes(img: Image.Image) -> list[str]:
    """What the index keeps per frame: the content box and its centre 80%. The query side already
    tries crops of the reel; the stored crop catches the reverse, a reel that is a crop of the original
    (a 20% crop otherwise never matches: run.py bench)."""
    box = content_box(img)
    return [phash(box), phash(center_crop(box))]


def stored_from_variants(variants: list[str]) -> list[str]:
    """stored_hashes() for a keyframe whose variants() are already computed."""
    return [variants[0], variants[2]]


def image_stats(img: Image.Image) -> tuple[float, float]:
    gray = np.asarray(img.convert("L"), dtype=np.float32)
    return float(gray.mean()), float(gray.std())


def hamming(a: str, b: str) -> int:
    return (int(a, 16) ^ int(b, 16)).bit_count()


def similarity(a: str, b: str) -> float:
    return 1.0 - hamming(a, b) / HASH_BITS


def best_match(frame_variants: list[list[str]], candidate_hashes: list[str]) -> tuple[float, int | None]:
    """Highest similarity between any keyframe variant and any candidate hash.
    Returns (similarity, keyframe position) or (0.0, None)."""
    best, best_i = 0.0, None
    for i, fv in enumerate(frame_variants):
        for a in fv:
            for b in candidate_hashes:
                s = similarity(a, b)
                if s > best:
                    best, best_i = s, i
    return best, best_i


def frames_matching(frame_variants: list[list[str]], candidate_hashes: list[str], threshold: float) -> int:
    """How many distinct keyframes match the candidate at or above threshold."""
    return sum(1 for fv in frame_variants
               if any(similarity(a, b) >= threshold for a in fv for b in candidate_hashes))
