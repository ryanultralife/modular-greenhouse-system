"""Admin inventory management + weekly material-needs planning."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from production import compute_material_needs

from .. import catalog_store, inventory_store
from ..db import session_dependency
from ..models_db import InventoryItem, Order

router = APIRouter(tags=["inventory"])


class InventoryUpsert(BaseModel):
    kind: str  # finished_unit | material
    key: str
    name: str = ""
    on_hand: float | None = None
    unit: str = "each"
    reorder_point: float | None = None
    copacker: str | None = None


class AdjustRequest(BaseModel):
    delta: float


def _out(i: InventoryItem) -> dict:
    return {
        "id": i.id,
        "kind": i.kind,
        "key": i.key,
        "name": i.name,
        "on_hand": i.on_hand,
        "unit": i.unit,
        "reorder_point": i.reorder_point,
        "copacker": i.copacker,
        "low": i.on_hand <= i.reorder_point,
    }


@router.get("/inventory")
def list_inventory(kind: str | None = None, db: Session = Depends(session_dependency)):
    stmt = select(InventoryItem).order_by(InventoryItem.kind, InventoryItem.name)
    if kind:
        stmt = stmt.where(InventoryItem.kind == kind)
    return [_out(i) for i in db.scalars(stmt).all()]


@router.put("/inventory")
def upsert_inventory(req: InventoryUpsert, db: Session = Depends(session_dependency)):
    if req.kind not in ("finished_unit", "material"):
        raise HTTPException(status_code=400, detail="kind must be 'finished_unit' or 'material'.")
    item = inventory_store.upsert_item(
        db,
        kind=req.kind,
        key=req.key,
        name=req.name,
        on_hand=req.on_hand,
        unit=req.unit,
        reorder_point=req.reorder_point,
        copacker=req.copacker,
    )
    return _out(item)


@router.post("/inventory/{key}/adjust")
def adjust_inventory(key: str, req: AdjustRequest, db: Session = Depends(session_dependency)):
    item = inventory_store.adjust(db, key, req.delta)
    if item is None:
        raise HTTPException(status_code=404, detail="Inventory item not found.")
    return _out(item)


@router.get("/inventory/low-stock")
def low_stock(db: Session = Depends(session_dependency)):
    return [_out(i) for i in inventory_store.low_stock(db)]


@router.get("/production/material-needs")
def material_needs(status: str = "confirmed", db: Session = Depends(session_dependency)):
    """Materials required for all orders in a given status (e.g. next week's builds)."""
    orders = [
        {"id": o.id, "model_id": o.model_id, "bom": o.bom}
        for o in db.scalars(select(Order).where(Order.status == status)).all()
    ]
    plan = compute_material_needs(orders, catalog_store.load(db))
    return {
        "status": status,
        "order_count": len(plan.order_ids),
        "complete": plan.complete,
        "needs": [
            {"material_id": n.material_id, "name": n.name, "unit": n.unit, "quantity": n.quantity, "complete": n.complete}
            for n in plan.needs
        ],
    }
