"""End-to-end runs on synthetic reels with every external API faked."""
import json
from datetime import date

import pytest

from app.core.http import HttpError
from app.pipeline import extract
from app.pipeline.models import DEBUNKED, LIKELY_OLD_FOOTAGE, NO_CONTRADICTION_FOUND, UNVERIFIED
from app.pipeline.runner import analyze

from .conftest import gemini_handler, gemini_reply, jpeg, make_video, reel_frame, scene, yt_thumb

TODAY = date(2026, 10, 25)
CLAIM = {
    "claim_text": "A plane crashed at Hyderabad airport today.",
    "event": "plane crash", "location": "Hyderabad airport", "claimed_date": "2026-10-25",
    "recency": "current", "keywords": ["plane crash", "Hyderabad", "airport", "fire"],
    "search_queries": ["plane crash runway fire", "aircraft crash landing fire"],
    "factcheck_queries": ["plane crash Hyderabad airport"], "language": "te",
    "visual_description": "A burning aircraft on a runway.",
    "transcript": "ఈరోజు హైదరాబాద్ ఎయిర్‌పోర్ట్‌లో విమాన ప్రమాదం", "onscreen_text": "BREAKING\nHyderabad",
}


def yt_item(vid, title, published):
    return {"id": {"videoId": vid}, "snippet": {"title": title, "channelTitle": "Some channel",
                                                "publishedAt": f"{published}T10:00:00Z"}}


def install_youtube(http, items, frames_by_id):
    http.route("youtube/v3/search", {"items": items})
    for vid, img in frames_by_id.items():
        http.bytes_routes[f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg"] = yt_thumb(img)
        for n in (1, 2, 3):
            http.bytes_routes[f"https://i.ytimg.com/vi/{vid}/{n}.jpg"] = jpeg(img.resize((120, 90)))


@pytest.fixture
def old_footage():
    return [scene(10), scene(11)]


@pytest.fixture
def reel(tmp_path, old_footage):
    return make_video(tmp_path / "reel.mp4", [reel_frame(f, "BREAKING Hyderabad") for f in old_footage])


def test_recycled_footage_is_flagged(settings, store, http, reel, old_footage):
    http.route("generativelanguage", gemini_handler(CLAIM))
    http.route("factchecktools", {})
    install_youtube(http, [yt_item("OLD123", "Plane crash caught on camera", "2015-03-02"),
                           yt_item("OTHER1", "Airport tour", "2019-01-01")],
                    {"OLD123": old_footage[0], "OTHER1": scene(99)})

    r = analyze(reel, settings, http=http, store=store, posted_date=TODAY)

    assert r["verdict"] == LIKELY_OLD_FOOTAGE
    assert r["confidence"] >= 0.7
    top = r["evidence"][0]
    assert top["source"] == "youtube" and top["url"].endswith("OLD123") and top["similarity"] >= 0.9
    assert top["date"] == "2015-03-02" and top["supports"] == "earlier_footage"
    unrelated = next(e for e in r["evidence"] if e["url"].endswith("OTHER1"))
    assert unrelated["similarity"] < 0.8 and unrelated["supports"] == "lead"
    # Vision is the last resort and must not be spent when YouTube already answered.
    assert next(c for c in r["checks"] if c["name"] == "vision_web")["status"] == "not_needed"
    assert http.count("vision.googleapis") == 0
    # YouTube was asked only for videos published before the claim.
    yt = next(c for c in http.calls if "youtube/v3/search" in c[1])
    assert yt[2]["publishedBefore"] == "2026-10-23T00:00:00Z"
    # Gemini gave us the Telugu transcript and on-screen text.
    assert r["transcript"]["engine"] == "gemini" and "హైదరాబాద్" in r["transcript"]["text"]
    assert r["onscreen_text"] == ["BREAKING", "Hyderabad"]
    # Report files, comparison image, saved keyframes.
    out = settings.output_dir / r["job_id"]
    assert (out / "report.json").is_file() and (out / "report.md").is_file()
    assert r["comparisons"] and (out / r["comparisons"][0]["image"]).is_file()
    assert r["keyframes"] and all((out / k).is_file() for k in r["keyframes"])
    assert r["summary"] == "Summary from evidence." and not r["partial"]


def test_claim_call_sends_frames_and_audio(settings, store, http, reel):
    http.route("generativelanguage", gemini_handler(CLAIM))
    http.route("factchecktools", {})
    http.route("youtube/v3/search", {"items": []})
    http.route("vision.googleapis", {"responses": []})
    analyze(reel, settings, http=http, store=store, posted_date=TODAY)
    claim_call = next(c for c in http.calls if "generativelanguage" in c[1]
                      and "claim_text" in c[3]["generationConfig"]["responseSchema"]["properties"])
    mimes = [p["inline_data"]["mime_type"] for p in claim_call[3]["contents"][0]["parts"] if "inline_data" in p]
    assert "audio/wav" in mimes  # Whisper is unavailable, so Gemini listens
    assert mimes.count("image/jpeg") >= 2
    assert "Reference date" in claim_call[3]["contents"][0]["parts"][0]["text"]


def test_existing_fact_check_debunks(settings, store, http, reel):
    http.route("generativelanguage", gemini_handler(CLAIM))
    http.route("factchecktools", {"claims": [{
        "text": "Video shows plane crash at Hyderabad airport",
        "claimDate": "2026-10-24T00:00:00Z",
        "claimReview": [{"publisher": {"name": "Factly"}, "url": "https://factly.in/old-crash",
                         "title": "Old plane crash video from Brazil shared as Hyderabad airport",
                         "reviewDate": "2026-10-24T08:00:00Z", "textualRating": "Misleading"}]}]})
    http.route("youtube/v3/search", {"items": []})
    r = analyze(reel, settings, http=http, store=store, posted_date=TODAY)
    assert r["verdict"] == DEBUNKED
    assert r["evidence"][0]["publisher"] == "Factly" and r["evidence"][0]["supports"] == "debunk"


def test_unrelated_fact_check_is_not_a_debunk(settings, store, http, reel):
    http.route("generativelanguage", gemini_handler(CLAIM))
    http.route("factchecktools", {"claims": [{
        "text": "Cricket star retires", "claimReview": [{
            "publisher": {"name": "X"}, "url": "https://x/1", "title": "Cricket star retirement rumour",
            "textualRating": "False"}]}]})
    http.route("youtube/v3/search", {"items": []})
    http.route("vision.googleapis", {"responses": []})
    r = analyze(reel, settings, http=http, store=store, posted_date=TODAY)
    assert r["verdict"] == NO_CONTRADICTION_FOUND


def test_genuine_reel_is_not_flagged(settings, store, http, tmp_path):
    reel = make_video(tmp_path / "new.mp4", [reel_frame(scene(50)), reel_frame(scene(51))])
    http.route("generativelanguage", gemini_handler(CLAIM))
    http.route("factchecktools", {})
    install_youtube(http, [yt_item(f"V{i}", "crash video", "2018-05-05") for i in range(5)],
                    {f"V{i}": scene(200 + i) for i in range(5)})
    http.route("vision.googleapis", {"responses": [{"webDetection": {"pagesWithMatchingImages": [
        {"url": "https://news.example/today", "pageTitle": "<b>Live</b> updates", "partialMatchingImages": [{}]}]}}]})
    r = analyze(reel, settings, http=http, store=store, posted_date=TODAY)
    assert r["verdict"] == NO_CONTRADICTION_FOUND
    assert all(e["supports"] == "lead" for e in r["evidence"])
    vision = [e for e in r["evidence"] if e["source"] == "vision_web"]
    assert vision and vision[0]["title"] == "Live updates"
    assert 0 < r["confidence"] <= 0.6


def test_no_keys_gives_unverified_with_manual_links(settings, store, http, reel):
    from dataclasses import replace
    bare = replace(settings, gemini_api_key="", google_api_key="")
    r = analyze(reel, bare, http=http, store=store, caption="Plane crash today at Hyderabad")
    assert r["verdict"] == UNVERIFIED and r["partial"]
    assert r["claim"]["engine"] == "heuristic" and r["claim"]["recency"] == "current"
    assert {m["name"] for m in r["manual_links"]} >= {"Google Lens", "Yandex Images"}
    assert not http.calls


def test_own_index_catches_known_footage_offline(settings, store, http, tmp_path, old_footage):
    from dataclasses import replace

    from PIL import ImageOps

    from app.pipeline import fingerprint as fp
    store.footage_add(kind="debunked", phashes=[fp.variants(f)[0] for f in old_footage],
                      source_url="https://youtube.com/watch?v=orig", first_seen="2016-07-01",
                      claim_note="2016 cargo plane crash, Brazil", fact_check_url="")
    mirrored = make_video(tmp_path / "copy.mp4", [reel_frame(ImageOps.mirror(f)) for f in old_footage], audio=False)
    bare = replace(settings, gemini_api_key="", google_api_key="")
    r = analyze(mirrored, bare, http=http, store=store, caption="Today: plane crash in Hyderabad", posted_date=TODAY)
    assert r["verdict"] == LIKELY_OLD_FOOTAGE
    assert r["evidence"][0]["source"] == "own_index" and r["evidence"][0]["date"] == "2016-07-01"


def test_dark_reel_is_unverified(settings, store, http, tmp_path):
    from PIL import Image
    dark = make_video(tmp_path / "dark.mp4", [Image.new("RGB", (360, 640), (3, 3, 3))] * 2, audio=False)
    from dataclasses import replace
    http.route("factchecktools", {})
    http.route("youtube/v3/search", {"items": []})
    r = analyze(dark, replace(settings, gemini_api_key=""), http=http, store=store, posted_date=TODAY)
    assert r["verdict"] == UNVERIFIED


def test_youtube_quota_exhausted_gives_partial_report(settings, store, http, reel):
    from dataclasses import replace
    tight = replace(settings, youtube_daily_units=50)
    http.route("generativelanguage", gemini_handler(CLAIM))
    http.route("factchecktools", {})
    http.route("vision.googleapis", {"responses": []})
    r = analyze(reel, tight, http=http, store=store, posted_date=TODAY)
    yt = next(c for c in r["checks"] if c["name"] == "youtube")
    assert yt["status"] == "quota" and r["partial"]
    assert http.count("youtube/v3") == 0


def test_same_file_is_served_from_cache(settings, store, http, reel):
    http.route("generativelanguage", gemini_handler(CLAIM))
    http.route("factchecktools", {})
    http.route("youtube/v3/search", {"items": []})
    http.route("vision.googleapis", {"responses": []})
    first = analyze(reel, settings, http=http, store=store, posted_date=TODAY)
    n = len(http.calls)
    second = analyze(reel, settings, http=http, store=store, posted_date=TODAY)
    assert second["cached"] and second["job_id"] == first["job_id"] and len(http.calls) == n
    third = analyze(reel, settings, http=http, store=store, posted_date=TODAY, fresh=True)
    assert third["job_id"] != first["job_id"]
    # External responses were cached, so the fresh run made no new API calls apart from Gemini.
    assert http.count("factchecktools") == 1 and http.count("youtube/v3") == 2
    # The reel's fingerprint went into the index once, and it never matches itself.
    assert len(store.footage_all()) == 1
    assert not [e for e in third["evidence"] if e["source"] == "own_index"]


def test_gemini_quota_falls_back_to_heuristic(settings, store, http, reel):
    http.route("generativelanguage", HttpError(429, "RESOURCE_EXHAUSTED"))
    http.route("factchecktools", {})
    http.route("youtube/v3/search", {"items": []})
    http.route("vision.googleapis", {"responses": []})
    r = analyze(reel, settings, http=http, store=store, caption="Plane crash Hyderabad today", posted_date=TODAY)
    assert r["claim"]["engine"] == "heuristic" and r["summary_engine"] == "template"
    assert "quota" in next(c for c in r["checks"] if c["name"] == "claim")["detail"]


def test_gemini_retired_model_uses_fallback(settings, store, http):
    from app.pipeline.llm import Gemini
    seen = []

    def handler(url, params, body):
        seen.append(url)
        if settings.gemini_model in url:
            return HttpError(404, "model not found")
        return gemini_reply({"ok": True})
    http.route("generativelanguage", handler)
    out = Gemini(settings, http, store).generate_json(["hi"], {"type": "OBJECT"})
    assert out == {"ok": True} and settings.gemini_fallback_model in seen[-1]


def test_api_key_never_in_error_text():
    err = HttpError(400, "bad request for https://x/y?key=SECRET123&q=1")
    assert "SECRET123" not in str(err)


def test_report_json_is_serialisable(settings, store, http, reel):
    http.route("generativelanguage", gemini_handler(CLAIM))
    http.route("factchecktools", {})
    http.route("youtube/v3/search", {"items": []})
    http.route("vision.googleapis", {"responses": []})
    r = analyze(reel, settings, http=http, store=store, posted_date=TODAY)
    saved = json.loads((settings.output_dir / r["job_id"] / "report.json").read_text())
    assert saved["verdict"] == r["verdict"] and saved["evidence"] == r["evidence"]


def test_corrupt_upload_raises(settings, store, http, tmp_path):
    bad = tmp_path / "bad.mp4"
    bad.write_bytes(b"\x00" * 5000)
    with pytest.raises(extract.InputError):
        analyze(bad, settings, http=http, store=store)


def test_partly_related_fact_check_is_only_a_lead(settings, store, http):
    """Same city, different event: a 'False' rating on it must not debunk this reel."""
    from app.pipeline.context import Context
    from app.pipeline.evidence import factcheck_api
    from app.pipeline.llm import Gemini
    from app.pipeline.models import Claim
    http.route("factchecktools", {"claims": [{
        "text": "Video of Hyderabad flood", "claimReview": [{
            "publisher": {"name": "Y"}, "url": "https://y/1", "title": "Old flood video shared as Hyderabad",
            "textualRating": "False"}]}]})
    ctx = Context(settings, http, store, Gemini(settings, http, store), TODAY)
    claim = Claim(claim_text="Plane crash at Hyderabad airport", factcheck_queries=["plane crash Hyderabad"],
                  keywords=["plane crash", "Hyderabad", "airport", "fire"])
    found = factcheck_api.search(ctx, claim)
    assert len(found) == 1 and 0 < found[0].relevance < settings.factcheck_min_relevance
    assert found[0].supports == "lead"
