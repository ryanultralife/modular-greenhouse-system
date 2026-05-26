"""Shipping / same-day dispatch workflow.

  * shipment-plan: per-order package list + total weight, gated on every SKU
    having a known weight (``ready``).
  * ship: record carrier/tracking/ship-date and move the order to 'shipped'.
    Flags same-day when the ship date equals the order date.
  * queue: orders in a given status with a ship-readiness summary — the daily
    "what can go out today" view.
"""

from __future__ import annotations

from dataclasses import asdict
from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from production import build_shipment_plan

from .. import catalog_store
from ..db import session_dependency
from ..models_db import Order
from ..schemas import ShipmentPlanOut, ShipRequest

router = APIRouter(tags=["shipping"])


def _plan_payload(order: Order, db: Session) -> dict:
    catalog_data = catalog_store.load(db)
    plan = build_shipment_plan({"id": order.id, "model_id": order.model_id, "bom": order.bom}, catalog_data)
    return {
        "order_id": plan.order_id,
        "lines": [asdict(l) for l in plan.lines],
        "total_weight_lb": plan.total_weight_lb,
        "weight_complete": plan.weight_complete,
        "ready": plan.ready,
        "total_units": plan.total_units,
    }


@router.get("/orders/{order_id}/shipment-plan", response_model=ShipmentPlanOut)
def shipment_plan(order_id: int, db: Session = Depends(session_dependency)):
    order = db.get(Order, order_id)
    if order is None:
        raise HTTPException(status_code=404, detail="Order not found")
    return _plan_payload(order, db)


@router.post("/orders/{order_id}/ship")
def ship_order(order_id: int, req: ShipRequest, db: Session = Depends(session_dependency)):
    order = db.get(Order, order_id)
    if order is None:
        raise HTTPException(status_code=404, detail="Order not found")

    plan = _plan_payload(order, db)
    if not plan["ready"]:
        raise HTTPException(
            status_code=400,
            detail="Cannot ship: some items have no weight set. Add weights in the Catalog tab.",
        )

    ship_date = req.ship_date or date.today()
    order_date = order.created_at.date() if isinstance(order.created_at, datetime) else None
    order.shipping = {
        "carrier": req.carrier,
        "tracking": req.tracking,
        "ship_date": ship_date.isoformat(),
        "shipped_at": datetime.now(timezone.utc).isoformat(),
        "total_weight_lb": plan["total_weight_lb"],
        "same_day": order_date is not None and ship_date == order_date,
    }
    order.status = "shipped"
    db.commit()
    return {"ok": True, "status": order.status, "shipping": order.shipping}


@router.get("/shipping/queue")
def shipping_queue(status: str = "in_production", db: Session = Depends(session_dependency)):
    """Orders in a given status with a ship-readiness summary."""
    orders = db.scalars(select(Order).where(Order.status == status)).all()
    out = []
    for o in orders:
        plan = _plan_payload(o, db)
        out.append(
            {
                "order_id": o.id,
                "customer_name": o.customer_name,
                "model_id": o.model_id,
                "total_units": plan["total_units"],
                "total_weight_lb": plan["total_weight_lb"],
                "ready": plan["ready"],
            }
        )
    return {"status": status, "count": len(out), "orders": out}
