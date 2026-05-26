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
| **Integrations** | Josh adds his own Stripe / Calendly / QuickBooks / SMTP / custom API keys in the UI. Keys are **encrypted at rest** and validated with a read-only test call. |
| **Billing** | Create a Stripe invoice from a confirmed order (draft, or finalize + send). Sync the same order to QuickBooks Online as a customer + invoice. |
| **Scheduling** | Generate a Calendly single-use install booking link per order, optionally emailed to the customer. |
| **Email** | Send order confirmations and install links via the configured SMTP provider. |
| **Auth** | Admin UI/API behind a login; the public website flow stays open. |

## Run it

```bash
./scripts/run.sh           # installs deps, starts the server
# then open http://127.0.0.1:8000/
```

Set `MGS_ADMIN_PASSWORD` for the admin login (user `admin`). If unset, a random
password is generated on first run and printed to the logs / stored in the
git-ignored `data/.admin_password`. The public quote page (`/ui/quote.html`)
needs no login.

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
production/      Pure logic: weekly stock list + co-packer split; shipment plans
api/             FastAPI backend (single source of truth, SQLite)
  routers/         auth, quotes, orders, catalog, production, integrations, public, shipping
  auth.py          Admin login + bearer-token dependency
  security.py      Fernet encryption for integration secrets
  billing.py / stripe_client.py        Stripe invoicing
  quickbooks_sync.py / quickbooks_client.py   QuickBooks Online customer + invoice
  calendly_actions.py / calendly_client.py    Install scheduling links
  email_service.py                     SMTP send (confirmations, install links)
  integrations_providers.py            Provider registry + connection tests
ui/              Static admin UI + public quote page (vanilla HTML/JS, no build step)
data/            catalog.json (tracked) + app.db / .secret_key / .admin_password (git-ignored)
tests/           70 tests (engine, planner, security, auth, email, billing, QBO, Calendly, shipping, full API)
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
- **Admin auth**: every `/api` route except the public website flow and login
  requires a bearer token issued by `POST /api/auth/login`. The password comes
  from `MGS_ADMIN_PASSWORD` or a generated, git-ignored `data/.admin_password`.
- The engineering triage is **not** a structural certification. Non-standard
  builds always require a qualified engineer's sign-off before the published
  ratings are advertised for them.
- **Live integration actions** (Stripe/QuickBooks invoices, Calendly links,
  email) are guarded: they need the relevant integration configured, a complete
  quote where money is involved, are idempotent, and fail with clear messages
  rather than partial state.

## Deploy (Vercel + Supabase)

The app runs statelessly on Vercel serverless backed by Supabase Postgres — no
filesystem writes (catalog edits persist in the DB; secrets come from env vars).

1. **Supabase** — the migration in `supabase/migrations/` creates the schema.
   With the Supabase GitHub integration connected, it runs on push to `main`
   (or run `supabase db push` locally). Grab the Postgres **pooler** connection
   string from Supabase → Project Settings → Database.
2. **Vercel** — `vercel.json` builds `index.py` (the ASGI app) and routes all
   traffic to it (the app also serves the static `ui/`). Set these env vars in
   the Vercel project:
   - `DATABASE_URL` — the Supabase pooler connection string
   - `MGS_SECRET_KEY` — a Fernet key (`python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`)
   - `MGS_ADMIN_PASSWORD` — the admin login password
   - `MGS_CORS_ORIGINS` — (optional) allowed origins for the public widget

Locally, with no `DATABASE_URL`, it falls back to a SQLite file — handy for dev
and what the test suite uses.

## Tests

```bash
python3 -m unittest discover -s tests
```

## Roadmap

- Production calendar + capacity planning per fabrication session
- Carrier API integration for real shipping labels + live tracking
- Multi-user admin accounts and roles (current auth is single-admin)
- Live end-to-end validation of QuickBooks/Calendly against real credentials
  (happy paths currently covered by mocked tests)
