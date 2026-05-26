"""ORM models."""

from __future__ import annotations

from datetime import date, datetime, timezone

from sqlalchemy import JSON, Boolean, Date, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base

# Order lifecycle.
ORDER_STATUSES = ("quote", "confirmed", "in_production", "shipped", "cancelled")
SESSION_STATUSES = ("planned", "locked", "done")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Order(Base):
    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    customer_name: Mapped[str] = mapped_column(String(200), default="")
    customer_email: Mapped[str] = mapped_column(String(200), default="")

    model_id: Mapped[str] = mapped_column(String(64))
    shape: Mapped[str] = mapped_column(String(16))
    runs: Mapped[list] = mapped_column(JSON)  # list[float]
    status: Mapped[str] = mapped_column(String(20), default="quote")

    # Snapshots taken at creation so history is stable if the catalog changes.
    bom: Mapped[list] = mapped_column(JSON, default=list)
    pricing: Mapped[dict] = mapped_column(JSON, default=dict)
    engineering: Mapped[dict] = mapped_column(JSON, default=dict)

    fab_session_id: Mapped[int | None] = mapped_column(
        ForeignKey("fab_sessions.id"), nullable=True
    )
    fab_session: Mapped["FabricationSession | None"] = relationship(back_populates="orders")


class FabricationSession(Base):
    __tablename__ = "fab_sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    week_of: Mapped[date] = mapped_column(Date)
    label: Mapped[str] = mapped_column(String(120), default="")
    status: Mapped[str] = mapped_column(String(20), default="planned")

    orders: Mapped[list[Order]] = relationship(back_populates="fab_session")


class Integration(Base):
    __tablename__ = "integrations"

    id: Mapped[int] = mapped_column(primary_key=True)
    provider: Mapped[str] = mapped_column(String(40))  # stripe | calendly | quickbooks | custom
    label: Mapped[str] = mapped_column(String(120), default="")
    secret_blob: Mapped[str] = mapped_column(Text)  # Fernet-encrypted JSON of credentials
    field_names: Mapped[list] = mapped_column(JSON, default=list)  # which fields are stored
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)
    last_test_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_test_ok: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    last_test_message: Mapped[str] = mapped_column(String(400), default="")
