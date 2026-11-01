"""Android app endpoints (Phase 9, docs/mobile-api.md).

POST /api/app/session   create an anonymous account → {user_id, token} (the app keeps the token)
GET  /api/app/me        today's allowance: free check left, ad credits, when it resets
POST /api/app/check     a reel link or a video file → job (202), cached report (200), or 402 watch_ad
GET  /api/admob/ssv     AdMob rewarded-ad callback (signed by Google) → one ad credit

Every app call except the callback sends `Authorization: Bearer <token>`. The server,
not the app, counts checks: one free check per India day, then one ad credit per check.
A job that fails, or whose report is partial, is refunded by the worker. Answers from
cache (the same link or file checked before) cost nothing. Progress and reports use the
same endpoints as the website (/api/jobs/{id}, /api/reports/{id}).
"""
from __future__ import annotations

import hashlib
import logging
import secrets
from datetime import UTC, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.responses import PlainTextResponse

from ..core.config import Settings
from ..core.http import Http
from ..db.store import Store
from ..pipeline import fetch
from ..pipeline.runner import new_id
from . import admob, views
from .deps import client_key, get_settings, get_store
from .routes import _error, _parse_posted, accept_upload, cached_job, check_caption

router = APIRouter()
log = logging.getLogger("reel-checker.app")

WATCH_AD = "You've used today's free check. Watch a short ad to run another check."


def get_http(request: Request) -> Http:
    return request.app.state.http


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def current_user(authorization: str = Header(""), store: Store = Depends(get_store)) -> dict:
    scheme, _, token = authorization.partition(" ")
    user = store.app_user_by_token(_token_hash(token.strip())) if scheme.lower() == "bearer" and token else None
    if not user:
        raise HTTPException(401, {"code": "signed_out", "message": "Please reopen the app to sign in again."})
    return user


def app_day(settings: Settings) -> tuple[str, str]:
    """(today in the app's time zone, when the next day starts, as UTC ISO)."""
    tz = timezone(timedelta(minutes=settings.app_day_utc_offset_minutes))
    now = datetime.now(tz)
    midnight = datetime.combine(now.date() + timedelta(days=1), datetime.min.time(), tz)
    return now.date().isoformat(), midnight.astimezone(UTC).isoformat(timespec="seconds")


def allowance(settings: Settings, store: Store, user_id: str) -> dict:
    day, resets_at = app_day(settings)
    user = store.app_user(user_id) or {"ad_credits": 0}
    free_left = max(settings.app_free_checks_per_day - store.app_free_used(user_id, day), 0)
    return {"free_left": free_left, "ad_credits": user["ad_credits"],
            "can_check": bool(free_left or user["ad_credits"]),
            "can_watch_ad": user["ad_credits"] < settings.app_max_ad_credits, "resets_at": resets_at,
            "ads_enabled": bool(settings.admob_ad_unit_ids)}


@router.post("/api/app/session", status_code=201)
def create_session(request: Request, settings: Settings = Depends(get_settings), store: Store = Depends(get_store)):
    if not store.rate_take("session:" + client_key(request, settings), settings.app_sessions_per_ip_day):
        raise _error(429, "rate_limited", "Too many new sign-ins from this network today. Try again tomorrow.")
    user_id, token = secrets.token_hex(8), secrets.token_urlsafe(32)
    store.app_user_create(user_id, _token_hash(token))
    return {"user_id": user_id, "token": token, **allowance(settings, store, user_id)}


@router.get("/api/app/me")
def me(user: dict = Depends(current_user), settings: Settings = Depends(get_settings),
       store: Store = Depends(get_store)):
    return {"user_id": user["id"], **allowance(settings, store, user["id"])}


@router.post("/api/app/check", status_code=202)
def check(request: Request, url: str = Form(""), file: UploadFile | None = File(None), caption: str = Form(""),
          posted_date: str | None = Form(None), user: dict = Depends(current_user),
          settings: Settings = Depends(get_settings), store: Store = Depends(get_store)):
    base = settings.public_base_url
    link = fetch.canonical(url) if url.strip() else None
    if file is None:
        if not url.strip():
            raise _error(422, "missing_input", "Paste a reel link or share the video file.")
        if not link:
            raise _error(422, "bad_link", "This doesn't look like an Instagram reel link.")
    # A cached answer (the same link or file, no caption) is free: no limit, no charge.
    dest = info = None
    if file is not None:
        job_id, dest, info, caption, posted = accept_upload(request, file, caption, posted_date, settings)
        cache = None if caption else store.report_get(info.sha256)
        hit = cached_job(store, job_id, cache, base, video_hash=info.sha256, user_id=user["id"])
    else:
        job_id, caption, posted = new_id(), check_caption(caption), _parse_posted(posted_date)
        key = fetch.link_key(link)
        hit = None if caption else cached_job(store, job_id, store.link_report(key), base, video_hash=None,
                                                user_id=user["id"])
        if not hit and not settings.link_fetch_enabled:
            raise _error(422, "need_file", "Links can't be checked right now. Share the video file instead.")
    if hit:
        if dest:
            dest.unlink(missing_ok=True)
        return hit

    try:
        if not store.rate_take("app:" + client_key(request, settings), settings.app_ip_daily_limit):
            raise _error(429, "rate_limited", "Too many checks from this network today. Try again tomorrow.")
        day, resets_at = app_day(settings)
        charge = store.app_spend(user["id"], day, settings.app_free_checks_per_day)
        if not charge:
            raise HTTPException(402, {"code": "watch_ad", "message": WATCH_AD, "resets_at": resets_at,
                                      "ads_enabled": bool(settings.admob_ad_unit_ids)})
    except HTTPException:
        if dest:
            dest.unlink(missing_ok=True)
        raise
    common = dict(caption=caption, posted_date=posted.isoformat() if posted else None, user_id=user["id"],
                  charge=charge, charge_day=day)
    if dest:
        store.job_create(job_id, video_hash=info.sha256, upload_path=str(dest), **common)
    else:
        store.job_create(job_id, video_hash=None, upload_path=None, source_url=link, link_key=key, **common)
    body = views.public_job(store.job_get(job_id), store.job_queue_position(job_id), base)
    return body | {"cached": False, "charged": charge, **allowance(settings, store, user["id"])}


@router.get("/api/admob/ssv", response_class=PlainTextResponse)
def admob_ssv(request: Request, settings: Settings = Depends(get_settings), store: Store = Depends(get_store),
              http: Http = Depends(get_http)):
    try:
        outcome = admob.handle_callback(request.url.query, settings, http, store)
    except admob.SsvError as exc:
        log.warning("admob callback refused: %s", exc.code)
        raise HTTPException(exc.status, {"code": exc.code, "message": str(exc)}) from None
    if outcome not in ("granted", "duplicate"):
        log.warning("admob callback: %s", outcome)
    return PlainTextResponse("ok")  # 200 for every verified callback, so AdMob doesn't retry it
