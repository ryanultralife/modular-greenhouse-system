"""Go-live readiness: one endpoint that inspects real state and reports what's
left before the store can take real orders and payments."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from greenhouse import Catalog

from .. import catalog_store, inventory_store, security
from ..db import session_dependency
from ..models_db import Integration, Preset, Setting

router = APIRouter(tags=["setup"])


def _creds(db: Session, provider: str) -> dict | None:
    integ = db.scalar(
        select(Integration).where(Integration.provider == provider, Integration.enabled.is_(True))
    )
    if integ is None:
        return None
    try:
        return security.decrypt_dict(integ.secret_blob)
    except ValueError:
        return {}


def _check(id, label, ok, required, detail, fix):
    return {"id": id, "label": label, "ok": bool(ok), "required": required, "detail": detail, "fix": fix}


@router.get("/setup/status")
def setup_status(db: Session = Depends(session_dependency)):
    checks = []

    stripe = _creds(db, "stripe") or {}
    checks.append(_check(
        "stripe_key", "Stripe payment key", bool(stripe.get("secret_key")), True,
        "Secret key is set." if stripe.get("secret_key") else "No Stripe secret key — card payments can't run.",
        "Integrations tab → Stripe",
    ))
    checks.append(_check(
        "stripe_webhook", "Stripe webhook secret", bool(stripe.get("webhook_secret")), True,
        "Webhook secret is set." if stripe.get("webhook_secret") else "No webhook secret — paid orders won't be confirmed.",
        "Integrations tab → Stripe (+ point a Stripe webhook at /api/stripe/webhook)",
    ))

    presets = db.scalars(select(Preset).where(Preset.active.is_(True))).all()
    buyable = 0
    for p in presets:
        item = inventory_store.get_item(db, p.stock_key)
        if p.verified_price and p.price_usd and item and item.on_hand > 0:
            buyable += 1
    checks.append(_check(
        "presets_buyable", "Buyable presets", buyable > 0, True,
        f"{buyable} preset(s) priced and in stock." if buyable else "No preset is both priced and in stock yet.",
        "Presets tab (set a verified price) + Inventory tab (stock preset:<id>)",
    ))

    catalog = Catalog(catalog_store.load(db))
    unverified = []
    for mid in catalog.model_ids():
        for sid, sku in catalog.model(mid).get("skus", {}).items():
            if not sku.get("verified_price"):
                unverified.append(f"{mid}/{sid}")
    checks.append(_check(
        "catalog_prices", "Configurator prices verified", not unverified, False,
        "All catalog prices verified." if not unverified else f"{len(unverified)} SKU price(s) still unverified — custom quotes will show 'TBD'.",
        "Catalog & Pricing tab",
    ))

    cp = db.get(Setting, "copacker_config")
    cp_val = (cp.value if cp and cp.value else {}) or {}
    checks.append(_check(
        "copacker", "Co-packer contact", bool(cp_val.get("name") or cp_val.get("email")), False,
        "Co-packer contact set." if (cp_val.get("name") or cp_val.get("email")) else "No co-packer contact — replenishment orders won't be addressed/emailed.",
        "Co-packer tab",
    ))

    smtp = _creds(db, "smtp") or {}
    smtp_ok = bool(smtp.get("host") and smtp.get("from_email"))
    checks.append(_check(
        "smtp", "Email (SMTP)", smtp_ok, False,
        "Email is configured." if smtp_ok else "No email configured — confirmations and co-packer orders won't send.",
        "Integrations tab → Email (SMTP)",
    ))

    bom = catalog_store.load(db).get("material_bom", {})
    missing = sum(
        1 for entries in bom.values() if isinstance(entries, list)
        for e in entries if isinstance(e, dict) and e.get("qty") is None
    )
    checks.append(_check(
        "materials", "Material quantities", missing == 0, False,
        "Material quantities entered." if missing == 0 else f"{missing} per-SKU material quantity(ies) still blank — weekly material planning is incomplete.",
        "data/catalog.json material_bom",
    ))

    required_ok = all(c["ok"] for c in checks if c["required"])
    return {"ready": required_ok, "checks": checks}
