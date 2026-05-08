"""FastAPI application entry — autoclip HTTP server.

Lifecycle:
- Startup: ensure_data_dir() + init_db() + mount engine/session_factory on app.state
- Shutdown: dispose engine

Endpoints:
- GET  /health                      — liveness probe
- POST /api/jobs                    — create job + dispatch pipeline
- GET  /api/jobs                    — list jobs
- GET  /api/jobs/{id}               — get state.json detail
- POST /api/jobs/{id}/cancel        — request cancellation

Run:
    poetry run uvicorn autoclip.main:app --host 0.0.0.0 --port 8000 --reload
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI

from . import __version__
from .api import jobs_router
from .config import get_settings
from .db import create_app_engine, init_db, make_session_factory
from .web.routes import router as web_router

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """App lifespan — wire DB engine + session factory to app.state."""
    settings = get_settings()
    settings.ensure_data_dir()

    db_path = settings.data_dir / "autoclip.db"
    engine = create_app_engine(db_path)
    init_db(engine)
    session_factory = make_session_factory(engine)

    app.state.engine = engine
    app.state.session_factory = session_factory
    app.state.settings = settings

    logger.info(
        "AutoClip %s started — data_dir=%s db=%s",
        __version__, settings.data_dir, db_path,
    )

    # M3.8: start cron cleanup background task
    async def _cron_task() -> None:
        while True:
            await asyncio.sleep(3600)  # run hourly
            try:
                from .compliance.cleanup import cron_cleanup_temp
                deleted = cron_cleanup_temp(settings.data_dir)
                if deleted:
                    logger.info("Cron cleanup: deleted %d expired output zips", deleted)
            except Exception as cron_err:
                logger.warning("Cron cleanup error: %s", cron_err)

    cron_task = asyncio.create_task(_cron_task())
    logger.info("Cron cleanup task started")

    try:
        yield
    finally:
        cron_task.cancel()
        engine.dispose()
        logger.info("AutoClip stopped — engine disposed")


def create_app() -> FastAPI:
    """Application factory (testable: each test gets a fresh app)."""
    app = FastAPI(
        title="AutoClip",
        version=__version__,
        description="AI-powered automatic video clip & narration generator",
        lifespan=lifespan,
    )

    @app.get("/health", tags=["meta"])
    def health() -> dict[str, Any]:
        """Liveness probe — returns ok + version for uptime monitors."""
        return {"status": "ok", "version": __version__}

    app.include_router(jobs_router, prefix="/api")
    app.include_router(web_router)
    return app


# Module-level app for `uvicorn autoclip.main:app`
app = create_app()
