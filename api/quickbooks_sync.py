"""Sync a confirmed order to QuickBooks Online as a customer + invoice.

Same guardrails as Stripe billing: needs an enabled QuickBooks integration, a
complete quote with a positive subtotal, and is idempotent (an order already
synced returns its stored refs).
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import security
from .models_db import Integration, Order
from .quickbooks_client import QuickBooksClient, QuickBooksError


class QuickBooksSyncError(Exception):
    pass


def _client_from_db(db: Session) -> tuple[QuickBooksClient, str | None]:
    integ = db.scalar(
        select(Integration).where(Integration.provider == "quickbooks", Integration.enabled.is_(True))
    )
    if integ is None:
        raise QuickBooksSyncError(
            "No enabled QuickBooks integration is configured. Add your QuickBooks "
            "OAuth credentials under Integrations first."
        )
    creds = security.decrypt_dict(integ.secret_blob)
    required = ("client_id", "client_secret", "refresh_token", "realm_id")
    if not all(creds.get(k) for k in required):
        raise QuickBooksSyncError(
            "QuickBooks integration is missing one of: " + ", ".join(required)
        )
    client = QuickBooksClient(
        client_id=creds["client_id"],
        client_secret=creds["client_secret"],
        refresh_token=creds["refresh_token"],
        realm_id=creds["realm_id"],
        environment=creds.get("environment", "production"),
    )
    return client, creds.get("item_ref")


def sync_order(db: Session, order: Order, *, client: QuickBooksClient | None = None, item_ref: str | None = None) -> dict:
    pricing = order.pricing or {}
    if not pricing.get("quote_complete"):
        raise QuickBooksSyncError(
            "Cannot sync: this quote still has unverified (TBD) prices. Set all "
            "prices in the Catalog tab first."
        )
    if (pricing.get("verified_subtotal_usd") or 0) <= 0:
        raise QuickBooksSyncError("Cannot sync: the quote subtotal is zero.")

    refs = dict(order.external_refs or {})
    if refs.get("qbo_invoice_id"):
        return refs  # already synced — idempotent

    owns = client is None
    if client is None:
        client, item_ref = _client_from_db(db)

    try:
        if not item_ref:
            item_ref = client.first_item_ref()
        if not item_ref:
            raise QuickBooksSyncError(
                "No QuickBooks item is available to put on the invoice. Create an "
                "item in QuickBooks or set 'item_ref' on the integration."
            )

        display_name = order.customer_name or (order.contact or {}).get("email") or f"Order {order.id}"
        email = (order.contact or {}).get("email") or order.customer_email
        customer = client.find_customer(display_name) or client.create_customer(display_name, email)
        customer_id = customer["Id"]

        lines = []
        for line in order.quote_lines or []:
            price = line.get("unit_price_usd")
            if not price:
                continue
            qty = int(line["quantity"])
            lines.append(
                {
                    "amount": price * qty,
                    "unit_price": price,
                    "qty": qty,
                    "description": line.get("name", "item"),
                }
            )

        invoice = client.create_invoice(customer_id, lines, item_ref)
        refs.update(
            {
                "qbo_customer_id": customer_id,
                "qbo_invoice_id": invoice["Id"],
                "qbo_invoice_doc_number": invoice.get("DocNumber"),
            }
        )
        order.external_refs = refs
        db.commit()
        return refs
    except QuickBooksError as exc:
        raise QuickBooksSyncError(str(exc)) from exc
    finally:
        if owns:
            client.close()
