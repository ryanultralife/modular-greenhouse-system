"""Billing actions wired to integrations (currently Stripe invoicing).

Guardrails (so a confirm never produces a wrong invoice):
  * a Stripe integration must be configured and enabled,
  * the quote must be complete (no TBD prices) with a positive subtotal,
  * invoicing is idempotent — an order already invoiced returns its existing refs.

By default an invoice is created as a DRAFT (no email sent). Passing send=True
finalizes and sends it via Stripe.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import security
from .models_db import Integration, Order
from .stripe_client import StripeClient, StripeError


class BillingError(Exception):
    pass


def _stripe_key(db: Session) -> str:
    integ = db.scalar(
        select(Integration).where(Integration.provider == "stripe", Integration.enabled.is_(True))
    )
    if integ is None:
        raise BillingError(
            "No enabled Stripe integration is configured. Add your Stripe secret "
            "key under Integrations first."
        )
    creds = security.decrypt_dict(integ.secret_blob)
    key = creds.get("secret_key")
    if not key:
        raise BillingError("The stored Stripe integration has no secret_key.")
    return key


def create_invoice_for_order(
    db: Session, order: Order, *, send: bool = False, stripe_client: StripeClient | None = None
) -> dict:
    pricing = order.pricing or {}
    if not pricing.get("quote_complete"):
        raise BillingError(
            "Cannot invoice: this quote still has unverified (TBD) prices. "
            "Set all prices in the Catalog tab first."
        )
    subtotal = pricing.get("verified_subtotal_usd") or 0
    if subtotal <= 0:
        raise BillingError("Cannot invoice: the quote subtotal is zero.")

    refs = dict(order.external_refs or {})
    if refs.get("stripe_invoice_id"):
        return refs  # already invoiced — idempotent

    owns = stripe_client is None
    if stripe_client is None:
        stripe_client = StripeClient(_stripe_key(db))

    try:
        contact = order.contact or {}
        customer = stripe_client.create_customer(
            contact.get("email") or order.customer_email, order.customer_name
        )
        customer_id = customer["id"]

        for line in order.quote_lines or []:
            price = line.get("unit_price_usd")
            if not price:
                continue
            stripe_client.create_invoice_item(
                customer=customer_id,
                unit_amount_cents=int(round(price * 100)),
                quantity=int(line["quantity"]),
                currency="usd",
                description=line.get("name", "item"),
            )

        invoice = stripe_client.create_invoice(customer_id)
        invoice_id = invoice["id"]
        status = invoice.get("status", "draft")

        if send:
            stripe_client.finalize_invoice(invoice_id)
            invoice = stripe_client.send_invoice(invoice_id)
            status = invoice.get("status", "open")

        refs.update(
            {
                "stripe_customer_id": customer_id,
                "stripe_invoice_id": invoice_id,
                "stripe_invoice_url": invoice.get("hosted_invoice_url"),
                "stripe_invoice_status": status,
            }
        )
        order.external_refs = refs
        db.commit()
        return refs
    except StripeError as exc:
        raise BillingError(str(exc)) from exc
    finally:
        if owns:
            stripe_client.close()
