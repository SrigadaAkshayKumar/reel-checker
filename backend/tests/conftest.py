from __future__ import annotations

import io
import json
import subprocess
from pathlib import Path

import numpy as np
import pytest
from PIL import Image, ImageDraw

from app.core.config import Settings
from app.core.http import HttpError
from app.db.store import Store
from app.pipeline import transcribe


def scene(seed: int, size=(640, 360)) -> Image.Image:
    """A textured synthetic 'footage' frame; different seeds look unrelated."""
    w, h = size
    r = np.random.default_rng(seed)
    yy, xx = np.mgrid[0:h, 0:w]
    base = np.stack([60 + yy * 0.2, 100 + xx * 0.05, 150 + yy * 0.1], -1) + r.normal(0, 6, (h, w, 3))
    img = Image.fromarray(np.clip(base, 0, 255).astype("uint8"))
    d = ImageDraw.Draw(img)
    for _ in range(12):
        x, y = r.integers(0, w - 40), r.integers(0, h - 40)
        d.ellipse([x, y, x + r.integers(30, 160), y + r.integers(30, 120)],
                  fill=tuple(int(v) for v in r.integers(0, 255, 3)))
    return img


def jpeg(img: Image.Image, quality: int = 60) -> bytes:
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=quality)
    return buf.getvalue()


def yt_thumb(img: Image.Image) -> bytes:
    """YouTube hqdefault style: 480x360 with black bars."""
    canvas = Image.new("RGB", (480, 360))
    canvas.paste(img.resize((480, 270)), (0, 45))
    return jpeg(canvas)


def reel_frame(img: Image.Image, caption: str = "") -> Image.Image:
    """Landscape footage letterboxed into a 9:16 reel, with a caption strip."""
    canvas = Image.new("RGB", (360, 640))
    canvas.paste(img.resize((360, 202)), (0, 219))
    if caption:
        ImageDraw.Draw(canvas).text((16, 120), caption, fill=(255, 255, 255))
    return canvas


def make_video(path: Path, frames: list[Image.Image], seconds_each: float = 2.0, audio: bool = True) -> Path:
    tmp = path.parent / f"{path.stem}_src"
    tmp.mkdir(exist_ok=True)
    inputs, filters = [], []
    for i, img in enumerate(frames):
        p = tmp / f"{i}.png"
        img.save(p)
        inputs += ["-loop", "1", "-t", str(seconds_each), "-framerate", "25", "-i", str(p)]
        filters.append(f"[{i}:v]scale=360:640,setsar=1,format=yuv420p[v{i}]")
    n = len(frames)
    graph = ";".join(filters) + ";" + "".join(f"[v{i}]" for i in range(n)) + f"concat=n={n}:v=1:a=0[v]"
    cmd = ["ffmpeg", "-v", "error", "-y", *inputs]
    if audio:
        cmd += ["-f", "lavfi", "-t", str(seconds_each * n), "-i", "sine=f=330"]
    cmd += ["-filter_complex", graph, "-map", "[v]"]
    if audio:
        cmd += ["-map", f"{n}:a", "-c:a", "aac", "-shortest"]
    cmd += ["-c:v", "libx264", "-pix_fmt", "yuv420p", str(path)]
    subprocess.run(cmd, check=True)
    return path


class FakeHttp:
    """Routes requests by URL substring. Handlers get (url, params, body)."""

    def __init__(self):
        self.json_routes: list[tuple[str, object]] = []
        self.bytes_routes: dict[str, bytes] = {}
        self.calls: list[tuple[str, str, dict | None, dict | None]] = []

    def route(self, fragment: str, handler):
        self.json_routes.append((fragment, handler))

    def _json(self, method, url, params, body):
        self.calls.append((method, url, params, body))
        for fragment, handler in self.json_routes:
            if fragment in url:
                result = handler(url, params, body) if callable(handler) else handler
                if isinstance(result, Exception):
                    raise result
                return result
        raise HttpError(404, f"no fake route for {url}")

    def get_json(self, url, params=None, headers=None):
        return self._json("GET", url, params, None)

    def post_json(self, url, body, params=None, headers=None, timeout=None):
        return self._json("POST", url, params, body)

    def get_bytes(self, url):
        self.calls.append(("BYTES", url, None, None))
        if url in self.bytes_routes:
            return self.bytes_routes[url]
        raise HttpError(404, "not found")

    def count(self, fragment: str) -> int:
        return sum(1 for c in self.calls if fragment in c[1])


def gemini_reply(payload: dict) -> dict:
    return {"candidates": [{"content": {"parts": [{"text": json.dumps(payload)}]}}]}


def gemini_handler(claim: dict, summary: str = "Summary from evidence."):
    def handler(url, params, body):
        props = body["generationConfig"]["responseSchema"]["properties"]
        if "summary" in props:
            return gemini_reply({"summary": summary, "summary_local": ""})
        return gemini_reply(claim)
    return handler


@pytest.fixture(autouse=True)
def no_whisper(monkeypatch):
    """Tests never load Whisper models (they need a download)."""
    monkeypatch.setattr(transcribe, "transcribe", lambda audio, settings: (None, "disabled in tests"))


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(gemini_api_key="test-gemini", google_api_key="test-google",
                    data_dir=tmp_path / "data", db_path=tmp_path / "data" / "test.sqlite",
                    uploads_dir=tmp_path / "data" / "uploads", output_dir=tmp_path / "out", ocr_engine="gemini")


@pytest.fixture
def store(settings):
    s = Store(settings.db_path)
    yield s
    s.close()


@pytest.fixture
def http():
    return FakeHttp()
