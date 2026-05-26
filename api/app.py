"""FastAPI application: the single-source backend + served admin UI.

Run it with:
    uvicorn api.app:app --reload
Then open http://127.0.0.1:8000/
"""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from .db import init_db
from .routers import catalog, integrations, orders, production, public, quotes, shipping

UI_DIR = Path(__file__).resolve().parents[1] / "ui"

DEFAULT_CORS = "https://www.modulargreenhouses.com,https://modulargreenhouses.com"


def create_app(db_url: str | None = None) -> FastAPI:
    app = FastAPI(
        title="Modular Greenhouse System",
        version="0.2.0",
        description="Configurator, quoting, orders, production, and integrations.",
    )
    init_db(db_url)

    origins = [o.strip() for o in os.environ.get("MGS_CORS_ORIGINS", DEFAULT_CORS).split(",") if o.strip()]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
    )

    for r in (quotes, orders, catalog, production, integrations, public, shipping):
        app.include_router(r.router, prefix="/api")

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.get("/", include_in_schema=False)
    def root():
        return RedirectResponse(url="/ui/")

    if UI_DIR.exists():
        app.mount("/ui", StaticFiles(directory=str(UI_DIR), html=True), name="ui")

    return app


app = create_app()
