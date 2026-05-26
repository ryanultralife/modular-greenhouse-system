# Modular Greenhouse System

Self-serve operations suite for [Modular Greenhouses](https://www.modulargreenhouses.com)
(Reno, NV — Joshua Smith, patent US 10,426,102): configure any greenhouse from
the modular parts, quote it, take orders, plan the weekly fabrication build
(including co-packer handoff), and manage third-party integrations — all from
one admin UI backed by a single database. No developer needed for day-to-day
operation.

## What it does

| Area | Capability |
|------|-----------|
| **Configurator** | Assemble any layout (straight / L / T / X, 4′ increments) from the modular catalog. |
| **Quoting** | Bill of materials + price. Unverified prices are flagged and kept out of the total. |
| **Engineering triage** | Straight runs = `STANDARD`; non-standard layouts = `PRELIMINARY_OK` within verified limits, else `REQUIRES_ENGINEER_SIGNOFF`. Never auto-certifies. |
| **Orders** | Save quotes as orders with a status lifecycle (quote → confirmed → in_production → shipped). |
| **Production** | Group orders into a weekly fabrication session; auto-generate the aggregated stock/build list, split into in-house vs. each co-packer. |
| **Catalog & pricing** | Edit prices, weights, verified flags, and co-packer assignment in the browser — written straight to the catalog. |
| **Integrations** | Josh adds his own Stripe / Calendly / QuickBooks / custom API keys in the UI. Keys are **encrypted at rest** and validated with a read-only test call. |

## Run it

```bash
./scripts/run.sh           # installs deps, starts the server
# then open http://127.0.0.1:8000/
```

Or manually:

```bash
python3 -m pip install -r requirements.txt
python3 -m uvicorn api.app:app --reload
```

The CLI from the core engine still works standalone:

```bash
python3 -m greenhouse.cli quote --model barn_6_5 --shape straight --runs 20
```

## Architecture

```
greenhouse/      Pure engine: catalog, layout geometry, configurator, engineering, quoting, CLI
production/      Pure planner: aggregate orders -> weekly stock list + co-packer split
api/             FastAPI backend (single source of truth, SQLite)
  routers/         quotes, orders, catalog, production, integrations
  security.py      Fernet encryption for integration secrets
  integrations_providers.py  Stripe/Calendly/QuickBooks/custom adapters + connection tests
ui/              Static admin UI (vanilla HTML/JS, no build step)
data/            catalog.json (tracked) + app.db / .secret_key (git-ignored)
tests/           34 tests (engine, planner, security, full API)
```

The engine and planner have **no** web or database dependencies, so they stay
fully unit-testable. The API is a thin layer over them; the UI is a thin layer
over the API.

## Data & security model

- `data/catalog.json` is the single source of truth for products, prices, and
  engineering limits. Every figure is flagged **verified** vs **placeholder**.
  See [`docs/engineering_data.md`](docs/engineering_data.md).
- **Verified today:** base-model prices ($899 / $1,699), 4′ bay increment, the
  published 130 mph / 6 ft / 10-yr ratings.
- **Placeholders Josh fills in (now via the Catalog tab):** extension /
  junction / end-cap prices, per-SKU weights, co-packer assignment, and the
  configuration limits.
- **Integration secrets** are encrypted with a master key from `MGS_SECRET_KEY`
  (or an auto-generated, git-ignored `data/.secret_key`). Secrets are never
  logged, never committed, and only ever returned masked.
- The engineering triage is **not** a structural certification. Non-standard
  builds always require a qualified engineer's sign-off before the published
  ratings are advertised for them.

## Tests

```bash
python3 -m unittest discover -s tests
```

## Roadmap

- Connect the configurator/quote flow to modulargreenhouses.com (public quote → order)
- Wire integration adapters into live actions (Stripe invoice on order confirm, QuickBooks sync, Calendly install scheduling)
- Production calendar + capacity planning per fabrication session
- Shipping labels / same-day shipping workflow using the per-SKU weights
