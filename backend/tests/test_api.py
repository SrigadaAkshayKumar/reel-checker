"""API + worker, end to end, with every external API faked."""
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from app.db.store import Store
from app.main import create_app
from app.worker import Worker

from .conftest import gemini_handler, make_video, reel_frame, scene
from .test_pipeline import CLAIM, install_youtube, yt_item


@pytest.fixture
def api_settings(settings):
    return replace(settings, rate_limit_per_day=5, ip_hash_salt="test-salt",
                   public_base_url="https://reelcheck.example")


@pytest.fixture
def client(api_settings):
    with TestClient(create_app(api_settings, start_worker=False)) as c:
        yield c


@pytest.fixture
def fake_apis(http, old_footage):
    http.route("generativelanguage", gemini_handler(CLAIM))
    http.route("factchecktools", {})
    install_youtube(http, [yt_item("OLD123", "Plane crash caught on camera", "2015-03-02")],
                    {"OLD123": old_footage[0]})
    http.route("vision.googleapis", {"responses": []})
    return http


@pytest.fixture
def old_footage():
    return [scene(10), scene(11)]


@pytest.fixture
def reel(tmp_path, old_footage):
    return make_video(tmp_path / "reel.mp4", [reel_frame(f, "BREAKING Hyderabad") for f in old_footage])


def upload(client, path, name="reel.mp4", **form):
    with open(path, "rb") as f:
        return client.post("/api/analyze", files={"file": (name, f, "video/mp4")}, data=form)


def work(settings, http) -> bool:
    return Worker(settings, http).run_once()


def test_upload_analyse_report_share(client, api_settings, fake_apis, reel):
    r = upload(client, reel, posted_date="2026-10-25")
    assert r.status_code == 202, r.text
    job = r.json()
    assert job["status"] == "queued" and job["queue_position"] == 1 and job["cached"] is False
    assert list(api_settings.uploads_dir.iterdir())  # stored until the worker runs

    assert work(api_settings, fake_apis)
    assert not work(api_settings, fake_apis)  # queue now empty

    status = client.get(f"/api/jobs/{job['job_id']}").json()
    assert status["status"] == "done" and status["step"] == "done"
    assert status["report_id"] == job["job_id"]
    assert status["share_url"] == f"https://reelcheck.example/r/{job['job_id']}"
    # Privacy: the upload is gone, only the report is kept.
    assert not list(api_settings.uploads_dir.iterdir())

    rep = client.get(status["report_url"]).json()
    assert rep["verdict"] == "LIKELY_OLD_FOOTAGE" and rep["report_id"] == job["job_id"]
    assert "output_dir" not in rep
    img = client.get(rep["comparisons"][0]["image_url"])
    assert img.status_code == 200 and img.headers["content-type"] == "image/jpeg"
    assert client.get(rep["keyframes"][0]).status_code == 200

    page = client.get(f"/r/{job['job_id']}")
    assert page.status_code == 200
    assert 'og:title" content="Reel check: Likely old footage"' in page.text
    assert "https://reelcheck.example/api/reports/" in page.text  # absolute og:image
    assert "wa.me" in page.text

    fb = client.post(f"/api/reports/{job['job_id']}/feedback", json={"correct": False, "note": "It is new"})
    assert fb.status_code == 201
    store = Store(api_settings.db_path)
    row = store.db.execute("select * from feedback").fetchone()
    assert row["report_id"] == job["job_id"] and row["correct"] == 0 and row["note"] == "It is new"
    store.close()


def test_progress_steps_are_recorded(client, api_settings, fake_apis, reel):
    job_id = upload(client, reel).json()["job_id"]
    seen = []
    store = Store(api_settings.db_path)
    original = store.job_update

    def spy(jid, **fields):
        if "step" in fields:
            seen.append(fields["step"])
        original(jid, **fields)
    claimed = store.job_claim()
    assert claimed["id"] == job_id
    store.job_update = spy
    Worker(api_settings, fake_apis)._process(store, claimed)
    store.close()
    assert seen[:6] == ["extracting", "transcribing", "understanding", "searching", "comparing", "done"]


def test_same_file_is_answered_from_cache_without_queueing(client, api_settings, fake_apis, reel):
    first = upload(client, reel).json()
    work(api_settings, fake_apis)
    again = upload(client, reel)
    assert again.status_code == 200
    body = again.json()
    assert body["cached"] and body["status"] == "done" and body["report_id"] == first["job_id"]
    assert body["job_id"] != first["job_id"]
    assert not work(api_settings, fake_apis)
    assert not list(api_settings.uploads_dir.iterdir())
    # A cached answer does not use up the daily allowance.
    store = Store(api_settings.db_path)
    assert store.db.execute("select sum(used) as n from rate_limit").fetchone()["n"] == 1
    store.close()


def test_rejects_bad_uploads(client, api_settings, tmp_path, reel):
    txt = tmp_path / "notes.txt"
    txt.write_text("hello")
    assert upload(client, txt, name="notes.txt").status_code == 415

    bad = tmp_path / "bad.mp4"
    bad.write_bytes(b"\x00" * 4000)
    r = upload(client, bad)
    assert r.status_code == 400 and r.json()["detail"]["code"] == "bad_video"

    empty = tmp_path / "empty.mp4"
    empty.write_bytes(b"")
    assert upload(client, empty).status_code == 400

    assert upload(client, reel, posted_date="2999-01-01").status_code == 422
    assert upload(client, reel, posted_date="yesterday").status_code == 422
    assert upload(client, reel, caption="x" * 2300).status_code == 422
    assert not list(api_settings.uploads_dir.iterdir())


def test_size_and_duration_limits(api_settings, reel, tmp_path):
    small = replace(api_settings, max_upload_mb=0.01)
    with TestClient(create_app(small, start_worker=False)) as c:
        assert upload(c, reel).status_code == 413
    short = replace(api_settings, max_video_seconds=1)
    with TestClient(create_app(short, start_worker=False)) as c:
        r = upload(c, reel)
        assert r.status_code == 400 and "limit" in r.json()["detail"]["message"]
    assert not list(api_settings.uploads_dir.iterdir())


def test_daily_rate_limit_per_client(api_settings, tmp_path):
    one = replace(api_settings, rate_limit_per_day=1)
    a = make_video(tmp_path / "a.mp4", [reel_frame(scene(1))], audio=False)
    b = make_video(tmp_path / "b.mp4", [reel_frame(scene(2))], audio=False)
    with TestClient(create_app(one, start_worker=False)) as c:
        assert upload(c, a).status_code == 202
        r = upload(c, b)
        assert r.status_code == 429 and r.json()["detail"]["code"] == "rate_limited"
    store = Store(api_settings.db_path)
    clients = [row["client"] for row in store.db.execute("select client from rate_limit")]
    store.close()
    assert clients and all("127.0.0.1" not in c and "testclient" not in c for c in clients)


def test_missing_upload_fails_the_job_cleanly(client, api_settings, fake_apis, reel):
    job_id = upload(client, reel).json()["job_id"]
    for f in api_settings.uploads_dir.iterdir():
        f.unlink()
    work(api_settings, fake_apis)
    status = client.get(f"/api/jobs/{job_id}").json()
    assert status["status"] == "failed" and "upload it again" in status["error"]


def test_crashed_pipeline_reports_generic_error(client, api_settings, fake_apis, reel, monkeypatch):
    import app.worker as worker_mod

    def boom(*a, **k):
        raise RuntimeError("secret internals")
    monkeypatch.setattr(worker_mod, "analyze", boom)
    job_id = upload(client, reel).json()["job_id"]
    work(api_settings, fake_apis)
    status = client.get(f"/api/jobs/{job_id}").json()
    assert status["status"] == "failed" and "secret" not in status["error"]
    assert not list(api_settings.uploads_dir.iterdir())


def test_stale_running_jobs_are_requeued_then_failed(api_settings):
    store = Store(api_settings.db_path)
    store.job_create("aaaaaaaaaaaa", video_hash="h", upload_path=None)
    store.job_claim()
    store.db.execute("update jobs set started_at = '2000-01-01T00:00:00+00:00'")
    store.db.commit()
    assert store.job_recover_stale(600, max_attempts=2) == ["aaaaaaaaaaaa"]
    assert store.job_get("aaaaaaaaaaaa")["status"] == "queued"
    store.job_claim()
    store.db.execute("update jobs set started_at = '2000-01-01T00:00:00+00:00'")
    store.db.commit()
    store.job_recover_stale(600, max_attempts=2)
    assert store.job_get("aaaaaaaaaaaa")["status"] == "failed"
    store.close()


def test_claim_is_fifo_and_exclusive(api_settings):
    a, b = Store(api_settings.db_path), Store(api_settings.db_path)
    for i in range(3):
        a.job_create(f"{i:012x}", video_hash="h", upload_path=None)
    got = [a.job_claim()["id"], b.job_claim()["id"], a.job_claim()["id"]]
    assert got == ["000000000000", "000000000001", "000000000002"]
    assert b.job_claim() is None
    a.close()
    b.close()


def test_unknown_ids_and_path_traversal(client):
    assert client.get("/api/jobs/doesnotexist").status_code == 404
    assert client.get("/api/reports/0123456789ab").status_code == 404
    assert client.get("/r/0123456789ab").status_code == 404
    assert client.get("/api/reports/0123456789ab/files/../../.env").status_code == 404
    assert client.get("/api/reports/0123456789ab/files/report.json").status_code == 404
    assert client.post("/api/reports/0123456789ab/feedback", json={"correct": True}).status_code == 404


def test_health_reports_key_presence_not_values(client):
    body = client.get("/api/health").json()
    assert body["ok"] and body["keys"] == {"gemini": True, "factcheck": True, "youtube": True, "vision": True}
    assert "test-google" not in str(body) and "test-gemini" not in str(body)


def test_upload_page(client):
    page = client.get("/")
    assert page.status_code == 200 and "/api/analyze" in page.text and 'type="file"' in page.text


def test_v0_reports_table_is_migrated(tmp_path):
    import sqlite3
    db = tmp_path / "old.sqlite"
    con = sqlite3.connect(db)
    con.execute("create table reports (video_hash text primary key, job_id text not null, verdict text,"
                " report text not null, created_at text not null)")
    con.execute("insert into reports values ('h1', 'abcabcabcabc', 'UNVERIFIED', '{\"job_id\": \"abcabcabcabc\"}',"
                " '2026-10-01')")
    con.commit()
    con.close()
    store = Store(db)
    assert store.report_by_id("abcabcabcabc") == {"job_id": "abcabcabcabc"}
    assert store.report_get("h1")["job_id"] == "abcabcabcabc"
    store.report_put("h1", {"job_id": "defdefdefdef"})
    assert store.report_by_id("abcabcabcabc")  # old share link survives a re-run
    assert store.report_get("h1")["job_id"] == "defdefdefdef"
    store.close()


def test_share_page_does_not_present_non_matches_as_partial_matches(client, api_settings, http, reel):
    http.route("generativelanguage", gemini_handler(CLAIM))
    http.route("factchecktools", {})
    install_youtube(http, [yt_item("OTHER1", "Airport tour", "2019-01-01")], {"OTHER1": scene(99)})
    http.route("vision.googleapis", {"responses": []})
    job_id = upload(client, reel).json()["job_id"]
    work(api_settings, http)
    page = client.get(f"/r/{job_id}").text
    assert "frames do not match" in page and "% frame match" not in page
