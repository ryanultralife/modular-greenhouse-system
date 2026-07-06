"""The AI greenhouse advisor — a customer-facing assistant grounded on the
pricing/engineering engine via tool use.

Guardrail model (why customers can trust it):
  * Prices and engineering verdicts come ONLY from tools that call the same
    engine as the configurator. Unverified prices arrive as TBD; the system
    prompt forbids inventing numbers, and there are no numbers in the prompt
    to leak.
  * Non-standard layouts carry the engineering sign-off caveat from the
    engine itself.
  * The only write the advisor can perform is submitting a quote request —
    the same action the public website form performs.

Cost/abuse guardrails: capped history, capped reply tokens, per-IP and global
daily exchange caps enforced via the audit-event log.

The Anthropic client is injectable so tests run a scripted fake offline.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from greenhouse import Catalog, CatalogError

from . import catalog_store, inventory_store, security
from .audit import record_event
from .engine_bridge import compute_quote
from .models_db import AuditEvent, Integration, Order, Preset

DEFAULT_MODEL = "claude-opus-4-8"
MAX_TOKENS = 1024
MAX_HISTORY_MESSAGES = 30
MAX_MESSAGE_CHARS = 2000
MAX_TOOL_ITERATIONS = 5
PER_IP_DAILY_CAP = 60
GLOBAL_DAILY_CAP = 400


class AdvisorError(Exception):
    """User-safe advisor failure; `status` maps to the HTTP response."""

    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


# ---- system prompt (STATIC — cacheable; no dynamic content, no prices) ----
SYSTEM_PROMPT = """\
You are the greenhouse advisor for Modular Greenhouses (Reno, NV) — a friendly, \
knowledgeable assistant on the company's website that helps visitors design the \
right modular greenhouse and get a price.

About the product: patented modular greenhouse kits (US patent 10,426,102) built \
from 4-foot sections. Layouts: straight runs, L-shapes, T-shapes, and X/cross — \
all extendable later in 4-ft increments. A section assembles in about two hours \
using a foldable hinge design. Standard straight-run builds are engineered for \
130 mph winds and 6 ft of snow, with a 10-year guarantee.

Hard rules — never break these:
1. NEVER state a price you did not get from a tool in this conversation. If a \
tool reports pricing as incomplete or TBD, say the base price and explain the \
final quote is confirmed when the team follows up. Do not estimate or guess \
missing prices.
2. The published 130 mph / 6 ft ratings apply to STANDARD STRAIGHT runs. When a \
customer wants an L, T, X, or extended layout, always mention that an engineer \
reviews and signs off on custom layouts before those ratings are confirmed for \
their build — the price_configuration tool tells you the engineering status.
3. Do not promise shipping dates, install dates, discounts, or anything else \
not returned by a tool.
4. Stay on topic: greenhouses, growing, and this company's products. For \
anything else, politely say you can only help with greenhouse questions.
5. You may only take one action: submitting a quote request on the customer's \
behalf (with their permission and their email or phone). You cannot place \
orders, take payments, or change anything.

Style: warm, plain language, short replies (2-4 sentences unless walking \
through options). Ask one question at a time. When a visitor shows buying \
interest, offer to send their configuration to the team as a quote request — \
collect a name and an email or phone first."""

# ---- tools (STATIC list — cacheable) ----
TOOLS = [
    {
        "name": "get_catalog_overview",
        "description": (
            "Get the current product catalog: greenhouse models with verified base "
            "prices, available layout shapes with their arm counts, published "
            "engineering ratings, and any ready-to-ship preset products in stock. "
            "Call this before discussing models, prices, or availability."
        ),
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "price_configuration",
        "description": (
            "Price a specific greenhouse configuration using the company's real "
            "pricing engine. Call this whenever the customer describes a size or "
            "layout they want — never estimate a price yourself. Returns the bill "
            "of materials, the verified subtotal, whether pricing is complete, and "
            "the engineering status (standard vs. requires engineer sign-off)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "model": {"type": "string", "description": "Model id from get_catalog_overview, e.g. 'barn_6_5'"},
                "shape": {"type": "string", "description": "Layout: 'straight', 'L', 'T', or 'X'"},
                "runs": {
                    "type": "array",
                    "items": {"type": "number"},
                    "description": "Length in feet of each arm (multiples of 4). straight=1 arm, L=2, T=3, X=4.",
                },
            },
            "required": ["model", "shape", "runs"],
            "additionalProperties": False,
        },
    },
    {
        "name": "submit_quote_request",
        "description": (
            "Submit the customer's configuration to the team as a quote request. "
            "Only call this after the customer agrees and has given a name plus an "
            "email or phone number. This is the only action you can take."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "model": {"type": "string"},
                "shape": {"type": "string"},
                "runs": {"type": "array", "items": {"type": "number"}},
                "name": {"type": "string"},
                "email": {"type": "string"},
                "phone": {"type": "string"},
                "notes": {"type": "string", "description": "Anything else the customer mentioned (site, timeline, questions)"},
            },
            "required": ["model", "shape", "runs", "name"],
            "additionalProperties": False,
        },
    },
]


# ---- credentials ----
def get_advisor_config(db: Session) -> dict | None:
    """API key + options from the 'anthropic' integration, or env fallback."""
    integ = db.scalar(
        select(Integration).where(Integration.provider == "anthropic", Integration.enabled.is_(True))
    )
    if integ is not None:
        creds = security.decrypt_dict(integ.secret_blob)
        if creds.get("api_key"):
            return {"api_key": creds["api_key"], "model": creds.get("model") or DEFAULT_MODEL}
    env_key = os.environ.get("ANTHROPIC_API_KEY")
    if env_key:
        return {"api_key": env_key, "model": os.environ.get("MGS_ADVISOR_MODEL") or DEFAULT_MODEL}
    return None


# ---- tool execution (all grounded on the engine / DB) ----
def _tool_get_catalog_overview(db: Session, _args: dict) -> dict:
    catalog = Catalog(catalog_store.load(db))
    models = []
    for mid in catalog.model_ids():
        m = catalog.model(mid)
        base = m.get("skus", {}).get("base_kit", {})
        models.append(
            {
                "id": mid,
                "name": m["name"],
                "width_ft": m.get("width_ft"),
                "section_length_ft": m.get("bay_length_ft"),
                "verified_base_price_usd": base.get("price_usd") if base.get("verified_price") else None,
            }
        )
    from greenhouse import shape_options

    presets = []
    for p in db.scalars(select(Preset).where(Preset.active.is_(True))).all():
        item = inventory_store.get_item(db, p.stock_key)
        if p.verified_price and p.price_usd and item and item.on_hand > 0:
            presets.append({"name": p.name, "price_usd": p.price_usd, "ships": p.ship_speed})

    env = catalog.engineering_envelope
    return {
        "models": models,
        "shapes": shape_options(),
        "engineering_ratings_standard_straight_runs": {
            "wind_mph": (env.get("wind_mph") or {}).get("value"),
            "snow_depth_ft": (env.get("snow_depth_ft") or {}).get("value"),
            "warranty_years": (env.get("warranty_years") or {}).get("value"),
        },
        "ready_to_ship_now": presets,
        "note": "verified_base_price_usd null means pricing is confirmed on follow-up, not unknown quality",
    }


def _tool_price_configuration(db: Session, args: dict) -> dict:
    runs = [float(r) for r in (args.get("runs") or [])][:8]
    result = compute_quote(catalog_store.load(db), str(args.get("model", "")), str(args.get("shape", "")), runs)
    return {
        "model": result["model_name"],
        "shape": result["shape"],
        "runs_ft": result["runs"],
        "total_sections": result["total_bays"],
        "footprint_sqft": result["footprint_sqft"],
        "bill_of_materials": result["bom"],
        "verified_subtotal_usd": result["verified_subtotal_usd"],
        "pricing_complete": result["quote_complete"],
        "engineering_status": result["engineering"]["status"],
        "engineering_disclaimer": result["engineering"]["disclaimer"],
    }


def _tool_submit_quote_request(db: Session, args: dict, attribution: dict) -> dict:
    email = str(args.get("email") or "")[:200]
    phone = str(args.get("phone") or "")[:40]
    if not (email or phone):
        return {"ok": False, "error": "Need an email or phone number before submitting."}
    runs = [float(r) for r in (args.get("runs") or [])][:8]
    result = compute_quote(catalog_store.load(db), str(args.get("model", "")), str(args.get("shape", "")), runs)
    order = Order(
        customer_name=str(args.get("name") or "")[:200],
        customer_email=email,
        source="website",
        contact={"email": email, "phone": phone, "message": str(args.get("notes") or "")[:2000], "via": "advisor"},
        model_id=result["model_id"],
        shape=result["shape"],
        runs=result["runs"],
        status="quote",
        bom=result["bom"],
        quote_lines=result["quote_lines"],
        pricing=result["pricing"],
        engineering=result["engineering"],
        attribution=attribution or {},
    )
    db.add(order)
    db.commit()
    record_event(
        db, "lead.created", entity_type="order", entity_id=order.id, actor="agent:advisor",
        data={"email": email, "phone": phone, "attribution": attribution or {}, "source": "website"},
    )
    return {"ok": True, "quote_request_id": order.id, "message": "Submitted — the team will follow up."}


def _execute_tool(db: Session, name: str, args: dict, attribution: dict) -> tuple[dict, bool]:
    """Returns (result, is_error)."""
    try:
        if name == "get_catalog_overview":
            return _tool_get_catalog_overview(db, args), False
        if name == "price_configuration":
            return _tool_price_configuration(db, args), False
        if name == "submit_quote_request":
            return _tool_submit_quote_request(db, args, attribution), False
        return {"error": f"Unknown tool '{name}'."}, True
    except (CatalogError, ValueError) as exc:
        return {"error": str(exc)}, True


# ---- rate limiting via the event log ----
def _check_rate_limits(db: Session, ip: str) -> None:
    day_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    total_today = db.scalar(
        select(func.count()).select_from(AuditEvent).where(
            AuditEvent.kind == "advisor.exchange", AuditEvent.occurred_at >= day_start
        )
    ) or 0
    if total_today >= GLOBAL_DAILY_CAP:
        raise AdvisorError("The advisor is very busy today — please use the configurator or the quote form instead.", status=429)
    if ip:
        events = db.scalars(
            select(AuditEvent).where(
                AuditEvent.kind == "advisor.exchange", AuditEvent.occurred_at >= day_start
            )
        ).all()
        mine = sum(1 for e in events if (e.data or {}).get("ip") == ip)
        if mine >= PER_IP_DAILY_CAP:
            raise AdvisorError("You've reached today's chat limit — please use the quote form and the team will follow up.", status=429)


# ---- validation ----
def _validate_history(messages: list) -> list[dict]:
    if not isinstance(messages, list) or not messages:
        raise AdvisorError("messages must be a non-empty list.")
    clean: list[dict] = []
    for m in messages[-MAX_HISTORY_MESSAGES:]:
        role = m.get("role")
        content = m.get("content")
        if role not in ("user", "assistant") or not isinstance(content, str) or not content.strip():
            raise AdvisorError("Each message needs role user/assistant and text content.")
        clean.append({"role": role, "content": content[:MAX_MESSAGE_CHARS]})
    if clean[-1]["role"] != "user":
        raise AdvisorError("The last message must be from the user.")
    return clean


# ---- the main loop ----
def run_advisor(
    db: Session,
    messages: list,
    *,
    attribution: dict | None = None,
    ip: str = "",
    client=None,
) -> dict:
    import anthropic

    config = get_advisor_config(db)
    if config is None:
        raise AdvisorError(
            "The advisor isn't available right now — please use the configurator or quote form.",
            status=503,
        )

    _check_rate_limits(db, ip)
    history = _validate_history(messages)
    user_text = history[-1]["content"]

    owns = client is None
    if client is None:
        client = anthropic.Anthropic(api_key=config["api_key"])

    convo: list = list(history)
    lead_captured = False
    reply = ""
    try:
        for _ in range(MAX_TOOL_ITERATIONS):
            try:
                response = client.messages.create(
                    model=config["model"],
                    max_tokens=MAX_TOKENS,
                    thinking={"type": "adaptive"},
                    output_config={"effort": "medium"},
                    system=[{"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}],
                    tools=TOOLS,
                    messages=convo,
                )
            except anthropic.AuthenticationError as exc:
                raise AdvisorError("The advisor is misconfigured (invalid API key) — the site owner has been notified via the event log.", status=503) from exc
            except anthropic.RateLimitError as exc:
                raise AdvisorError("The advisor is momentarily over capacity — please try again in a minute.", status=429) from exc
            except (anthropic.APIStatusError, anthropic.APIConnectionError) as exc:
                raise AdvisorError("The advisor had a hiccup — please try again.", status=502) from exc

            if response.stop_reason == "refusal":
                reply = "I can't help with that — but I'm happy to answer anything about our greenhouses!"
                break

            if response.stop_reason == "tool_use":
                tool_results = []
                for block in response.content:
                    if block.type == "tool_use":
                        result, is_error = _execute_tool(db, block.name, dict(block.input or {}), attribution or {})
                        if block.name == "submit_quote_request" and not is_error and result.get("ok"):
                            lead_captured = True
                        import json as _json

                        tool_results.append(
                            {
                                "type": "tool_result",
                                "tool_use_id": block.id,
                                "content": _json.dumps(result),
                                **({"is_error": True} if is_error else {}),
                            }
                        )
                convo.append({"role": "assistant", "content": response.content})
                convo.append({"role": "user", "content": tool_results})
                continue

            # end_turn (or max_tokens): extract the text and finish.
            reply = "".join(b.text for b in response.content if b.type == "text").strip()
            break
        else:
            reply = reply or "Let me hand this to the team — please use the quote form and we'll follow up directly."
    finally:
        if owns and hasattr(client, "close"):
            client.close()

    if not reply:
        reply = "Sorry — I lost my train of thought. Could you rephrase that?"

    record_event(
        db, "advisor.exchange", entity_type="", entity_id=None, actor="agent:advisor",
        data={"ip": ip, "user": user_text[:300], "reply": reply[:300], "lead_captured": lead_captured},
    )
    return {"reply": reply, "lead_captured": lead_captured}
