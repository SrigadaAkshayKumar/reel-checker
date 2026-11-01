"""Android app API: anonymous accounts, daily free check, rewarded-ad credits (AdMob SSV),
reel links fetched by the worker, refunds. Every external service is faked."""
import base64
import shutil
from dataclasses import replace

import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi.testclient import TestClient

from app.api.mobile import app_day
from app.db.store import Store
from app.main import create_app
from app.pipeline import fetch
from app.worker import Worker

from . import test_api

# Shared fixtures: faked Gemini / Fact Check / YouTube / Vision, and a reel of old footage.
fake_apis, old_footage, reel = test_api.fake_apis, test_api.old_footage, test_api.reel

AD_UNIT = "ca-app-pub-1111111111111111/2222222222"
LINK = "https://www.instagram.com/reel/C0deAbc123/?igsh=MWQ1ZGUxMzBkMA=="


@pytest.fixture
def app_settings(settings):
    return replace(settings, ip_hash_salt="test-salt", public_base_url="https://reelcheck.example",
                   admob_ad_unit_ids=AD_UNIT)


@pytest.fixture
def signing_key(http):
    key = ec.generate_private_key(ec.SECP256R1())
    pem = key.public_key().public_bytes(serialization.Encoding.PEM,
                                        serialization.PublicFormat.SubjectPublicKeyInfo).decode()
    http.route("verifier-keys", {"keys": [{"keyId": 3335741209, "pem": pem, "base64": "unused"}]})
    return key


@pytest.fixture
def client(app_settings, http):
    with TestClient(create_app(app_settings, start_worker=False, http=http)) as c:
        yield c


def signed_callback(key, user_id, transaction="tx-1", ad_unit="2222222222", key_id="3335741209"):
    message = (f"ad_network=5450213213286189855&ad_unit={ad_unit}&reward_amount=1&reward_item=check"
               f"&timestamp=1730000000000&transaction_id={transaction}&user_id={user_id}")
    sig = base64.urlsafe_b64encode(key.sign(message.encode(), ec.ECDSA(hashes.SHA256()))).decode().rstrip("=")
    return f"/api/admob/ssv?{message}&signature={sig}&key_id={key_id}"


def session(client):
    r = client.post("/api/app/session")
    assert r.status_code == 201, r.text
    body = r.json()
    return body["user_id"], {"Authorization": f"Bearer {body['token']}"}


def send_file(client, headers, path, **form):
    with open(path, "rb") as f:
        return client.post("/api/app/check", headers=headers, files={"file": ("reel.mp4", f, "video/mp4")}, data=form)


def copy_downloader(source):
    def download(url, dest_dir, settings):
        assert url == "https://www.instagram.com/reel/C0deAbc123/"  # only the canonical link reaches yt-dlp
        dest_dir.mkdir(parents=True, exist_ok=True)
        return shutil.copy(source, dest_dir / "reel.mp4") and dest_dir / "reel.mp4"
    return download


def failing_downloader(url, dest_dir, settings):
    raise fetch.FetchError("Instagram did not let us fetch this reel.")


def test_free_check_then_ad_credit_then_watch_ad(client, app_settings, fake_apis, signing_key, reel, tmp_path):
    user_id, auth = session(client)
    me = client.get("/api/app/me", headers=auth).json()
    assert (me["free_left"], me["ad_credits"], me["can_check"], me["ads_enabled"]) == (1, 0, True, True)

    first = send_file(client, auth, reel)
    assert first.status_code == 202 and first.json()["charged"] == "free" and first.json()["free_left"] == 0
    second = send_file(client, auth, reel, caption="another question")  # a caption skips the cache
    assert second.status_code == 402
    assert second.json()["detail"]["code"] == "watch_ad" and second.json()["detail"]["ads_enabled"] is True
    assert not list(app_settings.uploads_dir.iterdir())[1:]  # the refused upload was not kept

    assert client.get(signed_callback(signing_key, user_id)).status_code == 200
    assert client.get(signed_callback(signing_key, user_id)).status_code == 200  # AdMob retry: same transaction
    assert client.get("/api/app/me", headers=auth).json()["ad_credits"] == 1

    third = send_file(client, auth, reel, caption="another question")
    assert third.status_code == 202 and third.json()["charged"] == "ad" and third.json()["ad_credits"] == 0
    assert send_file(client, auth, reel, caption="once more").status_code == 402


def test_ad_callbacks_cannot_be_forged(client, app_settings, http, signing_key):
    user_id, auth = session(client)
    good = signed_callback(signing_key, user_id, transaction="tx-9")
    assert client.get(good.replace("reward_amount=1", "reward_amount=9")).status_code == 403   # tampered
    assert client.get(good.split("&signature=")[0]).status_code == 400                       # unsigned
    other = ec.generate_private_key(ec.SECP256R1())
    assert client.get(signed_callback(other, user_id, transaction="tx-8")).status_code == 403  # someone else's key
    assert client.get(signed_callback(signing_key, user_id, transaction="tx-7", ad_unit="999")).status_code == 403
    before = http.count("verifier-keys")
    assert client.get(signed_callback(signing_key, user_id, key_id="42")).status_code == 403   # unknown key...
    assert http.count("verifier-keys") == before + 1                                           # ...refetched once
    assert client.get("/api/app/me", headers=auth).json()["ad_credits"] == 0


def test_ad_credits_are_capped_and_unknown_users_ignored(client, app_settings, signing_key):
    user_id, auth = session(client)
    for i in range(app_settings.app_max_ad_credits + 2):
        assert client.get(signed_callback(signing_key, user_id, transaction=f"t{i}")).status_code == 200
    me = client.get("/api/app/me", headers=auth).json()
    assert me["ad_credits"] == app_settings.app_max_ad_credits and me["can_watch_ad"] is False
    assert client.get(signed_callback(signing_key, "0000000000000000", transaction="x")).status_code == 200
    store = Store(app_settings.db_path)
    outcomes = [r["outcome"] for r in store.db.execute("select outcome from ssv_seen order by created_at")]
    assert outcomes.count("capped") == 2 and outcomes.count("unknown_user") == 1


def test_ads_refused_when_no_ad_unit_is_configured(app_settings, http, signing_key):
    with TestClient(create_app(replace(app_settings, admob_ad_unit_ids=""), start_worker=False, http=http)) as c:
        user_id, auth = session(c)
        assert c.get(signed_callback(signing_key, user_id)).status_code == 403
        assert c.get("/api/app/me", headers=auth).json()["ads_enabled"] is False


def test_auth_is_required_and_tokens_are_stored_hashed(client, app_settings):
    assert client.get("/api/app/me").status_code == 401
    assert client.get("/api/app/me", headers={"Authorization": "Bearer nope"}).json()["detail"]["code"] == "signed_out"
    r = client.post("/api/app/session").json()
    rows = Store(app_settings.db_path).db.execute("select * from app_users").fetchall()
    assert r["token"] not in str([tuple(row) for row in rows])


def test_link_is_fetched_by_the_worker_then_answered_from_cache(client, app_settings, fake_apis, reel):
    _, auth = session(client)
    r = client.post("/api/app/check", headers=auth, data={"url": LINK})
    assert r.status_code == 202, r.text
    job = r.json()
    assert job["charged"] == "free" and job["steps"][0] == "downloading"

    assert Worker(app_settings, fake_apis, downloader=copy_downloader(reel)).run_once()
    status = client.get(f"/api/jobs/{job['job_id']}").json()
    assert status["status"] == "done" and status["report_id"] == job["job_id"]
    store = Store(app_settings.db_path)
    row = store.job_get(job["job_id"])
    assert row["source_url"] is None and row["upload_path"] is None  # the link and the video are gone
    assert not list(app_settings.uploads_dir.iterdir())
    assert "C0deAbc123" not in str([tuple(x) for x in store.db.execute("select * from link_reports")])

    # Same reel, link copied differently, after the free check is used: answered from cache, free.
    again = client.post("/api/app/check", headers=auth, data={"url": "https://instagram.com/reels/C0deAbc123"})
    assert again.status_code == 200 and again.json()["cached"] is True
    assert again.json()["report_id"] == job["job_id"]


def test_failed_fetch_asks_for_the_file_and_refunds(client, app_settings, fake_apis):
    _, auth = session(client)
    job = client.post("/api/app/check", headers=auth, data={"url": LINK}).json()
    assert client.get("/api/app/me", headers=auth).json()["free_left"] == 0
    Worker(app_settings, fake_apis, downloader=failing_downloader).run_once()
    status = client.get(f"/api/jobs/{job['job_id']}").json()
    assert status["status"] == "failed" and status["error_code"] == "need_file"
    assert "share the file" in status["error"]
    assert client.get("/api/app/me", headers=auth).json()["free_left"] == 1  # refunded
    assert Store(app_settings.db_path).job_get(job["job_id"])["charge"] == "refunded:free"


def test_partial_report_refunds_the_ad_credit(app_settings, http, fake_apis, signing_key, reel):
    no_google = replace(app_settings, google_api_key="")  # Fact Check + YouTube can't run → partial report
    with TestClient(create_app(no_google, start_worker=False, http=http)) as c:
        user_id, auth = session(c)
        Store(no_google.db_path).app_spend(user_id, app_day(no_google)[0], 1)  # free check already used
        c.get(signed_callback(signing_key, user_id))
        job = send_file(c, auth, reel).json()
        assert job["charged"] == "ad"
        Worker(no_google, fake_apis).run_once()
        assert c.get(f"/api/jobs/{job['job_id']}").json()["status"] == "done"
        assert c.get("/api/app/me", headers=auth).json()["ad_credits"] == 1


def test_stale_job_that_finally_fails_is_refunded(client, app_settings):
    _, auth = session(client)
    job = client.post("/api/app/check", headers=auth, data={"url": LINK}).json()
    store = Store(app_settings.db_path)
    store.db.execute("update jobs set status = 'running', attempts = 9, started_at = '2020-01-01' where id = ?",
                     (job["job_id"],))
    store.db.commit()
    store.job_recover_stale(60, 2)
    assert store.job_get(job["job_id"])["charge"] == "refunded:free"
    assert store.charge_refund(job["job_id"]) is None  # never twice
    assert client.get("/api/app/me", headers=auth).json()["free_left"] == 1


@pytest.mark.parametrize("url", [
    "https://example.com/video.mp4", "http://169.254.169.254/latest/meta-data/", "file:///etc/passwd",
    "https://www.instagram.com/someuser/", "https://instagram.com.evil.example/reel/C0deAbc123/",
    "https://www.instagram.com/reel/C0deAbc123/@evil.example", "not a link"])
def test_only_instagram_reel_links_are_accepted(client, url):
    _, auth = session(client)
    r = client.post("/api/app/check", headers=auth, data={"url": url})
    assert r.status_code == 422 and r.json()["detail"]["code"] == "bad_link"
    assert client.get("/api/app/me", headers=auth).json()["free_left"] == 1  # nothing charged


def test_canonical_links():
    c = fetch.canonical
    assert c("https://www.instagram.com/reel/C0deAbc123/?igsh=abc") == "https://www.instagram.com/reel/C0deAbc123/"
    assert c("https://m.instagram.com/reels/C0deAbc123") == "https://www.instagram.com/reel/C0deAbc123/"
    assert c("https://www.instagram.com/some.user/reel/C0deAbc123/") == "https://www.instagram.com/reel/C0deAbc123/"
    assert c("https://instagram.com/p/C0deAbc123/") == "https://www.instagram.com/p/C0deAbc123/"
    with pytest.raises(fetch.FetchError):
        fetch.download("https://example.com/x", None, None)  # never handed to yt-dlp


def test_links_switched_off_ask_for_the_file(app_settings, http):
    with TestClient(create_app(replace(app_settings, link_fetch_enabled=False), start_worker=False, http=http)) as c:
        _, auth = session(c)
        r = c.post("/api/app/check", headers=auth, data={"url": LINK})
        assert r.status_code == 422 and r.json()["detail"]["code"] == "need_file"
        assert c.get("/api/app/me", headers=auth).json()["free_left"] == 1


def test_new_accounts_are_limited_per_network(app_settings, http):
    with TestClient(create_app(replace(app_settings, app_sessions_per_ip_day=2), start_worker=False, http=http)) as c:
        assert [c.post("/api/app/session").status_code for _ in range(3)] == [201, 201, 429]


def test_free_check_resets_at_india_midnight(app_settings):
    day, resets = app_day(app_settings)
    assert resets.endswith("18:30:00+00:00")  # 00:00 IST
    store = Store(app_settings.db_path)
    store.app_user_create("u1", "h1")
    assert store.app_spend("u1", "2026-10-31", 1) == "free"
    assert store.app_spend("u1", "2026-10-31", 1) is None
    assert store.app_spend("u1", "2026-11-01", 1) == "free"


def test_jobs_table_gains_app_columns(tmp_path):
    import sqlite3
    path = tmp_path / "old.sqlite"
    db = sqlite3.connect(path)
    db.execute("create table jobs (id text primary key, status text not null default 'queued', step text,"
               " video_hash text, upload_path text, caption text not null default '', posted_date text,"
               " error text, report_id text, attempts integer not null default 0, created_at text not null,"
               " started_at text, finished_at text)")
    db.execute("insert into jobs (id, created_at) values ('abc', '2026-01-01')")
    db.commit()
    db.close()
    store = Store(path)
    assert store.job_get("abc")["charge"] is None and "link_key" in store.job_get("abc")
