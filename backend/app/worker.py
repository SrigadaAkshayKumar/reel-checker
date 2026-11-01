"""Job runner. Takes queued jobs from the `jobs` table, runs the pipeline,
records progress steps, and always deletes the upload afterwards.

  python -m app.worker            # standalone process (recommended once traffic grows)

The API also starts one in a background thread when EMBEDDED_WORKER=true
(the default), which is enough for a single free VM. Several workers can
share the database: claiming a job is atomic.
"""
from __future__ import annotations

import logging
import shutil
import signal
import threading
import time
from datetime import UTC, date, datetime
from pathlib import Path

from .core.config import Settings, load_settings
from .core.http import Http
from .db.store import Store
from .pipeline import extract, fetch
from .pipeline.runner import analyze

log = logging.getLogger("reel-checker.worker")


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def sweep_uploads(settings: Settings, store: Store) -> int:
    """Privacy backstop: delete uploads no queued or running job owns (left by a crash between
    saving and queueing, or a killed container). Recent files are left alone: the API may be
    between writing the file and creating its job."""
    if not settings.uploads_dir.is_dir():
        return 0
    active = {row["id"] for row in store.db.execute("select id from jobs where status in ('queued', 'running')")}
    cutoff = time.time() - settings.job_stale_seconds
    swept = 0
    for f in settings.uploads_dir.iterdir():
        if f.stem not in active and f.stat().st_mtime < cutoff:
            if f.is_dir():  # a link download interrupted by a crash
                shutil.rmtree(f, ignore_errors=True)
            else:
                f.unlink(missing_ok=True)
            swept += 1
    return swept


NEED_FILE = ("We couldn't fetch this reel from its link. Save the video (or screen-record it) "
             "and share the file instead.")


class Worker:
    def __init__(self, settings: Settings, http: Http | None = None, downloader=None):
        self.settings = settings
        self.http = http or Http()
        self.download = downloader or fetch.download  # (url, dest_dir, settings) -> Path; tests swap it
        self._last_recovery = 0.0

    def recover(self, store: Store) -> None:
        ids = store.job_recover_stale(self.settings.job_stale_seconds, self.settings.job_max_attempts)
        if ids:
            log.warning("recovered stale jobs: %s", ", ".join(ids))
        swept = sweep_uploads(self.settings, store)
        if swept:
            log.warning("deleted %d orphaned upload(s)", swept)
        self._last_recovery = time.monotonic()

    def run_once(self) -> bool:
        """Process one queued job. Returns False when the queue is empty."""
        store = Store(self.settings.db_path)
        try:
            if time.monotonic() - self._last_recovery > 60:
                self.recover(store)
            job = store.job_claim()
            if not job:
                return False
            self._process(store, job)
            return True
        finally:
            store.close()

    def _fetch(self, store: Store, job: dict) -> Path:
        """Download a link job's video into uploads/ (the same place, and fate, as an upload)."""
        store.job_update(job["id"], step="downloading")
        tmp = self.settings.uploads_dir / f"{job['id']}.download"
        try:
            got = self.download(job["source_url"], tmp, self.settings)
            dest = self.settings.uploads_dir / f"{job['id']}{got.suffix.lower() or '.mp4'}"
            got.replace(dest)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        store.job_update(job["id"], upload_path=str(dest), source_url=None)
        return dest

    def _process(self, store: Store, job: dict) -> None:
        job_id = job["id"]
        upload = Path(job["upload_path"]) if job["upload_path"] else None
        log.info("job %s: start", job_id)
        refund = True
        try:
            if job.get("source_url") and not upload:
                upload = self._fetch(store, job)
            if not upload or not upload.is_file():
                raise extract.InputError("the uploaded file is no longer available; please upload it again")
            result = analyze(
                upload, self.settings, caption=job["caption"] or "",
                posted_date=date.fromisoformat(job["posted_date"]) if job["posted_date"] else None,
                http=self.http, store=store, job_id=job_id,
                progress=lambda step: store.job_update(job_id, step=step))
            store.job_update(job_id, status="done", step="done", report_id=result["job_id"], finished_at=_now())
            if job.get("link_key") and not result.get("partial"):
                store.link_report_put(job["link_key"], result["job_id"])
            refund = bool(result.get("partial"))  # some checks could not run: the check is on us
            log.info("job %s: %s in %.1fs", job_id, result["verdict"], result.get("seconds", 0))
        except fetch.FetchError as exc:
            store.job_update(job_id, status="failed", step="failed", error=NEED_FILE, error_code="need_file",
                             finished_at=_now())
            log.info("job %s: link not fetched: %s", job_id, exc)
        except extract.InputError as exc:
            store.job_update(job_id, status="failed", step="failed", error=str(exc), error_code="bad_video",
                             finished_at=_now())
            log.info("job %s: rejected input: %s", job_id, exc)
        except Exception:
            log.exception("job %s: crashed", job_id)
            store.job_update(job_id, status="failed", step="failed", finished_at=_now(), error_code="error",
                             error="Something went wrong while analysing this reel. Please try again.")
        finally:
            # Privacy: the video never outlives its analysis, and neither does the link.
            if upload:
                upload.unlink(missing_ok=True)
            store.job_update(job_id, upload_path=None, source_url=None)
            if refund and store.charge_refund(job_id):
                log.info("job %s: check refunded", job_id)

    def run_forever(self, stop: threading.Event) -> None:
        log.info("worker started (db %s)", self.settings.db_path)
        while not stop.is_set():
            try:
                busy = self.run_once()
            except Exception:
                log.exception("worker loop error")
                busy = False
            if not busy:
                stop.wait(self.settings.worker_poll_seconds)
        log.info("worker stopped")


def start_background(settings: Settings, http: Http | None = None) -> tuple[threading.Thread, threading.Event]:
    stop = threading.Event()
    thread = threading.Thread(target=Worker(settings, http).run_forever, args=(stop,), name="reel-worker",
                              daemon=True)
    thread.start()
    return thread, stop


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    stop = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stop.set())
    Worker(load_settings()).run_forever(stop)


if __name__ == "__main__":
    main()
