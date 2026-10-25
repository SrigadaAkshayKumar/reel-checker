"""Request-scoped helpers: settings, a Store per request, client identity."""
from __future__ import annotations

import hashlib
import re
import secrets
from collections.abc import Iterator

from fastapi import HTTPException, Request

from ..core.config import Settings
from ..db.store import Store

ID_RE = re.compile(r"^[0-9a-f]{12}$")


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_store(request: Request) -> Iterator[Store]:
    store = Store(request.app.state.settings.db_path)
    try:
        yield store
    finally:
        store.close()


def check_id(value: str, what: str = "report") -> str:
    if not ID_RE.match(value):
        raise HTTPException(404, f"{what} not found")
    return value


def client_ip(request: Request, settings: Settings) -> str:
    if settings.trust_proxy:
        forwarded = request.headers.get("x-forwarded-for", "")
        if forwarded:
            return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def ip_salt(settings: Settings) -> str:
    if settings.ip_hash_salt:
        return settings.ip_hash_salt
    path = settings.data_dir / ".ip_salt"
    if not path.is_file():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(secrets.token_hex(16))
    return path.read_text().strip()


def client_key(request: Request, settings: Settings) -> str:
    """Rate-limit identity: a salted hash, so raw IPs are never stored."""
    raw = f"{ip_salt(settings)}:{client_ip(request, settings)}"
    return hashlib.sha256(raw.encode()).hexdigest()[:32]
