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

// Capture marketing attribution on first visit (sticky across the session) so
// it can be attached to whatever the visitor eventually submits.
function _captureAttribution() {
  try {
    const stored = sessionStorage.getItem("mgs_attrib");
    if (stored) return JSON.parse(stored);
    const params = new URLSearchParams(location.search);
    const a = {};
    ["utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content"].forEach((k) => {
      const v = params.get(k); if (v) a[k] = v;
    });
    if (document.referrer && new URL(document.referrer).host !== location.host) a.referrer = document.referrer;
    a.landing_path = location.pathname;
    sessionStorage.setItem("mgs_attrib", JSON.stringify(a));
    return a;
  } catch (e) { return {}; }
}
const ATTRIBUTION = _captureAttribution();

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
  MODELS.shapes.forEach((x) => s.append(el("option", { value: x.name }, x.label || x.name)));
  s.addEventListener("change", renderShape);
  renderShape();
}

// Inline SVG diagrams per shape (match the homepage), keyed by shape name.
const SHAPE_SVG = {
  straight: '<rect x="20" y="40" width="80" height="20" rx="3" fill="#8cc63f"/>',
  L: '<rect x="20" y="20" width="20" height="60" rx="3" fill="#8cc63f"/><rect x="20" y="60" width="70" height="20" rx="3" fill="#8cc63f"/>',
  T: '<rect x="15" y="40" width="90" height="20" rx="3" fill="#8cc63f"/><rect x="50" y="60" width="20" height="32" rx="3" fill="#8cc63f"/>',
  X: '<rect x="15" y="40" width="90" height="20" rx="3" fill="#8cc63f"/><rect x="50" y="10" width="20" height="80" rx="3" fill="#8cc63f"/>',
};

function currentShape() {
  const name = document.getElementById("shape").value;
  return MODELS.shapes.find((x) => x.name === name) || { name, runs: 1, arm_labels: ["Length"] };
}

function renderShape() {
  const shape = currentShape();
  const guide = document.getElementById("shape-guide");
  guide.innerHTML =
    `<svg viewBox="0 0 120 100" role="img" aria-label="${shape.label || shape.name} diagram">${SHAPE_SVG[shape.name] || ""}</svg>` +
    `<div class="shape-guide-text"><b>${shape.label || shape.name}</b><br>${shape.description || ""}</div>`;
  renderRuns(shape);
}

function renderRuns(shape) {
  const labels = shape.arm_labels || [];
  const box = document.getElementById("runs");
  box.innerHTML = "";
  for (let i = 0; i < shape.runs; i++) {
    const label = labels[i] || `Arm ${i + 1}`;
    box.append(el("label", { class: "fld" },
      el("span", {}, `${label} length (ft)`),
      el("input", { type: "number", min: "4", step: "4", value: "8", class: "run" })));
  }
  box.append(el("p", { class: "hint" }, "Lengths in 4-foot increments (4, 8, 12, …)."));
}

document.getElementById("estimate-btn").addEventListener("click", async () => {
  const runs = [...document.querySelectorAll(".run")].map((i) => parseFloat(i.value));
  if (runs.some((r) => !r || r < 4)) { toast("Each arm must be at least 4 ft.", true); return; }
  if (runs.some((r) => r % 4 !== 0)) { toast("Lengths must be in 4-foot increments (4, 8, 12, …).", true); return; }
  const body = { model: document.getElementById("model").value, shape: document.getElementById("shape").value, runs };
  try {
    const q = await api("/quote", { method: "POST", body: JSON.stringify(body) });
    LAST = body;
    renderEstimate(q);
    document.getElementById("lead").classList.remove("hidden");
    document.getElementById("estimate").scrollIntoView({ behavior: "smooth", block: "nearest" });
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
    attribution: ATTRIBUTION,
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
