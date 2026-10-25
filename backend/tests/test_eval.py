"""Phase 7: shared classification, the evaluator, threshold sweep, review queue, benchmark."""
import csv
import subprocess
import sys
from dataclasses import replace
from datetime import date
from pathlib import Path

import pytest
from PIL import Image

from app.db.store import Store
from app.eval import bench, evaluate, review
from app.pipeline import fingerprint as fp
from app.pipeline.models import Evidence
from app.pipeline.runner import analyze
from app.pipeline.scoring import Thresholds, classify

from .conftest import gemini_handler, make_video, reel_frame, scene
from .test_pipeline import CLAIM, install_youtube, yt_item

CUTOFF = date(2026, 10, 25)


@pytest.fixture
def t(settings):
    return Thresholds.of(settings)


def test_classify_rules(t):
    yt = lambda sim, d="2015-01-01", **k: Evidence("youtube", "x", "u", date=d, similarity=sim, **k)  # noqa: E731
    assert classify(yt(0.81), CUTOFF, t) == "earlier_footage"
    assert classify(yt(0.79), CUTOFF, t) == "lead"
    assert classify(yt(0.99, d="2026-10-24"), CUTOFF, t) == "lead"  # inside the 2-day tolerance
    assert classify(yt(0.5, clip_similarity=0.97), CUTOFF, t) == "earlier_footage"
    idx = lambda sim, n: Evidence("own_index", "x", "u", date="2016-01-01", similarity=sim, frames_matching=n)  # noqa: E731
    assert classify(idx(0.85, 1), CUTOFF, t) == "lead"            # one weak frame: could be chance
    assert classify(idx(0.85, 2), CUTOFF, t) == "earlier_footage"
    assert classify(idx(0.92, 1), CUTOFF, t) == "earlier_footage"
    fc = lambda rating, rel: Evidence("fact_check", "x", "u", rating=rating, relevance=rel)  # noqa: E731
    assert classify(fc("Misleading", 0.5), CUTOFF, t) == "debunk"
    assert classify(fc("Misleading", 0.2), CUTOFF, t) == "lead"
    assert classify(fc("True", 0.9), CUTOFF, t) == "lead"
    deb = Evidence("own_index", "x", "u", rating="debunked footage", similarity=0.88, frames_matching=3)
    assert classify(deb, CUTOFF, t) == "lead" and classify(replace(deb, similarity=0.95), CUTOFF, t) == "debunk"
    assert classify(Evidence("vision_web", "x", "u"), CUTOFF, t) == "lead"


def _apis(http, old):
    http.route("generativelanguage", gemini_handler(CLAIM))
    http.route("factchecktools", {})
    install_youtube(http, [yt_item("OLD123", "Plane crash caught on camera", "2015-03-02"),
                           yt_item("OTHER1", "Airport tour", "2019-01-01")], {"OLD123": old, "OTHER1": scene(99)})


def test_rescoring_at_production_thresholds_reproduces_production(settings, store, http, tmp_path):
    """The sweep is only meaningful if re-scoring saved evidence gives what production decided."""
    _apis(http, scene(10))
    reel = make_video(tmp_path / "r.mp4", [reel_frame(scene(10)), reel_frame(scene(11))])
    report = analyze(reel, settings, http=http, store=store, posted_date=CUTOFF)
    scored = evaluate.score(evaluate.Result(evaluate.Case(reel, "recycled"), report), settings, Thresholds.of(settings))
    assert scored.verdict == report["verdict"] and scored.confidence == report["confidence"]


def _cases(tmp_path, old) -> Path:
    make_video(tmp_path / "recycled.mp4", [reel_frame(old, "BREAKING"), reel_frame(scene(11))])
    make_video(tmp_path / "genuine.mp4", [reel_frame(scene(50)), reel_frame(scene(51))])
    make_video(tmp_path / "dark.mp4", [Image.new("RGB", (360, 640), (2, 2, 2))] * 2, audio=False)
    (tmp_path / "corrupt.mp4").write_bytes(b"\x00" * 3000)
    path = tmp_path / "cases.csv"
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["file", "expected", "caption", "posted_date", "original_url", "tags", "notes"])
        original = "https://www.youtube.com/watch?v=OLD123"
        w.writerow(["recycled.mp4", "recycled", "", "2026-10-25", original, "letterbox,te", ""])
        w.writerow(["genuine.mp4", "genuine", "", "2026-10-25", "", "te", ""])
        w.writerow(["dark.mp4", "poor", "", "", "", "dark", ""])
        w.writerow(["corrupt.mp4", "error", "", "", "", "", ""])
    return path


def test_eval_end_to_end_keeps_live_database_clean(settings, http, tmp_path):
    old = scene(10)
    _apis(http, old)
    http.route("vision.googleapis", {"responses": []})
    cases = evaluate.read_cases(_cases(tmp_path, old))
    live = Store(settings.db_path)
    live.footage_add(kind="debunked", phashes=[fp.variants(scene(77))[0]], first_seen="2010-01-01")
    live.close()

    results = evaluate.run_cases(cases, settings, http=http)
    out = evaluate.write_report(tmp_path / "eval", results, settings, max_fpr=0.0)
    m = out["metrics"]
    assert (m["recall"], m["precision"], m["false_positive_rate"]) == (1.0, 1.0, 0.0)
    assert (m["poor_handled"], m["errors_handled"], m["source_found"], m["accuracy"]) == (1.0, 1.0, 1.0, 1.0)
    assert m["by_tag"]["te"] == {"n": 2, "correct": 2, "accuracy": 1.0}
    report = (tmp_path / "eval" / "report.md").read_text()
    assert "| Recall | 100% |" in report and "STRONG_SIMILARITY=" in report
    # Gemini summary and Vision are not spent on evaluation.
    assert http.count("vision.googleapis") == 0
    assert not any("summary" in c[3]["generationConfig"]["responseSchema"]["properties"]
                   for c in http.calls if "generativelanguage" in c[1])

    live = Store(settings.db_path)
    assert len(live.footage_all()) == 1                       # no test reels in the index
    assert live.db.execute("select count(*) from reports").fetchone()[0] == 0
    assert live.cache_get(next(k for (k,) in live.db.execute("select key from api_cache") if k.startswith("yt:")), 1)
    # Charged to the real budget: 2 searches (the second case repeats them and hits the cache), 3 claim calls.
    assert live.quota_used("youtube") == 200 and live.quota_used("gemini") == 3
    live.close()

    # Re-scoring the saved run needs no API calls and gives the same numbers.
    n = len(http.calls)
    again = evaluate.load_results(tmp_path / "eval" / "results.json")
    assert evaluate.metrics([evaluate.score(r, settings, Thresholds.of(settings)) for r in again]) == m
    assert len(http.calls) == n


def _result(expected: str, sim: float, d: str = "2015-01-01", tags=()) -> evaluate.Result:
    report = {"claim": {"claim_text": "A crash today", "keywords": ["crash"], "recency": "current"},
              "cutoff_date": "2026-10-25",
              "quality": {"duration": 20, "total_frames": 6, "usable_frames": 6, "has_speech": True, "has_text": True},
              "checks": [{"name": n, "status": "ok", "detail": "", "seconds": 0}
                         for n in ("own_index", "fact_check", "youtube", "vision_web")],
              "evidence": [{"source": "youtube", "title": "x", "url": "https://www.youtube.com/watch?v=AAAAAAAAAAA",
                            "date": d, "similarity": sim, "frames_matching": 2, "supports": "lead"}],
              "verdict": "X", "partial": False}
    return evaluate.Result(evaluate.Case(Path(f"{expected}.mp4"), expected, tags=list(tags)), report, "", 10.0)


def test_sweep_finds_threshold_that_removes_false_positive(settings):
    results = [_result("recycled", 0.97), _result("recycled", 0.91), _result("genuine", 0.83),
               _result("genuine", 0.55)]
    current = evaluate.metrics([evaluate.score(r, settings, Thresholds.of(settings)) for r in results])
    assert current["false_positive_rate"] == 0.5 and current["recall"] == 1.0
    best = evaluate.recommend(evaluate.sweep(results, settings), max_fpr=0.0)
    assert best["recall"] == 1.0 and best["false_positive_rate"] == 0.0 and 0.84 <= best["weak"] <= 0.90


def test_read_cases_validation(tmp_path):
    bad = tmp_path / "bad.csv"
    bad.write_text("file,expected\nmissing.mp4,recycled\n")
    with pytest.raises(evaluate.CaseError, match="file not found"):
        evaluate.read_cases(bad)
    bad.write_text("file,expected\nx.mp4,maybe\n")
    with pytest.raises(evaluate.CaseError, match="expected must be"):
        evaluate.read_cases(bad)
    (tmp_path / "x.mp4").write_bytes(b"x")
    bad.write_text("file,expected,posted_date\nx.mp4,LIKELY_OLD_FOOTAGE,yesterday\n")
    with pytest.raises(evaluate.CaseError, match="posted_date"):
        evaluate.read_cases(bad)
    bad.write_text("file,expected\nx.mp4,LIKELY_OLD_FOOTAGE\n")
    assert evaluate.read_cases(bad)[0].expected == "recycled"  # verdict names map to groups


def test_review_queue(store):
    def put(rid, verdict):
        store.report_put("h" + rid, {"job_id": rid, "verdict": verdict, "confidence": 0.9,
                                     "claim": {"claim_text": f"claim {rid}"}, "evidence": []})
    put("aaaaaaaaaaaa", "LIKELY_OLD_FOOTAGE")
    put("bbbbbbbbbbbb", "NO_CONTRADICTION_FOUND")
    put("cccccccccccc", "NO_CONTRADICTION_FOUND")
    put("dddddddddddd", "DEBUNKED")
    store.feedback_add("cccccccccccc", False, "this is old, from 2019")
    q = review.queue(store)
    assert [i["id"] for i in q] == ["cccccccccccc", "aaaaaaaaaaaa", "dddddddddddd"]  # user complaints first
    review.mark(store, "aaaaaaaaaaaa", "correct")
    review.mark(store, "dddddddddddd", "wrong", "fact-check was about another video")
    with pytest.raises(ValueError):
        review.mark(store, "cccccccccccc", "maybe")
    with pytest.raises(KeyError):
        review.mark(store, "eeeeeeeeeeee", "correct")
    st = review.stats(store)
    assert st["open"] == 1 and st["flag_precision"] == 0.5 and st["feedback_no"] == 1
    assert len(review.queue(store, include_reviewed=True)) == 3


def test_bench_small(settings, tmp_path):
    videos = [make_video(tmp_path / f"v{i}.mp4", [scene(300 + i * 3 + j, size=(1280, 720)) for j in range(3)],
                         seconds_each=3, audio=False) for i in range(3)]
    result = bench.run(videos, settings, ["mirror", "letterbox_9x16"], progress=lambda *_: None)
    assert result["current"]["recall"] == 1.0 and result["current"]["false_matches"] == 0
    assert result["separation"]["true_best_p10"] > result["separation"]["false_best_max"]
    path = bench.write_report(result, tmp_path / "bench", synthetic=False)
    assert "| mirror | mirrored | 100% | 0/6 |" in path.read_text()


def test_cli_eval_rescore_and_review(settings, http, tmp_path):
    results = [_result("recycled", 0.97), _result("genuine", 0.55)]
    evaluate.write_report(tmp_path / "run", results, settings, 0.0)
    backend = Path(__file__).resolve().parents[1]
    env = {"PATH": "/usr/bin:/bin", "DATA_DIR": str(tmp_path), "OUTPUT_DIR": str(tmp_path / "o")}
    res = subprocess.run([sys.executable, "run.py", "eval", "--rescore", str(tmp_path / "run" / "results.json")],
                         cwd=backend, env=env, capture_output=True, text=True, timeout=120)
    assert res.returncode == 0 and "recall 100%" in res.stdout and "report:" in res.stdout
    res = subprocess.run([sys.executable, "run.py", "review", "stats"], cwd=backend, env=env,
                         capture_output=True, text=True, timeout=60)
    assert res.returncode == 0 and "open in queue: 0" in res.stdout


def test_cases_cannot_match_each_other(settings, http, tmp_path):
    """Two cases with the same footage: the second must not find the first in the index."""
    bare = replace(settings, gemini_api_key="", google_api_key="")
    for name in ("a", "b"):
        make_video(tmp_path / f"{name}.mp4", [reel_frame(scene(10), name), reel_frame(scene(11))], audio=False)
    path = tmp_path / "cases.csv"
    path.write_text("file,expected,caption\na.mp4,genuine,crash today\nb.mp4,genuine,crash today\n")
    results = evaluate.run_cases(evaluate.read_cases(path), bare, http=http)
    assert [e for r in results for e in r.report["evidence"] if e["source"] == "own_index"] == []


def test_chance_estimate_and_recommendation_respect_index_scale(settings):
    from app.pipeline.evidence.own_index import chance_matches
    assert chance_matches(0.90, 0.80) < 0.01 < chance_matches(0.90, 0.78) < chance_matches(0.90, 0.74)
    assert chance_matches(0.90, 0.80, index_fingerprints=10_000) < chance_matches(0.90, 0.80)
    # A loose weak threshold that catches one more case on a tiny set must not be recommended.
    results = [_result("recycled", 0.97), _result("recycled", 0.76), _result("genuine", 0.55)]
    rows = evaluate.sweep(results, settings)
    assert max(r["recall"] for r in rows) == 1.0          # weak <= 0.76 would catch both...
    best = evaluate.recommend(rows, max_fpr=0.0)
    assert best["recall"] == 0.5 and best["weak"] >= 0.80  # ...but is unsafe at production scale
