"""The owner copilot — an operations assistant for the admin, grounded on live
business data via tool use.

Deliberately READ-ONLY: it analyzes (sales, build queue, stock, marketing
attribution) and points Josh at the right tab to act. Money-moving and
state-changing actions stay behind their explicit buttons — an assistant that
can silently ship orders or send invoices is a liability, not a feature.

The snapshot builders are plain functions shared with the AI daily digest
automation, so the copilot and the digest can never disagree about the data.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import inventory_store
from .advisor import get_advisor_config
from .audit import record_event
from .models_db import AuditEvent, Automation, CoPackerOrder, Order, Preset

MAX_TOKENS = 1500
MAX_HISTORY_MESSAGES = 30
MAX_MESSAGE_CHARS = 4000
MAX_TOOL_ITERATIONS = 6


class CopilotError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


# ---- shared data builders (used by copilot tools AND the daily digest) ----
def build_business_snapshot(db: Session) -> dict:
    now = datetime.now(timezone.utc)
    week_ago = now - timedelta(days=7)

    orders = db.scalars(select(Order)).all()
    by_status = Counter(o.status for o in orders)
    paid_like = [o for o in orders if o.status in ("paid", "confirmed", "in_production", "shipped")]
    revenue_total = round(sum((o.pricing or {}).get("verified_subtotal_usd") or 0 for o in paid_like), 2)
    leads_this_week = sum(
        1 for o in orders if o.source == "website" and o.created_at and o.created_at.replace(tzinfo=timezone.utc) >= week_ago
    )

    low = inventory_store.low_stock(db)
    pending_cp = db.scalars(
        select(CoPackerOrder).where(CoPackerOrder.status.in_(("draft", "sent")))
    ).all()
    buyable = 0
    for p in db.scalars(select(Preset).where(Preset.active.is_(True))).all():
        item = inventory_store.get_item(db, p.stock_key)
        if p.verified_price and p.price_usd and item and item.on_hand > 0:
            buyable += 1

    return {
        "orders_by_status": dict(by_status),
        "verified_revenue_usd_all_active_orders": revenue_total,
        "website_leads_last_7_days": leads_this_week,
        "buyable_presets": buyable,
        "low_stock_items": [
            {"name": i.name or i.key, "on_hand": i.on_hand, "reorder_point": i.reorder_point, "unit": i.unit}
            for i in low
        ],
        "pending_copacker_orders": [
            {"id": c.id, "copacker": c.copacker, "status": c.status, "trigger": c.trigger} for c in pending_cp
        ],
    }


def build_marketing_insights(db: Session) -> dict:
    orders = db.scalars(select(Order).where(Order.source == "website")).all()
    by_source: Counter = Counter()
    paid_by_source: Counter = Counter()
    for o in orders:
        src = (o.attribution or {}).get("utm_source") or ((o.attribution or {}).get("referrer") and "referral") or "direct"
        by_source[src] += 1
        if o.payment_status == "paid" or o.status in ("paid", "shipped", "in_production", "confirmed"):
            paid_by_source[src] += 1

    day_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    advisor_today = db.scalar(
        select(func.count()).select_from(AuditEvent).where(
            AuditEvent.kind == "advisor.exchange", AuditEvent.occurred_at >= day_start
        )
    ) or 0
    abandoned = db.scalar(
        select(func.count()).select_from(Order).where(Order.status == "pending_payment")
    ) or 0

    automations = [
        {"kind": a.kind, "enabled": a.enabled, "last_run_ok": a.last_run_ok, "last_run_message": a.last_run_message}
        for a in db.scalars(select(Automation)).all()
    ]
    return {
        "website_leads_by_source": dict(by_source),
        "converting_leads_by_source": dict(paid_by_source),
        "advisor_conversations_today": advisor_today,
        "abandoned_checkouts_open": abandoned,
        "automations": automations,
    }


def build_work_summary(db: Session) -> dict:
    # Reuse the exact board the staff sees, so copilot answers match the Today tab.
    from .routers.work import work_board

    return work_board(db)


def list_recent_orders(db: Session, status: str | None = None, limit: int = 15) -> list[dict]:
    stmt = select(Order).order_by(Order.created_at.desc()).limit(max(1, min(int(limit), 50)))
    if status:
        stmt = stmt.where(Order.status == status)
    return [
        {
            "id": o.id,
            "created_at": o.created_at.isoformat() if o.created_at else None,
            "customer": o.customer_name or "—",
            "build": f"{o.model_id} {o.shape} {o.runs}",
            "status": o.status,
            "source": o.source,
            "verified_subtotal_usd": (o.pricing or {}).get("verified_subtotal_usd"),
            "utm_source": (o.attribution or {}).get("utm_source"),
        }
        for o in db.scalars(stmt).all()
    ]


# ---- copilot definition ----
SYSTEM_PROMPT = """\
You are the operations copilot for the owner of Modular Greenhouses (Reno, NV), \
embedded in the company's admin dashboard. You answer questions about sales, \
production, inventory, and marketing using live data from tools.

Hard rules:
1. Every number you state must come from a tool call in this conversation. If \
the data doesn't answer the question, say what's missing — never estimate.
2. You are read-only. You cannot ship orders, send invoices, change prices, or \
edit anything. When the owner should act, name the exact tab (e.g. "Ship it \
from the Today board" / "Enable that on the Marketing tab").
3. Placeholder data is real in this system: unverified prices, missing weights, \
and incomplete material quantities are flagged in the data — surface those \
honestly rather than working around them.

Style: direct and concise. Lead with the answer, then the one or two numbers \
that support it. Suggest a next action when one is obvious."""

TOOLS = [
    {
        "name": "get_business_snapshot",
        "description": (
            "Live business overview: order counts by status, verified revenue across "
            "active orders, website leads this week, buyable presets, low-stock items, "
            "and pending co-packer orders. Call for any 'how are we doing' question."
        ),
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "get_work_board",
        "description": (
            "The same live board staff see: new paid orders, what to build this week "
            "(sections + materials), ready-to-ship orders, restock needs, and next "
            "week's plan. Call for any production/build/ship question."
        ),
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "get_marketing_insights",
        "description": (
            "Marketing funnel data: website leads by traffic source (UTM), which "
            "sources convert, advisor conversations today, open abandoned checkouts, "
            "and the status of each marketing automation. Call for any marketing/"
            "attribution/channel question."
        ),
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "list_recent_orders",
        "description": "Recent orders, newest first, optionally filtered by status. Includes customer, build, subtotal, and traffic source.",
        "input_schema": {
            "type": "object",
            "properties": {
                "status": {
                    "type": "string",
                    "description": "Optional filter: quote, pending_payment, paid, confirmed, in_production, shipped, cancelled",
                },
                "limit": {"type": "integer", "description": "Max rows (default 15, max 50)"},
            },
            "additionalProperties": False,
        },
    },
]


def _execute_tool(db: Session, name: str, args: dict) -> tuple[dict | list, bool]:
    try:
        if name == "get_business_snapshot":
            return build_business_snapshot(db), False
        if name == "get_work_board":
            return build_work_summary(db), False
        if name == "get_marketing_insights":
            return build_marketing_insights(db), False
        if name == "list_recent_orders":
            return list_recent_orders(db, args.get("status"), args.get("limit") or 15), False
        return {"error": f"Unknown tool '{name}'."}, True
    except Exception as exc:  # noqa: BLE001 — surface to the model, don't 500 the chat
        return {"error": f"{exc.__class__.__name__}: {exc}"}, True


def _validate_history(messages: list) -> list[dict]:
    if not isinstance(messages, list) or not messages:
        raise CopilotError("messages must be a non-empty list.")
    clean = []
    for m in messages[-MAX_HISTORY_MESSAGES:]:
        role, content = m.get("role"), m.get("content")
        if role not in ("user", "assistant") or not isinstance(content, str) or not content.strip():
            raise CopilotError("Each message needs role user/assistant and text content.")
        clean.append({"role": role, "content": content[:MAX_MESSAGE_CHARS]})
    if clean[-1]["role"] != "user":
        raise CopilotError("The last message must be from the user.")
    return clean


def run_copilot(db: Session, messages: list, *, username: str = "", client=None) -> dict:
    import json

    import anthropic

    config = get_advisor_config(db)
    if config is None:
        raise CopilotError(
            "The copilot needs an Anthropic API key — add one under Integrations → Anthropic (AI advisor).",
            status=503,
        )

    history = _validate_history(messages)
    owns = client is None
    if client is None:
        client = anthropic.Anthropic(api_key=config["api_key"])

    convo: list = list(history)
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
                raise CopilotError("The Anthropic key is invalid — update it under Integrations.", status=503) from exc
            except anthropic.RateLimitError as exc:
                raise CopilotError("Over Anthropic capacity right now — try again in a minute.", status=429) from exc
            except (anthropic.APIStatusError, anthropic.APIConnectionError) as exc:
                raise CopilotError("The copilot had a hiccup — please try again.", status=502) from exc

            if response.stop_reason == "refusal":
                reply = "I can't help with that one. Ask me about sales, production, inventory, or marketing."
                break

            if response.stop_reason == "tool_use":
                results = []
                for block in response.content:
                    if block.type == "tool_use":
                        result, is_error = _execute_tool(db, block.name, dict(block.input or {}))
                        results.append(
                            {
                                "type": "tool_result",
                                "tool_use_id": block.id,
                                "content": json.dumps(result, default=str),
                                **({"is_error": True} if is_error else {}),
                            }
                        )
                convo.append({"role": "assistant", "content": response.content})
                convo.append({"role": "user", "content": results})
                continue

            reply = "".join(b.text for b in response.content if b.type == "text").strip()
            break
        else:
            reply = "That took more digging than I can do in one go — try a more specific question."
    finally:
        if owns and hasattr(client, "close"):
            client.close()

    if not reply:
        reply = "Sorry — I came back empty. Could you rephrase that?"

    record_event(
        db, "copilot.exchange", actor=f"agent:copilot({username})" if username else "agent:copilot",
        data={"user": history[-1]["content"][:300], "reply": reply[:300]},
    )
    return {"reply": reply}
