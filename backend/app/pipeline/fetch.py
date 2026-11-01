"""Fetch a reel from a link the user pasted (Android app, Phase 9).

Only public Instagram reel/post links are accepted, normalised to the canonical
form, and handed to yt-dlp with every extractor except Instagram's disabled, so
a link can never make the server fetch an arbitrary URL. No login, no cookies,
no config files. The video is deleted after analysis like any upload; only a
hash of the reel's code is kept, to answer the same link again from cache.

When fetching fails (Instagram often refuses servers), the job fails with
`need_file` and the app asks the user to share the video file instead.
"""
from __future__ import annotations

import hashlib
import re
import shutil
import subprocess
import sys
from pathlib import Path

from ..core.config import Settings

LINK_RE = re.compile(
    r"^https?://(?:www\.|m\.)?instagram\.com/(?:[A-Za-z0-9_.]{1,30}/)?(reels?|p|tv)/([A-Za-z0-9_-]{5,40})/?"
    r"(?:[?#].*)?$")


class FetchError(Exception):
    """The link could not be fetched. The message is safe to show the user."""


def canonical(url: str) -> str | None:
    """https://www.instagram.com/reel/<code>/ for an Instagram reel or post link, else None."""
    m = LINK_RE.match(url.strip())
    if not m:
        return None
    kind = "reel" if m.group(1).startswith("reel") else m.group(1)
    return f"https://www.instagram.com/{kind}/{m.group(2)}/"


def link_key(url: str) -> str:
    """Cache key for a canonical link. A hash, so stored keys don't list which reels people checked."""
    code = url.rstrip("/").rsplit("/", 1)[-1]
    return hashlib.sha256(f"instagram:{code}".encode()).hexdigest()[:32]


def available() -> bool:
    try:
        import yt_dlp  # noqa: F401
    except ImportError:
        return False
    return True


def download(url: str, dest_dir: Path, settings: Settings) -> Path:
    """Download one canonical link into dest_dir. Raises FetchError."""
    if canonical(url) != url:
        raise FetchError("This is not an Instagram reel link.")
    if not available():
        raise FetchError("Fetching links is not available on this server.")
    dest_dir.mkdir(parents=True, exist_ok=True)
    limit_mb = int(settings.max_upload_mb)
    cmd = [sys.executable, "-m", "yt_dlp", "--no-config", "--no-cache-dir", "--no-playlist",
           "--use-extractors", "Instagram", "--no-part", "--no-mtime", "--quiet", "--no-warnings",
           "--no-progress", "--socket-timeout", "20", "--retries", "2",
           "--max-filesize", f"{limit_mb}M", "-f", f"b[filesize<{limit_mb}M]/b",
           "-o", str(dest_dir / "reel.%(ext)s"), url]
    try:
        res = subprocess.run(cmd, capture_output=True, timeout=settings.link_fetch_timeout)
    except subprocess.TimeoutExpired:
        shutil.rmtree(dest_dir, ignore_errors=True)
        raise FetchError("Instagram took too long to respond.") from None
    files = [f for f in dest_dir.iterdir() if f.is_file() and f.stat().st_size > 0]
    if res.returncode != 0 or not files:
        # yt-dlp's stderr names the link; it is not logged (privacy) and not shown (internals).
        shutil.rmtree(dest_dir, ignore_errors=True)
        raise FetchError("Instagram did not let us fetch this reel.")
    return max(files, key=lambda f: f.stat().st_size)
