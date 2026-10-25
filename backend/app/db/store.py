"""SQLite store for the CLI phase: API cache, quota counters, finished reports
and the known-footage index. The tables mirror the Postgres schema in
docs/workflow.md so moving to Postgres/pgvector later is a driver swap.
"""
from __future__ import annotations

import json
import sqlite3
import time
from datetime import UTC, date, datetime
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
  video_hash text primary key,
  job_id text not null,
  verdict text,
  report text not null,
  created_at text not null
);
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
"""


class Store:
    def __init__(self, path: Path | str):
        self.path = Path(path)
        if str(path) != ":memory:":
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(path))
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)

    def close(self) -> None:
        self.db.close()

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
        row = self.db.execute("select report from reports where video_hash = ?", (video_hash,)).fetchone()
        return json.loads(row["report"]) if row else None

    def report_put(self, video_hash: str, report: dict) -> None:
        self.db.execute("insert or replace into reports values (?, ?, ?, ?, ?)",
                        (video_hash, report["job_id"], report.get("verdict"),
                         json.dumps(report, ensure_ascii=False), _now()))
        self.db.commit()

    def report_delete(self, video_hash: str) -> None:
        self.db.execute("delete from reports where video_hash = ?", (video_hash,))
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


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")
