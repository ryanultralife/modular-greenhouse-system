"""Price a configuration from its bill of materials.

A line is only added to the verified subtotal when its SKU has a real,
verified price. Lines whose price is still a placeholder are listed
separately as "price TBD" so a quote is never silently wrong.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .catalog import Catalog
from .configurator import Configuration


@dataclass(frozen=True)
class QuoteLine:
    sku_id: str
    name: str
    quantity: int
    unit_price_usd: float | None
    verified_price: bool

    @property
    def extended_usd(self) -> float | None:
        if self.unit_price_usd is None:
            return None
        return round(self.unit_price_usd * self.quantity, 2)


@dataclass
class Quote:
    model_name: str
    lines: list[QuoteLine] = field(default_factory=list)

    @property
    def verified_subtotal_usd(self) -> float:
        return round(
            sum(
                ln.extended_usd
                for ln in self.lines
                if ln.verified_price and ln.extended_usd is not None
            ),
            2,
        )

    @property
    def tbd_lines(self) -> list[QuoteLine]:
        return [ln for ln in self.lines if not ln.verified_price or ln.unit_price_usd is None]

    @property
    def is_complete(self) -> bool:
        """True when every line has a verified price (quote is final)."""
        return not self.tbd_lines


def build_quote(catalog: Catalog, config: Configuration) -> Quote:
    quote = Quote(model_name=config.model_name)
    for line in config.bom:
        sku = catalog.sku(config.model_id, line.sku_id)
        quote.lines.append(
            QuoteLine(
                sku_id=line.sku_id,
                name=line.name,
                quantity=line.quantity,
                unit_price_usd=sku.get("price_usd"),
                verified_price=bool(sku.get("verified_price", False)),
            )
        )
    return quote
