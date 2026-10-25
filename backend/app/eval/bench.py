"""Fingerprint robustness benchmark: no API keys, no labels needed.

  python run.py bench ~/Videos/*.mp4              any footage you have (your own phone videos are fine)
  python run.py bench --synthetic 8               generated footage, for a quick self-check

Each source video (first 30 s) is fingerprinted into an in-memory index, the way seeding does.
Then every source is put through the edits recycled footage usually gets (re-encoding, crops,
mirroring, 9:16 letterboxing, caption strips, watermarks, colour grading, blur, speed-up, a slight
rotation, picture-in-picture, a phone screen recording, an excerpt, and all of it at once). Each edited copy
is matched against the whole index:

- recall: the copy matches its own source (the edit was survived)
- false matches: the copy matches some *other* source (what a wrong flag is made of)

at every strong / weak threshold pair, using the same match rule as the own index (one frame >=
strong, or two frames >= weak). Only hashes are kept; the edited videos live in a temp dir.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from ..core.config import Settings
from ..pipeline import extract
from ..pipeline import fingerprint as fp
from ..pipeline.evidence.own_index import chance_matches

CLIP_SECONDS = 30
NORM_169 = "scale=1280:720:force_original_aspect_ratio=decrease,pad=1280:720:(ow-iw)/2:(oh-ih)/2"
FIT_916 = "scale=720:1280:force_original_aspect_ratio=decrease,pad=720:1280:(ow-iw)/2:(oh-ih)/2"

# name: (what it imitates, ffmpeg -filter_complex graph; [0:v] is the source, [1:v] a caption strip,
#        [2:v] a watermark, output label [v])
TRANSFORMS: dict[str, tuple[str, str]] = {
    "reencode": ("heavy re-compression at 480p", "[0:v]scale=480:-2[v]"),
    "crop10": ("10% crop", "[0:v]crop=iw*0.9:ih*0.9[v]"),
    "crop20": ("20% crop", "[0:v]crop=iw*0.8:ih*0.8[v]"),
    "mirror": ("mirrored", "[0:v]hflip[v]"),
    "letterbox_9x16": ("landscape clip in a vertical reel", f"[0:v]{FIT_916}[v]"),
    "blurbg_9x16": ("vertical reel over a blurred copy of itself",
                    "[0:v]split[a][b];[a]scale=720:1280:force_original_aspect_ratio=increase,crop=720:1280,"
                    "boxblur=20[bg];[b]scale=720:1280:force_original_aspect_ratio=decrease[fg];"
                    "[bg][fg]overlay=(W-w)/2:(H-h)/2[v]"),
    "caption": ("caption strip burned into the picture", f"[0:v]{NORM_169}[s];[s][1:v]overlay=0:40[v]"),
    "caption_9x16": ("vertical reel with a caption in the top bar",
                     f"[0:v]{FIT_916}[s];[1:v]scale=720:-2[c];[s][c]overlay=0:230[v]"),
    "watermark": ("channel logo in the corner", f"[0:v]{NORM_169}[s];[s][2:v]overlay=W-w-30:30[v]"),
    "color": ("colour grading", "[0:v]eq=brightness=0.06:contrast=1.25:saturation=1.5[v]"),
    "blur": ("soft / out of focus", "[0:v]gblur=sigma=2[v]"),
    "speed": ("sped up 1.33x", "[0:v]setpts=0.75*PTS[v]"),
    "rotate3": ("tilted 3 degrees", "[0:v]rotate=3*PI/180:fillcolor=black[v]"),
    "pip60": ("picture-in-picture at 60%",
              "[0:v]scale=trunc(iw*0.3)*2:-2,pad=trunc(iw/0.6/2)*2:trunc(ih/0.6/2)*2:(ow-iw)/2:(oh-ih)/2:"
              "color=gray[v]"),
    "screenrec": ("phone screen recording of the reel",
                  f"[0:v]{FIT_916}[s];[1:v]scale=720:-2[c];[s][c]overlay=0:230,scale=540:-2[v]"),
    "excerpt": ("10-second excerpt", "[0:v]trim=start=10:duration=10,setpts=PTS-STARTPTS[v]"),
    "combo": ("crop + mirror + caption + colour + heavy re-compression",
              f"[0:v]crop=iw*0.9:ih*0.9,hflip,eq=contrast=1.2:saturation=1.3,{NORM_169}[s];"
              "[s][1:v]overlay=0:40,scale=640:-2[v]"),
}
CRF = {"reencode": "38", "screenrec": "33", "combo": "35"}
INDEX_SCALE = 1_000_000   # fingerprints a production index is expected to reach
CHANCE_BUDGET = 0.01      # expected chance matches per reel allowed at that scale
STRONG_GRID = (0.84, 0.86, 0.88, 0.90, 0.92, 0.94)
WEAK_GRID = (0.70, 0.74, 0.76, 0.78, 0.80, 0.82, 0.84, 0.86)


@dataclass
class Source:
    name: str
    path: Path            # normalised 30 s clip
    hashes: np.ndarray    # uint64 seed fingerprints


def _ffmpeg(args: list[str], timeout: int = 300) -> None:
    res = subprocess.run(["ffmpeg", "-v", "error", "-y", *args], capture_output=True, text=True, timeout=timeout)
    if res.returncode != 0:
        raise RuntimeError(res.stderr.strip()[-400:])


def _assets(tmp: Path) -> tuple[Path, Path]:
    try:
        font = ImageFont.load_default(size=46)
    except TypeError:  # Pillow < 10.1
        font = ImageFont.load_default()
    cap = Image.new("RGBA", (1280, 120), (255, 255, 255, 235))
    ImageDraw.Draw(cap).text((30, 30), "BREAKING: shocking video from today, share now", fill=(0, 0, 0), font=font)
    logo = Image.new("RGBA", (220, 80), (0, 0, 0, 0))
    d = ImageDraw.Draw(logo)
    d.rounded_rectangle((0, 0, 219, 79), 14, fill=(200, 30, 30, 160))
    d.text((24, 16), "NEWS 24", fill=(255, 255, 255, 230), font=font)
    cap.save(tmp / "caption.png")
    logo.save(tmp / "logo.png")
    return tmp / "caption.png", tmp / "logo.png"


def _scene(seed: int, size: tuple[int, int] = (1920, 1080)) -> Image.Image:
    """A textured frame: gradient + noise + random shapes; different seeds look unrelated."""
    w, h = size
    r = np.random.default_rng(seed)
    yy, xx = np.mgrid[0:h, 0:w]
    base = np.stack([60 + yy * 0.12 * r.random(), 90 + xx * 0.06 * r.random(), 140 + yy * 0.05], -1)
    img = Image.fromarray(np.clip(base + r.normal(0, 6, (h, w, 3)), 0, 255).astype("uint8"))
    d = ImageDraw.Draw(img)
    for _ in range(40):
        x, y = int(r.integers(0, w - 80)), int(r.integers(0, h - 80))
        d.ellipse([x, y, x + int(r.integers(40, 360)), y + int(r.integers(40, 260))],
                  fill=tuple(int(v) for v in r.integers(0, 255, 3)))
    return img


def synthetic_sources(out: Path, n: int, seconds: int = 12) -> list[Path]:
    """Generated 'footage': textured scenes with slow camera moves and sensor noise."""
    out.mkdir(parents=True, exist_ok=True)
    paths = []
    for i in range(n):
        shots = []
        for j in range(3):
            img = out / f"s{i}_{j}.png"
            _scene(1000 + i * 10 + j).save(img)
            shots.append(img)
        inputs, graph = [], []
        per = seconds / 3
        for j, img in enumerate(shots):
            inputs += ["-i", str(img)]  # one still frame; zoompan emits d frames from it
            graph.append(f"[{j}:v]zoompan=z='1+0.0015*on':x='iw/2-(iw/zoom/2)+on*{1 + j}':y='ih/2-(ih/zoom/2)':"
                         f"d={int(per * 25)}:s=1280x720:fps=25,noise=alls=6:allf=t,format=yuv420p[v{j}]")
        graph.append("".join(f"[v{j}]" for j in range(3)) + "concat=n=3:v=1:a=0[v]")
        path = out / f"synthetic_{i}.mp4"
        _ffmpeg([*inputs, "-filter_complex", ";".join(graph), "-map", "[v]", "-c:v", "libx264", "-preset",
                 "veryfast", "-crf", "20", str(path)])
        paths.append(path)
    return paths


def _keyframe_variants(path: Path, settings: Settings, work: Path) -> list[list[str]]:
    info = extract.probe(path, 3600, 4096)
    frames = extract.keyframes(path, info, work, max_frames=settings.max_keyframes,
                               scene_threshold=settings.scene_threshold)
    usable = [k for k in frames if k.usable] or frames
    return [k.variants for k in usable]


def _per_frame_similarity(frame_variants: list[list[str]], hashes: np.ndarray) -> np.ndarray:
    """Best similarity of each keyframe (over its variants) to any of the row's hashes."""
    out = np.zeros(len(frame_variants))
    for i, variants in enumerate(frame_variants):
        v = np.array([int(h, 16) for h in variants], dtype=np.uint64)
        out[i] = 1.0 - np.bitwise_count(v[:, None] ^ hashes[None, :]).min() / fp.HASH_BITS
    return out


def matched(sims: np.ndarray, strong: float, weak: float) -> bool:
    return bool(len(sims)) and (sims.max() >= strong or int((sims >= weak).sum()) >= 2)


def run(videos: list[Path], settings: Settings, transforms: list[str] | None = None,
        progress=print) -> dict:
    names = transforms or list(TRANSFORMS)
    tmp = Path(tempfile.mkdtemp(prefix="reel-bench-"))
    try:
        caption, logo = _assets(tmp)
        sources: list[Source] = []
        for i, video in enumerate(videos):
            clip = tmp / f"src{i}.mp4"
            _ffmpeg(["-i", str(video), "-t", str(CLIP_SECONDS), "-an", "-c:v", "libx264", "-preset", "veryfast",
                     "-crf", "18", str(clip)])
            info = extract.probe(clip, 3600, 4096)
            frames = extract.keyframes(clip, info, tmp / f"seed{i}", max_frames=24,
                                       scene_threshold=settings.scene_threshold)
            hashes = [h for k in frames if k.usable for h in fp.stored_from_variants(k.variants)]
            if not hashes:
                progress(f"skip {video.name}: no usable frames")
                continue
            sources.append(Source(video.name, clip, np.array([int(h, 16) for h in hashes], dtype=np.uint64)))
        if len(sources) < 2:
            raise ValueError("need at least 2 usable source videos (false matches are measured between them)")
        progress(f"{len(sources)} sources fingerprinted; applying {len(names)} edits each")

        # sims[t][i][j]: per-frame similarity of source i's edited copy (edit t) to source j's fingerprints
        sims: dict[str, list[list[np.ndarray]]] = {}
        for t in names:
            graph = TRANSFORMS[t][1]
            sims[t] = []
            for i, src in enumerate(sources):
                out = tmp / f"{t}_{i}.mp4"
                _ffmpeg(["-i", str(src.path), "-i", str(caption), "-i", str(logo), "-filter_complex", graph,
                         "-map", "[v]", "-c:v", "libx264", "-preset", "veryfast", "-crf", CRF.get(t, "26"),
                         "-pix_fmt", "yuv420p", str(out)])
                fv = _keyframe_variants(out, settings, tmp / f"kf_{t}_{i}")
                sims[t].append([_per_frame_similarity(fv, other.hashes) for other in sources])
                out.unlink(missing_ok=True)
            progress(f"  {t:<15} done")

        n = len(sources)

        def evaluate(strong: float, weak: float) -> dict:
            per = {}
            for t in names:
                hits = sum(matched(sims[t][i][i], strong, weak) for i in range(n))
                false = sum(matched(sims[t][i][j], strong, weak) for i in range(n) for j in range(n) if i != j)
                per[t] = {"recall": hits / n, "false_matches": false, "pairs": n * (n - 1)}
            total_false = sum(p["false_matches"] for p in per.values())
            total_pairs = sum(p["pairs"] for p in per.values())
            return {"strong": strong, "weak": weak, "recall": float(np.mean([p["recall"] for p in per.values()])),
                    "false_match_rate": total_false / total_pairs, "false_matches": total_false,
                    "chance_at_scale": chance_matches(strong, weak, INDEX_SCALE), "by_edit": per}

        current = evaluate(settings.strong_similarity, settings.weak_similarity)
        grid = [evaluate(s, w) for s in STRONG_GRID for w in WEAK_GRID if w <= s]
        # A handful of sources can't reveal chance matches at production scale, so the binomial
        # estimate rules out loose settings that this small sample happens not to punish.
        clean = [g for g in grid if g["false_matches"] == 0 and g["chance_at_scale"] <= CHANCE_BUDGET]
        best = max(clean, key=lambda g: (g["recall"], g["weak"], g["strong"])) if clean else None
        # How far apart are true and false matches? (best single-frame similarity)
        true_best = [float(sims[t][i][i].max()) for t in names for i in range(n) if len(sims[t][i][i])]
        false_best = [float(sims[t][i][j].max()) for t in names for i in range(n) for j in range(n)
                      if i != j and len(sims[t][i][j])]
        return {"sources": [s.name for s in sources], "edits": {t: TRANSFORMS[t][0] for t in names},
                "current": current, "best_without_false_matches": best, "grid": grid,
                "separation": {"true_best_p10": float(np.percentile(true_best, 10)), "false_best_max": max(false_best),
                               "false_best_p99": float(np.percentile(false_best, 99))}}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def write_report(result: dict, out: Path, synthetic: bool) -> Path:
    out.mkdir(parents=True, exist_ok=True)
    cur, best, sep = result["current"], result["best_without_false_matches"], result["separation"]
    pct = lambda x: f"{x:.0%}"  # noqa: E731
    lines = [f"# Fingerprint benchmark: {datetime.now():%Y-%m-%d %H:%M}", "",
             f"{len(result['sources'])} source videos × {len(result['edits'])} edits"
             + (" (**synthetic footage**: a self-check of the method, not a measurement on real reels)"
                if synthetic else ""), "",
             f"## Current thresholds (strong {cur['strong']}, weak {cur['weak']})", "",
             f"Recall {pct(cur['recall'])} averaged over edits · false matches {cur['false_matches']} of "
             f"{sum(p['pairs'] for p in cur['by_edit'].values())} cross-source pairs", "",
             "| Edit | What it imitates | Recall | False matches |", "|---|---|---|---|"]
    lines += [f"| {t} | {result['edits'][t]} | {pct(p['recall'])} | {p['false_matches']}/{p['pairs']} |"
              for t, p in cur["by_edit"].items()]
    lines += ["", "## Separation", "",
              f"Worst 10% of true matches reach {sep['true_best_p10']:.2f} on their best frame; the closest "
              f"wrong source reaches {sep['false_best_max']:.2f} (99th percentile {sep['false_best_p99']:.2f}). "
              "Thresholds belong in the gap.", ""]
    if best:
        lines += ["## Best safe setting", "",
                  f"strong {best['strong']}, weak {best['weak']}: recall {pct(best['recall'])}. No false matches here, "
                  f"and at most {CHANCE_BUDGET} expected chance matches per reel in a {INDEX_SCALE:,}-fingerprint "
                  "index (binomial estimate; real images are less random, so keep the margin).", "",
                  "| Edit | Recall |", "|---|---|"]
        lines += [f"| {t} | {pct(p['recall'])} |" for t, p in best["by_edit"].items()]
        lines.append("")
    lines += ["## Grid", "",
              f"Chance matches = expected unrelated matches per reel in a {INDEX_SCALE:,}-fingerprint index.", "",
              "| Strong | Weak | Recall | False matches here | Chance matches at scale |", "|---|---|---|---|---|"]
    lines += [f"| {g['strong']} | {g['weak']} | {pct(g['recall'])} | {g['false_matches']} | "
              f"{g['chance_at_scale']:.3g} |" for g in result["grid"]]
    lines += ["", "This measures fingerprints only. It says nothing about claim extraction or the external "
              "searches; `run.py eval` measures the whole pipeline on labelled reels.", ""]
    path = out / "bench.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    (out / "bench.json").write_text(json.dumps(result, indent=1), encoding="utf-8")
    return path
