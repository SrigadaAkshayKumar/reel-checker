"""SQLite store: API cache, quota counters, reports, the known-footage index,
and (for the API) the job queue, per-IP rate limits and feedback. The tables
mirror the Postgres schema in docs/workflow.md so moving to Postgres/pgvector
later is a driver swap. WAL mode lets the API and the worker share one file.
"""
from __future__ import annotations

import json
import sqlite3
import time
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

SCHEMA = """
create table if not exists api_cache (
  key text primary key,
  response text not null,
  fetched_at real not null
);
create table if not exists quota (
  period text not null,
  api text not null,
  used integer not null default 0,
  primary key (period, api)
);
create table if not exists reports (
  job_id text primary key,         -- also the public report id (/r/<id>)
  video_hash text not null,
  verdict text,
  report text not null,
  created_at text not null
);
create index if not exists reports_video on reports(video_hash, created_at);
create table if not exists known_footage (
  id integer primary key autoincrement,
  kind text not null,              -- 'debunked' (seeded) | 'seen' (analysed reel)
  source_url text,
  first_seen text,                 -- ISO date
  claim_note text,
  fact_check_url text,
  phashes text not null,           -- JSON list of 16-char hex hashes
  video_hash text,
  added_at text not null
);
create index if not exists known_footage_video on known_footage(video_hash);
create table if not exists jobs (
  id text primary key,
  status text not null default 'queued',  -- queued | running | done | failed
  step text,
  video_hash text,
  upload_path text,
  caption text not null default '',
  posted_date text,
  error text,
  report_id text,
  attempts integer not null default 0,
  created_at text not null,
  started_at text,
  finished_at text
);
create index if not exists jobs_status on jobs(status, created_at);
create table if not exists rate_limit (
  day text not null,
  client text not null,            -- salted hash of the IP, never the IP itself
  used integer not null default 0,
  primary key (day, client)
);
create table if not exists feedback (
  id integer primary key autoincrement,
  report_id text not null,
  correct integer,                 -- 1 / 0 / null
  note text,
  created_at text not null
);
"""

JOB_FIELDS = {"status", "step", "error", "report_id", "started_at", "finished_at", "upload_path", "attempts"}


class Store:
    def __init__(self, path: Path | str):
        self.path = Path(path)
        memory = str(path) == ":memory:"
        if not memory:
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(path), timeout=30, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        if not memory:
            self.db.execute("pragma journal_mode=wal")
        self._migrate()
        self.db.executescript(SCHEMA)

    def close(self) -> None:
        self.db.close()

    def _migrate(self) -> None:
        # v0 (first CLI release) keyed reports by video hash, so a re-run replaced
        # the old report and broke its share link. v1 keys them by job id.
        cols = {r["name"]: r["pk"] for r in self.db.execute("pragma table_info(reports)")}
        if cols.get("video_hash") == 1:
            self.db.executescript("""
                alter table reports rename to reports_v0;
                create table reports (job_id text primary key, video_hash text not null, verdict text,
                                      report text not null, created_at text not null);
                insert into reports select job_id, video_hash, verdict, report, created_at from reports_v0;
                drop table reports_v0;
            """)

    # --- cache -------------------------------------------------------------
    def cache_get(self, key: str, ttl_days: float) -> dict | list | None:
        row = self.db.execute("select response, fetched_at from api_cache where key = ?", (key,)).fetchone()
        if not row or time.time() - row["fetched_at"] > ttl_days * 86400:
            return None
        return json.loads(row["response"])

    def cache_put(self, key: str, value) -> None:
        self.db.execute("insert or replace into api_cache values (?, ?, ?)",
                        (key, json.dumps(value, ensure_ascii=False), time.time()))
        self.db.commit()

    # --- quota -------------------------------------------------------------
    @staticmethod
    def _period(monthly: bool) -> str:
        today = date.today()
        return today.strftime("%Y-%m") if monthly else today.isoformat()

    def quota_used(self, api: str, monthly: bool = False) -> int:
        row = self.db.execute("select used from quota where period = ? and api = ?",
                              (self._period(monthly), api)).fetchone()
        return row["used"] if row else 0

    def quota_take(self, api: str, units: int, limit: int, monthly: bool = False) -> bool:
        """Reserve `units` of the daily (or monthly) budget. False when exhausted."""
        if self.quota_used(api, monthly) + units > limit:
            return False
        self.db.execute(
            "insert into quota values (?, ?, ?) on conflict(period, api) do update set used = used + ?",
            (self._period(monthly), api, units, units))
        self.db.commit()
        return True

    # --- reports -----------------------------------------------------------
    def report_get(self, video_hash: str) -> dict | None:
        """Latest report for this exact file."""
        row = self.db.execute("select report from reports where video_hash = ?"
                              " order by created_at desc, rowid desc limit 1", (video_hash,)).fetchone()
        return json.loads(row["report"]) if row else None

    def report_by_id(self, report_id: str) -> dict | None:
        row = self.db.execute("select report from reports where job_id = ?", (report_id,)).fetchone()
        return json.loads(row["report"]) if row else None

    def report_put(self, video_hash: str, report: dict) -> None:
        self.db.execute("insert or replace into reports values (?, ?, ?, ?, ?)",
                        (report["job_id"], video_hash, report.get("verdict"),
                         json.dumps(report, ensure_ascii=False), _now()))
        self.db.commit()

    # --- known footage -----------------------------------------------------
    def footage_add(self, *, kind: str, phashes: list[str], source_url: str = "",
                    first_seen: str | None = None, claim_note: str = "",
                    fact_check_url: str = "", video_hash: str = "") -> int:
        cur = self.db.execute(
            "insert into known_footage (kind, source_url, first_seen, claim_note, fact_check_url,"
            " phashes, video_hash, added_at) values (?, ?, ?, ?, ?, ?, ?, ?)",
            (kind, source_url, first_seen, claim_note, fact_check_url,
             json.dumps(phashes), video_hash, _now()))
        self.db.commit()
        return cur.lastrowid

    def footage_has_video(self, video_hash: str) -> bool:
        return self.db.execute("select 1 from known_footage where video_hash = ?",
                               (video_hash,)).fetchone() is not None

    def footage_all(self) -> list[dict]:
        rows = self.db.execute("select * from known_footage order by id").fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["phashes"] = json.loads(d["phashes"])
            out.append(d)
        return out

    # --- jobs ----------------------------------------------------------------
    def job_create(self, job_id: str, *, video_hash: str, upload_path: str | None, caption: str = "",
                   posted_date: str | None = None, status: str = "queued", report_id: str | None = None) -> None:
        now = _now()
        done = status == "done"
        self.db.execute(
            "insert into jobs (id, status, step, video_hash, upload_path, caption, posted_date, report_id,"
            " created_at, finished_at) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (job_id, status, "done" if done else None, video_hash, upload_path, caption, posted_date,
             report_id, now, now if done else None))
        self.db.commit()

    def job_get(self, job_id: str) -> dict | None:
        row = self.db.execute("select * from jobs where id = ?", (job_id,)).fetchone()
        return dict(row) if row else None

    def job_update(self, job_id: str, **fields) -> None:
        unknown = set(fields) - JOB_FIELDS
        if unknown:
            raise ValueError(f"unknown job fields: {unknown}")
        cols = ", ".join(f"{k} = ?" for k in fields)
        self.db.execute(f"update jobs set {cols} where id = ?", (*fields.values(), job_id))
        self.db.commit()

    def job_claim(self) -> dict | None:
        """Atomically take the oldest queued job (safe across processes)."""
        self.db.execute("begin immediate")
        try:
            row = self.db.execute("select id from jobs where status = 'queued' order by created_at, rowid limit 1"
                                  ).fetchone()
            if not row:
                self.db.commit()
                return None
            self.db.execute("update jobs set status = 'running', step = 'starting', started_at = ?,"
                            " attempts = attempts + 1 where id = ?", (_now(), row["id"]))
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise
        return self.job_get(row["id"])

    def job_queue_position(self, job_id: str) -> int | None:
        """1 = next in line; None when the job is not queued."""
        job = self.job_get(job_id)
        if not job or job["status"] != "queued":
            return None
        row = self.db.execute(
            "select count(*) as n from jobs where status = 'queued' and (created_at < ? or"
            " (created_at = ? and rowid <= (select rowid from jobs where id = ?)))",
            (job["created_at"], job["created_at"], job_id)).fetchone()
        return row["n"]

    def job_recover_stale(self, older_than_s: float, max_attempts: int) -> list[str]:
        """Jobs left 'running' by a crashed worker: requeue, or fail after max_attempts."""
        cutoff = (datetime.now(UTC) - timedelta(seconds=older_than_s)).isoformat(timespec="seconds")
        rows = self.db.execute("select id, attempts from jobs where status = 'running' and started_at < ?",
                               (cutoff,)).fetchall()
        for r in rows:
            if r["attempts"] >= max_attempts:
                self.job_update(r["id"], status="failed", step="failed", finished_at=_now(),
                                error="The analysis stopped unexpectedly. Please try again.")
            else:
                self.job_update(r["id"], status="queued", step=None)
        return [r["id"] for r in rows]

    # --- rate limit + feedback ------------------------------------------------
    def rate_used(self, client: str) -> int:
        row = self.db.execute("select used from rate_limit where day = ? and client = ?",
                              (date.today().isoformat(), client)).fetchone()
        return row["used"] if row else 0

    def rate_take(self, client: str, limit: int) -> bool:
        if self.rate_used(client) >= limit:
            return False
        self.db.execute("insert into rate_limit values (?, ?, 1)"
                        " on conflict(day, client) do update set used = used + 1",
                        (date.today().isoformat(), client))
        self.db.commit()
        return True

    def feedback_add(self, report_id: str, correct: bool | None, note: str) -> int:
        cur = self.db.execute("insert into feedback (report_id, correct, note, created_at) values (?, ?, ?, ?)",
                              (report_id, None if correct is None else int(correct), note, _now()))
        self.db.commit()
        return cur.lastrowid


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")
