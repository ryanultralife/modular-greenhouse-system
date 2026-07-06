"""Growth automations: AI lead follow-up and the social post pack.

Both follow the house automation rules: grounded on real data only, idempotent
via the event log, degrade gracefully to templates when no Anthropic key is
configured, and never block the cron on an AI failure.

Content guardrails: emails and posts are generated ONLY from each lead's saved
configuration snapshot or the verified catalog — no discounts, no promises, no
invented specs. The AI prompt enforces it; the template fallback can't violate
it by construction.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from html import escape

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from .audit import has_event, record_event
from .email_service import EmailError, send_email
from .models_db import AuditEvent, Order

FOLLOWUP_EVENT = "marketing.lead_followup.sent"
SOCIAL_EVENT = "marketing.social_posts.sent"


# ---------------------------------------------------------------- lead follow-up
def _lead_context(order: Order) -> dict:
    """The grounded facts an email may use — nothing else."""
    pricing = order.pricing or {}
    eng = order.engineering or {}
    return {
        "name": order.customer_name or "there",
        "build": f"{order.model_id} / {order.shape} / arms {order.runs} ft",
        "verified_subtotal_usd": pricing.get("verified_subtotal_usd"),
        "pricing_complete": bool(pricing.get("quote_complete")),
        "needs_engineer_signoff": bool(eng.get("requires_signoff")),
    }


def _template_followup(ctx: dict) -> str:
    name = escape(str(ctx["name"]))
    build = escape(str(ctx["build"]))
    lines = [
        f"<p>Hi {name},</p>",
        f"<p>Thanks for configuring a greenhouse with us — we have your request for: {build}.</p>",
    ]
    subtotal = ctx.get("verified_subtotal_usd")
    if subtotal and ctx.get("pricing_complete"):
        lines.append(f"<p>Your configuration comes to ${subtotal:,.2f}.</p>")
    elif subtotal:
        lines.append(f"<p>Your configuration starts from ${subtotal:,.2f}; we'll confirm final pricing when we follow up.</p>")
    if ctx.get("needs_engineer_signoff"):
        lines.append("<p>Since this is a custom layout, our engineer will review it and confirm the wind/snow ratings for your exact build.</p>")
    lines.append("<p>Just reply to this email with any questions — happy to help you get growing.</p>")
    lines.append("<p>— Modular Greenhouses, Reno NV</p>")
    return "".join(lines)


def _ai_followup(db: Session, ctx: dict) -> str | None:
    from .advisor import get_advisor_config

    config = get_advisor_config(db)
    if config is None:
        return None
    try:
        import anthropic

        client = anthropic.Anthropic(api_key=config["api_key"])
        try:
            response = client.messages.create(
                model=config["model"],
                max_tokens=500,
                thinking={"type": "adaptive"},
                output_config={"effort": "low"},
                system=(
                    "Write a short, warm follow-up email (plain HTML fragment, <p> tags, under "
                    "120 words) from Modular Greenhouses (Reno, NV) to a customer who just "
                    "requested a greenhouse quote on our website. Use ONLY the facts in the "
                    "JSON. Rules: state the price only if pricing_complete is true, otherwise "
                    "say final pricing is confirmed on follow-up; if needs_engineer_signoff is "
                    "true, mention our engineer reviews custom layouts before confirming the "
                    "wind/snow ratings; no discounts, no delivery promises, no invented specs; "
                    "invite them to reply with questions; sign off as Modular Greenhouses."
                ),
                messages=[{"role": "user", "content": json.dumps(ctx, default=str)}],
            )
        finally:
            client.close()
        if response.stop_reason == "refusal":
            return None
        text = "".join(b.text for b in response.content if b.type == "text").strip()
        return text or None
    except Exception:  # noqa: BLE001 — degrade to template, never break the cron
        return None


def run_lead_followup(db: Session, config: dict) -> tuple[bool | None, str]:
    delay = int(config.get("delay_minutes", 60) or 0)
    max_per_run = int(config.get("max_per_run", 10) or 10)
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=delay)

    candidates = db.scalars(
        select(Order)
        .where(Order.status == "quote", Order.source == "website", Order.created_at <= cutoff)
        .order_by(Order.created_at.asc())
    ).all()

    sent = skipped = 0
    last_error = ""
    mode = "template"
    for order in candidates:
        if sent >= max_per_run:
            break
        if has_event(db, kind=FOLLOWUP_EVENT, entity_id=order.id):
            continue
        to = (order.contact or {}).get("email") or order.customer_email
        if not to:
            skipped += 1
            continue
        ctx = _lead_context(order)
        html = _ai_followup(db, ctx)
        mode = "ai" if html else "template"
        if html is None:
            html = _template_followup(ctx)
        try:
            send_email(db, to, config.get("subject") or "About your greenhouse quote", html)
        except EmailError as exc:
            last_error = str(exc)
            break  # SMTP down; stop this run
        record_event(db, FOLLOWUP_EVENT, entity_type="order", entity_id=order.id,
                     data={"to": to, "mode": mode})
        sent += 1

    summary = f"{sent} followed up ({mode}), {skipped} skipped (no email)"
    if last_error:
        return False, f"{summary}; SMTP failed: {last_error}"
    return True, summary


# ---------------------------------------------------------------- social posts
def _grounded_social_facts(db: Session) -> dict:
    """Only verified/real facts a post may mention."""
    from .copilot import build_business_snapshot

    from greenhouse import Catalog

    from . import catalog_store, inventory_store
    from .models_db import Preset

    catalog = Catalog(catalog_store.load(db))
    models = []
    for mid in catalog.model_ids():
        m = catalog.model(mid)
        base = m.get("skus", {}).get("base_kit", {})
        if base.get("verified_price"):
            models.append({"name": m["name"], "from_price_usd": base["price_usd"]})

    presets = []
    for p in db.scalars(select(Preset).where(Preset.active.is_(True))).all():
        item = inventory_store.get_item(db, p.stock_key)
        if p.verified_price and p.price_usd and item and item.on_hand > 0:
            presets.append({"name": p.name, "price_usd": p.price_usd, "ships": p.ship_speed})

    env = catalog.engineering_envelope
    week_ago = datetime.now(timezone.utc) - timedelta(days=7)
    shipped_this_week = sum(
        1 for o in db.scalars(select(Order).where(Order.status == "shipped")).all()
        if o.created_at and o.created_at.replace(tzinfo=timezone.utc) >= week_ago
    )
    snapshot = build_business_snapshot(db)
    return {
        "company": "Modular Greenhouses — Reno, NV. Patented modular greenhouse kits (US 10,426,102), 4-ft expandable sections, foldable-hinge assembly in ~2 hours per section.",
        "engineering_standard_straight_runs": {
            "wind_mph": (env.get("wind_mph") or {}).get("value"),
            "snow_depth_ft": (env.get("snow_depth_ft") or {}).get("value"),
            "warranty_years": (env.get("warranty_years") or {}).get("value"),
        },
        "models_with_verified_prices": models,
        "ready_to_ship_presets": presets,
        "shipped_this_week": shipped_this_week,
        "website_leads_last_7_days": snapshot.get("website_leads_last_7_days"),
    }


def _template_posts(facts: dict, count: int) -> list[dict]:
    posts: list[dict] = []
    env = facts.get("engineering_standard_straight_runs") or {}
    if env.get("wind_mph"):
        posts.append({
            "text": (
                f"Built for real weather: our standard straight-run greenhouses are engineered for "
                f"{env['wind_mph']} mph winds and {env.get('snow_depth_ft', '—')} ft of snow, backed by a "
                f"{env.get('warranty_years', '—')}-year guarantee. Designed & made in Reno, NV. 🌿"
            ),
            "image_hint": "Greenhouse standing in snow or wind, or a build photo",
        })
    for p in facts.get("ready_to_ship_presets") or []:
        posts.append({
            "text": (
                f"Ready to ship now: {p['name']} — ${p['price_usd']:,.0f}, ships {str(p['ships']).replace('_', ' ')}. "
                f"Grab it on our site before it's gone. 🏡🌱"
            ),
            "image_hint": f"Photo of the {p['name']}",
        })
    posts.append({
        "text": (
            "Start small, grow anytime: every one of our greenhouses extends in 4-ft sections — "
            "add a module in about two hours with our patented foldable-hinge design. "
            "Straight, L, T, or X layouts. Design yours on our site."
        ),
        "image_hint": "Assembly photo or shape diagram",
    })
    return posts[: max(1, count)]


def _ai_posts(db: Session, facts: dict, count: int) -> list[dict] | None:
    from .advisor import get_advisor_config

    config = get_advisor_config(db)
    if config is None:
        return None
    try:
        import anthropic

        client = anthropic.Anthropic(api_key=config["api_key"])
        try:
            response = client.messages.create(
                model=config["model"],
                max_tokens=1200,
                thinking={"type": "adaptive"},
                output_config={"effort": "medium"},
                system=(
                    "You write Facebook posts for a small modular-greenhouse company. From the "
                    "JSON facts, write engaging, warm posts a small-town Nevada manufacturer "
                    "would actually publish. Rules: use ONLY facts present in the JSON (prices, "
                    "ratings, counts); engineering ratings apply to standard straight runs — "
                    "don't generalize them; no discounts, giveaways, or promises not in the "
                    "data; 1-3 tasteful emoji max per post; each post under 80 words with a "
                    "simple call to action to visit the website. Respond with ONLY a JSON array "
                    'of objects: [{"text": "...", "image_hint": "what photo would suit this"}].'
                ),
                messages=[{"role": "user", "content": f"Write {count} posts from these facts:\n" + json.dumps(facts, default=str)}],
            )
        finally:
            client.close()
        if response.stop_reason == "refusal":
            return None
        text = "".join(b.text for b in response.content if b.type == "text").strip()
        start, end = text.find("["), text.rfind("]")
        if start < 0 or end <= start:
            return None
        posts = json.loads(text[start : end + 1])
        clean = [
            {"text": str(p.get("text", ""))[:1000], "image_hint": str(p.get("image_hint", ""))[:200]}
            for p in posts
            if isinstance(p, dict) and p.get("text")
        ]
        return clean or None
    except Exception:  # noqa: BLE001
        return None


def run_social_posts(db: Session, config: dict, *, http_client: httpx.Client | None = None) -> tuple[bool | None, str]:
    recipient = (config.get("recipient") or "").strip()
    webhook = (config.get("webhook_url") or "").strip()
    if not recipient and not webhook:
        return None, "no recipient or webhook_url configured"

    cadence_days = int(config.get("cadence_days", 7) or 7)
    count = max(1, min(int(config.get("posts_per_batch", 3) or 3), 10))

    last = db.scalar(
        select(AuditEvent.occurred_at).where(AuditEvent.kind == SOCIAL_EVENT)
        .order_by(AuditEvent.id.desc()).limit(1)
    )
    if last is not None:
        next_due = last.replace(tzinfo=timezone.utc) + timedelta(days=cadence_days)
        if datetime.now(timezone.utc) < next_due:
            return True, f"next batch due {next_due.date().isoformat()}"

    facts = _grounded_social_facts(db)
    posts = _ai_posts(db, facts, count)
    mode = "ai" if posts else "template"
    if posts is None:
        posts = _template_posts(facts, count)

    delivered = []
    # Webhook delivery (Zapier/Make → Facebook Page).
    if webhook:
        owns = http_client is None
        client = http_client or httpx.Client(timeout=15.0)
        pushed = 0
        try:
            for post in posts:
                try:
                    r = client.post(webhook, json={"kind": "social_post", **post})
                except httpx.HTTPError as exc:
                    return False, f"webhook failed after {pushed} post(s): {exc}"
                if r.status_code >= 400:
                    return False, f"webhook HTTP {r.status_code} after {pushed} post(s)"
                pushed += 1
        finally:
            if owns:
                client.close()
        delivered.append(f"{pushed} to webhook")

    # Email pack delivery.
    if recipient:
        items = "".join(
            f"<li style='margin-bottom:12px'><p>{escape(p['text'])}</p>"
            f"<p style='color:#777;font-size:12px'>Photo idea: {escape(p.get('image_hint', ''))}</p></li>"
            for p in posts
        )
        html = f"<h3>This week's social post pack ({mode})</h3><ol>{items}</ol>"
        try:
            send_email(db, recipient, config.get("subject") or "Your social post pack", html)
            delivered.append("pack emailed")
        except EmailError as exc:
            if not delivered:
                return False, f"SMTP failed: {exc}"
            delivered.append(f"email failed: {exc}")

    record_event(db, SOCIAL_EVENT, data={"count": len(posts), "mode": mode, "delivered": delivered})
    return True, f"{len(posts)} posts ({mode}): " + ", ".join(delivered)
