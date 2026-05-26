"""Persisted orders (quotes that have been saved)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from greenhouse import CatalogError

from ..db import session_dependency
from ..engine_bridge import compute_quote
from ..models_db import ORDER_STATUSES, Order
from ..schemas import OrderCreate, OrderOut, OrderStatusUpdate

router = APIRouter(tags=["orders"])


def _to_out(order: Order) -> dict:
    return {
        "id": order.id,
        "created_at": order.created_at,
        "customer_name": order.customer_name,
        "customer_email": order.customer_email,
        "model_id": order.model_id,
        "shape": order.shape,
        "runs": order.runs,
        "status": order.status,
        "bom": order.bom,
        "pricing": order.pricing,
        "engineering": order.engineering,
        "fab_session_id": order.fab_session_id,
    }


@router.get("/orders", response_model=list[OrderOut])
def list_orders(status: str | None = None, db: Session = Depends(session_dependency)):
    stmt = select(Order).order_by(Order.created_at.desc())
    if status:
        stmt = stmt.where(Order.status == status)
    return [_to_out(o) for o in db.scalars(stmt).all()]


@router.post("/orders", response_model=OrderOut, status_code=201)
def create_order(req: OrderCreate, db: Session = Depends(session_dependency)):
    try:
        result = compute_quote(req.model, req.shape, req.runs)
    except (CatalogError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    order = Order(
        customer_name=req.customer_name,
        customer_email=req.customer_email,
        model_id=result["model_id"],
        shape=result["shape"],
        runs=result["runs"],
        status="quote",
        bom=result["bom"],
        pricing=result["pricing"],
        engineering=result["engineering"],
    )
    db.add(order)
    db.commit()
    return _to_out(order)


@router.get("/orders/{order_id}", response_model=OrderOut)
def get_order(order_id: int, db: Session = Depends(session_dependency)):
    order = db.get(Order, order_id)
    if order is None:
        raise HTTPException(status_code=404, detail="Order not found")
    return _to_out(order)


@router.patch("/orders/{order_id}", response_model=OrderOut)
def update_order(
    order_id: int, req: OrderStatusUpdate, db: Session = Depends(session_dependency)
):
    order = db.get(Order, order_id)
    if order is None:
        raise HTTPException(status_code=404, detail="Order not found")
    if req.status is not None:
        if req.status not in ORDER_STATUSES:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid status. Allowed: {', '.join(ORDER_STATUSES)}",
            )
        order.status = req.status
    if req.fab_session_id is not None:
        order.fab_session_id = req.fab_session_id or None
    db.commit()
    return _to_out(order)
