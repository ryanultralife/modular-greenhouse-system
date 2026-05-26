"""Read/write access to data/catalog.json for the admin UI.

The engine (greenhouse.Catalog) reads this same file, so any edit made here is
picked up by the next quote. Writes are atomic (temp file + replace) and the
JSON is validated before it replaces the live file.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from greenhouse.catalog import DEFAULT_CATALOG_PATH


def load() -> dict[str, Any]:
    return json.loads(Path(DEFAULT_CATALOG_PATH).read_text())


def _atomic_write(data: dict[str, Any]) -> None:
    path = Path(DEFAULT_CATALOG_PATH)
    text = json.dumps(data, indent=2)
    json.loads(text)  # validate round-trip before touching the live file
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".json.tmp")
    try:
        with os.fdopen(fd, "w") as fh:
            fh.write(text)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


def update_sku(model_id: str, sku_id: str, fields: dict[str, Any]) -> dict[str, Any]:
    """Update mutable fields on a SKU. Returns the updated SKU."""
    data = load()
    models = data.get("models", {})
    if model_id not in models:
        raise KeyError(f"Unknown model '{model_id}'")
    skus = models[model_id].get("skus", {})
    if sku_id not in skus:
        raise KeyError(f"Unknown SKU '{sku_id}' on model '{model_id}'")

    sku = skus[sku_id]
    allowed = {"price_usd", "verified_price", "weight_lb", "fulfillment", "copacker"}
    for key, value in fields.items():
        if key not in allowed:
            raise KeyError(f"Field '{key}' is not editable on a SKU")
        sku[key] = value

    _atomic_write(data)
    return sku


def update_limit(key: str, value: Any, verified: bool) -> dict[str, Any]:
    """Set a configuration limit's value and verified flag."""
    data = load()
    limits = data.setdefault("configuration_limits", {})
    entry = limits.get(key)
    if not isinstance(entry, dict):
        raise KeyError(f"Unknown configuration limit '{key}'")
    entry["value"] = value
    entry["verified"] = bool(verified)
    _atomic_write(data)
    return entry
