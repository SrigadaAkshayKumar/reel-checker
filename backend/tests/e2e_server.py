"""Backend for the frontend's end-to-end tests: the real API, queue and worker,
with only the external services faked (same fakes as test_pipeline.py).

  python -m tests.e2e_server --port 8010 --data /tmp/e2e --frontend http://localhost:3010

Writes test reels to <data>/fixtures/: recycled.mp4 (old footage, found on
"YouTube" from 2015) and fresh.mp4 (nothing earlier exists).
"""
from __future__ import annotations

import argparse
import shutil
from pathlib import Path

import uvicorn

from app.core.config import Settings
from app.main import create_app
from app.pipeline import transcribe
from app.worker import start_background

from .conftest import FakeHttp, gemini_handler, make_video, reel_frame, scene
from .test_pipeline import CLAIM, install_youtube, yt_item

SUMMARY = ("This footage was on YouTube on 2 March 2015, years before the date the reel claims.\n"
           "The reel presents it as a plane crash at Hyderabad airport today.\n"
           "The frames match closely, so this is very likely old footage being reshared.")


def fake_services() -> FakeHttp:
    http = FakeHttp()
    http.route("generativelanguage", gemini_handler(CLAIM, SUMMARY))
    http.route("factchecktools", {})
    install_youtube(http, [yt_item("OLD123", "Cargo plane crash caught on camera", "2015-03-02"),
                           yt_item("OTHER1", "Airport tour", "2019-01-01")],
                    {"OLD123": scene(10), "OTHER1": scene(99)})
    http.route("vision.googleapis", {"responses": []})
    return http


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--port", type=int, default=8010)
    p.add_argument("--data", type=Path, required=True)
    p.add_argument("--frontend", default="http://localhost:3010")
    a = p.parse_args()

    shutil.rmtree(a.data, ignore_errors=True)
    fixtures = a.data / "fixtures"
    fixtures.mkdir(parents=True)
    make_video(fixtures / "recycled.mp4", [reel_frame(f, "BREAKING Hyderabad") for f in (scene(10), scene(11))])
    make_video(fixtures / "fresh.mp4", [reel_frame(scene(50)), reel_frame(scene(51))])

    transcribe.transcribe = lambda audio, settings: (None, "disabled in e2e")
    settings = Settings(
        gemini_api_key="e2e", google_api_key="e2e", data_dir=a.data, db_path=a.data / "e2e.sqlite",
        uploads_dir=a.data / "uploads", output_dir=a.data / "out", ocr_engine="gemini",
        cors_origins=a.frontend, public_base_url=a.frontend, ip_hash_salt="e2e", rate_limit_per_day=1000,
        worker_poll_seconds=0.2,
    )
    app = create_app(settings, start_worker=False)
    start_background(settings, http=fake_services())
    uvicorn.run(app, host="127.0.0.1", port=a.port, log_level="warning")


if __name__ == "__main__":
    main()
