"""Generate a Calendly single-use scheduling link for a greenhouse install.

The event type is taken from the integration's stored ``event_type_uri`` if
set; otherwise the customer's first active event type is used. The resulting
booking URL is stored on the order so Josh can send it to the customer.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import security
from .calendly_client import CalendlyClient, CalendlyError
from .models_db import Integration, Order


class CalendlySchedulingError(Exception):
    pass


def _client_from_db(db: Session) -> tuple[CalendlyClient, str | None]:
    integ = db.scalar(
        select(Integration).where(Integration.provider == "calendly", Integration.enabled.is_(True))
    )
    if integ is None:
        raise CalendlySchedulingError(
            "No enabled Calendly integration is configured. Add your Calendly "
            "access token under Integrations first."
        )
    creds = security.decrypt_dict(integ.secret_blob)
    token = creds.get("access_token")
    if not token:
        raise CalendlySchedulingError("The stored Calendly integration has no access_token.")
    return CalendlyClient(token), creds.get("event_type_uri")


def create_install_link(
    db: Session, order: Order, *, client: CalendlyClient | None = None, event_type_uri: str | None = None
) -> str:
    refs = dict(order.external_refs or {})
    if refs.get("calendly_booking_url"):
        return refs["calendly_booking_url"]  # already scheduled — idempotent

    owns = client is None
    if client is None:
        client, event_type_uri = _client_from_db(db)

    try:
        if not event_type_uri:
            user = client.me()
            event_types = client.active_event_types(user["uri"])
            if not event_types:
                raise CalendlySchedulingError(
                    "No active Calendly event type found. Create one (e.g. "
                    "'Greenhouse install') or set 'event_type_uri' on the integration."
                )
            event_type_uri = event_types[0]["uri"]

        booking_url = client.create_single_use_link(event_type_uri)
        refs["calendly_booking_url"] = booking_url
        order.external_refs = refs
        db.commit()
        return booking_url
    except CalendlyError as exc:
        raise CalendlySchedulingError(str(exc)) from exc
    finally:
        if owns:
            client.close()
