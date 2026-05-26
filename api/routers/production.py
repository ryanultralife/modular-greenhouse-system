"""Weekly fabrication sessions and the aggregated stock list / co-packer split."""

from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from production import build_stock_list

from .. import catalog_store
from ..db import session_dependency
from ..models_db import FabricationSession, Order
from ..schemas import FabSessionAssign, FabSessionCreate, FabSessionOut

router = APIRouter(tags=["production"])


def _session_out(s: FabricationSession) -> dict:
    return {
        "id": s.id,
        "week_of": s.week_of,
        "label": s.label,
        "status": s.status,
        "order_ids": [o.id for o in s.orders],
    }


@router.get("/fab-sessions", response_model=list[FabSessionOut])
def list_sessions(db: Session = Depends(session_dependency)):
    stmt = select(FabricationSession).order_by(FabricationSession.week_of.desc())
    return [_session_out(s) for s in db.scalars(stmt).all()]


@router.post("/fab-sessions", response_model=FabSessionOut, status_code=201)
def create_session(req: FabSessionCreate, db: Session = Depends(session_dependency)):
    s = FabricationSession(week_of=req.week_of, label=req.label)
    db.add(s)
    db.commit()
    return _session_out(s)


@router.post("/fab-sessions/{session_id}/assign", response_model=FabSessionOut)
def assign_orders(
    session_id: int, req: FabSessionAssign, db: Session = Depends(session_dependency)
):
    s = db.get(FabricationSession, session_id)
    if s is None:
        raise HTTPException(status_code=404, detail="Fabrication session not found")
    for oid in req.order_ids:
        order = db.get(Order, oid)
        if order is None:
            raise HTTPException(status_code=404, detail=f"Order {oid} not found")
        order.fab_session_id = session_id
    db.commit()
    db.refresh(s)
    return _session_out(s)


@router.get("/fab-sessions/{session_id}/stock-list")
def session_stock_list(session_id: int, db: Session = Depends(session_dependency)):
    s = db.get(FabricationSession, session_id)
    if s is None:
        raise HTTPException(status_code=404, detail="Fabrication session not found")
    return _stock_list_payload(
        [{"id": o.id, "model_id": o.model_id, "bom": o.bom} for o in s.orders]
    )


@router.get("/production/stock-list")
def stock_list_for_status(
    status: str = "confirmed", db: Session = Depends(session_dependency)
):
    """Ad-hoc stock list across all orders with a given status."""
    stmt = select(Order).where(Order.status == status)
    orders = [
        {"id": o.id, "model_id": o.model_id, "bom": o.bom}
        for o in db.scalars(stmt).all()
    ]
    return _stock_list_payload(orders)


def _stock_list_payload(orders: list[dict]) -> dict:
    catalog_data = catalog_store.load()
    stock = build_stock_list(orders, catalog_data)
    return {
        "order_ids": stock.order_ids,
        "order_count": len(stock.order_ids),
        "in_house": [asdict(l) for l in stock.in_house],
        "copacker": {
            name: [asdict(l) for l in lines]
            for name, lines in stock.by_copacker().items()
        },
        "all_lines": [asdict(l) for l in stock.lines],
    }
