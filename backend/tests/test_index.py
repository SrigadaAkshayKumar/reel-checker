"""Phase 6: the known-footage index, seeding tools and how analyses use them."""
import csv
import json
import os
import subprocess
import sys
from dataclasses import replace
from datetime import date
from pathlib import Path

import numpy as np
import pytest

from app.db.store import Store
from app.pipeline import fingerprint as fp
from app.pipeline import seeding
from app.pipeline.context import Context
from app.pipeline.evidence import own_index
from app.pipeline.llm import Gemini
from app.pipeline.report import to_console, to_markdown
from app.pipeline.runner import analyze

from .conftest import jpeg, make_video, reel_frame, scene, yt_thumb
from .test_pipeline import CLAIM, gemini_handler

TODAY = date(2026, 10, 25)


@pytest.fixture
def bare(settings):
    """No API keys: everything below must work offline from the index alone."""
    return replace(settings, gemini_api_key="", google_api_key="", public_base_url="https://reelcheck.example")


@pytest.fixture
def ctx(settings, store, http):
    return Context(settings, http, store, Gemini(settings, http, store), TODAY)


def test_vectorised_match_agrees_with_reference(ctx, store):
    rng = np.random.default_rng(7)
    rand = lambda: f"{int(rng.integers(0, 2**63)):016x}"  # noqa: E731
    rows = [[rand() for _ in range(int(rng.integers(1, 8)))] for _ in range(40)]
    for hashes in rows:
        store.footage_add(kind="debunked", phashes=hashes, first_seen="2016-01-01")
    # Frames: some exact copies of stored hashes with a few bits flipped, some random.
    frames = []
    for i in range(6):
        base = int(rows[i * 5][0], 16) ^ (0b1011 << i) if i % 2 == 0 else int(rand(), 16)
        frames.append([f"{base:016x}", rand()])
    got = {m.row["id"]: m for m in own_index.match(own_index.load_index(ctx), frames, 0.0, 0.0)}
    for row_id, hashes in enumerate(rows, start=1):
        sim, _ = fp.best_match(frames, hashes)
        assert got[row_id].similarity == pytest.approx(sim), row_id
        assert got[row_id].frames_matching == fp.frames_matching(frames, hashes, 0.0)


def test_large_index_does_not_match_by_chance():
    """~1e8 random comparisons: single-frame 0.80 hits happen by chance; they must not count."""
    rng = np.random.default_rng(1)
    rows, per = 50_000, 12
    index = own_index.FootageIndex((rows, rows), [{"id": i} for i in range(rows)],
                                   rng.integers(0, 2**63, size=rows * per, dtype=np.uint64),
                                   np.arange(0, rows * per, per), {})
    frames = [[f"{int(x):016x}" for x in rng.integers(0, 2**63, size=7)] for _ in range(12)]
    assert own_index.match(index, frames, 0.0, 0.0)  # sanity: the rows are there
    single = own_index.match(index, frames, 0.80, 0.80)  # any row with one frame >= 0.80
    assert own_index.match(index, frames, 0.80, 0.90) == []
    assert single and all(m.frames_matching == 1 for m in single)  # chance hits the two-frame rule drops


def test_weak_match_needs_two_frames(ctx, store):
    a, b = int(fp.variants(scene(1))[0], 16), int(fp.variants(scene(2))[0], 16)
    store.footage_add(kind="debunked", phashes=[f"{a:016x}", f"{b:016x}"], first_seen="2016-01-01")
    near = lambda h: [f"{h ^ 0b1111111111:016x}"]  # noqa: E731  10 bits off: similarity 0.84
    index = own_index.load_index(ctx)
    assert own_index.match(index, [near(a)], 0.80, 0.90) == []
    two = own_index.match(index, [near(a), near(b)], 0.80, 0.90)
    assert len(two) == 1 and two[0].frames_matching == 2 and two[0].similarity == pytest.approx(0.84375)


def test_second_sighting_links_earlier_report_and_counts_instead_of_duplicating(bare, store, http, tmp_path):
    first = make_video(tmp_path / "a.mp4", [reel_frame(scene(10)), reel_frame(scene(11))])
    r1 = analyze(first, bare, http=http, store=store, caption="Plane crash", posted_date=date(2026, 10, 1))
    assert r1["fingerprint"] == "added"
    store.db.execute("update known_footage set first_seen = '2026-10-01'")
    store.db.commit()

    # A re-encoded copy with a new caption overlay, shared weeks later as "today".
    copy = make_video(tmp_path / "b.mp4", [reel_frame(scene(10), "TODAY"), reel_frame(scene(11))], audio=False)
    r2 = analyze(copy, bare, http=http, store=store, caption="Plane crash today", posted_date=TODAY)
    assert r2["verdict"] == "LIKELY_OLD_FOOTAGE"
    ev = r2["evidence"][0]
    assert ev["source"] == "own_index" and ev["date"] == "2026-10-01"
    assert ev["url"] == f"https://reelcheck.example/r/{r1['job_id']}"
    assert "first seen 2026-10-01 in our database of known footage" in r2["reasons"][0]
    assert "own_index" not in " ".join(r2["reasons"])
    # One row, two sightings.
    rows = store.footage_all()
    assert len(rows) == 1 and rows[0]["times_seen"] == 2 and r2["fingerprint"] == "merged"
    assert rows[0]["last_seen"] == date.today().isoformat()


def test_evidence_without_a_link_renders_everywhere(bare, store, http, tmp_path, settings):
    """Rows recorded before report links existed have no URL; that crashed report writing once."""
    from fastapi.testclient import TestClient

    from app.main import create_app
    store.footage_add(kind="seen", phashes=[fp.variants(scene(10))[0], fp.variants(scene(11))[0]],
                      first_seen="2026-09-01", video_hash="old")
    reel = make_video(tmp_path / "r.mp4", [reel_frame(scene(10)), reel_frame(scene(11))])
    r = analyze(reel, bare, http=http, store=store, caption="today", posted_date=TODAY)
    ev = r["evidence"][0]
    assert ev["source"] == "own_index" and "url" not in ev and ev["title"] == "Checked here on 2026-09-01"
    assert "Checked here on 2026-09-01" in to_markdown(r) and to_console(r)
    with TestClient(create_app(replace(settings, db_path=bare.db_path, output_dir=bare.output_dir),
                               start_worker=False)) as c:
        page = c.get(f"/r/{r['job_id']}")
        assert page.status_code == 200 and "<strong>Checked here on 2026-09-01</strong>" in page.text
        assert "own_index" not in page.text.split("<script>")[0]


def test_strong_index_match_saves_youtube_quota(settings, store, http, tmp_path):
    store.footage_add(kind="debunked", phashes=[fp.variants(scene(10))[0], fp.variants(scene(11))[0]],
                      source_url="https://youtube.com/watch?v=orig", first_seen="2016-07-01",
                      claim_note="2016 cargo plane crash, Brazil", fact_check_url="https://factly.in/x")
    http.route("generativelanguage", gemini_handler(CLAIM))
    http.route("factchecktools", {})
    reel = make_video(tmp_path / "r.mp4", [reel_frame(scene(10)), reel_frame(scene(11))])
    r = analyze(reel, settings, http=http, store=store, posted_date=TODAY)
    checks = {c["name"]: c for c in r["checks"]}
    assert checks["youtube"]["status"] == "not_needed" and checks["vision_web"]["status"] == "not_needed"
    assert http.count("youtube/v3") == 0 and http.count("vision.googleapis") == 0
    assert http.count("factchecktools") == 1  # cheap, still asked
    assert r["verdict"] == "DEBUNKED" and not r["partial"]


def test_add_youtube_entry_uses_upload_date_and_skips_duplicates(ctx, http):
    for n, url in enumerate(("hqdefault", "1", "2", "3")):
        http.bytes_routes[f"https://i.ytimg.com/vi/AbCdEfGhIjK/{url}.jpg"] = (
            yt_thumb(scene(10)) if n == 0 else jpeg(scene(10).resize((120, 90))))
    http.route("youtube/v3/videos", {"items": [{"snippet": {"publishedAt": "2015-03-02T10:00:00Z",
                                                           "title": "Cargo plane crash"}}]})
    row, msg = seeding.add_entry(ctx, {"youtube": "https://youtu.be/AbCdEfGhIjK?t=3", "fact_check_url": "https://f/1"})
    assert row and "first seen 2015-03-02" in msg
    saved = ctx.store.footage_all()[0]
    assert saved["source_url"] == "https://www.youtube.com/watch?v=AbCdEfGhIjK"
    assert saved["claim_note"] == "Cargo plane crash" and saved["kind"] == "debunked"
    assert fp.best_match([fp.variants(reel_frame(scene(10)))], saved["phashes"])[0] >= 0.9
    again, msg = seeding.add_entry(ctx, {"youtube": "AbCdEfGhIjK"})
    assert again is None and "already indexed" in msg
    assert ctx.store.quota_used("youtube") == 2  # videos.list costs 1 unit each time


def test_entry_validation(ctx, tmp_path):
    with pytest.raises(seeding.SeedError, match="no footage"):
        seeding.add_entry(ctx, {"first_seen": "2016-01-01"})
    with pytest.raises(seeding.SeedError, match="first_seen is required"):
        seeding.add_entry(ctx, {"phashes": ["0123456789abcdef"]})
    with pytest.raises(seeding.SeedError, match="bad phash"):
        seeding.add_entry(ctx, {"phashes": ["xyz"], "first_seen": "2016-01-01"})
    with pytest.raises(seeding.SeedError, match="YYYY-MM-DD"):
        seeding.add_entry(ctx, {"phashes": ["0123456789abcdef"], "first_seen": "last year"})
    with pytest.raises(seeding.SeedError, match="not a YouTube"):
        seeding.add_entry(ctx, {"youtube": "https://vimeo.com/123", "first_seen": "2016-01-01"})
    assert seeding.youtube_id("https://www.youtube.com/shorts/AbCdEfGhIjK") == "AbCdEfGhIjK"


def test_add_images_and_video(ctx, tmp_path):
    still = tmp_path / "still.jpg"
    still.write_bytes(jpeg(scene(20)))
    row, _ = seeding.add_entry(ctx, {"images": [str(still)], "first_seen": "2019-05-05", "source_url": "https://a"})
    video = make_video(tmp_path / "orig.mp4", [scene(30), scene(31)], audio=False)
    row2, msg = seeding.add_entry(ctx, {"video": str(video), "first_seen": "2018-01-01", "source_url": "https://b"})
    assert row and row2 and "fingerprints" in msg
    hashes = ctx.store.footage_all()[1]["phashes"]
    assert fp.best_match([fp.variants(reel_frame(scene(31)))], hashes)[0] >= 0.9


def test_csv_import_export_roundtrip(ctx, tmp_path, settings):
    still = tmp_path / "s.jpg"
    still.write_bytes(jpeg(scene(40)))
    candidates = tmp_path / "candidates.csv"
    with open(candidates, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=seeding.CSV_FIELDS)
        w.writeheader()
        w.writerow({"claim_note": "Flood video from 2019", "first_seen": "2019-08-01", "images": "s.jpg",
                    "fact_check_url": "https://f/2"})
        w.writerow({"claim_note": "Not filled in yet", "fact_check_url": "https://f/3"})
        w.writerow({"claim_note": "Hashes", "first_seen": "2017-01-01", "phashes": "0123456789abcdef fedcba9876543210",
                    "source_url": "https://c"})
        w.writerow({"claim_note": "Broken", "first_seen": "2017-01-01", "images": "missing.jpg"})
    result = seeding.import_file(ctx, candidates)
    assert len(result["added"]) == 2 and len(result["skipped"]) == 1 and len(result["failed"]) == 1
    assert "missing.jpg" in result["failed"][0]

    pack = tmp_path / "pack.json"
    pack.write_text(json.dumps(seeding.export_entries(ctx)))
    assert all(set(e) == {"source_url", "first_seen", "claim_note", "fact_check_url", "phashes"}
               for e in json.loads(pack.read_text()))
    other = Store(tmp_path / "other.sqlite")
    fresh = Context(settings, ctx.http, other, ctx.llm, TODAY)
    assert len(seeding.import_file(fresh, pack)["added"]) == 2
    assert [r["phashes"] for r in other.footage_all()] == [r["phashes"] for r in ctx.store.footage_all()]
    other.close()


def test_harvest_collects_only_false_ratings_once(ctx, http, tmp_path):
    http.route("factchecktools", {"claims": [
        {"text": "Video shows plane crash in Hyderabad", "claimReview": [
            {"url": "https://factly.in/a", "title": "Old Brazil crash video shared as Hyderabad",
             "textualRating": "Misleading", "publisher": {"name": "Factly"}, "reviewDate": "2026-10-24T00:00:00Z"}]},
        {"text": "Minister inaugurated bridge", "claimReview": [
            {"url": "https://factly.in/b", "title": "Bridge opened", "textualRating": "True"}]}]})
    out = tmp_path / "candidates.csv"
    n, errors = seeding.harvest(ctx, ["old video", "plane crash video"], out)
    assert (n, errors) == (1, [])
    n2, _ = seeding.harvest(ctx, ["old video"], out)
    assert n2 == 0
    rows = list(csv.DictReader(open(out)))
    assert len(rows) == 1 and rows[0]["fact_check_url"] == "https://factly.in/a"
    assert rows[0]["publisher"] == "Factly" and rows[0]["review_date"] == "2026-10-24"


def test_index_cache_follows_adds_and_removes(ctx, store):
    assert own_index.load_index(ctx).rows == []
    rid = store.footage_add(kind="debunked", phashes=[fp.variants(scene(1))[0]], first_seen="2016-01-01")
    assert [r["id"] for r in own_index.load_index(ctx).rows] == [rid]
    assert store.footage_remove(rid)
    assert own_index.load_index(ctx).rows == []


def test_clip_scores_rescue_matches_phash_misses(ctx, store, monkeypatch, tmp_path):
    from app.pipeline import clip
    monkeypatch.setattr(clip, "available", lambda: True)
    monkeypatch.setattr(clip, "embed", lambda images: np.ones((len(images), 4), dtype=np.float32))
    use_clip = replace(ctx.settings, use_clip=True)
    still = tmp_path / "s.jpg"
    still.write_bytes(jpeg(scene(60)))
    seeding.add_entry(replace(ctx, settings=use_clip), {"images": [str(still)], "first_seen": "2015-01-01",
                                                         "source_url": "https://x"})
    assert store.footage_all(with_embeddings=True)[0]["embeddings"]
    frame = tmp_path / "f.jpg"
    reel_frame(scene(61)).save(frame)  # a different picture: pHash cannot match it
    from app.pipeline.models import Keyframe
    img = fp.open_image(frame.read_bytes())
    variants = fp.variants(img)
    k = Keyframe(0, 1.0, str(frame), *fp.image_stats(img), phash=variants[0], variants=variants)
    assert own_index.find(ctx, [k]) == []
    found = own_index.find(replace(ctx, settings=use_clip), [k])
    assert len(found) == 1 and found[0].clip_similarity == pytest.approx(1.0) and found[0].similarity < 0.8


def test_v1_known_footage_table_gains_phase6_columns(tmp_path):
    import sqlite3
    db = tmp_path / "v1.sqlite"
    con = sqlite3.connect(db)
    con.execute("create table known_footage (id integer primary key autoincrement, kind text not null,"
                " source_url text, first_seen text, claim_note text, fact_check_url text, phashes text not null,"
                " video_hash text, added_at text not null)")
    con.execute("insert into known_footage (kind, phashes, added_at) values ('seen', '[\"0123456789abcdef\"]', 'x')")
    con.commit()
    con.close()
    store = Store(db)
    row = store.footage_all()[0]
    assert row["times_seen"] == 1 and row["report_id"] is None
    store.footage_touch(row["id"], "2026-10-25")
    assert store.footage_all()[0]["times_seen"] == 2
    store.close()


def test_cli_index_commands(tmp_path):
    env = {**os.environ, "DATA_DIR": str(tmp_path), "GEMINI_API_KEY": "", "GOOGLE_API_KEY": ""}
    still = tmp_path / "s.jpg"
    still.write_bytes(jpeg(scene(70)))
    backend = Path(__file__).resolve().parents[1]

    def run(*args):
        res = subprocess.run([sys.executable, "run.py", "index", *args], cwd=backend, env=env,
                             capture_output=True, text=True, timeout=120)
        return res.returncode, res.stdout + res.stderr

    code, out = run("add-images", str(still), "--first-seen", "2015-05-05", "--source-url", "https://s",
                    "--note", "Old storm footage")
    assert code == 0 and "added #1" in out
    code, out = run("add-youtube", "AbCdEfGhIjK", "--first-seen", "2016-01-01")
    assert code == 2 and "no thumbnails" in out  # offline: YouTube unreachable, reported cleanly
    code, out = run("list")
    assert code == 0 and "Old storm footage" in out and "1 entries" in out
    code, out = run("export", str(tmp_path / "pack.json"))
    assert code == 0 and "wrote 1 entries" in out
    assert "removed" in run("remove", "1")[1]
    code, out = run("import", str(tmp_path / "pack.json"))
    assert code == 0 and "1 added" in out
    assert "1 entries (1 debunked), 1 fingerprints" in run("stats")[1]
