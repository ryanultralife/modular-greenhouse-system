"""Preset purchase via Stripe Checkout, and the on-paid fulfillment flow.

Flow:
  1. create_checkout_for_preset -> validates price + stock, creates a
     pending_payment order, returns a Stripe Checkout URL.
  2. Stripe redirects the customer to pay; on success Stripe calls our webhook.
  3. handle_paid_order -> marks the order paid, decrements finished-unit stock,
     and (per configuration) fires a co-packer replenishment order.
"""

from __future__ import annotations

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from . import inventory_store, security
from .audit import record_event
from .copacker import create_copacker_order
from .models_db import Integration, Order, Preset, Setting
from .stripe_client import StripeClient, StripeError


class CheckoutError(Exception):
    pass


def stripe_creds(db: Session) -> dict:
    integ = db.scalar(
        select(Integration).where(Integration.provider == "stripe", Integration.enabled.is_(True))
    )
    if integ is None:
        raise CheckoutError("No enabled Stripe integration is configured.")
    creds = security.decrypt_dict(integ.secret_blob)
    if not creds.get("secret_key"):
        raise CheckoutError("The Stripe integration has no secret_key.")
    return creds


def copacker_config(db: Session) -> dict:
    row = db.get(Setting, "copacker_config")
    return (row.value if row and row.value else {}) or {}


def create_checkout_for_preset(
    db: Session,
    preset: Preset,
    *,
    name: str,
    email: str,
    base_url: str,
    stripe_client: StripeClient | None = None,
    attribution: dict | None = None,
) -> dict:
    if not preset.active:
        raise CheckoutError("This product is not available.")
    if not preset.verified_price or not preset.price_usd or preset.price_usd <= 0:
        raise CheckoutError("This product has no confirmed price yet.")

    stock = inventory_store.get_item(db, preset.stock_key)
    if stock is None or stock.on_hand <= 0:
        raise CheckoutError("This product is out of stock. Please request a quote instead.")

    owns = stripe_client is None
    if stripe_client is None:
        stripe_client = StripeClient(stripe_creds(db)["secret_key"])

    order = Order(
        customer_name=name,
        customer_email=email,
        source="website",
        contact={"email": email},
        model_id=preset.model_id or "",
        shape=preset.shape or "straight",
        runs=preset.runs or [],
        status="pending_payment",
        payment_status="unpaid",
        preset_id=preset.id,
        bom=[],
        quote_lines=[],
        pricing={"verified_subtotal_usd": preset.price_usd, "quote_complete": True},
        engineering={},
        attribution=attribution or {},
    )
    db.add(order)
    db.commit()
    record_event(
        db, "checkout.started", entity_type="order", entity_id=order.id,
        data={"preset_id": preset.id, "email": email, "attribution": attribution or {}},
    )

    try:
        session = stripe_client.create_checkout_session(
            name=preset.name,
            unit_amount_cents=int(round(preset.price_usd * 100)),
            quantity=1,
            success_url=f"{base_url}/?purchase=success",
            cancel_url=f"{base_url}/?purchase=cancelled",
            customer_email=email or None,
            metadata={"order_id": str(order.id), "preset_id": str(preset.id)},
        )
    except StripeError as exc:
        raise CheckoutError(str(exc)) from exc
    finally:
        if owns:
            stripe_client.close()

    refs = dict(order.external_refs or {})
    refs["stripe_checkout_session_id"] = session.get("id")
    order.external_refs = refs
    db.commit()
    return {"order_id": order.id, "checkout_url": session.get("url")}


def handle_paid_order(db: Session, order: Order) -> Order:
    """Mark an order paid, decrement stock, and trigger co-packer replenishment.

    Idempotent and concurrency-safe against Stripe's at-least-once webhook
    delivery: the paid transition is a single conditional UPDATE, so only the
    first caller proceeds to fulfillment even if duplicate webhooks race.
    """
    # Atomically flip unpaid -> paid; rowcount tells us if WE won the race.
    won = db.execute(
        update(Order)
        .where(Order.id == order.id, Order.payment_status != "paid")
        .values(payment_status="paid", status="paid")
    ).rowcount
    db.commit()
    if not won:
        db.refresh(order)
        return order  # already fulfilled by a prior (or concurrent) delivery

    db.refresh(order)
    record_event(
        db, "order.paid", entity_type="order", entity_id=order.id,
        data={"preset_id": order.preset_id, "email": order.customer_email},
    )
    if order.preset_id is None:
        return order

    preset = db.get(Preset, order.preset_id)
    stock_key = f"preset:{order.preset_id}"
    # Clamp at zero: physical stock is never negative even on an oversell.
    inventory_store.adjust(db, stock_key, -1, floor=0)

    # Co-packer replenishment for the sold unit.
    item = inventory_store.get_item(db, stock_key)
    cfg = copacker_config(db)
    copacker = (item.copacker if item and item.copacker else cfg.get("name", ""))
    create_copacker_order(
        db,
        copacker=copacker,
        items=[{"key": stock_key, "name": preset.name if preset else stock_key, "quantity": 1}],
        trigger="preset_sale",
        related_order_id=order.id,
        notes=f"Replacement build for paid order #{order.id}.",
        email_to=cfg.get("email") or None,
    )
    return order


def handle_paid_session(db: Session, session_id: str) -> Order | None:
    """Look up the order tied to a Stripe Checkout session id and fulfill it."""
    if not session_id:
        return None
    for o in db.scalars(select(Order).where(Order.preset_id.is_not(None))).all():
        if (o.external_refs or {}).get("stripe_checkout_session_id") == session_id:
            return handle_paid_order(db, o)
    return None
