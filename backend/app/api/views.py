"""Shapes stored reports and jobs for the public API: no server paths, and
image references turned into URLs."""
from __future__ import annotations

from ..pipeline.runner import STEPS

PRIVATE_KEYS = ("output_dir",)


def report_url(report_id: str) -> str:
    return f"/api/reports/{report_id}"


def share_url(report_id: str, base: str = "") -> str:
    return f"{base.rstrip('/')}/r/{report_id}"


def file_url(report_id: str, name: str) -> str:
    return f"/api/reports/{report_id}/files/{name}"


def public_report(report: dict, base: str = "") -> dict:
    rid = report["job_id"]
    out = {k: v for k, v in report.items() if k not in PRIVATE_KEYS}
    out["report_id"] = rid
    out["comparisons"] = [{**c, "image_url": file_url(rid, c["image"])} for c in report.get("comparisons", [])]
    out["keyframes"] = [file_url(rid, k) for k in report.get("keyframes", [])]
    out["share_url"] = share_url(rid, base)
    return out


def public_job(job: dict, queue_position: int | None, base: str = "") -> dict:
    rid = job["report_id"]
    return {
        "job_id": job["id"],
        "status": job["status"],
        "step": job["step"],
        "steps": list(STEPS),
        "queue_position": queue_position,
        "error": job["error"],
        "report_id": rid,
        "report_url": report_url(rid) if rid else None,
        "share_url": share_url(rid, base) if rid else None,
        "created_at": job["created_at"],
        "started_at": job["started_at"],
        "finished_at": job["finished_at"],
    }
