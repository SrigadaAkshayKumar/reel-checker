"""ffmpeg stage: probe the upload, pull 16 kHz mono audio, and pick keyframes
(scene changes plus an even sweep, near-duplicates dropped, capped)."""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
from pathlib import Path

from PIL import Image

from . import fingerprint as fp
from .models import Keyframe, MediaInfo


class InputError(Exception):
    """The upload can't be analysed (corrupt, too long, too big, no video)."""


def _run(cmd: list[str], timeout: float = 120) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def probe(path: Path, max_seconds: float, max_mb: float) -> MediaInfo:
    if not path.is_file():
        raise InputError(f"file not found: {path}")
    size = path.stat().st_size
    if size > max_mb * 1024 * 1024:
        raise InputError(f"file is {size / 1048576:.1f} MB; the limit is {max_mb:g} MB")
    res = _run(["ffprobe", "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path)])
    if res.returncode != 0:
        raise InputError("not a readable video file (ffprobe failed)")
    data = json.loads(res.stdout or "{}")
    streams = data.get("streams", [])
    video = next((s for s in streams if s.get("codec_type") == "video"
                  and s.get("disposition", {}).get("attached_pic") != 1), None)
    if not video:
        raise InputError("no video stream found")
    duration = float(data.get("format", {}).get("duration") or video.get("duration") or 0)
    if duration <= 0:
        raise InputError("could not read the video duration")
    if duration > max_seconds:
        raise InputError(f"video is {duration:.0f} s; the limit is {max_seconds:g} s")
    width, height = int(video.get("width", 0)), int(video.get("height", 0))
    rotation = _rotation(video)
    if rotation in (90, 270):
        width, height = height, width
    return MediaInfo(path=str(path), sha256=sha256_file(path), duration=duration,
                     width=width, height=height,
                     has_audio=any(s.get("codec_type") == "audio" for s in streams),
                     size_bytes=size)


def _rotation(stream: dict) -> int:
    rot = stream.get("tags", {}).get("rotate")
    for sd in stream.get("side_data_list", []) or []:
        if "rotation" in sd:
            rot = sd["rotation"]
    try:
        return abs(int(float(rot))) % 360 if rot is not None else 0
    except ValueError:
        return 0


def extract_audio(path: Path, out_wav: Path) -> Path | None:
    res = _run(["ffmpeg", "-v", "error", "-y", "-i", str(path), "-vn", "-ac", "1", "-ar", "16000",
                "-c:a", "pcm_s16le", str(out_wav)])
    if res.returncode != 0 or not out_wav.is_file() or out_wav.stat().st_size < 1000:
        return None
    return out_wav


_PTS = re.compile(r"pts_time:([0-9.]+)")


def _scene_frames(path: Path, out_dir: Path, threshold: float, limit: int) -> list[tuple[float, Path]]:
    pattern = out_dir / "scene_%03d.jpg"
    vf = f"select='gt(scene,{threshold})',showinfo,scale='min(640,iw)':-2"
    res = _run(["ffmpeg", "-hide_banner", "-y", "-i", str(path), "-vf", vf, "-fps_mode", "vfr",
                "-frames:v", str(limit), "-q:v", "3", str(pattern)])
    times = [float(t) for t in _PTS.findall(res.stderr)]
    files = sorted(out_dir.glob("scene_*.jpg"))
    # showinfo can log one frame past the -frames:v cap, so pair up to the shorter list.
    return list(zip(times, files, strict=False))


def _frame_at(path: Path, t: float, out: Path) -> Path | None:
    res = _run(["ffmpeg", "-v", "error", "-y", "-ss", f"{t:.3f}", "-i", str(path), "-frames:v", "1",
                "-vf", "scale='min(640,iw)':-2", "-q:v", "3", str(out)])
    return out if res.returncode == 0 and out.is_file() else None


def keyframes(path: Path, info: MediaInfo, out_dir: Path, *, max_frames: int = 12,
              scene_threshold: float = 0.30) -> list[Keyframe]:
    out_dir.mkdir(parents=True, exist_ok=True)
    candidates: list[tuple[float, Path]] = []
    # Even sweep first so every part of the reel is represented.
    sweep = max(4, min(8, int(info.duration // 3) + 2))
    for i in range(sweep):
        t = info.duration * (i + 0.5) / sweep
        f = _frame_at(path, t, out_dir / f"sweep_{i:02d}.jpg")
        if f:
            candidates.append((t, f))
    candidates += _scene_frames(path, out_dir, scene_threshold, limit=max_frames * 2)
    candidates.sort(key=lambda c: c[0])

    frames: list[Keyframe] = []
    for t, f in candidates:
        img = fp.open_image(f)
        brightness, detail = fp.image_stats(img)
        variants = fp.variants(img)
        # Drop near-duplicates of a frame already kept.
        if any(fp.similarity(variants[0], k.phash) >= 0.94 for k in frames):
            f.unlink(missing_ok=True)
            continue
        frames.append(Keyframe(index=len(frames), time=round(t, 2), path=str(f),
                               brightness=round(brightness, 1), detail=round(detail, 1),
                               phash=variants[0], variants=variants))
    if len(frames) > max_frames:
        step = len(frames) / max_frames
        keep = {int(i * step) for i in range(max_frames)}
        frames = [k for i, k in enumerate(frames) if i in keep]
        for i, k in enumerate(frames):
            k.index = i
    return frames


def pick_frames(frames: list[Keyframe], n: int) -> list[Keyframe]:
    """The n most informative usable frames, spread over the reel, in time order."""
    usable = [k for k in frames if k.usable] or frames
    if len(usable) <= n:
        return usable
    ranked = sorted(usable, key=lambda k: k.detail, reverse=True)[: n * 2]
    ranked.sort(key=lambda k: k.time)
    step = len(ranked) / n
    return [ranked[int(i * step)] for i in range(n)]


def jpeg_bytes(path: str, max_side: int = 512) -> bytes:
    import io
    img = Image.open(path).convert("RGB")
    img.thumbnail((max_side, max_side))
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=80)
    return buf.getvalue()
