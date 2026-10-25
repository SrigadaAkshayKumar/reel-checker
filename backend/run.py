"""Reel Fact-Checker command line.

  python run.py reel.mp4 [--caption "text from the post"] [--posted 2026-10-24] [--json]
  python run.py index add-youtube URL [--first-seen 2016-05-01] --note "..." [--fact-check URL]
  python run.py index add old.mp4 --first-seen 2016-05-01 [--source-url URL] --note "..." [--fact-check URL]
  python run.py index add-images still1.jpg https://.../still2.jpg --first-seen ... --source-url URL --note "..."
  python run.py index import seeds.json|candidates.csv      python run.py index export pack.json
  python run.py index harvest [--query "old video"]... [--out ../data/seed/candidates.csv]
  python run.py index list | stats | remove ID
  python run.py quota
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

from app.core.config import load_settings
from app.core.http import Http
from app.db.store import Store
from app.pipeline import extract, seeding
from app.pipeline.context import Context
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


def _entry_args(p: argparse.ArgumentParser, first_seen_required: bool = True) -> None:
    p.add_argument("--first-seen", type=_date, required=first_seen_required,
                   help="earliest date the footage is known online")
    p.add_argument("--source-url", default="", help="where the original was first published")
    p.add_argument("--note", default="", help="what it really shows / the false claim it was used for")
    p.add_argument("--fact-check", default="", help="URL of a fact-check about it")


def cmd_index(argv: list[str]) -> int:
    p = argparse.ArgumentParser(prog="run.py index", description="Manage the known-footage index (hashes only).")
    sub = p.add_subparsers(dest="action", required=True)
    yt = sub.add_parser("add-youtube", help="fingerprint a YouTube video's thumbnails (nothing is downloaded)")
    yt.add_argument("url")
    _entry_args(yt, first_seen_required=False)
    add = sub.add_parser("add", help="fingerprint a local video (the video itself is not stored)")
    add.add_argument("video", type=Path)
    _entry_args(add)
    img = sub.add_parser("add-images", help="fingerprint stills (files or URLs), e.g. from a fact-check article")
    img.add_argument("images", nargs="+")
    _entry_args(img)
    imp = sub.add_parser("import", help="load a seed JSON or candidates CSV (see data/seed/README.md)")
    imp.add_argument("file", type=Path)
    exp = sub.add_parser("export", help="write the seeded entries as a shareable JSON pack (hashes only)")
    exp.add_argument("file", type=Path)
    exp.add_argument("--all", action="store_true", help="include 'seen' rows from analysed reels")
    hv = sub.add_parser("harvest", help="collect fact-checks rated false into a CSV of candidates to fill in")
    hv.add_argument("--query", action="append", help="search text (repeatable); default: data/seed/harvest_queries.txt")
    hv.add_argument("--out", type=Path, default=Path("../data/seed/candidates.csv"))
    sub.add_parser("list", help="show indexed footage")
    sub.add_parser("stats", help="counts and the most-resurfaced footage")
    rm = sub.add_parser("remove", help="delete an entry")
    rm.add_argument("id", type=int)
    a = p.parse_args(argv)

    settings = load_settings()
    store = Store(settings.db_path)
    http = Http()
    ctx = Context(settings, http, store, Gemini(settings, http, store), date.today())

    def entry(**footage) -> dict:
        return {"first_seen": a.first_seen.isoformat() if a.first_seen else "", "source_url": a.source_url,
                "claim_note": a.note, "fact_check_url": a.fact_check, **footage}
    try:
        if a.action in ("add-youtube", "add", "add-images"):
            if a.action == "add-youtube":
                footage = {"youtube": a.url}
            elif a.action == "add":
                footage = {"video": str(a.video)}
            else:
                footage = {"images": a.images}
            print(seeding.add_entry(ctx, entry(**footage))[1])
        elif a.action == "import":
            result = seeding.import_file(ctx, a.file)
            for key in ("added", "skipped", "failed"):
                for line in result[key]:
                    print(f"{key:<8} {line}")
            print(f"{len(result['added'])} added, {len(result['skipped'])} skipped, {len(result['failed'])} failed")
        elif a.action == "export":
            entries = seeding.export_entries(ctx, kind=None if a.all else "debunked")
            a.file.write_text(json.dumps(entries, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
            print(f"wrote {len(entries)} entries to {a.file}")
        elif a.action == "harvest":
            queries = a.query or [q.strip() for q in (settings.data_dir / "seed" / "harvest_queries.txt")
                                  .read_text(encoding="utf-8").splitlines() if q.strip() and not q.startswith("#")]
            n, errors = seeding.harvest(ctx, queries, a.out)
            for e in errors:
                print(f"error: {e}", file=sys.stderr)
            print(f"{n} new candidates in {a.out}. Fill in youtube / images / video and first_seen, "
                  f"then: python run.py index import {a.out}")
        elif a.action == "remove":
            print("removed" if store.footage_remove(a.id) else f"no entry #{a.id}")
        else:
            rows = store.footage_all()
            if a.action == "list":
                for r in rows:
                    print(f"#{r['id']:<4} {r['kind']:<9} {r['first_seen'] or '-':<10} {len(r['phashes']):>3} hashes "
                          f"x{r['times_seen']:<3} {(r['claim_note'] or '')[:50]}  {r['source_url'] or ''}")
            by_kind: dict[str, int] = {}
            for r in rows:
                by_kind[r["kind"]] = by_kind.get(r["kind"], 0) + 1
            print(f"{len(rows)} entries ({', '.join(f'{v} {k}' for k, v in sorted(by_kind.items())) or 'empty'}), "
                  f"{sum(len(r['phashes']) for r in rows)} fingerprints")
            if a.action == "stats":
                top = sorted((r for r in rows if r["times_seen"] > 1), key=lambda r: -r["times_seen"])[:10]
                for r in top:
                    note = (r["claim_note"] or "")[:60]
                    print(f"  seen {r['times_seen']}x since {r['first_seen']}: #{r['id']} {note}")
    except seeding.SeedError as exc:
        print(f"error: {exc}", file=sys.stderr)
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
