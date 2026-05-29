"""Staff work board: a prioritized, sanitized view of the day's tasks.

Accessible to staff and owner. Deliberately exposes NO pricing, payment refs,
or secrets — only operational fields (customer name, build, status, ship
readiness). Sales/inventory drive the priorities.
"""

from __future__ import annotations

from datetime import date, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from production import build_shipment_plan, build_stock_list, compute_material_needs

from .. import catalog_store, inventory_store
from ..db import session_dependency
from ..models_db import CoPackerOrder, FabricationSession, Order

router = APIRouter(prefix="/work", tags=["work"])

# Statuses that represent "in the build pipeline, not yet shipped/cancelled".
BUILD_STATUSES = ("confirmed", "paid", "in_production")
NEXT_WEEK_HORIZON_DAYS = 14  # look this far ahead for a "next week" fab session


def _task(o: Order) -> dict:
    """Operational, money-free summary of an order."""
    runs = o.runs or []
    return {
        "order_id": o.id,
        "customer_name": o.customer_name or "—",
        "model_id": o.model_id,
        "shape": o.shape,
        "runs": runs,
        "sections": len(runs),
        "status": o.status,
        "is_preset": o.preset_id is not None,
    }


def _summarize_orders(orders: list[Order], catalog: dict) -> dict:
    """Build the per-section/materials rollup for a set of orders."""
    fab_dicts = [{"id": o.id, "model_id": o.model_id, "bom": o.bom} for o in orders]
    stock = build_stock_list(fab_dicts, catalog)
    materials = compute_material_needs(fab_dicts, catalog)
    return {
        "count": len(orders),
        "orders": [_task(o) for o in orders],
        "build_items": [
            {"sku_id": l.sku_id, "name": l.name, "quantity": l.quantity} for l in stock.lines
        ],
        "materials": [
            {"name": n.name, "quantity": n.quantity, "unit": n.unit, "complete": n.complete}
            for n in materials.needs
        ],
        "materials_complete": materials.complete,
    }


def _pick_next_session(db: Session, today: date) -> FabricationSession | None:
    """The soonest planned fabrication session within the horizon, if any."""
    horizon = today + timedelta(days=NEXT_WEEK_HORIZON_DAYS)
    return db.scalar(
        select(FabricationSession)
        .where(
            FabricationSession.status == "planned",
            FabricationSession.week_of >= today,
            FabricationSession.week_of <= horizon,
        )
        .order_by(FabricationSession.week_of.asc())
    )


@router.get("/board")
def work_board(db: Session = Depends(session_dependency)):
    catalog = catalog_store.load(db)
    orders = db.scalars(select(Order)).all()

    fabricate, new_paid, ready = [], [], []
    for o in orders:
        if o.status in BUILD_STATUSES:
            fabricate.append(o)
        if o.status == "paid":
            new_paid.append(o)
        if o.status in ("paid", "in_production"):
            plan = build_shipment_plan({"id": o.id, "model_id": o.model_id, "bom": o.bom}, catalog)
            if plan.ready:
                ready.append((o, plan))

    low = inventory_store.low_stock(db)
    pending_cp = db.scalars(
        select(CoPackerOrder).where(CoPackerOrder.status.in_(("draft", "sent")))
    ).all()

    # Next week: if a planned fab session lands within the horizon, use its
    # assigned orders; otherwise show queued confirmed orders (heads-up for the
    # owner to schedule a session).
    today = date.today()
    session = _pick_next_session(db, today)
    if session is not None:
        next_orders = list(session.orders)
        nw = _summarize_orders(next_orders, catalog)
        nw["session"] = {
            "id": session.id,
            "week_of": session.week_of.isoformat(),
            "label": session.label,
        }
        nw["source"] = "fab_session"
    else:
        queued = [o for o in orders if o.status == "confirmed" and o.fab_session_id is None]
        nw = _summarize_orders(queued, catalog)
        nw["session"] = None
        nw["source"] = "queued"

    return {
        "fabricate": _summarize_orders(fabricate, catalog),
        "ready_to_ship": {
            "count": len(ready),
            "orders": [
                {**_task(o), "total_weight_lb": plan.total_weight_lb} for o, plan in ready
            ],
        },
        "restock": {
            "low_stock": [
                {"key": i.key, "name": i.name, "on_hand": i.on_hand, "reorder_point": i.reorder_point,
                 "unit": i.unit, "copacker": i.copacker}
                for i in low
            ],
            "pending_copacker": [
                {"id": c.id, "copacker": c.copacker, "items": c.items, "status": c.status, "trigger": c.trigger}
                for c in pending_cp
            ],
        },
        "new_paid": {
            "count": len(new_paid),
            "orders": [_task(o) for o in new_paid],
        },
        "next_week": nw,
    }


@router.post("/orders/{order_id}/start")
def start_build(order_id: int, db: Session = Depends(session_dependency)):
    """Staff action: move an order into production. No financial fields touched."""
    from fastapi import HTTPException

    o = db.get(Order, order_id)
    if o is None:
        raise HTTPException(status_code=404, detail="Order not found")
    if o.status not in ("confirmed", "paid"):
        raise HTTPException(status_code=400, detail=f"Order is '{o.status}', cannot start build.")
    o.status = "in_production"
    db.commit()
    return _task(o)
