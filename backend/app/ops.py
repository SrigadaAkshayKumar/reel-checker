"""Operations helpers for a deployed server."""
from __future__ import annotations

import sqlite3
import tarfile
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from .core.config import Settings


def backup(settings: Settings, dest: Path, keep: int = 14) -> tuple[Path, int]:
    """One .tar.gz with a consistent copy of the database (SQLite online backup, safe while the API
    and worker are writing) and the report images. Keeps the newest `keep` archives.
    Uploads are never included: they are deleted after each analysis anyway."""
    dest.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    archive = dest / f"reel-checker-{stamp}.tar.gz"
    with tempfile.TemporaryDirectory() as tmp:
        snapshot = Path(tmp) / "reel-checker.sqlite"
        with sqlite3.connect(settings.db_path) as src, sqlite3.connect(snapshot) as dst:
            src.backup(dst)
        partial = archive.with_suffix(".partial")
        with tarfile.open(partial, "w:gz") as tar:
            tar.add(snapshot, arcname="reel-checker.sqlite")
            if settings.output_dir.is_dir():
                tar.add(settings.output_dir, arcname="output")
        partial.rename(archive)  # never leave a half-written archive under the real name
    old = sorted(dest.glob("reel-checker-*.tar.gz"))[:-keep] if keep > 0 else []
    for f in old:
        f.unlink()
    return archive, len(old)


def restore(settings: Settings, archive: Path) -> Path | None:
    """Put a backup() archive back: the database (with SQLite's -wal / -shm side files removed, or the
    old journal would be replayed over it) and the report images. The current output folder is kept
    beside it as output.before-restore-<time>; that path is returned. Stop the api and worker first."""
    import shutil
    with tempfile.TemporaryDirectory() as tmp, tarfile.open(archive) as tar:
        tar.extractall(tmp, filter="data")
        db = Path(tmp) / "reel-checker.sqlite"
        if not db.is_file():
            raise ValueError(f"{archive} is not a reel-checker backup (no database inside)")
        settings.db_path.parent.mkdir(parents=True, exist_ok=True)
        for suffix in ("", "-wal", "-shm"):
            Path(f"{settings.db_path}{suffix}").unlink(missing_ok=True)
        shutil.copy2(db, settings.db_path)
        kept = None
        if settings.output_dir.exists():
            kept = settings.output_dir.with_name(f"output.before-restore-{datetime.now(UTC):%Y%m%d-%H%M%S}")
            settings.output_dir.rename(kept)
        if (Path(tmp) / "output").is_dir():
            shutil.copytree(Path(tmp) / "output", settings.output_dir)
        else:
            settings.output_dir.mkdir(parents=True)
    return kept
