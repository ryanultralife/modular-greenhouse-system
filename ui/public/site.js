"use strict";

// Customer-facing configurator. Talks only to the open /api/public/* endpoints.
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

function money(v) {
  return v == null ? "—" : "$" + Number(v).toLocaleString(undefined, { maximumFractionDigits: 0 });
}

async function init() {
  try {
    MODELS = await api("/models");
  } catch (e) {
    toast("Couldn't load options: " + e.message, true);
    return;
  }
  const m = document.getElementById("model");
  MODELS.models.forEach((x) => m.append(el("option", { value: x.id }, x.name)));
  const s = document.getElementById("shape");
  MODELS.shapes.forEach((x) => s.append(el("option", { value: x.name }, `${x.name} (${x.runs} section${x.runs > 1 ? "s" : ""})`)));
  s.addEventListener("change", renderRuns);
  renderRuns();
}

function renderRuns() {
  const shape = document.getElementById("shape").value;
  const n = MODELS.shapes.find((x) => x.name === shape)?.runs || 1;
  const box = document.getElementById("runs");
  box.innerHTML = "";
  for (let i = 0; i < n; i++) {
    box.append(el("label", { class: "fld" },
      el("span", {}, `Section ${i + 1} length (ft)`),
      el("input", { type: "number", min: "4", step: "4", value: "8", class: "run" })));
  }
}

document.getElementById("estimate-btn").addEventListener("click", async () => {
  const runs = [...document.querySelectorAll(".run")].map((i) => parseFloat(i.value));
  if (runs.some((r) => !r || r <= 0)) { toast("Enter a length for each section.", true); return; }
  const body = { model: document.getElementById("model").value, shape: document.getElementById("shape").value, runs };
  try {
    const q = await api("/quote", { method: "POST", body: JSON.stringify(body) });
    LAST = body;
    renderEstimate(q);
    document.getElementById("lead").classList.remove("hidden");
  } catch (e) { toast(e.message, true); }
});

function renderEstimate(q) {
  const box = document.getElementById("estimate");
  box.classList.remove("hidden");
  box.innerHTML = "";
  box.append(el("h3", { style: "margin-top:0" }, `${q.model_name} — ${q.shape}`));
  box.append(el("p", { class: "muted" }, `${q.total_bays} sections · about ${q.footprint_sqft} sq ft of growing space`));
  if (q.quote_complete) {
    box.append(el("div", { class: "big" }, "Estimated from " + money(q.verified_subtotal_usd)));
  } else {
    box.append(el("div", { class: "big" }, "From " + money(q.verified_subtotal_usd)));
    box.append(el("p", { class: "muted" }, "Final pricing on some options is confirmed when we follow up."));
  }
}

document.getElementById("submit-btn").addEventListener("click", async () => {
  if (!LAST) return;
  const body = {
    ...LAST,
    name: document.getElementById("f-name").value,
    email: document.getElementById("f-email").value,
    phone: document.getElementById("f-phone").value,
    message: document.getElementById("f-message").value,
  };
  if (!body.email && !body.phone) { toast("Please add an email or phone so we can reach you.", true); return; }
  try {
    const r = await api("/quote-request", { method: "POST", body: JSON.stringify(body) });
    document.getElementById("lead").classList.add("hidden");
    const box = document.getElementById("estimate");
    box.innerHTML = "";
    box.append(el("h3", { style: "margin-top:0" }, "Request received ✓"));
    box.append(el("p", {}, r.message));
  } catch (e) { toast(e.message, true); }
});

init();
