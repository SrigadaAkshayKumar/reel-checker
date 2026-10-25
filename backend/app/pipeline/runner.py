"""Runs one analysis end to end: extract → speech + OCR → claim → evidence
(own index, Fact Check, YouTube, then Vision only if still nothing) →
verdict → summary → report. Work files live in a temp dir that is deleted
afterwards; only fingerprints and the report are kept."""
from __future__ import annotations

import shutil
import tempfile
import time
import uuid
from collections.abc import Callable
from dataclasses import asdict
from datetime import UTC, date, datetime
from pathlib import Path

from ..core.config import Settings
from ..core.http import Http
from ..db.store import Store
from . import extract, ocr, report, transcribe
from .claims import extract_claim
from .context import Context, SkipCheck
from .evidence import factcheck_api, own_index, vision_web, youtube
from .llm import Gemini
from .models import VERDICT_LABELS, Check, Evidence, Transcript
from .verdict import InputQuality, decide

VERSION = "0.1.0"
STEPS = ("extracting", "transcribing", "understanding", "searching", "comparing", "done")


def _run_check(checks: list[Check], name: str, fn: Callable[[], list[Evidence]]) -> list[Evidence]:
    start = time.monotonic()
    try:
        found = fn()
        checks.append(Check(name, "ok", f"{len(found)} item(s)", round(time.monotonic() - start, 2)))
        return found
    except SkipCheck as exc:
        checks.append(Check(name, exc.status, exc.detail, round(time.monotonic() - start, 2)))
    except Exception as exc:  # one broken source must not sink the report
        checks.append(Check(name, "failed", f"{exc.__class__.__name__}: {str(exc)[:160]}",
                            round(time.monotonic() - start, 2)))
    return []


def analyze(video: Path, settings: Settings, *, caption: str = "", posted_date: date | None = None,
            http: Http | None = None, store: Store | None = None, fresh: bool = False,
            keep_work: bool = False, out_dir: Path | None = None, job_id: str | None = None,
            progress: Callable[[str], None] | None = None) -> dict:
    """Raises extract.InputError for unusable uploads; everything else degrades
    into a (possibly partial) report. `job_id` becomes the report id (the API
    passes its job id); a cached report keeps its original id."""
    started = time.monotonic()
    http = http or Http()
    own_store = store is None
    store = store or Store(settings.db_path)
    ctx = Context(settings, http, store, Gemini(settings, http, store), posted_date or date.today())
    step = progress or (lambda _s: None)
    try:
        info = extract.probe(Path(video), settings.max_video_seconds, settings.max_upload_mb)
        if not fresh:
            cached = store.report_get(info.sha256)
            if cached and not cached.get("partial") and not caption:
                cached["cached"] = True
                return cached
        return _analyze(ctx, info, caption, keep_work, out_dir, step, started, job_id or new_id())
    finally:
        if own_store:
            store.close()


def new_id() -> str:
    return uuid.uuid4().hex[:12]


def _analyze(ctx: Context, info, caption: str, keep_work: bool, out_dir: Path | None,
             step: Callable[[str], None], started: float, job_id: str) -> dict:
    s = ctx.settings
    checks: list[Check] = []
    work = Path(tempfile.mkdtemp(prefix="reel-"))
    try:
        # 1. Extract
        step("extracting")
        t = time.monotonic()
        frames = extract.keyframes(Path(info.path), info, work / "frames", max_frames=s.max_keyframes,
                                   scene_threshold=s.scene_threshold)
        audio = extract.extract_audio(Path(info.path), work / "audio.wav") if info.has_audio else None
        usable = [k for k in frames if k.usable]
        checks.append(Check("extract", "ok", f"{len(frames)} keyframes ({len(usable)} usable), "
                            f"audio {'yes' if audio else 'no'}", round(time.monotonic() - t, 2)))

        # 2. Speech + on-screen text (local where installed)
        step("transcribing")
        t = time.monotonic()
        transcript, t_detail = transcribe.transcribe(audio, s)
        confident = bool(transcript and transcript.confidence is not None
                         and transcript.confidence >= s.whisper_min_confidence)
        checks.append(Check("transcribe", "ok" if confident or (transcript and not transcript.text) else "skipped",
                            t_detail, round(time.monotonic() - t, 2)))
        t = time.monotonic()
        ocr_lines, ocr_engine, o_detail = ocr.read_text(frames, s)
        checks.append(Check("ocr", "ok" if ocr_lines is not None else "skipped", o_detail,
                            round(time.monotonic() - t, 2)))

        # 3. Claim (one Gemini call; it also listens / reads when local tools could not)
        step("understanding")
        t = time.monotonic()
        picked = extract.pick_frames(frames, s.llm_frames)
        audio_bytes = None
        if audio and not confident and ctx.llm.available and audio.stat().st_size < 15 * 1024 * 1024:
            audio_bytes = audio.read_bytes()
        frame_bytes = [extract.jpeg_bytes(k.path) for k in picked] if ctx.llm.available else []
        claim, g_transcript, g_onscreen, c_detail = extract_claim(
            ctx.llm, caption=caption, transcript=transcript if confident else None,
            ocr_lines=ocr_lines, frames=frame_bytes, audio=audio_bytes, reference=ctx.reference)
        if g_transcript and not confident:
            transcript = Transcript(g_transcript, claim.language, None, "gemini")
        if g_onscreen and not ocr_lines:
            ocr_lines = ocr.dedupe_lines(g_onscreen.splitlines())
        if claim.recency == "current" and not claim.claimed_date:
            claim.claimed_date = ctx.reference.isoformat()
        checks.append(Check("claim", "ok" if claim.engine == "gemini" else "skipped", c_detail,
                            round(time.monotonic() - t, 2)))

        # 4. Evidence, cheapest and most specific first
        step("searching")
        evidence: list[Evidence] = []
        evidence += _run_check(checks, "own_index", lambda: own_index.lookup(ctx, claim, frames, info.sha256))
        evidence += _run_check(checks, "fact_check", lambda: factcheck_api.search(ctx, claim))
        evidence += _run_check(checks, "youtube", lambda: youtube.search(ctx, claim, frames))
        if any(e.supports in ("debunk", "earlier_footage") for e in evidence):
            checks.append(Check("vision_web", "not_needed", "earlier evidence already found"))
        else:
            evidence += _run_check(checks, "vision_web", lambda: vision_web.search(ctx, frames))

        # 5. Verdict + summary
        step("comparing")
        quality = InputQuality(
            duration=info.duration, total_frames=len(frames), usable_frames=len(usable),
            has_speech=bool(transcript and transcript.text), has_text=bool(caption or ocr_lines))
        verdict = decide(s, claim, evidence, quality, checks)
        evidence.sort(key=lambda e: ({"debunk": 0, "earlier_footage": 1}.get(e.supports, 2),
                                     -(e.similarity or e.relevance or 0)))
        summary, summary_local, summary_engine = report.summarize(ctx, verdict, claim, evidence)

        out = (out_dir or s.output_dir / job_id)
        keyframes_saved, comparisons = report.save_visuals(ctx, out, frames, picked or frames[:3], evidence)
        remembered = own_index.remember(ctx, frames, info.sha256)

        partial = any(c.status in ("quota", "failed") for c in checks) or any(
            c.status == "skipped" for c in checks if c.name in ("fact_check", "youtube"))
        result = {
            "version": VERSION,
            "job_id": job_id,
            "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "reference_date": ctx.reference.isoformat(),
            "input": {"sha256": info.sha256, "duration": round(info.duration, 2), "width": info.width,
                      "height": info.height, "has_audio": info.has_audio, "size_bytes": info.size_bytes},
            "caption": caption,
            "claim": asdict(claim),
            "transcript": asdict(transcript) if transcript else None,
            "onscreen_text": ocr_lines or [],
            "verdict": verdict.verdict,
            "verdict_label": VERDICT_LABELS[verdict.verdict],
            "confidence": verdict.confidence,
            "reasons": verdict.reasons,
            "summary": summary,
            "summary_local": summary_local,
            "summary_engine": summary_engine,
            "evidence": [e.to_dict() for e in evidence],
            "comparisons": comparisons,
            "keyframes": keyframes_saved,
            "checks": [asdict(c) for c in checks],
            "partial": partial,
            "manual_links": report.manual_links(claim),
            "fingerprint_saved": remembered,
            "disclaimer": report.DISCLAIMER,
            "seconds": round(time.monotonic() - started, 1),
        }
        ctx.store.report_put(info.sha256, result)
        report.write(result, out)
        result["output_dir"] = str(out)
        step("done")
        return result
    finally:
        if keep_work:
            print(f"work files kept in {work}")
        else:
            shutil.rmtree(work, ignore_errors=True)
