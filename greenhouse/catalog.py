"""Load and access the modular parts catalog.

The catalog (data/catalog.json) is the single source of truth for models,
SKUs, prices, and engineering limits. Every numeric figure carries a
``verified`` / ``verified_price`` flag so the rest of the system can tell
real, signed-off data apart from placeholders that still need Josh's input.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

DEFAULT_CATALOG_PATH = Path(__file__).resolve().parents[1] / "data" / "catalog.json"


class CatalogError(Exception):
    """Raised when the catalog is missing, malformed, or queried wrongly."""


class Catalog:
    def __init__(self, data: dict[str, Any]):
        self._data = data

    @classmethod
    def load(cls, path: str | Path | None = None) -> "Catalog":
        path = Path(path) if path else DEFAULT_CATALOG_PATH
        if not path.exists():
            raise CatalogError(f"Catalog file not found: {path}")
        try:
            data = json.loads(path.read_text())
        except json.JSONDecodeError as exc:
            raise CatalogError(f"Catalog is not valid JSON: {exc}") from exc
        return cls(data)

    @property
    def schema_version(self) -> str:
        return self._data.get("schema_version", "unknown")

    @property
    def company(self) -> dict[str, Any]:
        return self._data.get("company", {})

    @property
    def engineering_envelope(self) -> dict[str, Any]:
        return self._data.get("engineering_envelope", {})

    @property
    def configuration_limits(self) -> dict[str, Any]:
        return self._data.get("configuration_limits", {})

    @property
    def accessories(self) -> dict[str, Any]:
        return self._data.get("accessories", {})

    def model_ids(self) -> list[str]:
        return list(self._data.get("models", {}).keys())

    def model(self, model_id: str) -> dict[str, Any]:
        models = self._data.get("models", {})
        if model_id not in models:
            raise CatalogError(
                f"Unknown model '{model_id}'. Available: {', '.join(models) or '(none)'}"
            )
        return models[model_id]

    def sku(self, model_id: str, sku_id: str) -> dict[str, Any]:
        skus = self.model(model_id).get("skus", {})
        if sku_id not in skus:
            raise CatalogError(
                f"Model '{model_id}' has no SKU '{sku_id}'. "
                f"Available: {', '.join(skus) or '(none)'}"
            )
        return skus[sku_id]
