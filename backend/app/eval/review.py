"""Human review of production results (docs/workflow.md: "manually review every LIKELY_OLD_FOOTAGE
result in the first month").

  python run.py review                     the queue: flagged reports + reports users said were wrong
  python run.py review show ID             one report's claim, evidence and user feedback
  python run.py review mark ID correct|wrong|unsure [--note "..."]
  python run.py review stats               precision measured on reviewed production results

The queue holds every DEBUNKED / LIKELY_OLD_FOOTAGE report and every report with a "No, report a
mistake" answer, until it is marked. Outcomes are what Phase 7 thresholds should ultimately answer to.
"""
from __future__ import annotations

import json

from ..db.store import Store
from ..pipeline.models import DEBUNKED, LIKELY_OLD_FOOTAGE

FLAGGED = (DEBUNKED, LIKELY_OLD_FOOTAGE)
OUTCOMES = ("correct", "wrong", "unsure")


def queue(store: Store, include_reviewed: bool = False) -> list[dict]:
    rows = store.db.execute(
        "select r.job_id, r.verdict, r.created_at, r.report, v.outcome,"
        " (select count(*) from feedback f where f.report_id = r.job_id and f.correct = 0) as said_wrong,"
        " (select count(*) from feedback f where f.report_id = r.job_id and f.correct = 1) as said_right"
        " from reports r left join reviews v on v.report_id = r.job_id"
        " where (r.verdict in (?, ?) or exists (select 1 from feedback f where f.report_id = r.job_id"
        "        and f.correct = 0))" + ("" if include_reviewed else " and v.outcome is null")
        + " order by said_wrong desc, r.created_at", FLAGGED).fetchall()
    out = []
    for r in rows:
        report = json.loads(r["report"])
        top = next((e for e in report.get("evidence", []) if e.get("supports") != "lead"), None)
        out.append({"id": r["job_id"], "verdict": r["verdict"], "created_at": r["created_at"],
                    "confidence": report.get("confidence"), "claim": report.get("claim", {}).get("claim_text", ""),
                    "top_evidence": top, "said_wrong": r["said_wrong"], "said_right": r["said_right"],
                    "outcome": r["outcome"]})
    return out


def mark(store: Store, report_id: str, outcome: str, note: str = "") -> None:
    if outcome not in OUTCOMES:
        raise ValueError(f"outcome must be one of {', '.join(OUTCOMES)}")
    if not store.report_by_id(report_id):
        raise KeyError(report_id)
    store.review_put(report_id, outcome, note)


def stats(store: Store) -> dict:
    rows = store.db.execute(
        "select r.verdict, v.outcome, count(*) as n from reviews v join reports r on r.job_id = v.report_id"
        " group by r.verdict, v.outcome").fetchall()
    by: dict[str, dict[str, int]] = {}
    for r in rows:
        by.setdefault(r["verdict"], {})[r["outcome"]] = r["n"]
    flagged_right = sum(by.get(v, {}).get("correct", 0) for v in FLAGGED)
    flagged_wrong = sum(by.get(v, {}).get("wrong", 0) for v in FLAGGED)
    fb = store.db.execute("select sum(correct = 1) as yes, sum(correct = 0) as no from feedback").fetchone()
    return {"by_verdict": by, "open": len(queue(store)),
            "flag_precision": round(flagged_right / (flagged_right + flagged_wrong), 3)
            if flagged_right + flagged_wrong else None,
            "feedback_yes": fb["yes"] or 0, "feedback_no": fb["no"] or 0}
