"use strict";

const API = "/api";
let MODELS = null;       // {company, models, shapes}
let LAST_QUOTE = null;   // last computed quote request+result
let PROVIDERS = [];      // integration providers
let TOKEN = localStorage.getItem("mgs_token") || "";

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
  if (name === "orders") loadOrders();
  if (name === "catalog") loadCatalog();
  if (name === "production") loadFabSessions();
  if (name === "integrations") loadIntegrations();
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
  MODELS.shapes.forEach((s) => shapeSel.append(el("option", { value: s.name }, `${s.name} (${s.runs} run${s.runs > 1 ? "s" : ""})`)));
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

async function boot() {
  if (!TOKEN) { showLogin(); return; }
  try {
    await api("/auth/me");
    showApp();
    await initConfigurator();
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
    showApp();
    await initConfigurator();
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

boot();
