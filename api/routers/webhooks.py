"""Open webhook endpoints (no auth — verified by signature)."""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import security
from ..checkout import handle_paid_order
from ..db import session_dependency
from ..models_db import Integration, Order
from ..stripe_client import verify_webhook_signature

router = APIRouter(tags=["webhooks"])


@router.post("/stripe/webhook")
async def stripe_webhook(
    request: Request,
    stripe_signature: str = Header(default="", alias="Stripe-Signature"),
    db: Session = Depends(session_dependency),
):
    payload = await request.body()

    integ = db.scalar(
        select(Integration).where(Integration.provider == "stripe", Integration.enabled.is_(True))
    )
    secret = ""
    if integ:
        secret = security.decrypt_dict(integ.secret_blob).get("webhook_secret", "")
    if not secret:
        raise HTTPException(
            status_code=400,
            detail="Stripe webhook secret is not configured. Add 'webhook_secret' to the Stripe integration.",
        )
    if not verify_webhook_signature(payload, stripe_signature, secret):
        raise HTTPException(status_code=400, detail="Invalid webhook signature.")

    try:
        event = json.loads(payload.decode())
    except (ValueError, UnicodeDecodeError) as exc:
        raise HTTPException(status_code=400, detail="Invalid payload.") from exc

    if event.get("type") == "checkout.session.completed":
        obj = event.get("data", {}).get("object", {}) or {}
        order_id = (obj.get("metadata") or {}).get("order_id")
        if order_id:
            try:
                order = db.get(Order, int(order_id))
            except (TypeError, ValueError):
                order = None
            if order is not None:
                handle_paid_order(db, order)

    return {"received": True}
