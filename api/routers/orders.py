"""Persisted orders (quotes that have been saved)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from greenhouse import CatalogError

from ..billing import BillingError, create_invoice_for_order
from ..calendly_actions import CalendlySchedulingError, create_install_link
from ..db import session_dependency
from ..email_service import EmailError, send_email
from ..engine_bridge import compute_quote
from ..models_db import ORDER_STATUSES, Order
from ..quickbooks_sync import QuickBooksSyncError, sync_order
from ..schemas import (
    EmailResult,
    InvoiceResult,
    OrderCreate,
    OrderOut,
    OrderStatusUpdate,
    QuickBooksSyncResult,
    ScheduleResult,
)


def _recipient(order: Order) -> str:
    return (order.contact or {}).get("email") or order.customer_email or ""

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
        "source": order.source,
        "contact": order.contact or {},
        "bom": order.bom,
        "quote_lines": order.quote_lines or [],
        "pricing": order.pricing,
        "engineering": order.engineering,
        "external_refs": order.external_refs or {},
        "shipping": order.shipping or {},
        "fab_session_id": order.fab_session_id,
    }


def _build_order(req: OrderCreate) -> Order:
    result = compute_quote(req.model, req.shape, req.runs)
    return Order(
        customer_name=req.customer_name,
        customer_email=req.customer_email,
        source=req.source,
        contact=req.contact or {},
        model_id=result["model_id"],
        shape=result["shape"],
        runs=result["runs"],
        status="quote",
        bom=result["bom"],
        quote_lines=result["quote_lines"],
        pricing=result["pricing"],
        engineering=result["engineering"],
    )


@router.get("/orders", response_model=list[OrderOut])
def list_orders(status: str | None = None, db: Session = Depends(session_dependency)):
    stmt = select(Order).order_by(Order.created_at.desc())
    if status:
        stmt = stmt.where(Order.status == status)
    return [_to_out(o) for o in db.scalars(stmt).all()]


@router.post("/orders", response_model=OrderOut, status_code=201)
def create_order(req: OrderCreate, db: Session = Depends(session_dependency)):
    try:
        order = _build_order(req)
    except (CatalogError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
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

    if req.create_invoice:
        try:
            create_invoice_for_order(db, order, send=req.send_invoice)
        except BillingError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    return _to_out(order)


@router.post("/orders/{order_id}/invoice", response_model=InvoiceResult)
def invoice_order(
    order_id: int, send: bool = False, db: Session = Depends(session_dependency)
):
    order = db.get(Order, order_id)
    if order is None:
        raise HTTPException(status_code=404, detail="Order not found")
    try:
        refs = create_invoice_for_order(db, order, send=send)
    except BillingError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return refs


@router.post("/orders/{order_id}/quickbooks-sync", response_model=QuickBooksSyncResult)
def quickbooks_sync(order_id: int, db: Session = Depends(session_dependency)):
    order = db.get(Order, order_id)
    if order is None:
        raise HTTPException(status_code=404, detail="Order not found")
    try:
        return sync_order(db, order)
    except QuickBooksSyncError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/orders/{order_id}/schedule-install", response_model=ScheduleResult)
def schedule_install(order_id: int, notify: bool = False, db: Session = Depends(session_dependency)):
    order = db.get(Order, order_id)
    if order is None:
        raise HTTPException(status_code=404, detail="Order not found")
    try:
        booking_url = create_install_link(db, order)
    except CalendlySchedulingError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    emailed = False
    if notify:
        to = _recipient(order)
        name = order.customer_name or "there"
        html = (
            f"<p>Hi {name},</p><p>Thanks for your order with Modular Greenhouses. "
            f"Please pick a time for your install here:</p>"
            f"<p><a href='{booking_url}'>{booking_url}</a></p>"
        )
        try:
            send_email(db, to, "Schedule your greenhouse install", html)
            emailed = True
        except EmailError as exc:
            raise HTTPException(
                status_code=400, detail=f"Install link created but the email failed: {exc}"
            ) from exc
    return {"booking_url": booking_url, "emailed": emailed}


@router.post("/orders/{order_id}/send-confirmation", response_model=EmailResult)
def send_confirmation(order_id: int, db: Session = Depends(session_dependency)):
    order = db.get(Order, order_id)
    if order is None:
        raise HTTPException(status_code=404, detail="Order not found")
    to = _recipient(order)
    rows = "".join(
        f"<li>{l['quantity']} × {l['name']}</li>" for l in (order.bom or [])
    )
    subtotal = (order.pricing or {}).get("verified_subtotal_usd", 0)
    html = (
        f"<p>Hi {order.customer_name or 'there'},</p>"
        f"<p>Here is a summary of your {order.model_id} ({order.shape}) order:</p>"
        f"<ul>{rows}</ul>"
        f"<p>Estimated subtotal: ${subtotal:,.2f}</p>"
        f"<p>We'll be in touch with next steps. Thank you!</p>"
    )
    try:
        send_email(db, to, f"Your Modular Greenhouse order #{order.id}", html)
    except EmailError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True, "to": to}
