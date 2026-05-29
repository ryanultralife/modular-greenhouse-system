"""Public, website-facing endpoints for modulargreenhouses.com.

Read-only configurator + a quote-request that lands as a lead order
(source="website", status="quote"). No admin capabilities are exposed here.
"""

from __future__ import annotations

import os

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from greenhouse import Catalog, CatalogError, shape_options

from .. import catalog_store, checkout as checkout_svc, inventory_store
from ..checkout import CheckoutError
from ..db import session_dependency
from ..engine_bridge import compute_quote
from ..models_db import Order, Preset
from ..schemas import QuoteRequest

router = APIRouter(prefix="/public", tags=["public"])


class PresetCheckoutRequest(BaseModel):
    preset_id: int
    name: str = ""
    email: str = ""


class QuoteRequestPublic(QuoteRequest):
    name: str = ""
    email: str = ""
    phone: str = ""
    message: str = ""


@router.get("/models")
def public_models(db: Session = Depends(session_dependency)):
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
                "bay_length_ft": m.get("bay_length_ft"),
                "base_price_usd": base.get("price_usd") if base.get("verified_price") else None,
            }
        )
    env = catalog.engineering_envelope
    return {
        "company": {
            "name": catalog.company.get("name"),
            "location": catalog.company.get("location"),
            "website": catalog.company.get("website"),
        },
        "envelope": {
            "wind_mph": (env.get("wind_mph") or {}).get("value"),
            "snow_depth_ft": (env.get("snow_depth_ft") or {}).get("value"),
            "warranty_years": (env.get("warranty_years") or {}).get("value"),
        },
        "models": models,
        "shapes": shape_options(),
    }


@router.post("/quote")
def public_quote(req: QuoteRequest, db: Session = Depends(session_dependency)):
    """Read-only price/engineering preview for a website visitor."""
    try:
        result = compute_quote(catalog_store.load(db), req.model, req.shape, req.runs)
    except (CatalogError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    # Trim internals the public page doesn't need.
    return {
        "model_name": result["model_name"],
        "shape": result["shape"],
        "runs": result["runs"],
        "total_bays": result["total_bays"],
        "footprint_sqft": result["footprint_sqft"],
        "bom": result["bom"],
        "verified_subtotal_usd": result["verified_subtotal_usd"],
        "quote_complete": result["quote_complete"],
        "engineering_status": result["engineering"]["status"],
    }


@router.post("/quote-request", status_code=201)
def public_quote_request(req: QuoteRequestPublic, db: Session = Depends(session_dependency)):
    """Visitor submits a configuration; it lands as a lead order for Josh."""
    if not (req.email or req.phone):
        raise HTTPException(status_code=400, detail="Please provide an email or phone number.")
    try:
        result = compute_quote(catalog_store.load(db), req.model, req.shape, req.runs)
    except (CatalogError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    order = Order(
        customer_name=req.name,
        customer_email=req.email,
        source="website",
        contact={"email": req.email, "phone": req.phone, "message": req.message},
        model_id=result["model_id"],
        shape=result["shape"],
        runs=result["runs"],
        status="quote",
        bom=result["bom"],
        quote_lines=result["quote_lines"],
        pricing=result["pricing"],
        engineering=result["engineering"],
    )
    db.add(order)
    db.commit()
    return {
        "ok": True,
        "order_id": order.id,
        "model_name": result["model_name"],
        "total_bays": result["total_bays"],
        "message": "Thanks! Your request was received. We'll follow up shortly.",
    }


@router.get("/presets")
def public_presets(db: Session = Depends(session_dependency)):
    presets = db.scalars(select(Preset).where(Preset.active.is_(True))).all()
    out = []
    for p in presets:
        item = inventory_store.get_item(db, p.stock_key)
        in_stock = bool(item and item.on_hand > 0)
        priced = bool(p.verified_price and p.price_usd)
        out.append(
            {
                "id": p.id,
                "name": p.name,
                "description": p.description,
                "price_usd": p.price_usd if priced else None,
                "ship_speed": p.ship_speed,
                "image_url": p.image_url,
                "in_stock": in_stock,
                "buyable": in_stock and priced,
            }
        )
    return {"presets": out}


@router.post("/checkout")
def public_checkout(
    req: PresetCheckoutRequest, request: Request, db: Session = Depends(session_dependency)
):
    preset = db.get(Preset, req.preset_id)
    if preset is None:
        raise HTTPException(status_code=404, detail="Product not found")
    base = os.environ.get("MGS_PUBLIC_URL") or str(request.base_url).rstrip("/")
    try:
        return checkout_svc.create_checkout_for_preset(
            db, preset, name=req.name, email=req.email, base_url=base
        )
    except CheckoutError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
