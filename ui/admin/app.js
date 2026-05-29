"use strict";

const API = "/api";
let MODELS = null;       // {company, models, shapes}
let LAST_QUOTE = null;   // last computed quote request+result
let PROVIDERS = [];      // integration providers
let TOKEN = localStorage.getItem("mgs_token") || "";
let ROLE = "owner";      // set from /auth/me on boot

// ---- helpers ----------------------------------------------------------
async function api(path, opts = {}) {
  const headers = { "Content-Type": "application/json", ...(opts.headers || {}) };
  if (TOKEN) headers["Authorization"] = "Bearer " + TOKEN;
  const res = await fetch(API + path, { ...opts, headers });
  if (res.status === 401) {
    TOKEN = "";
    localStorage.removeItem("mgs_token");
    showLogin();
    throw new Error("Session expired — please sign in again.");
  }
  if (!res.ok) {
    let detail = res.statusText;
    try { detail = (await res.json()).detail || detail; } catch (e) {}
    throw new Error(detail);
  }
  if (res.status === 204) return null;
  return res.json();
}

function toast(msg, isErr = false) {
  const t = document.getElementById("toast");
  t.textContent = msg;
  t.className = isErr ? "err" : "";
  setTimeout(() => (t.className = "hidden"), 3500);
}

function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") node.className = v;
    else if (k === "html") node.innerHTML = v;
    else if (k.startsWith("on")) node.addEventListener(k.slice(2), v);
    else node.setAttribute(k, v);
  }
  for (const c of children) node.append(c?.nodeType ? c : document.createTextNode(c ?? ""));
  return node;
}

function usd(v) {
  return v == null ? "TBD" : "$" + Number(v).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

// ---- tabs -------------------------------------------------------------
document.querySelectorAll("#tabs button").forEach((b) => {
  b.addEventListener("click", () => {
    document.querySelectorAll("#tabs button").forEach((x) => x.classList.remove("active"));
    document.querySelectorAll(".tab").forEach((x) => x.classList.remove("active"));
    b.classList.add("active");
    document.getElementById(b.dataset.tab).classList.add("active");
    onTab(b.dataset.tab);
  });
});

function onTab(name) {
  if (name === "work") loadWork();
  if (name === "setup") loadSetup();
  if (name === "orders") loadOrders();
  if (name === "catalog") loadCatalog();
  if (name === "production") loadFabSessions();
  if (name === "integrations") loadIntegrations();
  if (name === "inventory") loadInventory();
  if (name === "presets") loadPresets();
  if (name === "copacker") loadCopacker();
  if (name === "staff") loadStaff();
}

function activateTab(name) {
  document.querySelectorAll("#tabs button").forEach((x) => x.classList.toggle("active", x.dataset.tab === name));
  document.querySelectorAll(".tab").forEach((x) => x.classList.toggle("active", x.id === name));
  onTab(name);
}

function applyRole() {
  const isOwner = ROLE === "owner";
  document.querySelectorAll(".owner-only").forEach((e) => { e.style.display = isOwner ? "" : "none"; });
  activateTab("work");  // everyone lands on Today
}

// ---- configurator -----------------------------------------------------
async function initConfigurator() {
  MODELS = await api("/models");
  document.getElementById("company").textContent =
    MODELS.company?.name ? `${MODELS.company.name} — ${MODELS.company.location || ""}` : "";

  const modelSel = document.getElementById("cfg-model");
  modelSel.innerHTML = "";
  MODELS.models.forEach((m) => modelSel.append(el("option", { value: m.id }, m.name)));

  const shapeSel = document.getElementById("cfg-shape");
  shapeSel.innerHTML = "";
  MODELS.shapes.forEach((s) => shapeSel.append(el("option", { value: s.name }, `${s.label || s.name} (${s.runs} run${s.runs > 1 ? "s" : ""})`)));
  shapeSel.addEventListener("change", renderRunInputs);
  renderRunInputs();
}

function renderRunInputs() {
  const shape = document.getElementById("cfg-shape").value;
  const n = MODELS.shapes.find((s) => s.name === shape)?.runs || 1;
  const box = document.getElementById("cfg-runs");
  box.innerHTML = "";
  for (let i = 0; i < n; i++) {
    box.append(el("label", {}, `Run ${i + 1} (ft)`, el("input", { type: "number", min: "1", step: "1", value: "8", class: "run-len" })));
  }
}

document.getElementById("cfg-quote").addEventListener("click", async () => {
  const runs = [...document.querySelectorAll(".run-len")].map((i) => parseFloat(i.value));
  const body = {
    model: document.getElementById("cfg-model").value,
    shape: document.getElementById("cfg-shape").value,
    runs,
  };
  try {
    const q = await api("/quote", { method: "POST", body: JSON.stringify(body) });
    LAST_QUOTE = { request: body, result: q };
    renderQuote(q);
    document.getElementById("cfg-save").classList.remove("hidden");
  } catch (e) {
    toast(e.message, true);
  }
});

function engBadge(eng) {
  if (eng.status === "STANDARD") return el("span", { class: "badge ok" }, "STANDARD");
  if (eng.status === "PRELIMINARY_OK") return el("span", { class: "badge ok" }, "PRELIMINARY OK");
  return el("span", { class: "badge warn" }, "NEEDS ENGINEER SIGN-OFF");
}

function renderQuote(q) {
  const box = document.getElementById("cfg-result");
  box.innerHTML = "";
  const card = el("div", { class: "card" });
  card.append(el("h3", {}, `${q.model_name} — ${q.shape}`));
  card.append(el("p", { class: "muted" }, `Bays: ${q.total_bays} · Footprint ~${q.footprint_sqft} sqft · Runs: ${q.runs.join(", ")} ft`));

  const table = el("table");
  table.append(el("tr", {}, el("th", {}, "Qty"), el("th", {}, "Item"), el("th", {}, "Unit"), el("th", {}, "Line")));
  q.quote_lines.forEach((l) => {
    const note = l.verified_price && l.unit_price_usd != null ? "" : " (price not verified)";
    table.append(el("tr", {},
      el("td", {}, String(l.quantity)),
      el("td", {}, l.name + note),
      el("td", {}, usd(l.unit_price_usd)),
      el("td", {}, usd(l.extended_usd))));
  });
  card.append(table);
  card.append(el("p", {}, el("b", {}, `Verified subtotal: ${usd(q.verified_subtotal_usd)}`)));
  if (!q.quote_complete) card.append(el("p", { class: "tbd" }, "Some lines have no verified price — quote is not final until set in Catalog."));

  const eng = el("p", {}, "Engineering: ", engBadge(q.engineering));
  card.append(eng);
  q.engineering.reasons.forEach((r) => card.append(el("div", { class: "muted" }, "• " + r)));
  card.append(el("p", { class: "muted" }, q.engineering.disclaimer));
  box.append(card);
}

document.getElementById("cfg-save-btn").addEventListener("click", async () => {
  if (!LAST_QUOTE) return;
  const body = {
    ...LAST_QUOTE.request,
    customer_name: document.getElementById("cfg-cust-name").value,
    customer_email: document.getElementById("cfg-cust-email").value,
  };
  try {
    const o = await api("/orders", { method: "POST", body: JSON.stringify(body) });
    toast(`Saved order #${o.id}`);
  } catch (e) {
    toast(e.message, true);
  }
});

// ---- orders -----------------------------------------------------------
async function loadOrders() {
  const status = document.getElementById("orders-filter").value;
  const orders = await api("/orders" + (status ? `?status=${status}` : ""));
  const box = document.getElementById("orders-list");
  box.innerHTML = "";
  if (!orders.length) { box.append(el("p", { class: "muted" }, "No orders yet.")); return; }

  const table = el("table");
  table.append(el("tr", {}, el("th", {}, "#"), el("th", {}, "Customer"), el("th", {}, "Src"), el("th", {}, "Build"),
    el("th", {}, "Subtotal"), el("th", {}, "Eng."), el("th", {}, "Status"), el("th", {}, ""), el("th", {}, "Invoice")));
  orders.forEach((o) => {
    const sel = el("select");
    ["quote", "confirmed", "in_production", "shipped", "cancelled"].forEach((s) =>
      sel.append(el("option", s === o.status ? { value: s, selected: "selected" } : { value: s }, s)));
    const save = el("button", { onclick: async () => {
      try { await api(`/orders/${o.id}`, { method: "PATCH", body: JSON.stringify({ status: sel.value }) }); toast(`Order #${o.id} → ${sel.value}`); }
      catch (e) { toast(e.message, true); }
    } }, "Set");
    const engOk = !o.engineering?.requires_signoff;

    const refs = o.external_refs || {};
    const actions = el("td", {});

    // Stripe invoice
    if (refs.stripe_invoice_id) {
      actions.append(refs.stripe_invoice_url
        ? el("a", { href: refs.stripe_invoice_url, target: "_blank" }, "invoice")
        : el("span", { class: "badge ok" }, "invoiced"), " ");
    } else {
      actions.append(el("button", { onclick: () => orderAction(o.id, "/invoice", "Stripe draft invoice") }, "Invoice"), " ");
    }
    // QuickBooks
    if (refs.qbo_invoice_id) actions.append(el("span", { class: "badge ok" }, "QBO " + (refs.qbo_invoice_doc_number || "✓")), " ");
    else actions.append(el("button", { onclick: () => orderAction(o.id, "/quickbooks-sync", "QuickBooks invoice") }, "QBO"), " ");
    // Calendly install
    if (refs.calendly_booking_url) actions.append(el("a", { href: refs.calendly_booking_url, target: "_blank" }, "install link"), " ");
    else actions.append(el("button", { onclick: () => orderAction(o.id, "/schedule-install", "Install scheduling link") }, "Schedule"), " ");
    // Shipping
    if (o.shipping?.ship_date) actions.append(el("span", { class: "badge ok" }, "shipped" + (o.shipping.same_day ? " (same-day)" : "")));
    else actions.append(el("button", { onclick: () => shipOrder(o.id) }, "Ship"));

    table.append(el("tr", {},
      el("td", {}, "#" + o.id),
      el("td", {}, o.customer_name || "—"),
      el("td", {}, el("span", { class: "badge muted" }, o.source || "admin")),
      el("td", {}, `${o.model_id} ${o.shape} [${(o.runs || []).join(",")}]`),
      el("td", {}, usd(o.pricing?.verified_subtotal_usd)),
      el("td", {}, el("span", { class: "badge " + (engOk ? "ok" : "warn") }, engOk ? "ok" : "sign-off")),
      el("td", {}, sel),
      el("td", {}, save),
      actions));
  });
  box.append(table);
}

async function orderAction(id, path, label) {
  try { await api(`/orders/${id}${path}`, { method: "POST" }); toast(`${label} created for #${id}`); loadOrders(); }
  catch (e) { toast(e.message, true); }
}

async function shipOrder(id) {
  const carrier = prompt("Carrier (e.g. UPS):", "UPS");
  if (carrier === null) return;
  const tracking = prompt("Tracking number (optional):", "") || "";
  try { const r = await api(`/orders/${id}/ship`, { method: "POST", body: JSON.stringify({ carrier, tracking }) }); toast(`Order #${id} shipped${r.shipping?.same_day ? " (same-day)" : ""}`); loadOrders(); }
  catch (e) { toast(e.message, true); }
}
document.getElementById("orders-refresh").addEventListener("click", loadOrders);
document.getElementById("orders-filter").addEventListener("change", loadOrders);

// ---- catalog ----------------------------------------------------------
async function loadCatalog() {
  const cat = await api("/catalog");
  const box = document.getElementById("catalog-models");
  box.innerHTML = "";
  for (const [mid, model] of Object.entries(cat.models || {})) {
    const card = el("div", { class: "card" });
    card.append(el("h3", {}, `${model.name} (${mid})`));
    const table = el("table");
    table.append(el("tr", {}, el("th", {}, "SKU"), el("th", {}, "Price"), el("th", {}, "Verified"),
      el("th", {}, "Weight (lb)"), el("th", {}, "Fulfillment"), el("th", {}, "Co-packer"), el("th", {}, "")));
    for (const [sid, sku] of Object.entries(model.skus || {})) {
      const price = el("input", { type: "number", step: "0.01", value: sku.price_usd ?? "", style: "width:90px" });
      const verified = el("input", { type: "checkbox" });
      if (sku.verified_price) verified.checked = true;
      const weight = el("input", { type: "number", step: "0.1", value: sku.weight_lb ?? "", style: "width:80px" });
      const fulfill = el("select");
      ["in_house", "copacker"].forEach((f) =>
        fulfill.append(el("option", f === (sku.fulfillment || "in_house") ? { value: f, selected: "selected" } : { value: f }, f)));
      const copacker = el("input", { value: sku.copacker ?? "", placeholder: "name", style: "width:120px" });
      const save = el("button", { onclick: async () => {
        const body = {
          price_usd: price.value === "" ? null : parseFloat(price.value),
          verified_price: verified.checked,
          weight_lb: weight.value === "" ? null : parseFloat(weight.value),
          fulfillment: fulfill.value,
          copacker: copacker.value || null,
        };
        try { await api(`/catalog/models/${mid}/skus/${sid}`, { method: "PUT", body: JSON.stringify(body) }); toast(`Saved ${sid}`); }
        catch (e) { toast(e.message, true); }
      } }, "Save");
      table.append(el("tr", {}, el("td", {}, sku.name || sid), el("td", {}, price), el("td", {}, verified),
        el("td", {}, weight), el("td", {}, fulfill), el("td", {}, copacker), el("td", {}, save)));
    }
    card.append(table);
    box.append(card);
  }
  renderLimits(cat.configuration_limits || {});
}

function renderLimits(limits) {
  const box = document.getElementById("catalog-limits");
  box.innerHTML = "";
  const table = el("table");
  table.append(el("tr", {}, el("th", {}, "Limit"), el("th", {}, "Value"), el("th", {}, "Verified"), el("th", {}, "")));
  for (const [key, entry] of Object.entries(limits)) {
    if (key.startsWith("_")) continue;
    const isList = Array.isArray(entry.value);
    const val = el("input", { value: isList ? (entry.value || []).join(", ") : (entry.value ?? ""), style: "width:160px" });
    const verified = el("input", { type: "checkbox" });
    if (entry.verified) verified.checked = true;
    const save = el("button", { onclick: async () => {
      let value;
      if (isList) value = val.value.split(",").map((s) => s.trim()).filter(Boolean);
      else value = val.value === "" ? null : parseFloat(val.value);
      try { await api(`/catalog/limits/${key}`, { method: "PUT", body: JSON.stringify({ value, verified: verified.checked }) }); toast(`Saved ${key}`); }
      catch (e) { toast(e.message, true); }
    } }, "Save");
    table.append(el("tr", {}, el("td", {}, key), el("td", {}, val), el("td", {}, verified), el("td", {}, save)));
  }
  box.append(table);
}

// ---- production -------------------------------------------------------
async function loadFabSessions() {
  const sessions = await api("/fab-sessions");
  const box = document.getElementById("fab-sessions");
  box.innerHTML = "";
  if (!sessions.length) { box.append(el("p", { class: "muted" }, "No fabrication sessions yet.")); return; }
  sessions.forEach((s) => {
    const card = el("div", { class: "card" });
    card.append(el("h3", {}, `${s.label || "Session"} — week of ${s.week_of} (${s.status})`));
    card.append(el("p", { class: "muted" }, `Orders: ${s.order_ids.join(", ") || "none assigned"}`));
    const assign = el("input", { placeholder: "order ids e.g. 1,2,3", style: "width:200px" });
    const assignBtn = el("button", { onclick: async () => {
      const ids = assign.value.split(",").map((x) => parseInt(x.trim(), 10)).filter((n) => !isNaN(n));
      try { await api(`/fab-sessions/${s.id}/assign`, { method: "POST", body: JSON.stringify({ order_ids: ids }) }); toast("Assigned"); loadFabSessions(); }
      catch (e) { toast(e.message, true); }
    } }, "Assign orders");
    const stockBtn = el("button", { onclick: async () => {
      try { const sl = await api(`/fab-sessions/${s.id}/stock-list`); renderStockList(sl, card); }
      catch (e) { toast(e.message, true); }
    } }, "Build stock list");
    card.append(el("div", { class: "row" }, assign, assignBtn, stockBtn));
    box.append(card);
  });
}

document.getElementById("fab-create").addEventListener("click", async () => {
  const week_of = document.getElementById("fab-week").value;
  if (!week_of) { toast("Pick a week-of date", true); return; }
  const label = document.getElementById("fab-label").value;
  try { await api("/fab-sessions", { method: "POST", body: JSON.stringify({ week_of, label }) }); toast("Session created"); loadFabSessions(); }
  catch (e) { toast(e.message, true); }
});

document.getElementById("stock-build").addEventListener("click", async () => {
  const status = document.getElementById("stock-status").value;
  try { const sl = await api(`/production/stock-list?status=${status}`); renderStockList(sl, document.getElementById("stock-result"), true); }
  catch (e) { toast(e.message, true); }
});

function stockTable(lines) {
  const table = el("table");
  table.append(el("tr", {}, el("th", {}, "Qty"), el("th", {}, "SKU"), el("th", {}, "Model"), el("th", {}, "Weight (lb)")));
  lines.forEach((l) => table.append(el("tr", {},
    el("td", {}, String(l.quantity)), el("td", {}, l.name), el("td", {}, l.model_id),
    el("td", {}, l.total_weight_lb == null ? "—" : String(l.total_weight_lb)))));
  return table;
}

function renderStockList(sl, container, replace = false) {
  const wrap = el("div", {});
  wrap.append(el("h4", {}, `Stock list — ${sl.order_count} order(s)`));
  if (sl.in_house.length) { wrap.append(el("p", { class: "muted" }, "In-house fabrication:")); wrap.append(stockTable(sl.in_house)); }
  const cps = sl.copacker || {};
  for (const [name, lines] of Object.entries(cps)) {
    wrap.append(el("p", { class: "muted" }, `Co-packer: ${name}`));
    wrap.append(stockTable(lines));
  }
  if (!sl.in_house.length && !Object.keys(cps).length) wrap.append(el("p", { class: "muted" }, "No items (no assigned orders)."));
  if (replace) container.innerHTML = "";
  container.append(wrap);
}

// ---- integrations -----------------------------------------------------
async function initIntegrationProviders() {
  PROVIDERS = await api("/integrations/providers");
  const sel = document.getElementById("int-provider");
  sel.innerHTML = "";
  PROVIDERS.forEach((p) => sel.append(el("option", { value: p.key }, p.label)));
  sel.addEventListener("change", renderIntFields);
  renderIntFields();
}

function renderIntFields() {
  const key = document.getElementById("int-provider").value;
  const provider = PROVIDERS.find((p) => p.key === key);
  const box = document.getElementById("int-fields");
  box.innerHTML = "";
  if (!provider) return;
  if (provider.docs_url) box.append(el("p", { class: "muted" }, el("a", { href: provider.docs_url, target: "_blank" }, "Where to find these keys")));
  provider.fields.forEach((f) => {
    box.append(el("label", {}, f.label, el("input", { type: f.secret ? "password" : "text", "data-field": f.name, class: "int-field" })));
  });
}

document.getElementById("int-save").addEventListener("click", async () => {
  const provider = document.getElementById("int-provider").value;
  const credentials = {};
  document.querySelectorAll(".int-field").forEach((i) => {
    if (i.value) credentials[i.dataset.field] = i.value;
  });
  if (!Object.keys(credentials).length) { toast("Enter at least one field", true); return; }
  try { await api("/integrations", { method: "POST", body: JSON.stringify({ provider, credentials }) }); toast("Credentials saved (encrypted)"); document.querySelectorAll(".int-field").forEach((i) => (i.value = "")); loadIntegrations(); }
  catch (e) { toast(e.message, true); }
});

async function loadIntegrations() {
  if (!PROVIDERS.length) await initIntegrationProviders();
  const items = await api("/integrations");
  const box = document.getElementById("int-list");
  box.innerHTML = "";
  if (!items.length) { box.append(el("p", { class: "muted" }, "No integrations configured.")); return; }
  items.forEach((it) => {
    const card = el("div", { class: "card" });
    card.append(el("h3", {}, it.label || it.provider));
    const masked = Object.entries(it.masked || {}).map(([k, v]) => `${k}: ${v}`).join("  ·  ");
    card.append(el("p", { class: "muted" }, masked));
    if (it.last_test_at) {
      const cls = it.last_test_ok === true ? "ok" : it.last_test_ok === false ? "warn" : "muted";
      card.append(el("p", {}, el("span", { class: "badge " + cls }, it.last_test_ok === true ? "verified" : it.last_test_ok === false ? "failed" : "stored"), " " + it.last_test_message));
    }
    const testBtn = el("button", { onclick: async () => {
      try { const r = await api(`/integrations/${it.id}/test`, { method: "POST" }); toast(r.message, r.ok === false); loadIntegrations(); }
      catch (e) { toast(e.message, true); }
    } }, "Test");
    const delBtn = el("button", { class: "danger", onclick: async () => {
      try { await api(`/integrations/${it.id}`, { method: "DELETE" }); toast("Deleted"); loadIntegrations(); }
      catch (e) { toast(e.message, true); }
    } }, "Delete");
    card.append(el("div", { class: "row" }, testBtn, delBtn));
    box.append(card);
  });
}

// ---- auth + boot ------------------------------------------------------
function showLogin() {
  document.getElementById("app").classList.add("hidden");
  document.getElementById("login").classList.remove("hidden");
}

function showApp() {
  document.getElementById("login").classList.add("hidden");
  document.getElementById("app").classList.remove("hidden");
}

// ---- Today / work board ----
function workOrderRow(o, actionBtn) {
  const cells = [
    el("td", {}, "#" + o.order_id),
    el("td", {}, o.customer_name),
    el("td", {}, `${o.model_id} ${o.shape} [${(o.runs || []).join(",")}]`),
    el("td", {}, o.status + (o.is_preset ? " · preset" : "")),
  ];
  if (actionBtn) cells.push(el("td", {}, actionBtn));
  return el("tr", {}, ...cells);
}

async function loadWork() {
  const box = document.getElementById("work-board");
  let b;
  try { b = await api("/work/board"); }
  catch (e) { box.innerHTML = ""; box.append(el("p", { class: "muted" }, e.message)); return; }
  box.innerHTML = "";

  // 1. New paid orders -> start build
  const np = el("div", { class: "card" });
  np.append(el("h3", {}, `New paid orders (${b.new_paid.count})`));
  if (!b.new_paid.orders.length) np.append(el("p", { class: "muted" }, "Nothing waiting to start."));
  else {
    const t = el("table");
    t.append(el("tr", {}, el("th", {}, "#"), el("th", {}, "Customer"), el("th", {}, "Build"), el("th", {}, "Status"), el("th", {}, "")));
    b.new_paid.orders.forEach((o) => t.append(workOrderRow(o, el("button", { class: "primary", onclick: () => startBuild(o.order_id) }, "Start build"))));
    np.append(t);
  }
  box.append(np);

  // 2. Build this week
  const fab = el("div", { class: "card" });
  fab.append(el("h3", {}, `Build this week (${b.fabricate.count} order${b.fabricate.count === 1 ? "" : "s"})`));
  if (b.fabricate.build_items.length) {
    fab.append(el("p", { class: "muted" }, "Sections to fabricate:"));
    const t = el("table");
    t.append(el("tr", {}, el("th", {}, "Qty"), el("th", {}, "Item")));
    b.fabricate.build_items.forEach((i) => t.append(el("tr", {}, el("td", {}, String(i.quantity)), el("td", {}, i.name))));
    fab.append(t);
  }
  if (b.fabricate.materials.length) {
    fab.append(el("p", { class: "muted" }, "Materials needed" + (b.fabricate.materials_complete ? ":" : " (incomplete — some per-unit quantities not set):")));
    const t = el("table");
    t.append(el("tr", {}, el("th", {}, "Material"), el("th", {}, "Qty"), el("th", {}, "Unit")));
    b.fabricate.materials.forEach((m) => t.append(el("tr", {}, el("td", {}, m.name), el("td", {}, m.complete ? String(m.quantity) : "?"), el("td", {}, m.unit))));
    fab.append(t);
  }
  if (!b.fabricate.build_items.length && !b.fabricate.materials.length) fab.append(el("p", { class: "muted" }, "Nothing in the build pipeline."));
  box.append(fab);

  // 3. Ready to ship
  const rs = el("div", { class: "card" });
  rs.append(el("h3", {}, `Ready to ship (${b.ready_to_ship.count})`));
  if (!b.ready_to_ship.orders.length) rs.append(el("p", { class: "muted" }, "Nothing ready to ship."));
  else {
    const t = el("table");
    t.append(el("tr", {}, el("th", {}, "#"), el("th", {}, "Customer"), el("th", {}, "Build"), el("th", {}, "Weight"), el("th", {}, "")));
    b.ready_to_ship.orders.forEach((o) => t.append(el("tr", {},
      el("td", {}, "#" + o.order_id), el("td", {}, o.customer_name),
      el("td", {}, `${o.model_id} ${o.shape}`),
      el("td", {}, o.total_weight_lb == null ? "—" : o.total_weight_lb + " lb"),
      el("td", {}, el("button", { class: "primary", onclick: () => shipFromWork(o.order_id) }, "Mark shipped")))));
    rs.append(t);
  }
  box.append(rs);

  // 4. Restock
  const rst = el("div", { class: "card" });
  rst.append(el("h3", {}, "Restock"));
  if (b.restock.low_stock.length) {
    rst.append(el("p", { class: "muted" }, "Low / out of stock:"));
    const t = el("table");
    t.append(el("tr", {}, el("th", {}, "Item"), el("th", {}, "On hand"), el("th", {}, "Reorder at"), el("th", {}, "Co-packer")));
    b.restock.low_stock.forEach((i) => t.append(el("tr", {}, el("td", {}, i.name || i.key), el("td", {}, `${i.on_hand} ${i.unit}`), el("td", {}, String(i.reorder_point)), el("td", {}, i.copacker || "—"))));
    rst.append(t);
  } else rst.append(el("p", { class: "muted" }, "Everything above reorder point."));
  if (b.restock.pending_copacker.length) {
    rst.append(el("p", { class: "muted" }, "Pending co-packer orders:"));
    b.restock.pending_copacker.forEach((c) => {
      const items = (c.items || []).map((i) => `${i.quantity}× ${i.name || i.key}`).join(", ");
      rst.append(el("div", { class: "muted" }, `#${c.id} ${c.copacker || ""} — ${items} (${c.status})`));
    });
  }
  box.append(rst);
}

async function startBuild(id) {
  try { await api(`/work/orders/${id}/start`, { method: "POST" }); toast(`Order #${id} → in production`); loadWork(); }
  catch (e) { toast(e.message, true); }
}

async function shipFromWork(id) {
  const carrier = prompt("Carrier (e.g. UPS):", "UPS");
  if (carrier === null) return;
  const tracking = prompt("Tracking number (optional):", "") || "";
  try { const r = await api(`/orders/${id}/ship`, { method: "POST", body: JSON.stringify({ carrier, tracking }) }); toast(`Order #${id} shipped${r.shipping?.same_day ? " (same-day)" : ""}`); loadWork(); }
  catch (e) { toast(e.message, true); }
}

document.getElementById("work-refresh").addEventListener("click", () => loadWork().catch((e) => toast(e.message, true)));

// ---- staff accounts (owner only) ----
async function loadStaff() {
  const items = await api("/staff");
  const box = document.getElementById("staff-list");
  box.innerHTML = "";
  if (!items.length) { box.append(el("p", { class: "muted" }, "No staff accounts yet.")); return; }
  const table = el("table");
  table.append(el("tr", {}, el("th", {}, "Username"), el("th", {}, "Role"), el("th", {}, "Active"), el("th", {}, "")));
  items.forEach((u) => {
    const toggle = el("button", { onclick: async () => {
      try { await api(`/staff/${u.id}`, { method: "PATCH", body: JSON.stringify({ active: !u.active }) }); toast("Updated"); loadStaff(); }
      catch (e) { toast(e.message, true); }
    } }, u.active ? "Disable" : "Enable");
    const reset = el("button", { onclick: async () => {
      const pw = prompt(`New password for ${u.username}:`);
      if (!pw) return;
      try { await api(`/staff/${u.id}`, { method: "PATCH", body: JSON.stringify({ password: pw }) }); toast("Password reset"); }
      catch (e) { toast(e.message, true); }
    } }, "Reset pw");
    const del = el("button", { class: "danger", onclick: async () => {
      try { await api(`/staff/${u.id}`, { method: "DELETE" }); toast("Removed"); loadStaff(); }
      catch (e) { toast(e.message, true); }
    } }, "Remove");
    table.append(el("tr", {}, el("td", {}, u.username), el("td", {}, u.role),
      el("td", {}, el("span", { class: "badge " + (u.active ? "ok" : "muted") }, u.active ? "active" : "disabled")),
      el("td", {}, toggle, " ", reset, " ", del)));
  });
  box.append(table);
}

document.getElementById("staff-add").addEventListener("click", async () => {
  const username = document.getElementById("staff-user").value.trim();
  const password = document.getElementById("staff-pass").value;
  if (!username || !password) { toast("Username and password required", true); return; }
  try {
    await api("/staff", { method: "POST", body: JSON.stringify({ username, password }) });
    toast("Staff member added");
    document.getElementById("staff-user").value = "";
    document.getElementById("staff-pass").value = "";
    loadStaff();
  } catch (e) { toast(e.message, true); }
});

async function afterAuth() {
  const me = await api("/auth/me");
  ROLE = me.role || "owner";
  showApp();
  applyRole();
  if (ROLE === "owner") {
    await initConfigurator();   // /models is owner-only
  } else {
    document.getElementById("company").textContent = "Staff";
  }
  loadWork().catch(() => {});   // everyone lands on Today
}

async function boot() {
  if (!TOKEN) { showLogin(); return; }
  try {
    await afterAuth();
  } catch (e) {
    showLogin();
  }
}

document.getElementById("login-btn").addEventListener("click", async () => {
  const username = document.getElementById("login-user").value;
  const password = document.getElementById("login-pass").value;
  const err = document.getElementById("login-err");
  err.textContent = "";
  try {
    const res = await fetch(API + "/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username, password }),
    });
    if (!res.ok) { err.textContent = "Invalid username or password."; return; }
    TOKEN = (await res.json()).token;
    localStorage.setItem("mgs_token", TOKEN);
    await afterAuth();
  } catch (e) {
    err.textContent = e.message;
  }
});

document.getElementById("login-pass").addEventListener("keydown", (e) => {
  if (e.key === "Enter") document.getElementById("login-btn").click();
});

document.getElementById("logout-btn").addEventListener("click", () => {
  TOKEN = "";
  localStorage.removeItem("mgs_token");
  showLogin();
});

// ---- go-live setup ----
async function loadSetup() {
  const data = await api("/setup/status");
  const banner = document.getElementById("setup-banner");
  banner.innerHTML = "";
  banner.append(el("div", { class: "card", style: data.ready ? "border-color:var(--ok)" : "border-color:var(--warn)" },
    el("h3", { style: "margin:0" }, data.ready ? "Ready to go live ✓" : "Not ready to go live yet"),
    el("p", { class: "muted", style: "margin:6px 0 0" },
      data.ready ? "All required steps are done. Do one real test purchase to confirm the full loop."
                 : "Finish the required (red) items below. Recommended items improve the experience but won't block sales.")));

  const box = document.getElementById("setup-list");
  box.innerHTML = "";
  const table = el("table");
  table.append(el("tr", {}, el("th", {}, ""), el("th", {}, "Step"), el("th", {}, "Status"), el("th", {}, "Where")));
  data.checks.forEach((c) => {
    const badge = c.ok
      ? el("span", { class: "badge ok" }, "done")
      : el("span", { class: "badge " + (c.required ? "warn" : "muted") }, c.required ? "required" : "recommended");
    table.append(el("tr", {},
      el("td", {}, c.ok ? "✓" : (c.required ? "●" : "○")),
      el("td", {}, el("b", {}, c.label), el("div", { class: "muted" }, c.detail)),
      el("td", {}, badge),
      el("td", { class: "muted" }, c.fix)));
  });
  box.append(table);
}

document.getElementById("setup-refresh").addEventListener("click", () => loadSetup().catch((e) => toast(e.message, true)));

// ---- materials needed ----
document.getElementById("mat-build").addEventListener("click", async () => {
  const status = document.getElementById("mat-status").value;
  try {
    const r = await api(`/production/material-needs?status=${status}`);
    const box = document.getElementById("mat-result");
    box.innerHTML = "";
    box.append(el("p", { class: "muted" }, `${r.order_count} order(s)` + (r.complete ? "" : " — incomplete: some materials have no per-unit quantity set in the catalog")));
    const table = el("table");
    table.append(el("tr", {}, el("th", {}, "Material"), el("th", {}, "Qty"), el("th", {}, "Unit")));
    r.needs.forEach((n) => table.append(el("tr", {}, el("td", {}, n.name), el("td", {}, n.complete ? String(n.quantity) : "?"), el("td", {}, n.unit))));
    box.append(table);
  } catch (e) { toast(e.message, true); }
});

// ---- inventory ----
async function loadInventory() {
  const items = await api("/inventory");
  const box = document.getElementById("inv-list");
  box.innerHTML = "";
  if (!items.length) { box.append(el("p", { class: "muted" }, "No inventory items yet.")); return; }
  const table = el("table");
  table.append(el("tr", {}, el("th", {}, "Kind"), el("th", {}, "Key"), el("th", {}, "Name"), el("th", {}, "On hand"), el("th", {}, "Unit"), el("th", {}, "Reorder"), el("th", {}, "Co-packer"), el("th", {}, "")));
  items.forEach((i) => {
    const onhand = el("input", { type: "number", step: "1", value: i.on_hand, style: "width:80px" });
    const reorder = el("input", { type: "number", step: "1", value: i.reorder_point, style: "width:70px" });
    const save = el("button", { onclick: async () => {
      try { await api("/inventory", { method: "PUT", body: JSON.stringify({ kind: i.kind, key: i.key, name: i.name, on_hand: parseFloat(onhand.value), unit: i.unit, reorder_point: parseFloat(reorder.value), copacker: i.copacker }) }); toast(`Saved ${i.key}`); loadInventory(); }
      catch (e) { toast(e.message, true); }
    } }, "Save");
    table.append(el("tr", { style: i.low ? "background:#fae7d8" : "" },
      el("td", {}, i.kind), el("td", {}, i.key), el("td", {}, i.name),
      el("td", {}, onhand), el("td", {}, i.unit), el("td", {}, reorder), el("td", {}, i.copacker || "—"), el("td", {}, save)));
  });
  box.append(table);
}

document.getElementById("inv-save").addEventListener("click", async () => {
  const body = {
    kind: document.getElementById("inv-kind").value,
    key: document.getElementById("inv-key").value.trim(),
    name: document.getElementById("inv-name").value,
    on_hand: parseFloat(document.getElementById("inv-onhand").value) || 0,
    unit: document.getElementById("inv-unit").value || "each",
    reorder_point: parseFloat(document.getElementById("inv-reorder").value) || 0,
    copacker: document.getElementById("inv-copacker").value,
  };
  if (!body.key) { toast("Key is required", true); return; }
  try { await api("/inventory", { method: "PUT", body: JSON.stringify(body) }); toast("Saved"); loadInventory(); }
  catch (e) { toast(e.message, true); }
});

// ---- presets ----
async function loadPresets() {
  const items = await api("/presets");
  const box = document.getElementById("ps-list");
  box.innerHTML = "";
  if (!items.length) { box.append(el("p", { class: "muted" }, "No presets yet.")); return; }
  const table = el("table");
  table.append(el("tr", {}, el("th", {}, "Name"), el("th", {}, "Build"), el("th", {}, "Price"), el("th", {}, "Verified"), el("th", {}, "Ship"), el("th", {}, "Stock"), el("th", {}, "Active"), el("th", {}, "")));
  items.forEach((p) => {
    const buyable = p.verified_price && p.price_usd && p.on_hand > 0;
    const del = el("button", { class: "danger", onclick: async () => {
      try { await api(`/presets/${p.id}`, { method: "DELETE" }); toast("Deleted"); loadPresets(); }
      catch (e) { toast(e.message, true); }
    } }, "Delete");
    table.append(el("tr", {},
      el("td", {}, p.name),
      el("td", {}, `${p.model_id || "—"} ${p.shape} [${(p.runs || []).join(",")}]`),
      el("td", {}, usd(p.price_usd)),
      el("td", {}, el("span", { class: "badge " + (p.verified_price ? "ok" : "warn") }, p.verified_price ? "yes" : "no")),
      el("td", {}, p.ship_speed),
      el("td", {}, String(p.on_hand)),
      el("td", {}, el("span", { class: "badge " + (buyable ? "ok" : "muted") }, buyable ? "buyable" : (p.active ? "not buyable" : "inactive"))),
      el("td", {}, del)));
  });
  box.append(table);
  box.append(el("p", { class: "muted" }, "Set stock for a preset in the Inventory tab using key preset:<id>."));
}

document.getElementById("ps-save").addEventListener("click", async () => {
  const runs = document.getElementById("ps-runs").value.split(",").map((s) => parseFloat(s.trim())).filter((n) => !isNaN(n));
  const body = {
    name: document.getElementById("ps-name").value,
    model_id: document.getElementById("ps-model").value,
    shape: document.getElementById("ps-shape").value || "straight",
    runs,
    price_usd: document.getElementById("ps-price").value === "" ? null : parseFloat(document.getElementById("ps-price").value),
    verified_price: document.getElementById("ps-verified").checked,
    ship_speed: document.getElementById("ps-ship").value,
  };
  if (!body.name) { toast("Name required", true); return; }
  try { await api("/presets", { method: "POST", body: JSON.stringify(body) }); toast("Preset created (set stock in Inventory)"); loadPresets(); }
  catch (e) { toast(e.message, true); }
});

// ---- co-packer ----
async function loadCopacker() {
  try {
    const cfg = await api("/copacker/config");
    document.getElementById("cp-name").value = cfg.name || "";
    document.getElementById("cp-email").value = cfg.email || "";
  } catch (e) {}
  const orders = await api("/copacker/orders");
  const box = document.getElementById("cp-orders");
  box.innerHTML = "";
  if (!orders.length) { box.append(el("p", { class: "muted" }, "No co-packer orders yet.")); return; }
  const table = el("table");
  table.append(el("tr", {}, el("th", {}, "#"), el("th", {}, "When"), el("th", {}, "Co-packer"), el("th", {}, "Items"), el("th", {}, "Trigger"), el("th", {}, "Status"), el("th", {}, "Emailed")));
  orders.forEach((o) => {
    const items = (o.items || []).map((i) => `${i.quantity}× ${i.name || i.key}`).join(", ");
    table.append(el("tr", {},
      el("td", {}, "#" + o.id),
      el("td", {}, (o.created_at || "").slice(0, 10)),
      el("td", {}, o.copacker || "—"),
      el("td", {}, items),
      el("td", {}, o.trigger),
      el("td", {}, o.status),
      el("td", {}, o.emailed ? "yes" : "no")));
  });
  box.append(table);
}

document.getElementById("cp-save").addEventListener("click", async () => {
  const body = { name: document.getElementById("cp-name").value, email: document.getElementById("cp-email").value };
  try { await api("/copacker/config", { method: "PUT", body: JSON.stringify(body) }); toast("Co-packer contact saved"); }
  catch (e) { toast(e.message, true); }
});

boot();
