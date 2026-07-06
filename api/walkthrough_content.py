"""Guided walkthroughs: the single source of truth for both the in-app
Walkthrough tab and the shareable docs/WALKTHROUGH.md.

Where help_content.py is a per-area *reference* ("what does the Catalog tab
do"), this is a narrative *tour of the flows* — what each flow is, WHY it's
built that way, and the structural decisions Josh should understand. Content
lives in code so it ships with each feature; regenerate the markdown doc with
scripts/gen_walkthrough_doc.py after editing.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# Status tags used on flows so the reader can tell built from planned.
BUILT = "built"
PARTIAL = "partial"
PLANNED = "planned"


@dataclass
class Flow:
    id: str
    title: str
    roles: tuple[str, ...]          # ("owner",) | ("staff",) | ("owner","staff")
    status: str                     # built | partial | planned
    why: str
    steps: list[str] = field(default_factory=list)
    structural_notes: list[str] = field(default_factory=list)


ARCHITECTURE = """\
The system is built in clean layers so each part can be understood, tested, and
extended on its own:

- **Engine** (`greenhouse/`) — pure logic: configures any greenhouse shape,
  computes the bill of materials, prices it, and runs the engineering triage.
  No database, no web — just rules. This is why pricing and engineering
  guardrails are trustworthy: they're enforced in code, not convention.
- **Planners** (`production/`) — pure logic for the weekly build list,
  co-packer split, materials needs, and shipment plans.
- **API** (`api/`) — a thin FastAPI layer over the engine + a SQLite/Postgres
  database. The real work lives in small service functions (checkout, billing,
  co-packer, inventory) that the routers just expose.
- **UI** (`ui/`) — a public marketing/store site at `/` and a role-aware admin
  at `/admin`, both plain HTML/JS (no build step).
- **Hosting** — static site on Vercel's CDN; the API runs serverless backed by
  Supabase Postgres. Nothing is written to disk at runtime, which is why
  catalog edits and secrets live in the database / environment.
"""

WHATS_NEXT = """\
**Marketing automation (building next).** The funnel below already captures
leads and buyers; the next phase adds an event log + a scheduled automation
runner so these run on their own: sync leads/buyers to an email tool,
recover abandoned checkouts, attribute every lead to its source (UTM), and send
post-purchase review/referral follow-ups — each with an on/off switch.

**Agentic operations (roadmap).** An audit trail of who/what changed,
machine-readable APIs, and a tool layer so an assistant could safely help
operate the company.
"""

WALKTHROUGHS: list[Flow] = [
    Flow(
        id="big_picture",
        title="The big picture",
        roles=("owner", "staff"),
        status=BUILT,
        why="Everything is one system: a public site that sells and captures leads, and an admin that runs operations off the same data — so a sale on the website immediately becomes a job on the floor.",
        steps=[
            "Public site (/) — customers design a greenhouse, get a price, request a quote, or buy a ready-to-ship preset.",
            "Admin (/admin) — owner runs setup, pricing, presets, integrations; staff run the day's build/ship work.",
            "The same order flows from website → admin → production → shipping, with no re-keying.",
        ],
        structural_notes=[
            "One source of truth: the database. The website and admin are two views of it.",
            "Roles: the owner sees money/keys; staff see only operational work. That split is enforced server-side.",
        ],
    ),
    Flow(
        id="customer_journey",
        title="Customer journey: visit → delivery",
        roles=("owner", "staff"),
        status=BUILT,
        why="This is the spine of the business. Knowing each stage shows where sales, operations, and (soon) marketing each plug in.",
        steps=[
            "Visit — customer lands on the marketing site, sees models, ratings, and shapes.",
            "Configure — they pick a model + shape (straight/L/T/X) and get an instant estimate.",
            "Convert — either request a firm quote (becomes a lead) or buy a preset and pay by card.",
            "Fulfill — a paid order decrements stock and auto-queues a co-packer replacement build.",
            "Operate — staff start the build, then ship when it's ready.",
            "Follow-up — (marketing) post-purchase review/referral — automation coming next.",
        ],
        structural_notes=[
            "Leads and purchases are both 'orders' with a source flag (website/admin) — one pipeline, not two.",
            "Marketing attaches at every stage: capture at visit, convert at quote, recover at checkout, nurture after delivery.",
        ],
    ),
    Flow(
        id="taking_orders",
        title="Taking & pricing an order",
        roles=("owner",),
        status=BUILT,
        why="The configurator turns the modular system into an instant, accurate quote — and refuses to show a number it can't stand behind.",
        steps=[
            "Configurator tab → pick model, shape, and each arm's length.",
            "The engine returns the bill of materials, a price, and an engineering triage.",
            "Save it as an order, or the customer creates it themselves from the website.",
        ],
        structural_notes=[
            "Unverified prices show as 'TBD' and never enter a total — a wrong number can't go out by accident.",
            "Non-standard shapes (L/T/X) return REQUIRES_ENGINEER_SIGNOFF — the system never auto-certifies wind/snow ratings.",
        ],
    ),
    Flow(
        id="money_path",
        title="The money path: payment → fulfillment → co-packer",
        roles=("owner",),
        status=BUILT,
        why="This is the automated heart of the store: a card payment should fulfill the order and restock without anyone touching it.",
        steps=[
            "Customer pays for a preset via Stripe Checkout.",
            "Stripe's webhook tells us it's paid; the order flips to 'paid'.",
            "Finished-unit stock drops by one.",
            "A replacement build order is automatically created for the co-packer (and emailed if SMTP is on).",
            "Owner can also raise a Stripe invoice or sync the order to QuickBooks.",
        ],
        structural_notes=[
            "The paid step is idempotent: Stripe can deliver the same webhook twice and we still fulfill exactly once (no double stock-drop, no double co-packer order).",
            "We refuse to mark an order paid unless the webhook signature verifies — nobody can spoof a 'paid' event.",
        ],
    ),
    Flow(
        id="daily_ops",
        title="Daily operations: the Today board",
        roles=("owner", "staff"),
        status=BUILT,
        why="Staff need one screen that says 'do this now' without seeing pricing or payments. That's the Today board.",
        steps=[
            "New paid orders → Start build.",
            "Build this week → the sections to fabricate and the materials to grab.",
            "Ready to ship → Mark shipped (records carrier + tracking; flags same-day).",
            "Restock → items at/below reorder point and pending co-packer orders.",
            "Next week → the upcoming fab session's build, or confirmed orders waiting to be scheduled.",
        ],
        structural_notes=[
            "The board is deliberately money-free — staff never see prices, payments, or keys.",
            "It's driven by current sales + inventory, so it's always live, not a static checklist.",
        ],
    ),
    Flow(
        id="production",
        title="Weekly production & materials",
        roles=("owner", "staff"),
        status=BUILT,
        why="Batching orders into a weekly fabrication session is how the shop actually plans work and buys materials.",
        steps=[
            "Group confirmed/paid orders into a fabrication session for a given week.",
            "The system rolls up the total sections to build and splits in-house vs. each co-packer.",
            "Materials needed are computed from each unit's bill of materials.",
        ],
        structural_notes=[
            "Material quantities per unit are entered once in the catalog; until then the plan honestly flags itself 'incomplete' rather than guessing.",
        ],
    ),
    Flow(
        id="marketing_funnel",
        title="The marketing funnel (and what's automated)",
        roles=("owner",),
        status=BUILT,
        why="Marketing isn't a separate tool bolted on — it attaches to each stage of the same order pipeline. Capture, attribute, sync, recover, nurture.",
        steps=[
            "Capture: every quote request becomes a lead with contact info and source.",
            "Attribution: the public site captures UTM params + referrer + landing path on first visit; every lead and purchase carries that source data.",
            "List sync: a configured webhook URL (Zapier/Make/n8n/custom) receives every new lead and paid order automatically.",
            "Recover: started-but-unpaid checkouts older than the grace period get a follow-up nudge by email.",
            "Nurture: shipped orders trigger an automated review / referral email after the configured delay.",
        ],
        structural_notes=[
            "All of this rides the existing order pipeline — no separate CRM to keep in sync.",
            "Backbone: an event log + a scheduled runner (Vercel Cron, hourly) so automations fire on their own, with an on/off toggle and editable templates per automation.",
            "Idempotent by construction: each automation records what it has done in the event log, so re-runs naturally skip already-handled items — duplicate cron deliveries can't double-send.",
            "Cron endpoint is protected by an env-var bearer token (CRON_SECRET), the same one Vercel Cron uses.",
        ],
    ),
    Flow(
        id="ai_advisor",
        title="The AI greenhouse advisor",
        roles=("owner",),
        status=BUILT,
        why="The website doesn't just display products — it can talk. A grounded AI assistant answers visitors, prices any configuration with the real engine, and turns interest into quote requests, 24/7.",
        steps=[
            "A visitor opens the chat bubble on the public site and describes what they want.",
            "The advisor calls the same pricing/engineering engine as the configurator — it cannot invent a price.",
            "Custom layouts automatically carry the engineer sign-off caveat from the engine.",
            "When the visitor is ready, the advisor collects a name + contact and submits a quote request — the same lead pipeline as the form.",
            "Every exchange lands in the event log (actor 'agent:advisor') so you can review what customers ask.",
        ],
        structural_notes=[
            "Grounding over generation: prices and engineering verdicts come only from tools backed by the engine; unverified prices stay TBD.",
            "One safe action: the advisor can submit a quote request and nothing else — no payments, no order changes.",
            "Cost is bounded: capped reply length, capped history, and per-visitor + global daily limits enforced through the event log.",
            "Setup is self-serve: paste an Anthropic API key under Integrations — same pattern as Stripe/QuickBooks.",
        ],
    ),
    Flow(
        id="owner_copilot",
        title="The owner copilot & daily digest",
        roles=("owner",),
        status=BUILT,
        why="Intelligence for the inside of the business: ask questions in plain English and get answers from live data, plus an automated morning briefing so you start each day knowing what needs attention.",
        steps=[
            "Copilot tab: ask 'what should we build this week?', 'how are sales?', 'which channel converts?' — it reads the same live data as your tabs.",
            "It is read-only on purpose: it analyzes and tells you where to act; the buttons stay under your finger.",
            "The ai_digest automation emails a daily briefing (restock, abandoned checkouts, builds due, lead sources) — AI-written when the Anthropic key is set, plain summary otherwise.",
            "Set the digest recipient and enable it on the Marketing tab; it sends once a day via the existing hourly cron.",
        ],
        structural_notes=[
            "Copilot and digest share the same data builders, so the chat and the email can never disagree.",
            "Read-only by design: an assistant that can silently ship orders or send invoices is a liability — actions stay behind explicit buttons.",
            "Every copilot exchange is logged in the event log (actor 'agent:copilot'), same as the customer advisor.",
        ],
    ),
    Flow(
        id="why_choices",
        title="Why these structural choices",
        roles=("owner",),
        status=BUILT,
        why="A few deliberate decisions keep the system trustworthy and safe to grow — worth knowing so changes don't undo them.",
        steps=[],
        structural_notes=[
            "Verified-data model: prices/limits are flagged verified vs placeholder; nothing unverified is ever quoted or advertised.",
            "Engineering never auto-certifies: custom layouts route to a human engineer.",
            "Roles: owner vs staff is enforced on the server, so the work board can't leak money data.",
            "Idempotency: payment fulfillment is safe against duplicate/retried webhooks.",
            "Serverless + Supabase: no runtime disk writes; data and secrets live in the DB/environment, which is why setup is done in the app and via env vars, not files.",
            "Migrations mirror the data model, so the production database schema is reproducible.",
        ],
    ),
]


def overview_for_role(role: str) -> dict:
    flows = [
        {
            "id": f.id,
            "title": f.title,
            "status": f.status,
            "why": f.why,
            "steps": f.steps,
            "structural_notes": f.structural_notes,
        }
        for f in WALKTHROUGHS
        if role in f.roles
    ]
    return {"role": role, "architecture": ARCHITECTURE, "whats_next": WHATS_NEXT, "flows": flows}


def render_markdown() -> str:
    """Render the full shareable doc (used by scripts/gen_walkthrough_doc.py)."""
    out: list[str] = []
    out.append("# Modular Greenhouse System — Owner's Walkthrough\n")
    out.append(
        "_A plain-language tour of what's built, why, and the flows you operate. "
        "This file is generated from `api/walkthrough_content.py` (the same source "
        "as the in-app Walkthrough tab), so it stays in sync with the system._\n"
    )
    out.append("## How it's built\n")
    out.append(ARCHITECTURE + "\n")

    status_label = {BUILT: "✅ Built", PARTIAL: "🟡 Partly built", PLANNED: "⏳ Planned"}
    out.append("## The flows\n")
    for f in WALKTHROUGHS:
        audience = " / ".join(f.roles)
        out.append(f"### {f.title}\n")
        out.append(f"**{status_label.get(f.status, f.status)}** · _Audience: {audience}_\n")
        out.append(f"{f.why}\n")
        if f.steps:
            out.append("**Steps:**\n")
            for s in f.steps:
                out.append(f"1. {s}")
            out.append("")
        if f.structural_notes:
            out.append("**Why it's built this way:**\n")
            for n in f.structural_notes:
                out.append(f"- {n}")
            out.append("")
    out.append("## What's next\n")
    out.append(WHATS_NEXT + "\n")
    return "\n".join(out)
