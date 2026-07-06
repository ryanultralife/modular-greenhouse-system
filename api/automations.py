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
    "ai_digest": {
        # Daily business briefing emailed to the owner. Sends once per day, on
        # the first hourly cron run at/after send_after_hour_utc. AI-written when
        # an Anthropic key is configured; otherwise a plain structured summary.
        "recipient": "",
        "send_after_hour_utc": 13,
        "subject": "Your Modular Greenhouses daily digest",
    },
    "lead_followup": {
        # Auto-send a personalized follow-up to each new website lead after the
        # delay. AI-written when the Anthropic key is set, template otherwise —
        # both use only the lead's saved configuration snapshot.
        "delay_minutes": 60,
        "max_per_run": 10,
        "subject": "About your greenhouse quote",
    },
    "social_posts": {
        # A batch of grounded Facebook/social post drafts every cadence_days.
        # Emailed to recipient and/or POSTed one-by-one to webhook_url (point a
        # Zapier/Make zap at your Facebook Page for hands-off publishing).
        "cadence_days": 7,
        "posts_per_batch": 3,
        "recipient": "",
        "webhook_url": "",
        "subject": "Your social post pack",
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


def _render_plain_digest(snapshot: dict, marketing: dict) -> str:
    """Structured fallback digest when no AI key is configured."""
    lines = ["<h3>Daily digest</h3>", "<h4>Business</h4><ul>"]
    for status, count in sorted((snapshot.get("orders_by_status") or {}).items()):
        lines.append(f"<li>{escape(status)}: {int(count)}</li>")
    lines.append(f"<li>Verified revenue (active orders): ${snapshot.get('verified_revenue_usd_all_active_orders', 0):,.2f}</li>")
    lines.append(f"<li>Website leads (7 days): {snapshot.get('website_leads_last_7_days', 0)}</li>")
    lines.append("</ul>")
    low = snapshot.get("low_stock_items") or []
    if low:
        lines.append("<h4>Restock</h4><ul>")
        for i in low:
            lines.append(f"<li>{escape(str(i['name']))}: {i['on_hand']} {escape(str(i['unit']))} (reorder at {i['reorder_point']})</li>")
        lines.append("</ul>")
    by_source = marketing.get("website_leads_by_source") or {}
    if by_source:
        lines.append("<h4>Leads by source</h4><ul>")
        for src, n in sorted(by_source.items(), key=lambda kv: -kv[1]):
            lines.append(f"<li>{escape(str(src))}: {int(n)}</li>")
        lines.append("</ul>")
    if marketing.get("abandoned_checkouts_open"):
        lines.append(f"<p>Open abandoned checkouts: {marketing['abandoned_checkouts_open']}</p>")
    return "".join(lines)


def _ai_digest_text(db: Session, snapshot: dict, marketing: dict) -> str | None:
    """AI-written digest when a key is configured; None on any failure (fallback)."""
    from .advisor import get_advisor_config

    config = get_advisor_config(db)
    if config is None:
        return None
    try:
        import json

        import anthropic

        client = anthropic.Anthropic(api_key=config["api_key"])
        try:
            response = client.messages.create(
                model=config["model"],
                max_tokens=800,
                thinking={"type": "adaptive"},
                output_config={"effort": "medium"},
                system=(
                    "You write a short morning business digest for the owner of a modular "
                    "greenhouse company, from the JSON data provided. Rules: use ONLY numbers "
                    "present in the data; lead with what needs attention today (restock, "
                    "abandoned checkouts, builds due); then a one-line pulse on sales and "
                    "lead sources. Plain HTML (<p>, <ul>), no invented facts, under 180 words."
                ),
                messages=[{
                    "role": "user",
                    "content": "Today's data:\n" + json.dumps({"business": snapshot, "marketing": marketing}, default=str),
                }],
            )
        finally:
            client.close()
        if response.stop_reason == "refusal":
            return None
        text = "".join(b.text for b in response.content if b.type == "text").strip()
        return text or None
    except Exception:  # noqa: BLE001 — digest must degrade, never crash the cron
        return None


def _run_ai_digest(db: Session, config: dict) -> tuple[bool | None, str]:
    from .copilot import build_business_snapshot, build_marketing_insights

    recipient = (config.get("recipient") or "").strip()
    if not recipient:
        return None, "no recipient configured"

    now = datetime.now(timezone.utc)
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    already = db.scalar(
        select(AuditEvent.id).where(
            AuditEvent.kind == "marketing.ai_digest.sent", AuditEvent.occurred_at >= day_start
        ).limit(1)
    )
    if already is not None:
        return True, "already sent today"
    send_after = int(config.get("send_after_hour_utc", 13) or 0)
    if now.hour < send_after:
        return True, f"waiting until {send_after:02d}:00 UTC"

    snapshot = build_business_snapshot(db)
    marketing = build_marketing_insights(db)
    html = _ai_digest_text(db, snapshot, marketing)
    mode = "ai"
    if html is None:
        html = _render_plain_digest(snapshot, marketing)
        mode = "plain"

    try:
        send_email(db, recipient, config.get("subject") or DEFAULTS["ai_digest"]["subject"], html)
    except EmailError as exc:
        return False, f"SMTP failed: {exc}"
    record_event(
        db, "marketing.ai_digest.sent", entity_type="", entity_id=None,
        data={"to": recipient, "mode": mode},
    )
    return True, f"sent ({mode})"


from .growth import run_lead_followup as _run_lead_followup  # noqa: E402
from .growth import run_social_posts as _run_social_posts  # noqa: E402

DISPATCHERS = {
    "abandoned_checkout": _run_abandoned_checkout,
    "review_followup": _run_review_followup,
    "list_sync": _run_list_sync,
    "ai_digest": _run_ai_digest,
    "lead_followup": _run_lead_followup,
    "social_posts": _run_social_posts,
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
