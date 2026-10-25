"""Settings from environment variables (and an optional .env file).

Every limit and threshold lives here so it can be tuned on the test set
without touching pipeline code.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, fields
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]


def _load_env_file(path: Path) -> None:
    """Minimal .env reader: KEY=VALUE lines; never overrides real env vars."""
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip().removeprefix("export ").strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def _bool(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    # Keys. One Google Cloud key can serve Fact Check, YouTube and Vision.
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.5-flash"
    gemini_fallback_model: str = "gemini-flash-latest"
    google_api_key: str = ""
    factcheck_api_key: str = ""
    youtube_api_key: str = ""
    vision_api_key: str = ""

    # Storage
    data_dir: Path = REPO_ROOT / "data"
    db_path: Path = REPO_ROOT / "data" / "reel-checker.sqlite"
    output_dir: Path = REPO_ROOT / "output"

    # Input limits
    max_video_seconds: float = 90.0
    max_upload_mb: float = 50.0
    min_video_seconds: float = 2.0

    # Extraction
    max_keyframes: int = 12
    scene_threshold: float = 0.30
    llm_frames: int = 5  # keyframes sent to Gemini with the claim prompt

    # Speech / OCR
    whisper_model: str = "base"
    whisper_fallback_model: str = "small"
    whisper_min_confidence: float = 0.55
    ocr_engine: str = "auto"  # auto | easyocr | tesseract | gemini | none
    use_clip: bool = False

    # Similarity thresholds (pHash similarity = 1 - hamming/64)
    strong_similarity: float = 0.90
    weak_similarity: float = 0.80
    clip_strong: float = 0.95
    factcheck_min_relevance: float = 0.34
    date_tolerance_days: int = 2

    # Free-tier budgets (per day unless noted)
    gemini_daily_limit: int = 100
    factcheck_daily_limit: int = 1000
    youtube_daily_units: int = 9000  # search.list costs 100 units; Google gives 10,000
    vision_monthly_units: int = 900  # 1,000 free units / month
    cache_ttl_days: int = 30

    # Feature switches
    llm_summary: bool = True
    vision_enabled: bool = True
    index_short_circuit: bool = True  # strong own-index match skips YouTube / Vision (eval turns it off)

    # API server (Phase 4)
    uploads_dir: Path = REPO_ROOT / "data" / "uploads"   # deleted after each analysis
    rate_limit_per_day: int = 10        # new analyses per client IP per day; cached results are free
    trust_proxy: bool = False           # read the client IP from X-Forwarded-For (behind Caddy/Cloudflare)
    ip_hash_salt: str = ""              # IPs are only stored salted+hashed; generated into data_dir if empty
    cors_origins: str = ""              # comma-separated, e.g. https://reelcheck.example
    public_base_url: str = ""           # absolute URLs in share-page previews (WhatsApp, X)
    embedded_worker: bool = True        # run the worker inside the API process (single free VM)
    worker_poll_seconds: float = 1.0
    job_stale_seconds: int = 600        # a 'running' job older than this is assumed dead
    job_max_attempts: int = 2

    @property
    def factcheck_key(self) -> str:
        return self.factcheck_api_key or self.google_api_key

    @property
    def youtube_key(self) -> str:
        return self.youtube_api_key or self.google_api_key

    @property
    def vision_key(self) -> str:
        return self.vision_api_key or self.google_api_key


def load_settings(env_file: Path | None = None, **overrides) -> Settings:
    _load_env_file(env_file or REPO_ROOT / ".env")
    values: dict = {}
    for f in fields(Settings):
        raw = os.environ.get(f.name.upper())
        if raw is None or raw == "":
            continue
        default = f.default
        if isinstance(default, bool):
            values[f.name] = _bool(raw)
        elif isinstance(default, int):
            values[f.name] = int(raw)
        elif isinstance(default, float):
            values[f.name] = float(raw)
        elif isinstance(default, Path):
            values[f.name] = Path(raw).expanduser()
        else:
            values[f.name] = raw
    if "data_dir" in values:
        values.setdefault("db_path", values["data_dir"] / "reel-checker.sqlite")
        values.setdefault("uploads_dir", values["data_dir"] / "uploads")
    values.update(overrides)
    return Settings(**values)
