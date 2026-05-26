"""Command-line interface for the configurator.

Examples:
    python3 -m greenhouse.cli models
    python3 -m greenhouse.cli quote --model barn_6_5 --shape straight --runs 20
    python3 -m greenhouse.cli quote --model raised_bed_4x4 --shape T --runs 16 16 12
"""

from __future__ import annotations

import argparse
import sys

from .catalog import Catalog, CatalogError
from .configurator import configure, footprint_sqft
from .engineering import assess
from .models import SHAPE_RUN_COUNTS, build_layout
from .quote import build_quote


def _fmt_usd(value: float | None) -> str:
    return f"${value:,.2f}" if value is not None else "TBD"


def cmd_models(catalog: Catalog) -> int:
    print(f"{catalog.company.get('name', 'Catalog')} — available models:\n")
    for mid in catalog.model_ids():
        m = catalog.model(mid)
        print(f"  {mid:<16} {m['name']}  ({m['width_ft']} ft wide, {m['bay_length_ft']} ft bays)")
    print("\nShapes:", ", ".join(f"{s} ({n} run)" for s, n in SHAPE_RUN_COUNTS.items()))
    return 0


def cmd_quote(catalog: Catalog, args: argparse.Namespace) -> int:
    layout = build_layout(args.shape, args.runs)
    config = configure(catalog, args.model, layout)
    check = assess(catalog, config)
    quote = build_quote(catalog, config)

    print(f"\n=== {config.model_name} — {layout.shape} ===")
    print(
        f"Runs: {', '.join(f'{r.length_ft:g}ft' for r in layout.runs)}"
        f"  |  Total {layout.total_linear_ft:g} ft"
        f"  |  Bays {config.total_bays}"
        f"  |  Footprint ~{footprint_sqft(catalog, config):g} sqft"
    )

    print("\nBill of materials:")
    for line in config.bom:
        print(f"  {line.quantity:>3} x  {line.name}")

    print("\nQuote:")
    for ln in quote.lines:
        unit = _fmt_usd(ln.unit_price_usd)
        ext = _fmt_usd(ln.extended_usd)
        flag = "" if ln.verified_price and ln.unit_price_usd is not None else "  <- price not verified"
        print(f"  {ln.quantity:>3} x {ln.name:<48} {unit:>12} = {ext:>12}{flag}")
    print(f"\n  Verified subtotal: {_fmt_usd(quote.verified_subtotal_usd)}")
    if not quote.is_complete:
        n = len(quote.tbd_lines)
        print(f"  NOTE: {n} line(s) have no verified price. Quote is NOT final until those are set in the catalog.")

    print(f"\nEngineering triage: {check.status}")
    for r in check.reasons:
        print(f"  - {r}")
    if not check.ok_without_signoff:
        print("  ** This configuration requires engineer sign-off before the published ratings apply. **")
    print(f"\n  {check.disclaimer}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="greenhouse", description="Modular greenhouse configurator")
    p.add_argument("--catalog", help="Path to catalog.json (default: bundled data/catalog.json)")
    sub = p.add_subparsers(dest="command", required=True)

    sub.add_parser("models", help="List available models and shapes")

    q = sub.add_parser("quote", help="Configure a build and produce BOM + quote + engineering triage")
    q.add_argument("--model", required=True, help="Model id (see 'models')")
    q.add_argument("--shape", required=True, choices=list(SHAPE_RUN_COUNTS), help="Layout shape")
    q.add_argument(
        "--runs",
        required=True,
        nargs="+",
        type=float,
        metavar="FT",
        help="Run length(s) in feet; count must match the shape",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        catalog = Catalog.load(args.catalog)
        if args.command == "models":
            return cmd_models(catalog)
        if args.command == "quote":
            return cmd_quote(catalog, args)
    except (CatalogError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
