"""Adapter between the pure engine (greenhouse package) and the API layer."""

from __future__ import annotations

from greenhouse import Catalog, assess, build_layout, build_quote, configure
from greenhouse.configurator import footprint_sqft
from greenhouse.engineering import REQUIRES_SIGNOFF


def compute_quote(catalog_data: dict, model: str, shape: str, runs: list[float]) -> dict:
    """Run the engine and return a fully serialized quote payload.

    ``catalog_data`` is the merged (seed + overrides) catalog from catalog_store.
    """
    catalog = Catalog(catalog_data)
    layout = build_layout(shape, runs)
    config = configure(catalog, model, layout)
    check = assess(catalog, config)
    quote = build_quote(catalog, config)

    bom = [
        {"sku_id": l.sku_id, "name": l.name, "quantity": l.quantity}
        for l in config.bom
    ]
    quote_lines = [
        {
            "sku_id": l.sku_id,
            "name": l.name,
            "quantity": l.quantity,
            "unit_price_usd": l.unit_price_usd,
            "verified_price": l.verified_price,
            "extended_usd": l.extended_usd,
        }
        for l in quote.lines
    ]
    engineering = {
        "status": check.status,
        "reasons": check.reasons,
        "requires_signoff": check.status == REQUIRES_SIGNOFF,
        "used_placeholder_limits": check.used_placeholder_limits,
        "disclaimer": check.disclaimer,
    }
    pricing = {
        "verified_subtotal_usd": quote.verified_subtotal_usd,
        "quote_complete": quote.is_complete,
    }

    return {
        "model_id": config.model_id,
        "model_name": config.model_name,
        "shape": layout.shape,
        "runs": [r.length_ft for r in layout.runs],
        "total_bays": config.total_bays,
        "footprint_sqft": footprint_sqft(catalog, config),
        "bom": bom,
        "quote_lines": quote_lines,
        "verified_subtotal_usd": quote.verified_subtotal_usd,
        "quote_complete": quote.is_complete,
        "engineering": engineering,
        "pricing": pricing,
    }
