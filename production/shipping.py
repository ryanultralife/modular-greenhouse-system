"""Build a per-order shipment plan from BOM + catalog weights.

Pure logic, no web/db. ``ready`` is True only when every SKU has a known
weight — that gates an order into the same-day shipping queue, so nothing
ships with an unknown package weight.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ShipmentLine:
    sku_id: str
    name: str
    quantity: int
    unit_weight_lb: float | None
    line_weight_lb: float | None


@dataclass
class ShipmentPlan:
    order_id: int | None
    lines: list[ShipmentLine] = field(default_factory=list)
    total_weight_lb: float | None = None
    weight_complete: bool = False

    @property
    def ready(self) -> bool:
        return self.weight_complete

    @property
    def total_units(self) -> int:
        return sum(l.quantity for l in self.lines)


def _sku_meta(catalog_data: dict, model_id: str, sku_id: str) -> dict:
    return catalog_data.get("models", {}).get(model_id, {}).get("skus", {}).get(sku_id, {})


def build_shipment_plan(order: dict, catalog_data: dict) -> ShipmentPlan:
    model_id = order["model_id"]
    plan = ShipmentPlan(order_id=order.get("id"))
    total = 0.0
    complete = True

    for line in order.get("bom", []):
        sku_id = line["sku_id"]
        qty = int(line["quantity"])
        unit = _sku_meta(catalog_data, model_id, sku_id).get("weight_lb")
        line_weight = None if unit is None else round(unit * qty, 1)
        if unit is None:
            complete = False
        else:
            total += line_weight
        plan.lines.append(
            ShipmentLine(
                sku_id=sku_id,
                name=line.get("name", sku_id),
                quantity=qty,
                unit_weight_lb=unit,
                line_weight_lb=line_weight,
            )
        )

    plan.weight_complete = complete and bool(plan.lines)
    plan.total_weight_lb = round(total, 1) if plan.weight_complete else None
    return plan
