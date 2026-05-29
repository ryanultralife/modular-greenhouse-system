"""ORM models."""

from __future__ import annotations

from datetime import date, datetime, timezone

from sqlalchemy import JSON, Boolean, Date, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base

# Order lifecycle.
ORDER_STATUSES = (
    "quote",
    "pending_payment",
    "paid",
    "confirmed",
    "in_production",
    "shipped",
    "cancelled",
)
SESSION_STATUSES = ("planned", "locked", "done")
COPACKER_ORDER_STATUSES = ("draft", "sent", "received", "cancelled")


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
    quote_lines: Mapped[list] = mapped_column(JSON, default=list)
    pricing: Mapped[dict] = mapped_column(JSON, default=dict)
    engineering: Mapped[dict] = mapped_column(JSON, default=dict)

    source: Mapped[str] = mapped_column(String(20), default="admin")  # admin | website
    contact: Mapped[dict] = mapped_column(JSON, default=dict)
    external_refs: Mapped[dict] = mapped_column(JSON, default=dict)  # stripe/quickbooks/calendly ids
    shipping: Mapped[dict] = mapped_column(JSON, default=dict)  # carrier/tracking/ship_date

    preset_id: Mapped[int | None] = mapped_column(Integer, nullable=True)  # set for preset purchases
    payment_status: Mapped[str] = mapped_column(String(20), default="unpaid")  # unpaid | paid

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


class Setting(Base):
    """Key/value store. Used for catalog overrides (serverless can't write the
    catalog.json file), and available for other small admin settings."""

    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[dict] = mapped_column(JSON, default=dict)


# Roles. "owner" sees everything (incl. secrets/pricing); "staff" gets the
# operational work board + inventory/production/shipping, no financial data.
ROLES = ("owner", "staff")


class User(Base):
    """A staff login. The owner authenticates via MGS_ADMIN_PASSWORD (not stored
    here); these are the additional employee accounts the owner creates."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(80), unique=True)
    password_hash: Mapped[str] = mapped_column(String(200))
    role: Mapped[str] = mapped_column(String(20), default="staff")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class Preset(Base):
    """A ready-to-ship product a customer can buy and pay for directly."""

    __tablename__ = "presets"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(160))
    description: Mapped[str] = mapped_column(String(400), default="")
    model_id: Mapped[str] = mapped_column(String(64), default="")
    shape: Mapped[str] = mapped_column(String(16), default="straight")
    runs: Mapped[list] = mapped_column(JSON, default=list)
    price_usd: Mapped[float | None] = mapped_column(nullable=True)
    verified_price: Mapped[bool] = mapped_column(Boolean, default=False)
    ship_speed: Mapped[str] = mapped_column(String(16), default="next_day")  # same_day | next_day
    image_url: Mapped[str] = mapped_column(String(400), default="")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)

    @property
    def stock_key(self) -> str:
        return f"preset:{self.id}"


class InventoryItem(Base):
    """On-hand stock. kind='finished_unit' (ready-to-ship, often co-packer built)
    or kind='material' (components consumed by builds)."""

    __tablename__ = "inventory_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(20))  # finished_unit | material
    key: Mapped[str] = mapped_column(String(80), unique=True)  # e.g. preset:3 or material id
    name: Mapped[str] = mapped_column(String(160), default="")
    on_hand: Mapped[float] = mapped_column(default=0)
    unit: Mapped[str] = mapped_column(String(24), default="each")
    reorder_point: Mapped[float] = mapped_column(default=0)
    copacker: Mapped[str] = mapped_column(String(120), default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)


class CoPackerOrder(Base):
    """A build/replenishment order sent to a co-packer."""

    __tablename__ = "copacker_orders"

    id: Mapped[int] = mapped_column(primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    copacker: Mapped[str] = mapped_column(String(120), default="")
    items: Mapped[list] = mapped_column(JSON, default=list)  # [{key,name,quantity}]
    status: Mapped[str] = mapped_column(String(20), default="draft")
    trigger: Mapped[str] = mapped_column(String(40), default="manual")  # preset_sale | low_stock | fab_session | manual
    related_order_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    emailed: Mapped[bool] = mapped_column(Boolean, default=False)
    notes: Mapped[str] = mapped_column(String(400), default="")
