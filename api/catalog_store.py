"""Catalog access with DB-backed overrides (serverless-safe).

The bundled ``data/catalog.json`` is the read-only SEED. Edits made in the
admin UI are stored as overrides in the ``settings`` table and deep-merged over
the seed at read time. Nothing is written to the filesystem, so this works on a
read-only serverless filesystem (Vercel) as well as locally.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from greenhouse.catalog import DEFAULT_CATALOG_PATH

from .models_db import Setting

OVERRIDES_KEY = "catalog_overrides"
_EDITABLE_SKU_FIELDS = {"price_usd", "verified_price", "weight_lb", "fulfillment", "copacker"}


def _seed() -> dict[str, Any]:
    return json.loads(Path(DEFAULT_CATALOG_PATH).read_text())


def _deep_merge(base: dict, override: dict) -> dict:
    out = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = copy.deepcopy(value)
    return out


def _get_overrides(db: Session) -> dict:
    row = db.get(Setting, OVERRIDES_KEY)
    return copy.deepcopy(row.value) if row and row.value else {}


def _save_overrides(db: Session, overrides: dict) -> None:
    row = db.get(Setting, OVERRIDES_KEY)
    if row is None:
        db.add(Setting(key=OVERRIDES_KEY, value=overrides))
    else:
        row.value = overrides  # reassign so SQLAlchemy detects the change
    db.commit()


def load(db: Session) -> dict[str, Any]:
    """Seed catalog deep-merged with any saved overrides."""
    return _deep_merge(_seed(), _get_overrides(db))


def update_sku(db: Session, model_id: str, sku_id: str, fields: dict[str, Any]) -> dict[str, Any]:
    seed = _seed()
    models = seed.get("models", {})
    if model_id not in models:
        raise KeyError(f"Unknown model '{model_id}'")
    if sku_id not in models[model_id].get("skus", {}):
        raise KeyError(f"Unknown SKU '{sku_id}' on model '{model_id}'")
    for key in fields:
        if key not in _EDITABLE_SKU_FIELDS:
            raise KeyError(f"Field '{key}' is not editable on a SKU")

    overrides = _get_overrides(db)
    sku_ov = (
        overrides.setdefault("models", {})
        .setdefault(model_id, {})
        .setdefault("skus", {})
        .setdefault(sku_id, {})
    )
    sku_ov.update(fields)
    _save_overrides(db, overrides)
    return _deep_merge(seed, overrides)["models"][model_id]["skus"][sku_id]


def update_limit(db: Session, key: str, value: Any, verified: bool) -> dict[str, Any]:
    seed = _seed()
    if key not in seed.get("configuration_limits", {}):
        raise KeyError(f"Unknown configuration limit '{key}'")
    overrides = _get_overrides(db)
    entry = {"value": value, "verified": bool(verified)}
    overrides.setdefault("configuration_limits", {})[key] = entry
    _save_overrides(db, overrides)
    return entry
