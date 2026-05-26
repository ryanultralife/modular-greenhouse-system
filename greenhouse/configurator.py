"""Turn a Layout into a concrete bill of materials (counts of SKUs).

The accounting rule, kept deliberately simple and auditable:

  total_bays      = round(total_linear_ft / bay_length)
  base_kit        = 1            (provides base_bays + base_end_caps)
  extension_module= total_bays - base_bays           (floored at 0)
  end_caps (extra)= open_ends   - base_end_caps       (floored at 0)
  junction_kit    = one per junction in the layout

Everything here is geometry/counting only. Whether the result is structurally
sound is decided separately in engineering.py.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from .catalog import Catalog
from .models import Layout


@dataclass(frozen=True)
class BomLine:
    sku_id: str
    name: str
    quantity: int


@dataclass(frozen=True)
class Configuration:
    model_id: str
    model_name: str
    layout: Layout
    total_bays: int
    open_ends: int
    bom: tuple[BomLine, ...]


def configure(catalog: Catalog, model_id: str, layout: Layout) -> Configuration:
    model = catalog.model(model_id)
    bay_length = model["bay_length_ft"]
    base_bays = model.get("base_bays", 1)
    base_end_caps = model.get("base_end_caps", 2)

    total_bays = max(base_bays, round(layout.total_linear_ft / bay_length))
    extension_modules = max(0, total_bays - base_bays)
    extra_end_caps = max(0, layout.open_ends - base_end_caps)
    junction_kits = len(layout.junctions)

    lines: list[BomLine] = [
        BomLine("base_kit", catalog.sku(model_id, "base_kit")["name"], 1)
    ]
    if extension_modules:
        lines.append(
            BomLine(
                "extension_module",
                catalog.sku(model_id, "extension_module")["name"],
                extension_modules,
            )
        )
    if extra_end_caps:
        lines.append(
            BomLine("end_cap", catalog.sku(model_id, "end_cap")["name"], extra_end_caps)
        )
    if junction_kits:
        lines.append(
            BomLine(
                "junction_kit",
                catalog.sku(model_id, "junction_kit")["name"],
                junction_kits,
            )
        )

    return Configuration(
        model_id=model_id,
        model_name=model["name"],
        layout=layout,
        total_bays=total_bays,
        open_ends=layout.open_ends,
        bom=tuple(lines),
    )


def footprint_sqft(catalog: Catalog, config: Configuration) -> float:
    """Approximate enclosed footprint in square feet."""
    width = catalog.model(config.model_id)["width_ft"]
    return round(config.layout.total_linear_ft * width, 1)
