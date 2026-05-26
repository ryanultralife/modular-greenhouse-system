"""Aggregate orders into a weekly fabrication stock list.

Pure functions: given a list of order snapshots and the catalog, roll up every
SKU across all orders into one build list, split by who fabricates it
(in-house vs. a named co-packer). No database or web concerns here, so this is
fully unit-testable.

Each order snapshot is a dict shaped like:
    {
      "id": 12,
      "model_id": "barn_6_5",
      "bom": [{"sku_id": "base_kit", "name": "...", "quantity": 1}, ...],
    }
"""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass, field


@dataclass
class AggregatedLine:
    model_id: str
    sku_id: str
    name: str
    quantity: int
    fulfillment: str  # "in_house" | "copacker"
    copacker: str | None
    total_weight_lb: float | None  # None if any unit weight is unknown


@dataclass
class StockList:
    order_ids: list[int]
    lines: list[AggregatedLine] = field(default_factory=list)

    @property
    def in_house(self) -> list[AggregatedLine]:
        return [l for l in self.lines if l.fulfillment != "copacker"]

    @property
    def copacker_lines(self) -> list[AggregatedLine]:
        return [l for l in self.lines if l.fulfillment == "copacker"]

    def by_copacker(self) -> dict[str, list[AggregatedLine]]:
        groups: dict[str, list[AggregatedLine]] = OrderedDict()
        for line in self.copacker_lines:
            groups.setdefault(line.copacker or "(unassigned co-packer)", []).append(line)
        return groups


def _sku_meta(catalog_data: dict, model_id: str, sku_id: str) -> dict:
    return (
        catalog_data.get("models", {})
        .get(model_id, {})
        .get("skus", {})
        .get(sku_id, {})
    )


def build_stock_list(orders: list[dict], catalog_data: dict) -> StockList:
    """Roll up all orders' BOM lines into one aggregated stock list."""
    agg: "OrderedDict[tuple[str, str], AggregatedLine]" = OrderedDict()
    order_ids: list[int] = []

    for order in orders:
        if "id" in order:
            order_ids.append(order["id"])
        model_id = order["model_id"]
        for line in order.get("bom", []):
            sku_id = line["sku_id"]
            qty = int(line["quantity"])
            meta = _sku_meta(catalog_data, model_id, sku_id)
            unit_weight = meta.get("weight_lb")
            key = (model_id, sku_id)

            if key not in agg:
                agg[key] = AggregatedLine(
                    model_id=model_id,
                    sku_id=sku_id,
                    name=line.get("name", meta.get("name", sku_id)),
                    quantity=0,
                    fulfillment=meta.get("fulfillment", "in_house"),
                    copacker=meta.get("copacker"),
                    total_weight_lb=0.0,
                )
            entry = agg[key]
            entry.quantity += qty
            if unit_weight is None or entry.total_weight_lb is None:
                entry.total_weight_lb = None  # unknown weight poisons the rollup
            else:
                entry.total_weight_lb = round(entry.total_weight_lb + unit_weight * qty, 1)

    return StockList(order_ids=order_ids, lines=list(agg.values()))
