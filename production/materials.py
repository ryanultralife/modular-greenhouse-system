"""Compute raw-material needs for a set of orders from the per-SKU material BOM.

Pure logic. For each order, every BOM line (sku_id x quantity) is expanded via
catalog ``material_bom`` into material quantities, then summed across orders.

If any consumed SKU has a placeholder (null) material quantity, the result is
flagged ``complete=False`` so the plan is never mistaken for real numbers.
"""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass, field


@dataclass
class MaterialNeed:
    material_id: str
    name: str
    unit: str
    quantity: float
    complete: bool  # False if any contributing per-SKU qty was a placeholder


@dataclass
class MaterialPlan:
    order_ids: list[int]
    needs: list[MaterialNeed] = field(default_factory=list)
    complete: bool = True  # False if any need has unknown (placeholder) data


def compute_material_needs(orders: list[dict], catalog_data: dict) -> MaterialPlan:
    materials = catalog_data.get("materials", {})
    bom = catalog_data.get("material_bom", {})

    agg: "OrderedDict[str, MaterialNeed]" = OrderedDict()
    order_ids: list[int] = []
    plan_complete = True

    for order in orders:
        if "id" in order:
            order_ids.append(order["id"])
        for line in order.get("bom", []):
            sku_id = line["sku_id"]
            sku_qty = int(line["quantity"])
            for entry in bom.get(sku_id, []):
                mat_id = entry["material"]
                per = entry.get("qty")
                meta = materials.get(mat_id, {})
                if mat_id not in agg:
                    agg[mat_id] = MaterialNeed(
                        material_id=mat_id,
                        name=meta.get("name", mat_id),
                        unit=meta.get("unit", "each"),
                        quantity=0.0,
                        complete=True,
                    )
                need = agg[mat_id]
                if per is None:
                    need.complete = False
                    plan_complete = False
                else:
                    need.quantity = round(need.quantity + per * sku_qty, 3)

    return MaterialPlan(order_ids=order_ids, needs=list(agg.values()), complete=plan_complete)
