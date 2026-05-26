# Modular Greenhouse System

Configuration, bill-of-materials, quoting, and engineering-triage engine for
[Modular Greenhouses](https://www.modulargreenhouses.com) (Reno, NV — Joshua
Smith, patent US 10,426,102).

The idea: take Josh's existing modular parts and let **any** configuration
(straight, L, T, X — any length, in 4′ increments) be assembled, priced, and
triaged for engineering, so quoting and production planning stop being manual.

## Status

Working core engine + CLI + tests. Pure Python 3.11 standard library — nothing
to install.

> **Data honesty:** the engine only uses figures from `data/catalog.json`, and
> every figure is flagged `verified` or placeholder. Verified today: the two
> base-model prices ($899 / $1,699), the 4′ bay increment, and the published
> 130 mph / 6 ft / 10-yr ratings. Everything else (extension/junction prices,
> the configuration limits) is a clearly-marked placeholder for Josh to fill
> in — the code never invents structural numbers or stamps a non-standard
> build as certified. See [`docs/engineering_data.md`](docs/engineering_data.md).

## Quick start

```bash
# List models and shapes
python3 -m greenhouse.cli models

# Quote a 20 ft straight Barn Style build
python3 -m greenhouse.cli quote --model barn_6_5 --shape straight --runs 20

# Quote a T-shaped Raised Bed (main run 16+16 ft, branch 12 ft)
python3 -m greenhouse.cli quote --model raised_bed_4x4 --shape T --runs 16 16 12

# Run the tests
python3 -m unittest discover -s tests
```

## What each part does

| Module | Responsibility |
|--------|----------------|
| `data/catalog.json` | Single source of truth: models, SKUs, prices, engineering limits — each flagged verified vs. placeholder. |
| `greenhouse/catalog.py` | Loads and validates the catalog. |
| `greenhouse/models.py` | Layout geometry: runs, junctions, shape presets (straight/L/T/X). |
| `greenhouse/configurator.py` | Turns a layout into a bill of materials (counts of SKUs). |
| `greenhouse/engineering.py` | Engineering **triage** — standard vs. needs-sign-off. Never certifies. |
| `greenhouse/quote.py` | Prices the BOM; keeps unverified prices out of the subtotal. |
| `greenhouse/cli.py` | Command-line front end. |

## Roadmap

The engine is structured so a thin API/UI layer can sit on top without
touching the core:

- FastAPI service wrapping `configure` / `assess` / `build_quote`
- Web admin UI for catalog editing and quoting
- Shipping/production planning (uses the per-SKU weights once entered)
- Integration with modulargreenhouses.com
