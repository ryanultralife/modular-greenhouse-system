"""FastAPI application: the single-source backend + served admin UI.

Run it with:
    uvicorn api.app:app --reload
Then open http://127.0.0.1:8000/
"""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from .auth import require_owner, require_staff
from .db import init_db
from .routers import (
    auth,
    catalog,
    help as help_router,
    integrations,
    inventory,
    orders,
    presets,
    production,
    public,
    quotes,
    setup,
    shipping,
    users,
    webhooks,
    work,
)

UI_DIR = Path(__file__).resolve().parents[1] / "ui"

DEFAULT_CORS = "https://www.modulargreenhouses.com,https://modulargreenhouses.com"


def _resolve_ui_base() -> Path:
    """Find the ui/ directory across the locations it can land in (local vs.
    the Vercel lambda, where cwd / file layout differ)."""
    here = Path(__file__).resolve().parents[1]
    candidates = [here, here.parent, Path.cwd(), Path("/var/task")]
    for base in candidates:
        if (base / "ui" / "public").is_dir():
            return base / "ui"
    return here / "ui"


UI_BASE = _resolve_ui_base()


def create_app(db_url: str | None = None) -> FastAPI:
    app = FastAPI(
        title="Modular Greenhouse System",
        version="0.2.0",
        description="Configurator, quoting, orders, production, and integrations.",
    )
    # If the DB can't be initialised (e.g. DATABASE_URL unset on Vercel), don't
    # crash the whole function — load anyway so /health and the UI work, and
    # return a clear 503 for API calls instead of an opaque 500.
    db_error: Exception | None = None
    try:
        init_db(db_url)
    except Exception as exc:  # noqa: BLE001
        db_error = exc

    origins = [o.strip() for o in os.environ.get("MGS_CORS_ORIGINS", DEFAULT_CORS).split(",") if o.strip()]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def _db_guard(request, call_next):
        if db_error is not None and request.url.path.startswith("/api"):
            return JSONResponse(
                status_code=503,
                content={"detail": f"Backend database is not configured: {db_error}"},
            )
        return await call_next(request)

    # Open routers: login, the public website flow, and signed webhooks.
    app.include_router(auth.router, prefix="/api")
    app.include_router(public.router, prefix="/api")
    app.include_router(webhooks.router, prefix="/api")

    # Owner-only routers: financials, pricing, secrets, staff management.
    for r in (quotes, orders, catalog, integrations, presets, setup, users):
        app.include_router(r.router, prefix="/api", dependencies=[Depends(require_owner)])

    # Staff + owner routers: the operational work board and the lists behind it.
    for r in (work, inventory, production, shipping, help_router):
        app.include_router(r.router, prefix="/api", dependencies=[Depends(require_staff)])

    @app.get("/health")
    def health():
        info = {
            "status": "ok",
            "db": "error" if db_error is not None else "ok",
            "ui_base": str(UI_BASE),
            "has_public": (UI_BASE / "public" / "index.html").is_file(),
            "has_admin": (UI_BASE / "admin" / "index.html").is_file(),
        }
        try:
            info["root_listing"] = sorted(p.name for p in Path(__file__).resolve().parents[1].iterdir())
        except OSError as exc:
            info["root_listing_error"] = str(exc)
        return info

    # Admin SPA at /admin; customer-facing site at / (mounted last as catch-all).
    admin_dir = UI_BASE / "admin"
    public_dir = UI_BASE / "public"
    if admin_dir.is_dir():
        app.mount("/admin", StaticFiles(directory=str(admin_dir), html=True), name="admin")
    if public_dir.is_dir():
        app.mount("/", StaticFiles(directory=str(public_dir), html=True), name="public")

    return app


app = create_app()
