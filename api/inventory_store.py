"""Inventory helpers: finished units (ready-to-ship) and materials."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models_db import InventoryItem


def get_item(db: Session, key: str) -> InventoryItem | None:
    return db.scalar(select(InventoryItem).where(InventoryItem.key == key))


def upsert_item(
    db: Session,
    *,
    kind: str,
    key: str,
    name: str = "",
    on_hand: float | None = None,
    unit: str = "each",
    reorder_point: float | None = None,
    copacker: str | None = None,
) -> InventoryItem:
    item = get_item(db, key)
    if item is None:
        item = InventoryItem(kind=kind, key=key, name=name or key, unit=unit)
        db.add(item)
    if name:
        item.name = name
    if on_hand is not None:
        item.on_hand = on_hand
    if unit:
        item.unit = unit
    if reorder_point is not None:
        item.reorder_point = reorder_point
    if copacker is not None:
        item.copacker = copacker
    db.commit()
    return item


def adjust(db: Session, key: str, delta: float, floor: float | None = None) -> InventoryItem | None:
    """Change on_hand by delta (negative to consume). No-op if the item is absent.

    If ``floor`` is given, on_hand is clamped to it (use floor=0 to prevent
    negative physical stock on an oversell)."""
    item = get_item(db, key)
    if item is None:
        return None
    new_value = item.on_hand + delta
    if floor is not None and new_value < floor:
        new_value = floor
    item.on_hand = new_value
    db.commit()
    return item


def low_stock(db: Session) -> list[InventoryItem]:
    items = db.scalars(select(InventoryItem)).all()
    return [i for i in items if i.on_hand <= i.reorder_point]
