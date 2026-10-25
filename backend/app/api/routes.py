"""HTTP endpoints (docs/workflow.md, Phase 4).

POST /api/analyze                     upload a reel → job id (202), or a cached report (200)
GET  /api/jobs/{id}                   queued / running (with step) / done / failed
GET  /api/reports/{id}                report JSON
GET  /api/reports/{id}/files/{name}   comparison images and keyframes
POST /api/reports/{id}/feedback       "was this correct?" / report an error
GET  /r/{id}                          public share page (share.py)
GET  /api/health
"""
from __future__ import annotations

import re
from datetime import date
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field

from ..core.config import Settings
from ..db.store import Store
from ..pipeline import extract
from ..pipeline.runner import VERSION, new_id
from . import views
from .deps import check_id, client_key, get_settings, get_store

router = APIRouter()

VIDEO_EXTS = {".mp4", ".mov", ".m4v", ".webm", ".mkv", ".3gp"}
FILE_RE = re.compile(r"^(compare_\d+\.jpg|frames/keyframe_[0-9]{2}_[0-9.]+s\.jpg)$")
CHUNK = 1 << 20


def _error(status: int, code: str, message: str) -> HTTPException:
    return HTTPException(status, {"code": code, "message": message})


def _save_upload(file: UploadFile, dest: Path, max_bytes: int) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    size = 0
    with open(dest, "wb") as out:
        while chunk := file.file.read(CHUNK):
            size += len(chunk)
            if size > max_bytes:
                out.close()
                dest.unlink(missing_ok=True)
                raise _error(413, "too_large", f"The file is larger than {max_bytes // 1048576} MB.")
            out.write(chunk)
    if size == 0:
        dest.unlink(missing_ok=True)
        raise _error(400, "empty", "The uploaded file is empty.")


def _parse_posted(value: str | None) -> date | None:
    if not value:
        return None
    try:
        posted = date.fromisoformat(value)
    except ValueError:
        raise _error(422, "bad_date", "posted_date must be YYYY-MM-DD.") from None
    if posted > date.today():
        raise _error(422, "bad_date", "posted_date is in the future.")
    return posted


@router.post("/api/analyze", status_code=202)
def analyze_upload(request: Request, file: UploadFile = File(...), caption: str = Form(""),
                   posted_date: str | None = Form(None), settings: Settings = Depends(get_settings),
                   store: Store = Depends(get_store)):
    max_bytes = int(settings.max_upload_mb * 1024 * 1024)
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > max_bytes + CHUNK:
        raise _error(413, "too_large", f"The file is larger than {settings.max_upload_mb:g} MB.")
    ext = Path(file.filename or "").suffix.lower()
    if ext not in VIDEO_EXTS:
        raise _error(415, "not_video", "Upload a video file (MP4, MOV, WEBM, MKV, 3GP).")
    caption = caption.strip()
    if len(caption) > 2200:
        raise _error(422, "caption_too_long", "The caption can be at most 2,200 characters.")
    posted = _parse_posted(posted_date)
    client = client_key(request, settings)
    if store.rate_used(client) >= settings.rate_limit_per_day:
        raise _error(429, "rate_limited", f"Daily limit of {settings.rate_limit_per_day} checks reached. "
                     "Try again tomorrow.")

    job_id = new_id()
    dest = settings.uploads_dir / f"{job_id}{ext}"
    _save_upload(file, dest, max_bytes)
    try:
        info = extract.probe(dest, settings.max_video_seconds, settings.max_upload_mb)
    except extract.InputError as exc:
        dest.unlink(missing_ok=True)
        raise _error(400, "bad_video", f"Cannot analyse this file: {exc}.") from None

    base = settings.public_base_url
    if not caption:  # same file, same question: reuse the finished report
        cached = store.report_get(info.sha256)
        if cached and not cached.get("partial"):
            dest.unlink(missing_ok=True)
            store.job_create(job_id, video_hash=info.sha256, upload_path=None, status="done",
                             report_id=cached["job_id"])
            body = views.public_job(store.job_get(job_id), None, base) | {"cached": True}
            return JSONResponse(body, status_code=200)

    if not store.rate_take(client, settings.rate_limit_per_day):
        dest.unlink(missing_ok=True)
        raise _error(429, "rate_limited", "Daily limit reached. Try again tomorrow.")
    store.job_create(job_id, video_hash=info.sha256, upload_path=str(dest), caption=caption,
                     posted_date=posted.isoformat() if posted else None)
    return views.public_job(store.job_get(job_id), store.job_queue_position(job_id), base) | {"cached": False}


@router.get("/api/jobs/{job_id}")
def job_status(job_id: str, settings: Settings = Depends(get_settings), store: Store = Depends(get_store)):
    job = store.job_get(check_id(job_id, "job"))
    if not job:
        raise HTTPException(404, "job not found")
    return views.public_job(job, store.job_queue_position(job_id), settings.public_base_url)


@router.get("/api/reports/{report_id}")
def get_report(report_id: str, settings: Settings = Depends(get_settings), store: Store = Depends(get_store)):
    report = store.report_by_id(check_id(report_id))
    if not report:
        raise HTTPException(404, "report not found")
    return views.public_report(report, settings.public_base_url)


@router.get("/api/reports/{report_id}/files/{name:path}")
def report_file(report_id: str, name: str, settings: Settings = Depends(get_settings)):
    check_id(report_id)
    if not FILE_RE.match(name):
        raise HTTPException(404, "file not found")
    path = settings.output_dir / report_id / name
    if not path.is_file():
        raise HTTPException(404, "file not found")
    return FileResponse(path, media_type="image/jpeg", headers={"Cache-Control": "public, max-age=86400"})


class Feedback(BaseModel):
    correct: bool | None = None
    note: str = Field("", max_length=1000)


@router.post("/api/reports/{report_id}/feedback", status_code=201)
def feedback(report_id: str, body: Feedback, store: Store = Depends(get_store)):
    if not store.report_by_id(check_id(report_id)):
        raise HTTPException(404, "report not found")
    store.feedback_add(report_id, body.correct, body.note.strip())
    return {"ok": True}


@router.get("/api/health")
def health(settings: Settings = Depends(get_settings), store: Store = Depends(get_store)):
    queued = store.db.execute("select count(*) as n from jobs where status = 'queued'").fetchone()["n"]
    return {"ok": True, "version": VERSION, "queued": queued,
            "keys": {"gemini": bool(settings.gemini_api_key), "factcheck": bool(settings.factcheck_key),
                     "youtube": bool(settings.youtube_key), "vision": bool(settings.vision_key)}}
