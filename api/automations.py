"""Marketing automation runner.

Each automation is idempotent by construction: when it acts on an entity it
records a "marketing.<kind>.sent" event; the next run skips entities that
already have one. That makes the cron loop safe to retry and trivial to reason
about.

Three automations today:

  abandoned_checkout — pending_payment orders older than the configured grace
                       period, with no nudge yet, get an SMTP email.
  review_followup    — shipped orders older than the configured delay, with no
                       review request yet, get an SMTP email.
  list_sync          — recent "lead.created" / "order.paid" events without a
                       sync record get POSTed to a configured webhook URL
                       (works with Zapier, Make, n8n, or any custom endpoint).

SMTP is reused from existing integration; the webhook URL is just a string in
the automation's config, no new integration provider needed.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from html import escape

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from .audit import has_event, record_event
from .email_service import EmailError, send_email
from .models_db import AUTOMATION_KINDS, AuditEvent, Automation, Order


# ---- config defaults; the owner can override per automation ----
DEFAULTS = {
    "abandoned_checkout": {
        "hours_after": 4,
        "subject": "Did something go wrong at checkout?",
        "body_html": (
            "<p>Hi {name},</p>"
            "<p>We noticed your order at Modular Greenhouses didn't finish. "
            "Reply to this email if you ran into any trouble and we'll help you out.</p>"
        ),
    },
    "review_followup": {
        "days_after": 14,
        "subject": "How's your greenhouse?",
        "body_html": (
            "<p>Hi {name},</p>"
            "<p>It's been a couple of weeks since we shipped your greenhouse. "
            "We'd love a quick review — and if you know someone else who'd love one, "
            "tell them about us. Thanks!</p>"
        ),
    },
    "list_sync": {
        # POST destination — accepts a JSON body. Use Zapier/Make/n8n hooks or a
        # custom endpoint. Empty string disables until configured.
        "webhook_url": "",
    },
}


# ---- helpers ----
def _ensure_seeded(db: Session) -> None:
    for kind in AUTOMATION_KINDS:
        if db.get(Automation, kind) is None:
            db.add(Automation(kind=kind, enabled=False, config=dict(DEFAULTS[kind])))
    db.commit()


def _record_run(automation: Automation, ok: bool | None, message: str) -> None:
    automation.last_run_at = datetime.now(timezone.utc)
    automation.last_run_ok = ok
    automation.last_run_message = message[:400]


def _recipient(order: Order) -> str:
    return (order.contact or {}).get("email") or order.customer_email or ""


def _personalize(template: str, order: Order) -> str:
    name = escape(order.customer_name or "there")
    return template.replace("{name}", name)


# ---- dispatchers ----
def _run_abandoned_checkout(db: Session, config: dict) -> tuple[bool | None, str]:
    hours = int(config.get("hours_after", 4) or 4)
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    candidates = db.scalars(
        select(Order).where(Order.status == "pending_payment", Order.created_at <= cutoff)
    ).all()
    sent = skipped = 0
    last_error = ""
    for order in candidates:
        if has_event(db, kind="marketing.abandoned_checkout.sent", entity_id=order.id):
            continue
        to = _recipient(order)
        if not to:
            skipped += 1
            continue
        try:
            send_email(
                db, to, config.get("subject", DEFAULTS["abandoned_checkout"]["subject"]),
                _personalize(config.get("body_html", DEFAULTS["abandoned_checkout"]["body_html"]), order),
            )
            record_event(
                db, "marketing.abandoned_checkout.sent",
                entity_type="order", entity_id=order.id, data={"to": to},
            )
            sent += 1
        except EmailError as exc:
            last_error = str(exc)
            break  # SMTP is down; stop trying this run
    summary = f"{sent} nudged, {skipped} skipped (no email)"
    if last_error:
        return False, f"{summary}; SMTP failed: {last_error}"
    return True, summary


def _run_review_followup(db: Session, config: dict) -> tuple[bool | None, str]:
    days = int(config.get("days_after", 14) or 14)
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    candidates = db.scalars(
        select(Order).where(Order.status == "shipped", Order.created_at <= cutoff)
    ).all()
    sent = skipped = 0
    last_error = ""
    for order in candidates:
        if has_event(db, kind="marketing.review_followup.sent", entity_id=order.id):
            continue
        to = _recipient(order)
        if not to:
            skipped += 1
            continue
        try:
            send_email(
                db, to, config.get("subject", DEFAULTS["review_followup"]["subject"]),
                _personalize(config.get("body_html", DEFAULTS["review_followup"]["body_html"]), order),
            )
            record_event(
                db, "marketing.review_followup.sent",
                entity_type="order", entity_id=order.id, data={"to": to},
            )
            sent += 1
        except EmailError as exc:
            last_error = str(exc)
            break
    summary = f"{sent} sent, {skipped} skipped (no email)"
    if last_error:
        return False, f"{summary}; SMTP failed: {last_error}"
    return True, summary


def _run_list_sync(db: Session, config: dict, *, http_client: httpx.Client | None = None) -> tuple[bool | None, str]:
    url = (config.get("webhook_url") or "").strip()
    if not url:
        return None, "no webhook_url configured"

    # Events to push: leads and paid orders we haven't synced yet.
    events = db.scalars(
        select(AuditEvent)
        .where(AuditEvent.kind.in_(("lead.created", "order.paid")))
        .order_by(AuditEvent.id.asc())
    ).all()
    pushed = failed = 0
    owns = http_client is None
    client = http_client or httpx.Client(timeout=15.0)
    last_error = ""
    try:
        for event in events:
            if has_event(db, kind="marketing.list_sync.sent", entity_id=event.id):
                continue
            order = db.get(Order, event.entity_id) if event.entity_id else None
            payload = {
                "event": event.kind,
                "occurred_at": event.occurred_at.isoformat() if event.occurred_at else None,
                "order_id": event.entity_id,
                "email": (order.customer_email if order else "") or (event.data or {}).get("email", ""),
                "name": (order.customer_name if order else "") or (event.data or {}).get("name", ""),
                "attribution": (order.attribution if order else {}) or {},
            }
            try:
                r = client.post(url, json=payload)
            except httpx.HTTPError as exc:
                last_error = f"network: {exc}"
                failed += 1
                break
            if r.status_code >= 400:
                last_error = f"HTTP {r.status_code}"
                failed += 1
                break
            record_event(
                db, "marketing.list_sync.sent",
                entity_type="event", entity_id=event.id, data={"url": url, "kind": event.kind},
            )
            pushed += 1
    finally:
        if owns:
            client.close()
    if failed:
        return False, f"{pushed} synced, {failed} failed: {last_error}"
    return True, f"{pushed} synced"


DISPATCHERS = {
    "abandoned_checkout": _run_abandoned_checkout,
    "review_followup": _run_review_followup,
    "list_sync": _run_list_sync,
}


def run_automations(db: Session, only_kind: str | None = None, *, actor: str = "system") -> list[dict]:
    """Run every enabled automation (or one specific kind) and return results."""
    _ensure_seeded(db)
    results = []
    targets = [only_kind] if only_kind else list(AUTOMATION_KINDS)
    for kind in targets:
        automation = db.get(Automation, kind)
        if automation is None or not automation.enabled:
            results.append({"kind": kind, "ok": None, "message": "disabled"})
            continue
        dispatcher = DISPATCHERS.get(kind)
        if dispatcher is None:
            results.append({"kind": kind, "ok": False, "message": "no dispatcher"})
            continue
        try:
            ok, message = dispatcher(db, dict(automation.config or {}))
        except Exception as exc:  # noqa: BLE001 — never let one automation kill the cron
            ok, message = False, f"{exc.__class__.__name__}: {exc}"
        _record_run(automation, ok, message)
        record_event(
            db, f"marketing.{kind}.run", entity_type="automation",
            entity_id=None, actor=actor, data={"ok": ok, "message": message},
        )
        results.append({"kind": kind, "ok": ok, "message": message})
    return results
