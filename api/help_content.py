"""In-app onboarding & reference content.

The single source of truth for the Help tab. Content lives in code so it ships
with each feature — when a PR adds capability, it updates the relevant section
here, and the docs in the running system stay current automatically.

Each section can carry a ``status_fn`` that returns a live snapshot from the DB
(e.g. "3 of 8 prices verified") so the doc reflects the system *right now*, not
a frozen tutorial.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from greenhouse import Catalog

from . import catalog_store
from .models_db import Integration, InventoryItem, Preset, Setting, User


@dataclass
class HelpSection:
    id: str
    title: str
    summary: str
    where: str                            # which tab this lives in
    roles: tuple[str, ...]                # ("owner",) | ("staff",) | ("owner","staff")
    steps: list[str] = field(default_factory=list)
    status_fn: Callable[[Session], dict] | None = None


# ---- status snippets (one cheap query each) ----
def _stripe_status(db: Session) -> dict:
    integ = db.scalar(select(Integration).where(Integration.provider == "stripe", Integration.enabled.is_(True)))
    return {"label": "configured" if integ else "not configured", "ok": bool(integ)}


def _smtp_status(db: Session) -> dict:
    integ = db.scalar(select(Integration).where(Integration.provider == "smtp", Integration.enabled.is_(True)))
    return {"label": "configured" if integ else "not configured", "ok": bool(integ)}


def _presets_status(db: Session) -> dict:
    n = db.scalar(select(func.count()).select_from(Preset).where(Preset.active.is_(True))) or 0
    return {"label": f"{n} active preset(s)", "ok": n > 0}


def _inventory_status(db: Session) -> dict:
    total = db.scalar(select(func.count()).select_from(InventoryItem)) or 0
    low = sum(1 for i in db.scalars(select(InventoryItem)).all() if i.on_hand <= i.reorder_point)
    return {"label": f"tracking {total} item(s), {low} at/below reorder", "ok": total > 0}


def _staff_status(db: Session) -> dict:
    n = db.scalar(select(func.count()).select_from(User).where(User.active.is_(True))) or 0
    return {"label": f"{n} active staff account(s)", "ok": True}


def _copacker_status(db: Session) -> dict:
    row = db.get(Setting, "copacker_config")
    has = bool(row and row.value and (row.value.get("name") or row.value.get("email")))
    return {"label": "contact set" if has else "no contact set", "ok": has}


def _prices_status(db: Session) -> dict:
    catalog = Catalog(catalog_store.load(db))
    total = unverified = 0
    for mid in catalog.model_ids():
        for sku in catalog.model(mid).get("skus", {}).values():
            total += 1
            if not sku.get("verified_price"):
                unverified += 1
    return {"label": f"{total - unverified} of {total} SKU prices verified", "ok": unverified == 0}


SECTIONS: list[HelpSection] = [
    # ---------- both roles ----------
    HelpSection(
        id="overview",
        title="What this system does",
        summary=(
            "One place to take orders, plan the week, manage inventory, ship, and trigger "
            "co-packer builds. The public site at / takes quote requests and direct preset "
            "purchases. The admin at /admin runs operations."
        ),
        where="—",
        roles=("owner", "staff"),
    ),
    HelpSection(
        id="loop",
        title="The daily loop",
        summary="A customer buys a preset → Stripe charges them → stock decrements → a co-packer order auto-fires → staff sees it on Today and ships when ready.",
        where="—",
        roles=("owner", "staff"),
        steps=[
            "Customer pays for a preset on the public site.",
            "Stripe webhook hits us, the order flips to 'paid' and stock drops by 1.",
            "A replacement build order is automatically queued for the co-packer.",
            "Staff sees it on the Today board under New paid → Start build, then Ready to ship → Mark shipped.",
        ],
    ),

    # ---------- staff sections ----------
    HelpSection(
        id="today",
        title="Today board (your home screen)",
        summary="Everything you should work on now. Refreshes when you hit Refresh or switch tabs.",
        where="Today",
        roles=("owner", "staff"),
        steps=[
            "New paid orders → click Start build to move them into production.",
            "Build this week shows the sections to fabricate and the materials to grab.",
            "Ready to ship lists orders with known weights — Mark shipped records carrier + tracking.",
            "Restock flags inventory at or below reorder point and the pending co-packer orders.",
        ],
    ),
    HelpSection(
        id="next_week",
        title="Next week (what's coming)",
        summary="If a fab session is planned for the next 14 days, this shows that session's build + materials. Otherwise it shows confirmed orders waiting to be scheduled.",
        where="Today",
        roles=("owner", "staff"),
    ),
    HelpSection(
        id="staff_scope",
        title="What you can and can't see",
        summary="You see the operational board, inventory, production and shipping. You do NOT see prices, payments, integration keys, or staff accounts — that's intentional, so the work board never leaks money information to the floor.",
        where="—",
        roles=("staff",),
    ),

    # ---------- owner sections ----------
    HelpSection(
        id="go_live",
        title="Go-live checklist",
        summary="The first tab the owner sees. Live red/green status of every step that gates the store going live.",
        where="Go-live",
        roles=("owner",),
        steps=[
            "Work through every required (red) row.",
            "Hit Refresh after each fix.",
            "When the banner turns green, do one real test purchase end to end.",
        ],
    ),
    HelpSection(
        id="prices",
        title="Catalog & pricing",
        summary="Set real per-SKU prices and mark them Verified. Unverified prices show as 'TBD' on public quotes and won't flow into totals — by design, so a wrong number never goes out.",
        where="Catalog & Pricing",
        roles=("owner",),
        status_fn=_prices_status,
        steps=[
            "Open Catalog & Pricing.",
            "For each SKU, enter the real price and tick Verified.",
            "Re-quote from the Configurator tab to confirm subtotals are no longer 'TBD'.",
        ],
    ),
    HelpSection(
        id="presets",
        title="Presets (ready-to-ship products)",
        summary="Pre-configured products customers can buy and pay for online. A preset is buyable only when its price is Verified and it has finished-unit stock > 0.",
        where="Presets",
        roles=("owner",),
        status_fn=_presets_status,
        steps=[
            "Create a preset with name, model, shape, and verified price.",
            "Stock it in the Inventory tab using key 'preset:<id>'.",
            "It will appear in the public 'Ready to ship' section once both are done.",
        ],
    ),
    HelpSection(
        id="inventory",
        title="Inventory (finished units + materials)",
        summary="Stock the system tracks. Each row has a reorder point — items at or below flag on the Today board.",
        where="Inventory",
        roles=("owner",),
        status_fn=_inventory_status,
        steps=[
            "Add a row per material (key like 'frame_tube') and per preset stock (key 'preset:<id>').",
            "Set on-hand and reorder-point.",
            "Materials consumed per SKU are configured in data/catalog.json under material_bom.",
        ],
    ),
    HelpSection(
        id="copacker",
        title="Co-packer",
        summary="When a preset is paid for, a replacement build order is automatically created and (if SMTP is on) emailed to the co-packer contact below.",
        where="Co-packer",
        roles=("owner",),
        status_fn=_copacker_status,
        steps=[
            "Save the co-packer name + email.",
            "Pending replenishments show in the orders list and on the Today board.",
        ],
    ),
    HelpSection(
        id="staff",
        title="Staff accounts",
        summary="Add an employee → they get a login limited to Today, Production, Inventory, and Shipping. They never see pricing, payments, or integration keys.",
        where="Staff",
        roles=("owner",),
        status_fn=_staff_status,
        steps=[
            "Username + a starter password (they can be reset later).",
            "Disable a row to revoke access without losing history.",
        ],
    ),
    HelpSection(
        id="stripe",
        title="Stripe (taking real card payments)",
        summary="Required to accept preset purchases. Webhook secret is required too — without it we refuse to mark orders paid, so nobody can spoof a paid event.",
        where="Integrations → Stripe",
        roles=("owner",),
        status_fn=_stripe_status,
        steps=[
            "Paste your Stripe secret_key.",
            "In Stripe, create a webhook for checkout.session.completed pointing at /api/stripe/webhook.",
            "Paste the resulting whsec_... into webhook_secret.",
        ],
    ),
    HelpSection(
        id="email",
        title="Email (SMTP)",
        summary="Optional. Used to auto-email co-packer orders, send install scheduling links, and order confirmations.",
        where="Integrations → Email (SMTP)",
        roles=("owner",),
        status_fn=_smtp_status,
    ),
]


def overview_for_role(db: Session, role: str) -> dict:
    out = []
    for s in SECTIONS:
        if role not in s.roles:
            continue
        item = {
            "id": s.id,
            "title": s.title,
            "summary": s.summary,
            "where": s.where,
            "steps": s.steps,
        }
        if s.status_fn:
            try:
                item["status"] = s.status_fn(db)
            except Exception as exc:  # noqa: BLE001 — status is decorative; never fail Help
                item["status"] = {"label": f"status unavailable ({exc.__class__.__name__})", "ok": None}
        out.append(item)
    return {"role": role, "sections": out}
