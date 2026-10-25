"""Evaluate the checker on a labelled set of reels and tune its thresholds.

  python run.py eval ../data/eval/cases.csv            run every case, report metrics, sweep thresholds
  python run.py eval --rescore output/eval/<run>/results.json   re-score a past run (no API calls)

cases.csv columns (see data/eval/README.md):
  file, expected (recycled | genuine | poor | error), caption, posted_date, original_url, tags, notes

How it stays honest and cheap:
- Cases run against a *copy* of the database: seeds and the API cache are used, but test reels never
  enter the live index, and no case can match another case. Afterwards the new API-cache entries
  and the quota spent are merged back, so a re-run costs nothing and the daily budgets stay true.
- Cases run with permissive "capture" thresholds and no index short-cut, so the saved evidence holds
  near-misses too. Verdicts at any thresholds are then recomputed from that evidence with the same
  `scoring.classify` and `verdict.decide` production uses. That is what makes the sweep possible.
- Vision and the LLM summary are switched off: they never change a verdict, and they cost quota.
"""
from __future__ import annotations

import csv
import json
import shutil
import sqlite3
import tempfile
import time
from collections.abc import Callable, Iterable
from dataclasses import asdict, dataclass, field, fields, replace
from datetime import date, datetime
from pathlib import Path

from ..core.config import Settings
from ..core.http import Http
from ..db.store import Store
from ..pipeline import extract
from ..pipeline.evidence.own_index import chance_matches
from ..pipeline.models import DEBUNKED, LIKELY_OLD_FOOTAGE, NO_CONTRADICTION_FOUND, UNVERIFIED, Check, Claim, Evidence
from ..pipeline.runner import analyze
from ..pipeline.scoring import Thresholds, reclassify
from ..pipeline.verdict import InputQuality, decide

FLAGGED = {DEBUNKED, LIKELY_OLD_FOOTAGE}
GROUPS = ("recycled", "genuine", "poor", "error")
VERDICT_GROUP = {DEBUNKED: "recycled", LIKELY_OLD_FOOTAGE: "recycled", NO_CONTRADICTION_FOUND: "genuine",
                 UNVERIFIED: "poor"}
STRONG_GRID = (0.84, 0.86, 0.88, 0.90, 0.92, 0.94, 0.96)
WEAK_GRID = (0.70, 0.72, 0.74, 0.76, 0.78, 0.80, 0.82, 0.84, 0.86, 0.88, 0.90)
RELEVANCE_GRID = (0.2, 0.34, 0.5)


class CaseError(Exception):
    pass


@dataclass
class Case:
    file: Path
    expected: str
    caption: str = ""
    posted_date: str = ""
    original_url: str = ""
    tags: list[str] = field(default_factory=list)
    notes: str = ""


@dataclass
class Result:
    case: Case
    report: dict | None = None   # full pipeline report (capture thresholds)
    error: str = ""              # input rejected (expected for 'error' cases)
    seconds: float = 0.0


@dataclass
class Scored:
    result: Result
    verdict: str                 # verdict at the thresholds being evaluated, or "ERROR"
    confidence: float = 0.0
    source_found: bool | None = None  # flagged recycled case: did the evidence include original_url?

    @property
    def group(self) -> str:
        return "error" if self.verdict == "ERROR" else VERDICT_GROUP[self.verdict]


def read_cases(path: Path) -> list[Case]:
    cases = []
    with open(path, newline="", encoding="utf-8-sig") as f:
        for n, row in enumerate(csv.DictReader(f), start=2):
            row = {k.strip(): (v or "").strip() for k, v in row.items() if k}
            if not row.get("file"):
                continue
            expected = row.get("expected", "").lower()
            expected = VERDICT_GROUP.get(expected.upper(), expected)
            if expected not in GROUPS:
                raise CaseError(f"line {n}: expected must be one of {', '.join(GROUPS)} (got {row.get('expected')!r})")
            file = Path(row["file"])
            file = file if file.is_absolute() else path.parent / file
            if not file.is_file() and expected != "error":
                raise CaseError(f"line {n}: file not found: {file}")
            if row.get("posted_date"):
                try:
                    date.fromisoformat(row["posted_date"])
                except ValueError:
                    raise CaseError(f"line {n}: posted_date must be YYYY-MM-DD") from None
            cases.append(Case(file=file, expected=expected, caption=row.get("caption", ""),
                              posted_date=row.get("posted_date", ""), original_url=row.get("original_url", ""),
                              tags=[t.strip() for t in row.get("tags", "").replace(";", ",").split(",") if t.strip()],
                              notes=row.get("notes", "")))
    if not cases:
        raise CaseError(f"no cases in {path}")
    return cases


def capture_settings(settings: Settings) -> Settings:
    return replace(settings, strong_similarity=min(STRONG_GRID), weak_similarity=min(WEAK_GRID),
                   factcheck_min_relevance=min(RELEVANCE_GRID), vision_enabled=False, llm_summary=False,
                   index_short_circuit=False)


def _copy_db(src: Path, dst: Path) -> None:
    if not src.is_file():
        Store(dst).close()
        return
    with sqlite3.connect(src) as a, sqlite3.connect(dst) as b:
        a.backup(b)  # consistent even while the API is writing (WAL)


def _merge_back(live_path: Path, copy: Store, started: float, quota_before: dict) -> None:
    """New cache entries and spent quota go back to the live database."""
    live = Store(live_path)
    try:
        for row in copy.db.execute("select key, response from api_cache where fetched_at >= ?", (started,)):
            live.cache_put(row["key"], json.loads(row["response"]))
        for row in copy.db.execute("select period, api, used from quota"):
            spent = row["used"] - quota_before.get((row["period"], row["api"]), 0)
            if spent > 0:
                live.quota_add(row["api"], row["period"], spent)
    finally:
        live.close()


def run_cases(cases: list[Case], settings: Settings, http: Http | None = None,
              progress: Callable[[int, Case, Result], None] | None = None) -> list[Result]:
    capture = capture_settings(settings)
    tmp = Path(tempfile.mkdtemp(prefix="reel-eval-"))
    results: list[Result] = []
    try:
        _copy_db(settings.db_path, tmp / "eval.sqlite")
        store = Store(tmp / "eval.sqlite")
        quota_before = {(r["period"], r["api"]): r["used"] for r in store.db.execute("select * from quota")}
        started = time.time()
        try:
            for n, case in enumerate(cases, start=1):
                t = time.monotonic()
                result = Result(case)
                try:
                    report = analyze(case.file, capture, caption=case.caption,
                                     posted_date=date.fromisoformat(case.posted_date) if case.posted_date else None,
                                     http=http, store=store, fresh=True, remember=False, out_dir=tmp / "out" / str(n))
                    report.pop("output_dir", None)
                    result.report = report
                except extract.InputError as exc:
                    result.error = str(exc)
                result.seconds = round(time.monotonic() - t, 2)
                results.append(result)
                if progress:
                    progress(n, case, result)
        finally:
            _merge_back(settings.db_path, store, started, quota_before)
            store.close()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return results


def _evidence(d: dict) -> Evidence:
    names = {f.name for f in fields(Evidence)}
    return Evidence(**{k: v for k, v in d.items() if k in names})


def _same_source(url: str, original: str) -> bool:
    if not url or not original:
        return False
    norm = lambda u: u.lower().split("://")[-1].removeprefix("www.").rstrip("/")  # noqa: E731
    if norm(url) == norm(original):
        return True
    from ..pipeline.seeding import SeedError, youtube_id
    try:
        return youtube_id(url) == youtube_id(original)
    except SeedError:
        return False


def score(result: Result, settings: Settings, t: Thresholds) -> Scored:
    if result.report is None:
        return Scored(result, "ERROR")
    r = result.report
    evidence = reclassify([_evidence(e) for e in r["evidence"]], date.fromisoformat(r["cutoff_date"]), t)
    v = decide(replace(settings, strong_similarity=t.strong, weak_similarity=t.weak,
                       factcheck_min_relevance=t.factcheck_min_relevance),
               Claim(**{k: v for k, v in r["claim"].items() if k in {f.name for f in fields(Claim)}}),
               evidence, InputQuality(**r["quality"]), [Check(**c) for c in r["checks"]])
    found = None
    if result.case.original_url and v.verdict in FLAGGED:
        found = any(_same_source(e.url, result.case.original_url)
                    for e in evidence if e.supports in ("debunk", "earlier_footage"))
    return Scored(result, v.verdict, v.confidence, found)


def _rate(num: int, den: int) -> float | None:
    return round(num / den, 3) if den else None


def metrics(scored: list[Scored]) -> dict:
    by = {g: [s for s in scored if s.result.case.expected == g] for g in GROUPS}
    flagged = [s for s in scored if s.verdict in FLAGGED]
    rec_flagged = [s for s in by["recycled"] if s.verdict in FLAGGED]
    with_source = [s for s in rec_flagged if s.source_found is not None]
    seconds = sorted(s.result.seconds for s in scored if s.result.report)
    pct = lambda q: seconds[min(len(seconds) - 1, int(q * len(seconds)))] if seconds else None  # noqa: E731
    tags: dict[str, dict] = {}
    for s in scored:
        for tag in s.result.case.tags:
            d = tags.setdefault(tag, {"n": 0, "correct": 0})
            d["n"] += 1
            d["correct"] += correct(s)
    for d in tags.values():
        d["accuracy"] = _rate(d["correct"], d["n"])
    confusion = {g: {v: sum(1 for s in by[g] if s.verdict == v)
                     for v in (DEBUNKED, LIKELY_OLD_FOOTAGE, NO_CONTRADICTION_FOUND, UNVERIFIED, "ERROR")}
                 for g in GROUPS if by[g]}
    return {
        "cases": len(scored),
        "counts": {g: len(by[g]) for g in GROUPS},
        "recall": _rate(len(rec_flagged), len(by["recycled"])),          # recycled footage caught
        "precision": _rate(len(rec_flagged), len(flagged)),              # flags that were right
        "false_positive_rate": _rate(sum(1 for s in by["genuine"] if s.verdict in FLAGGED), len(by["genuine"])),
        "poor_handled": _rate(sum(1 for s in by["poor"] if s.verdict == UNVERIFIED), len(by["poor"])),
        "errors_handled": _rate(sum(1 for s in by["error"] if s.verdict == "ERROR"), len(by["error"])),
        "recycled_unverified": sum(1 for s in by["recycled"] if s.verdict == UNVERIFIED),
        "source_found": _rate(sum(1 for s in with_source if s.source_found), len(with_source)),
        "accuracy": _rate(sum(correct(s) for s in scored), len(scored)),
        "seconds_p50": pct(0.5), "seconds_p95": pct(0.95), "seconds_max": seconds[-1] if seconds else None,
        "within_60s": _rate(sum(1 for x in seconds if x <= 60), len(seconds)),
        "partial_reports": sum(1 for s in scored if s.result.report and s.result.report.get("partial")),
        "by_tag": dict(sorted(tags.items())),
        "confusion": confusion,
    }


def correct(s: Scored) -> bool:
    g = s.result.case.expected
    if g == "recycled":
        return s.verdict in FLAGGED
    if g == "genuine":
        return s.verdict not in FLAGGED and s.verdict != "ERROR"
    if g == "poor":
        return s.verdict == UNVERIFIED
    return s.verdict == "ERROR"


def sweep(results: list[Result], settings: Settings) -> list[dict]:
    base = Thresholds.of(settings)
    rows = []
    for strong in STRONG_GRID:
        for weak in WEAK_GRID:
            if weak > strong:
                continue
            for rel in RELEVANCE_GRID:
                t = replace(base, strong=strong, weak=weak, factcheck_min_relevance=rel)
                m = metrics([score(r, settings, t) for r in results])
                rows.append({"strong": strong, "weak": weak, "relevance": rel, **{
                    k: m[k] for k in ("recall", "precision", "false_positive_rate", "accuracy")}})
    return rows


def recommend(rows: list[dict], max_fpr: float, chance_budget: float = 0.01) -> dict | None:
    """Most recycled footage caught without exceeding the false-positive budget; ties go to the
    stricter (more conservative) setting. Settings that would let a million-fingerprint index match
    reels by chance are excluded however well they do on a small test set."""
    ok = [r for r in rows if (r["false_positive_rate"] or 0) <= max_fpr and r["recall"] is not None
          and chance_matches(r["strong"], r["weak"]) <= chance_budget]
    if not ok:
        return None
    return max(ok, key=lambda r: (r["recall"], r["precision"] or 0, r["weak"], r["strong"], r["relevance"]))


def _fmt(x) -> str:
    return "-" if x is None else f"{x:.0%}" if isinstance(x, float) else str(x)


def write_report(out: Path, results: list[Result], settings: Settings, max_fpr: float, do_sweep: bool = True) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    current = Thresholds.of(settings)
    scored = [score(r, settings, current) for r in results]
    m = metrics(scored)
    rows = sweep(results, settings) if do_sweep else []
    best = recommend(rows, max_fpr) if rows else None

    lines = [f"# Evaluation: {datetime.now():%Y-%m-%d %H:%M}", "",
             f"{m['cases']} cases: " + ", ".join(f"{n} {g}" for g, n in m["counts"].items() if n), "",
             f"## At the current thresholds (strong {current.strong}, weak {current.weak}, "
             f"fact-check relevance {current.factcheck_min_relevance})", "",
             "| Measure | Value | What it means |", "|---|---|---|",
             f"| Recall | {_fmt(m['recall'])} | recycled footage caught (DEBUNKED or LIKELY_OLD_FOOTAGE) |",
             f"| Precision | {_fmt(m['precision'])} | flags that were right |",
             f"| False-positive rate | {_fmt(m['false_positive_rate'])} | genuine reels wrongly flagged |",
             f"| Poor input handled | {_fmt(m['poor_handled'])} | too short / dark / no claim → UNVERIFIED |",
             f"| Bad uploads rejected | {_fmt(m['errors_handled'])} | corrupt / oversized files refused |",
             f"| Source found | {_fmt(m['source_found'])} | flagged recycled cases whose evidence includes the "
             "true original |",
             f"| Accuracy | {_fmt(m['accuracy'])} | every case in its expected group |",
             f"| Time p50 / p95 / max | {m['seconds_p50']} / {m['seconds_p95']} / {m['seconds_max']} s | goal: under "
             "60 s |",
             f"| Partial reports | {m['partial_reports']} | a check could not run (key, quota) |", ""]
    if m["recycled_unverified"]:
        lines += [f"{m['recycled_unverified']} recycled case(s) came back UNVERIFIED: usually a missing key or "
                  "spent quota, see the cases table.", ""]
    if m["by_tag"]:
        lines += ["## By tag", "", "| Tag | Cases | Correct |", "|---|---|---|"]
        lines += [f"| {tag} | {d['n']} | {_fmt(d['accuracy'])} |" for tag, d in m["by_tag"].items()]
        lines.append("")
    lines += ["## Confusion (expected → verdict)", "",
              "| Expected | DEBUNKED | LIKELY_OLD | NO_CONTRADICTION | UNVERIFIED | ERROR |",
              "|---|---|---|---|---|---|"]
    lines += [f"| {g} | " + " | ".join(str(n) for n in row.values()) + " |" for g, row in m["confusion"].items()]
    lines.append("")
    if rows:
        lines += ["## Threshold sweep", ""]
        if not m["counts"]["genuine"]:
            lines += ["**No genuine reels in the set, so false positives cannot be measured.** Add recent, real "
                      "footage before trusting any recommendation.", ""]
        if best:
            lines += [f"Best with false-positive rate ≤ {max_fpr:.0%}: recall {_fmt(best['recall'])}, precision "
                      f"{_fmt(best['precision'])}, false positives {_fmt(best['false_positive_rate'])}. In `.env`:", "",
                      "```", f"STRONG_SIMILARITY={best['strong']}", f"WEAK_SIMILARITY={best['weak']}",
                      f"FACTCHECK_MIN_RELEVANCE={best['relevance']}", "```", ""]
        else:
            lines += [f"No setting keeps false positives at or below {max_fpr:.0%}.", ""]
        top = sorted(rows, key=lambda r: (-(r["recall"] or 0), r["false_positive_rate"] or 0, -r["weak"]))[:12]
        lines += ["| Strong | Weak | Relevance | Recall | Precision | False positives |", "|---|---|---|---|---|---|"]
        lines += [f"| {r['strong']} | {r['weak']} | {r['relevance']} | {_fmt(r['recall'])} | {_fmt(r['precision'])} "
                  f"| {_fmt(r['false_positive_rate'])} |" for r in top]
        lines += ["", "Small test sets overfit: prefer the stricter of equally good settings, and re-check on new "
                  "reels.", ""]
    lines += ["## Cases", "", "| # | File | Expected | Verdict | Conf. | Time | Tags | Top evidence |",
              "|---|---|---|---|---|---|---|---|"]
    for n, s in enumerate(scored, start=1):
        r = s.result
        ev = next((e for e in (r.report or {}).get("evidence", []) if e.get("url")), None)
        mark = "" if correct(s) else " ✗"
        lines.append(f"| {n} | {r.case.file.name} | {r.case.expected} | {s.verdict}{mark} | {_fmt(s.confidence)} | "
                     f"{r.seconds}s | {', '.join(r.case.tags)} | "
                     + (f"[{(ev.get('title') or ev['url'])[:40].replace('|', '/')}]({ev['url']})" if ev else
                        (r.error[:60] if r.error else "-")) + " |")
    (out / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (out / "results.json").write_text(json.dumps(
        {"settings": asdict(current), "metrics": m, "recommendation": best,
         "results": [{"case": {**asdict(r.case), "file": str(r.case.file)}, "report": r.report, "error": r.error,
                      "seconds": r.seconds} for r in results]}, indent=1, ensure_ascii=False, default=str),
        encoding="utf-8")
    if rows:
        with open(out / "sweep.csv", "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0]))
            w.writeheader()
            w.writerows(rows)
    return {"metrics": m, "recommendation": best}


def load_results(path: Path) -> list[Result]:
    data = json.loads(path.read_text(encoding="utf-8"))
    out = []
    for r in data["results"]:
        c = r["case"]
        out.append(Result(Case(Path(c["file"]), c["expected"], c["caption"], c["posted_date"], c["original_url"],
                               c["tags"], c["notes"]), r["report"], r["error"], r["seconds"]))
    return out


def summary_lines(m: dict, best: dict | None) -> Iterable[str]:
    yield (f"recall {_fmt(m['recall'])} · precision {_fmt(m['precision'])} · false positives "
           f"{_fmt(m['false_positive_rate'])} · accuracy {_fmt(m['accuracy'])} · p95 {m['seconds_p95']}s")
    if best:
        yield (f"recommended: STRONG_SIMILARITY={best['strong']} WEAK_SIMILARITY={best['weak']} "
               f"FACTCHECK_MIN_RELEVANCE={best['relevance']} (recall {_fmt(best['recall'])}, "
               f"false positives {_fmt(best['false_positive_rate'])})")
