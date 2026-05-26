"""Co-packer order creation and (optional) email dispatch."""

from __future__ import annotations

from sqlalchemy.orm import Session

from .email_service import EmailError, send_email
from .models_db import CoPackerOrder


def create_copacker_order(
    db: Session,
    *,
    copacker: str,
    items: list[dict],
    trigger: str = "manual",
    related_order_id: int | None = None,
    notes: str = "",
    email_to: str | None = None,
) -> CoPackerOrder:
    order = CoPackerOrder(
        copacker=copacker or "",
        items=items,
        trigger=trigger,
        related_order_id=related_order_id,
        notes=notes,
        status="draft",
    )
    db.add(order)
    db.commit()

    if email_to:
        rows = "".join(f"<li>{i['quantity']} × {i.get('name', i.get('key'))}</li>" for i in items)
        html = (
            f"<p>New co-packer build order ({trigger}):</p>"
            f"<ul>{rows}</ul>"
            f"{('<p>' + notes + '</p>') if notes else ''}"
        )
        try:
            send_email(db, email_to, f"Co-packer build order #{order.id}", html)
            order.emailed = True
            order.status = "sent"
            db.commit()
        except EmailError:
            # Email is best-effort; the order is recorded regardless.
            pass
    return order
