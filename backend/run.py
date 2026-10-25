"""Reel Fact-Checker command line.

  python run.py reel.mp4 [--caption "text from the post"] [--posted 2026-10-24] [--json]
  python run.py index add old.mp4 --source-url URL --first-seen 2016-05-01 --note "..." [--fact-check URL]
  python run.py index import data/seed/known_footage.json
  python run.py index list
  python run.py quota
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
from datetime import date
from pathlib import Path

from app.core.config import load_settings
from app.core.http import Http
from app.db.store import Store
from app.pipeline import extract
from app.pipeline.context import Context
from app.pipeline.evidence import own_index
from app.pipeline.llm import Gemini
from app.pipeline.report import to_console
from app.pipeline.runner import analyze


def _date(s: str) -> date:
    try:
        return date.fromisoformat(s)
    except ValueError:
        raise argparse.ArgumentTypeError("use YYYY-MM-DD") from None


def cmd_analyze(argv: list[str]) -> int:
    p = argparse.ArgumentParser(prog="run.py", description="Check whether a reel shows old footage.")
    p.add_argument("video", type=Path)
    p.add_argument("--caption", default="", help="the post's caption text, if you have it")
    p.add_argument("--posted", type=_date, help="date the reel was posted (default: today)")
    p.add_argument("--out", type=Path, help="report folder (default: output/<job_id>)")
    p.add_argument("--json", action="store_true", help="print the report JSON instead of the summary")
    p.add_argument("--fresh", action="store_true", help="ignore a cached report for this file")
    p.add_argument("--keep-work", action="store_true", help="keep extracted frames/audio for debugging")
    a = p.parse_args(argv)
    settings = load_settings()
    progress = (lambda s: print(f"… {s}", file=sys.stderr)) if not a.json else None
    try:
        result = analyze(a.video, settings, caption=a.caption, posted_date=a.posted, fresh=a.fresh,
                         keep_work=a.keep_work, out_dir=a.out, progress=progress)
    except extract.InputError as exc:
        print(f"Cannot analyse this file: {exc}", file=sys.stderr)
        return 2
    if a.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print(to_console(result))
        if result.get("cached"):
            print("\n(cached result for this exact file; use --fresh to re-run)")
        elif result.get("output_dir"):
            print(f"\nReport: {result['output_dir']}/report.md")
    return 0


def cmd_index(argv: list[str]) -> int:
    p = argparse.ArgumentParser(prog="run.py index", description="Manage the known-footage index.")
    sub = p.add_subparsers(dest="action", required=True)
    add = sub.add_parser("add", help="fingerprint a known old video (the video itself is not stored)")
    add.add_argument("video", type=Path)
    add.add_argument("--source-url", default="", help="where the original was first published")
    add.add_argument("--first-seen", type=_date, required=True, help="earliest known publication date")
    add.add_argument("--note", default="", help="what it really shows / the false claim")
    add.add_argument("--fact-check", default="", help="URL of a fact-check about it")
    imp = sub.add_parser("import", help="load a seed JSON file (see data/seed/README.md)")
    imp.add_argument("file", type=Path)
    sub.add_parser("list", help="show indexed footage")
    a = p.parse_args(argv)

    settings = load_settings()
    store = Store(settings.db_path)
    ctx = Context(settings, Http(), store, Gemini(settings, Http(), store), date.today())
    try:
        if a.action == "add":
            info = extract.probe(a.video, settings.max_video_seconds * 20, settings.max_upload_mb * 20)
            with tempfile.TemporaryDirectory() as tmp:
                frames = extract.keyframes(a.video, info, Path(tmp), max_frames=24,
                                           scene_threshold=settings.scene_threshold)
            hashes = [k.phash for k in frames if k.usable]
            row = store.footage_add(kind="debunked", phashes=hashes, source_url=a.source_url,
                                    first_seen=a.first_seen.isoformat(), claim_note=a.note,
                                    fact_check_url=a.fact_check, video_hash=info.sha256)
            print(f"added #{row}: {len(hashes)} frame fingerprints")
        elif a.action == "import":
            print(f"imported {own_index.import_seed(ctx, a.file)} entries")
        else:
            rows = store.footage_all()
            for r in rows:
                print(f"#{r['id']:<4} {r['kind']:<9} {r['first_seen'] or '-':<10} {len(r['phashes']):>3} hashes  "
                      f"{(r['claim_note'] or '')[:50]}  {r['source_url'] or ''}")
            print(f"{len(rows)} entries")
    except extract.InputError as exc:
        print(f"Cannot read this file: {exc}", file=sys.stderr)
        return 2
    finally:
        store.close()
    return 0


def cmd_quota() -> int:
    settings = load_settings()
    store = Store(settings.db_path)
    rows = [("gemini", store.quota_used("gemini"), settings.gemini_daily_limit, "today"),
            ("factcheck", store.quota_used("factcheck"), settings.factcheck_daily_limit, "today"),
            ("youtube", store.quota_used("youtube"), settings.youtube_daily_units, "today (units)"),
            ("vision", store.quota_used("vision", monthly=True), settings.vision_monthly_units, "this month")]
    for name, used, limit, period in rows:
        print(f"{name:<10} {used:>6} / {limit:<6} {period}")
    store.close()
    return 0


def main(argv: list[str]) -> int:
    if argv and argv[0] == "index":
        return cmd_index(argv[1:])
    if argv and argv[0] == "quota":
        return cmd_quota()
    return cmd_analyze(argv)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
