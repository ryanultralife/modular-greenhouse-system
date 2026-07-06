"""Persistence layer.

Uses Postgres (Supabase) when DATABASE_URL is set, else a local SQLite file
for development and tests. On Postgres we use NullPool because serverless
invocations must not hold connections across requests.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.pool import NullPool

DATA_DIR = Path(__file__).resolve().parents[1] / "data"
DB_PATH = DATA_DIR / "app.db"


class Base(DeclarativeBase):
    pass


_engine = None
_SessionLocal: sessionmaker[Session] | None = None


def _normalize_url(url: str) -> str:
    # Supabase/Heroku hand out postgres:// URLs; SQLAlchemy 2 + psycopg3 wants
    # the explicit postgresql+psycopg:// driver prefix.
    if url.startswith("postgres://"):
        return "postgresql+psycopg://" + url[len("postgres://"):]
    if url.startswith("postgresql://"):
        return "postgresql+psycopg://" + url[len("postgresql://"):]
    return url


def resolve_url(db_url: str | None = None) -> str:
    return _normalize_url(db_url or os.environ.get("DATABASE_URL") or f"sqlite:///{DB_PATH}")


def init_db(db_url: str | None = None):
    """Create the engine and tables. Safe to call repeatedly."""
    global _engine, _SessionLocal
    url = resolve_url(db_url)
    is_sqlite = url.startswith("sqlite")

    if is_sqlite and os.environ.get("VERCEL"):
        # SQLite can't be written on Vercel's read-only filesystem.
        raise RuntimeError(
            "DATABASE_URL is not set. On Vercel you must set DATABASE_URL to your "
            "Supabase Postgres connection string (use the pooler URL)."
        )

    kwargs: dict = {"future": True}
    if is_sqlite:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        kwargs["connect_args"] = {"check_same_thread": False}
    else:
        kwargs["poolclass"] = NullPool  # serverless: one connection per request
        # Supabase pooler (pgbouncer transaction mode) is incompatible with
        # client-side prepared statements, so disable them.
        kwargs["connect_args"] = {"prepare_threshold": None}

    _engine = create_engine(url, **kwargs)
    _SessionLocal = sessionmaker(bind=_engine, autoflush=False, expire_on_commit=False)
    from . import models_db  # noqa: F401  (register models before create_all)

    Base.metadata.create_all(_engine)  # checkfirst=True; complements Supabase migrations
    return _engine


def dispose_engine():
    """Release pooled connections. Needed on Windows, where an open pooled
    connection locks the SQLite file and blocks deletion (tests do this)."""
    if _engine is not None:
        _engine.dispose()


def get_session() -> Session:
    if _SessionLocal is None:
        init_db()
    assert _SessionLocal is not None
    return _SessionLocal()


def session_dependency() -> Iterator[Session]:
    """FastAPI dependency that yields a session and always closes it."""
    db = get_session()
    try:
        yield db
    finally:
        db.close()
