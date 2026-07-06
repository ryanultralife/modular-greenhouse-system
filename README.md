# Modular Greenhouse System

The complete business platform for [Modular Greenhouses](https://www.modulargreenhouses.com)
(Reno, NV — Joshua Smith, patent US 10,426,102): a customer-facing website with
an AI advisor, a full operations suite (orders → production → shipping →
co-packer), marketing automation, and an owner copilot — all one codebase, one
database, self-serve, no developer needed for day-to-day operation.

> **The full guided tour lives in [`docs/WALKTHROUGH.md`](docs/WALKTHROUGH.md)** —
> what each flow does, why it's built that way, and the structural decisions.
> It's generated from the same source as the in-app Walkthrough tab and a test
> keeps it in sync, so it can't drift from the running system.

## What it does

### Sell (public site at `/`)
| Area | Capability |
|------|-----------|
| **Marketing site** | Branded landing page, model cards with live prices, engineering ratings, FAQ. |
| **Configurator** | Any layout (straight / L / T / X, 4′ increments) → instant estimate → quote request. |
| **Buy now** | Ready-to-ship presets paid via Stripe Checkout; signed webhook fulfills, decrements stock, and auto-orders a co-packer replacement. |
| **AI advisor** | Grounded chat assistant: prices configurations with the real engine (can't invent numbers), flags engineer sign-off on custom layouts, captures leads. |
| **Attribution** | UTM source / referrer / landing page captured on first visit and attached to every lead and sale. |

### Operate (admin at `/admin`)
| Area | Capability |
|------|-----------|
| **Go-live checklist** | Live red/green readiness: what's left before the store can take real orders. |
| **Orders** | Status lifecycle with legal-transition guards; Stripe invoice, QuickBooks sync, Calendly install link, confirmation email per order. |
| **Today board** | Staff home screen: new paid orders → start build → build list + materials → ready to ship → restock. Plus next week's plan. |
| **Production** | Weekly fabrication sessions; aggregated stock list split in-house vs. each co-packer; material needs from per-SKU BOM. |
| **Inventory** | Finished units + materials with reorder points; ship-readiness gating on known weights. |
| **Catalog & pricing** | Prices, weights, verified flags, co-packer assignment, engineering limits — edited in the browser, stored in the DB. |
| **Staff & roles** | Owner vs. staff enforced server-side: staff see operational work, never pricing/payments/keys. |
| **Copilot** | Owner chat over live data (sales, builds, stock, channel conversion). Read-only by design — it names the tab to act in. |

### Grow (Marketing tab — all on hourly cron, all idempotent)
| Automation | What it does |
|------------|-------------|
| `lead_followup` | Auto-sends a personalized email about each new lead's exact configuration (AI-written with a key, honest template without). |
| `abandoned_checkout` | Nudges started-but-unpaid checkouts after a grace period. |
| `review_followup` | Review/referral email after shipping. |
| `list_sync` | Pushes every lead + paid order to any webhook (Zapier/Make → your email tool or CRM). |
| `social_posts` | Weekly grounded Facebook post pack — emailed with photo suggestions and/or pushed to a Zapier webhook that publishes to the Page. |
| `ai_digest` | Daily business briefing emailed to the owner (AI-written with a key, structured summary without). |

### Integrations (self-serve, encrypted at rest, connection-tested)
Stripe (payments + webhook) · QuickBooks Online · Calendly · SMTP email ·
Anthropic (AI advisor / copilot / digest) · custom API keys.

## Run it

```bash
./scripts/run.sh           # installs deps, starts the server
# public site: http://127.0.0.1:8000/   admin: http://127.0.0.1:8000/admin
```

Set `MGS_ADMIN_PASSWORD` for the owner login (user `admin`); if unset, one is
generated and printed to the logs. The engine CLI works standalone:

```bash
python3 -m greenhouse.cli quote --model barn_6_5 --shape straight --runs 20
```

## Architecture

```
greenhouse/      Pure engine: catalog, layout geometry, configurator, engineering triage, quoting, CLI
production/      Pure logic: weekly stock list + co-packer split, shipment plans, material needs
api/             FastAPI backend (single source of truth; SQLite locally, Supabase Postgres in prod)
  routers/         public, advisor, auth, quotes, orders, catalog, production, inventory, presets,
                   shipping, integrations, automations, copilot, work, users, setup, help,
                   walkthrough, webhooks (Stripe, signed), cron (token-gated)
  advisor.py       Customer AI advisor  — tool-use loop grounded on the engine
  copilot.py       Owner AI copilot     — tool-use loop grounded on live operations data
  automations.py / growth.py            Marketing automation engine (cron dispatchers)
  audit.py         Append-only event log: audit trail + automation idempotency queue
  checkout.py / billing.py / quickbooks_sync.py / calendly_actions.py / email_service.py
  security.py      Fernet encryption for integration secrets; auth.py: owner/staff roles (PBKDF2)
ui/public/       Customer site: landing, configurator, advisor chat widget (vanilla JS, no build step)
ui/admin/        Role-aware admin SPA (16 tabs, phone-friendly)
supabase/        SQL migrations mirroring the ORM
data/            catalog.json seed (tracked) + local db/secrets (git-ignored)
docs/            WALKTHROUGH.md (generated, test-synced) + engineering_data.md
tests/           158 tests — engine, planners, security, auth/roles, billing, QBO, Calendly,
                 shipping, checkout/webhook idempotency, marketing, advisor, copilot, growth
```

The engine and planners have no web/database dependencies. The API is a thin
layer over them; both AI assistants are thin loops over the same service layer
— which is why they can't disagree with the tabs.

## Data, security & AI grounding

- `data/catalog.json` (+ DB overrides) is the single source of truth. Every
  figure is flagged **verified** vs **placeholder**; unverified prices show as
  TBD and never enter totals. See [`docs/engineering_data.md`](docs/engineering_data.md).
- Engineering triage **never auto-certifies**: non-standard layouts require an
  engineer's sign-off before the published 130 mph / 6 ft ratings apply.
- **AI is grounded, not generative-about-facts**: the advisor, copilot, digest,
  lead emails, and social posts all draw exclusively from tools/templates over
  verified data — no invented prices, promises, or specs. Every AI exchange is
  recorded in the event log with an `agent:*` actor.
- Integration secrets: Fernet-encrypted at rest, masked in responses, never
  logged. Roles enforced server-side; staff never see money or keys.
- Payment fulfillment is idempotent against Stripe's at-least-once webhooks;
  automations are idempotent via the event log; order status changes follow a
  legal-transition graph.

## Deploy (Vercel + Supabase)

Static site on Vercel's CDN; `/api` runs serverless against Supabase Postgres.
Migrations in `supabase/migrations/` (applied on push via the Supabase GitHub
integration). Vercel env vars:

- `DATABASE_URL` — Supabase pooler connection string
- `MGS_SECRET_KEY` — Fernet key for secrets
- `MGS_ADMIN_PASSWORD` — owner login
- `CRON_SECRET` — enables the hourly automations cron
- `MGS_CORS_ORIGINS` (optional) · `ANTHROPIC_API_KEY` (optional env fallback —
  normally set via Integrations)

Locally, with no `DATABASE_URL`, it falls back to SQLite (what the tests use).

## Tests

```bash
python3 -m unittest discover -s tests   # 158 tests
```

## Roadmap

- Production calendar + capacity planning per fabrication session
- Carrier API integration for shipping labels + live tracking
- Direct Meta Graph API publishing (current social path: drafts + Zapier)
- MCP/tool layer exposing the service functions to external agents
- Live end-to-end validation of QuickBooks/Calendly/Anthropic against real
  credentials (happy paths covered by mocked tests)
