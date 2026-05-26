"""SQLite persistence layer (single source of truth)."""

from __future__ import annotations

from pathlib import Path
from typing import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

DATA_DIR = Path(__file__).resolve().parents[1] / "data"
DB_PATH = DATA_DIR / "app.db"


class Base(DeclarativeBase):
    pass


_engine = None
_SessionLocal: sessionmaker[Session] | None = None


def init_db(db_url: str | None = None):
    """Create the engine and tables. Safe to call repeatedly."""
    global _engine, _SessionLocal
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    url = db_url or f"sqlite:///{DB_PATH}"
    _engine = create_engine(url, connect_args={"check_same_thread": False}, future=True)
    _SessionLocal = sessionmaker(bind=_engine, autoflush=False, expire_on_commit=False)
    # Import models so they register on Base before create_all.
    from . import models_db  # noqa: F401

    Base.metadata.create_all(_engine)
    return _engine


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
