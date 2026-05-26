"use strict";

// Public configurator. Talks only to /api/public/*. Safe to embed via iframe.
const API = "/api/public";
let MODELS = null;
let LAST = null;

async function api(path, opts = {}) {
  const res = await fetch(API + path, { headers: { "Content-Type": "application/json" }, ...opts });
  if (!res.ok) {
    let d = res.statusText;
    try { d = (await res.json()).detail || d; } catch (e) {}
    throw new Error(d);
  }
  return res.json();
}

function toast(msg, isErr = false) {
  const t = document.getElementById("toast");
  t.textContent = msg;
  t.className = isErr ? "err" : "";
  setTimeout(() => (t.className = "hidden"), 4000);
}

function el(tag, attrs = {}, ...kids) {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") n.className = v;
    else if (k.startsWith("on")) n.addEventListener(k.slice(2), v);
    else n.setAttribute(k, v);
  }
  kids.forEach((c) => n.append(c?.nodeType ? c : document.createTextNode(c ?? "")));
  return n;
}

function usd(v) {
  return v == null ? "—" : "$" + Number(v).toLocaleString(undefined, { minimumFractionDigits: 0, maximumFractionDigits: 0 });
}

async function init() {
  MODELS = await api("/models");
  if (MODELS.company?.name) {
    document.getElementById("pub-company").textContent =
      `${MODELS.company.name}${MODELS.company.location ? " · " + MODELS.company.location : ""}`;
  }
  const m = document.getElementById("q-model");
  MODELS.models.forEach((x) => m.append(el("option", { value: x.id }, x.name)));
  const s = document.getElementById("q-shape");
  MODELS.shapes.forEach((x) => s.append(el("option", { value: x.name }, `${x.name} (${x.runs} section${x.runs > 1 ? "s" : ""})`)));
  s.addEventListener("change", renderRuns);
  renderRuns();
}

function renderRuns() {
  const shape = document.getElementById("q-shape").value;
  const n = MODELS.shapes.find((x) => x.name === shape)?.runs || 1;
  const box = document.getElementById("q-runs");
  box.innerHTML = "";
  for (let i = 0; i < n; i++) {
    box.append(el("label", {}, `Section ${i + 1} length (ft)`,
      el("input", { type: "number", min: "4", step: "4", value: "8", class: "run" })));
  }
}

document.getElementById("q-price").addEventListener("click", async () => {
  const runs = [...document.querySelectorAll(".run")].map((i) => parseFloat(i.value));
  const body = { model: document.getElementById("q-model").value, shape: document.getElementById("q-shape").value, runs };
  try {
    const q = await api("/quote", { method: "POST", body: JSON.stringify(body) });
    LAST = body;
    render(q);
    document.getElementById("q-form").classList.remove("hidden");
  } catch (e) { toast(e.message, true); }
});

function render(q) {
  const box = document.getElementById("q-result");
  box.innerHTML = "";
  const card = el("div", { class: "card" });
  card.append(el("h3", {}, `${q.model_name} — ${q.shape}`));
  card.append(el("p", { class: "muted" }, `${q.total_bays} bays · about ${q.footprint_sqft} sq ft of growing space`));
  if (q.quote_complete) {
    card.append(el("p", { class: "price" }, "Estimated from " + usd(q.verified_subtotal_usd)));
  } else {
    card.append(el("p", {}, el("b", {}, "Base price from " + usd(q.verified_subtotal_usd)),
      el("div", { class: "muted" }, "Final pricing on some options confirmed when we follow up.")));
  }
  box.append(card);
}

document.getElementById("q-submit").addEventListener("click", async () => {
  if (!LAST) return;
  const body = {
    ...LAST,
    name: document.getElementById("q-name").value,
    email: document.getElementById("q-email").value,
    phone: document.getElementById("q-phone").value,
    message: document.getElementById("q-message").value,
  };
  if (!body.email && !body.phone) { toast("Please add an email or phone so we can reach you.", true); return; }
  try {
    const r = await api("/quote-request", { method: "POST", body: JSON.stringify(body) });
    document.getElementById("q-form").classList.add("hidden");
    document.getElementById("q-result").innerHTML = "";
    document.getElementById("q-result").append(el("div", { class: "card" },
      el("h3", {}, "Request received ✓"), el("p", {}, r.message)));
  } catch (e) { toast(e.message, true); }
});

init().catch((e) => toast("Could not load: " + e.message, true));
