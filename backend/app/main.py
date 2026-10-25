"""FastAPI app.

  uvicorn app.main:app --host 0.0.0.0 --port 8000      (from backend/)

With EMBEDDED_WORKER=true (default) one worker thread runs inside the API
process; set it to false and run `python -m app.worker` separately to scale.
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api import pages, routes
from .core.config import Settings, load_settings
from .db.store import Store
from .pipeline.runner import VERSION


def create_app(settings: Settings | None = None, *, start_worker: bool | None = None) -> FastAPI:
    settings = settings or load_settings()
    run_worker = settings.embedded_worker if start_worker is None else start_worker

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        Store(settings.db_path).close()  # create / migrate the schema up front
        settings.uploads_dir.mkdir(parents=True, exist_ok=True)
        stop = None
        if run_worker:
            from .worker import start_background
            _, stop = start_background(settings)
        yield
        if stop:
            stop.set()

    app = FastAPI(title="Reel Fact-Checker", version=VERSION, lifespan=lifespan)
    app.state.settings = settings
    origins = [o.strip() for o in settings.cors_origins.split(",") if o.strip()]
    if origins:
        app.add_middleware(CORSMiddleware, allow_origins=origins, allow_methods=["GET", "POST"],
                           allow_headers=["Content-Type"])
    app.include_router(routes.router)
    app.include_router(pages.router)
    return app


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
app = create_app()
