/* app.js — the LATTICE console front-end.
   Vanilla ES modules, no framework. Talks to the FastAPI backend, renders the
   module grid, runs investigations, and draws the entity graph + map. Read it
   top-to-bottom: state → boot → data load → render → run → overlays. */

import { renderGraph } from "./graph.js";

// ---------------------------------------------------------------- state
const state = {
  plan: localStorage.getItem("plan") || "base",
  deep: false,
  modules: [],
  tiers: [],
  byCat: {},           // category -> [modules]
  detectType: "—",
  upload: null,        // upload token when an image is staged
  uploadName: "",
  lastResult: null,
  graphInstance: null,
  view: "home",
  authorized: false,
};

const CAT_META = {
  social:         { label: "Social & messaging", color: "var(--c-social)" },
  identity:       { label: "Identity & exposure", color: "var(--c-identity)" },
  infrastructure: { label: "Infrastructure",      color: "var(--c-infrastructure)" },
  image:          { label: "Image & geolocation", color: "var(--c-image)" },
  intel:          { label: "Intel & utilities",   color: "var(--c-intel)" },
};
const CAT_ORDER = ["social", "identity", "infrastructure", "image", "intel"];

const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
const el = (tag, cls, html) => { const e = document.createElement(tag); if (cls) e.className = cls; if (html != null) e.innerHTML = html; return e; };
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

// ---------------------------------------------------------------- boot
const BOOT_LINES = [
  ["loading modules", null],
  ["correlation engine", "ready"],
  ["entity graph", "online"],
  ["input detectors", "9 types"],
  ["secure channel", "established"],
];
async function playBoot(count) {
  const box = $("#boot-lines");
  const skip = () => { $("#boot").hidden = true; };
  $("#boot").addEventListener("click", skip);
  for (let i = 0; i < BOOT_LINES.length; i++) {
    const [k, v] = BOOT_LINES[i];
    const val = v ?? String(count);
    const line = el("div");
    line.innerHTML = `<span class="k">[ok]</span> ${k} ${".".repeat(Math.max(2, 22 - k.length))} ${val}`;
    box.appendChild(line);
    await new Promise((r) => setTimeout(r, 260));
  }
  const rdy = el("div"); rdy.innerHTML = `<span class="caret">&gt;</span> ready_`;
  box.appendChild(rdy);
  await new Promise((r) => setTimeout(r, 550));
  $("#boot").hidden = true;
}

// ---------------------------------------------------------------- data
async function loadData() {
  const [h, m] = await Promise.all([
    fetch("/api/health").then((r) => r.json()).catch(() => null),
    fetch("/api/modules").then((r) => r.json()),
  ]);
  state.modules = m.modules;
  state.tiers = m.tiers;
  state.byCat = {};
  for (const mod of m.modules) (state.byCat[mod.category] ||= []).push(mod);
  // health
  const ok = h && h.status === "ok";
  $("#health-dot").className = "dot" + (ok ? "" : " off");
  $("#health-txt").textContent = ok
    ? `${h.modules} modules · ${h.payments_live ? "live pay" : "demo pay"}`
    : "offline";
  return h ? h.modules : m.modules.length;
}

// ---------------------------------------------------------------- sidebar
function renderNav() {
  const nav = $("#nav");
  nav.innerHTML = "";
  nav.appendChild(navItem("home", "All modules", state.modules.length, "var(--accent)"));
  const h = el("div", "nav-h", "Categories"); nav.appendChild(h);
  for (const cat of CAT_ORDER) {
    const list = state.byCat[cat] || [];
    if (!list.length) continue;
    nav.appendChild(navItem(`cat:${cat}`, CAT_META[cat].label, list.length, CAT_META[cat].color));
  }
  const h2 = el("div", "nav-h", "Views"); nav.appendChild(h2);
  nav.appendChild(navItem("results", "Results", "", "var(--likely)"));
  nav.appendChild(navItem("graph", "Entity graph", "", "var(--c-social)"));
  nav.appendChild(navItem("pricing", "Plans", "", "var(--c-intel)"));
}
function navItem(key, label, count, color) {
  const i = el("div", "nav-i");
  i.dataset.key = key;
  i.innerHTML = `<span class="nav-dot" style="background:${color}"></span>
    <span class="nav-label">${esc(label)}</span>
    <span class="nav-count">${count}</span>`;
  i.onclick = () => { onNav(key); closeSidebar(); };
  return i;
}
function onNav(key) {
  $$(".nav-i").forEach((n) => n.classList.toggle("active", n.dataset.key === key));
  if (key === "home") showHome();
  else if (key.startsWith("cat:")) showHome(key.slice(4));
  else if (key === "results") showResults();
  else if (key === "graph") showGraph();
  else if (key === "pricing") showPricing();
}

// ---------------------------------------------------------------- HOME
function showHome(filterCat = null) {
  state.view = "home";
  $("#topbar-title").textContent = filterCat ? CAT_META[filterCat].label : "Console";
  syncTabs("home");
  const c = $("#content");
  c.className = "content view";
  c.innerHTML = "";
  c.appendChild(commandBar());
  c.appendChild(statStrip());

  const cats = filterCat ? [filterCat] : CAT_ORDER;
  for (const cat of cats) {
    const list = (state.byCat[cat] || []).filter((m) => m.inputs.length || m.id === "password_kanon");
    if (!list.length) continue;
    const head = el("div", "section-h");
    head.innerHTML = `<h2>${CAT_META[cat].label}</h2><span class="rule"></span><span class="hint">${list.length} modules</span>`;
    c.appendChild(head);
    const grid = el("div", "grid");
    for (const mod of list) grid.appendChild(moduleTile(mod));
    c.appendChild(grid);
  }
  bindCommandBar();
}

function commandBar() {
  const wrap = el("div", "command");
  wrap.innerHTML = `
    <div class="command-eyebrow">public-signal intelligence</div>
    <div class="command-row">
      <div class="input-wrap">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="7"/><path d="M21 21l-4-4"/></svg>
        <input id="target" placeholder="username, email, domain, IP, phone, hash…" autocomplete="off" spellcheck="false">
        <span class="type-pill" id="type-pill">—</span>
      </div>
      <button class="run-btn" id="run-btn">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4"><path d="M5 12h14M13 6l6 6-6 6"/></svg>
        Correlate
      </button>
    </div>
    <div class="command-opts">
      <button class="chip" id="chip-deep"><span class="toggle-knob"></span> Deep scan</button>
      <button class="chip" id="chip-upload"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 15V3M7 8l5-5 5 5M4 17v2a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-2"/></svg> Upload image</button>
      <button class="chip" id="chip-pw"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="4" y="10" width="16" height="10" rx="2"/><path d="M8 10V7a4 4 0 0 1 8 0v3"/></svg> Check my password</button>
    </div>`;
  return wrap;
}

function statStrip() {
  const s = el("div", "stats");
  const nCat = CAT_ORDER.filter((c) => (state.byCat[c] || []).length).length;
  const cells = [
    [state.modules.length, "Modules"],
    [nCat, "Domains"],
    [state.tiers.length, "Plans"],
    ["100%", "Public data"],
  ];
  s.innerHTML = cells.map(([n, l]) => `<div class="stat"><div class="stat-n">${n}</div><div class="stat-l">${l}</div></div>`).join("");
  return s;
}

function moduleTile(mod) {
  const t = el("div", "mod");
  t.style.setProperty("--cat", CAT_META[mod.category].color);
  const locked = tierIndex(mod.tier) > tierIndex(state.plan);
  t.innerHTML = `
    <div class="mod-top">
      <span class="mod-name">${esc(mod.name)}</span>
      <span class="mod-tier ${locked ? "locked" : ""}">${locked ? "🔒 " : ""}${mod.tier}</span>
    </div>
    <div class="mod-desc">${esc(mod.description)}</div>
    <div class="mod-cat">${mod.category}</div>`;
  t.onclick = () => {
    if (mod.id === "password_kanon") return openPwCheck();
    if (locked) return showPricing();
    const inp = $("#target");
    if (inp && inp.value.trim()) runSingle(mod.id);
    else { inp?.focus(); toast("Enter a target above, then tap a module"); }
  };
  return t;
}

// ---------------------------------------------------------------- command bar behaviour
let detectTimer = null;
function bindCommandBar() {
  const inp = $("#target");
  if (!inp) return;
  inp.addEventListener("input", () => {
    clearTimeout(detectTimer);
    detectTimer = setTimeout(async () => {
      const q = inp.value.trim();
      if (!q) { $("#type-pill").textContent = "—"; return; }
      try {
        const d = await fetch("/api/detect?q=" + encodeURIComponent(q)).then((r) => r.json());
        $("#type-pill").textContent = d.label;
        state.detectType = d.input_type;
      } catch {}
    }, 220);
  });
  inp.addEventListener("keydown", (e) => { if (e.key === "Enter") runAll(); });
  $("#run-btn").onclick = runAll;
  $("#chip-deep").onclick = (e) => {
    state.deep = !state.deep;
    e.currentTarget.classList.toggle("on", state.deep);
  };
  $("#chip-upload").onclick = () => $("#file-input").click();
  $("#chip-pw").onclick = openPwCheck;
}

// ---------------------------------------------------------------- RUN
function setProgress(on) { $("#progress").classList.toggle("on", on); if (on) $("#progress").style.width = "35%"; else $("#progress").style.width = "0"; }

async function runAll() {
  const target = $("#target")?.value.trim();
  if (!target && !state.upload) return toast("Enter a target first");
  setProgress(true);
  showResults(true);
  try {
    const body = { target, plan: state.plan, deep: state.deep, authorized: state.authorized };
    if (state.upload) body.upload = state.upload;
    $("#progress").style.width = "70%";
    const res = await fetch("/api/run", {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
    }).then((r) => r.json());
    state.lastResult = res;
    renderResults(res);
  } catch (e) {
    $("#content").innerHTML = `<div class="card err"><div class="card-head"><span class="card-title">Run failed</span></div><div class="card-body"><table class="rec"><tr><td class="v">${esc(e)}</td></tr></table></div></div>`;
  } finally {
    $("#progress").style.width = "100%";
    setTimeout(() => setProgress(false), 300);
  }
}

async function runSingle(moduleId) {
  const target = $("#target")?.value.trim();
  setProgress(true);
  showResults(true);
  try {
    const body = { module: moduleId, target, plan: state.plan, deep: state.deep };
    if (state.upload) body.upload = state.upload;
    const res = await fetch("/api/run_module", {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
    }).then((r) => r.json());
    state.lastResult = res;
    renderResults(res);
  } finally {
    setProgress(false);
  }
}

// ---------------------------------------------------------------- RESULTS view
function showResults(loading = false) {
  state.view = "results";
  $("#topbar-title").textContent = "Results";
  syncTabs("results");
  const c = $("#content");
  c.className = "content view";
  if (loading) {
    c.innerHTML = `<div class="results">${'<div class="skel"></div>'.repeat(5)}</div>`;
  } else if (state.lastResult) {
    renderResults(state.lastResult);
  } else {
    c.innerHTML = emptyState("No results yet", "Run a target from the console to see findings here.");
  }
}

function renderResults(res) {
  const c = $("#content");
  c.className = "content view";
  c.innerHTML = "";
  const st = res.stats || {};
  // toolbar
  const bar = el("div", "rtoolbar");
  bar.innerHTML = `<span class="target">${esc(res.target || "—")}</span>
    <span class="rstat">${st.ok || 0} ok · ${st.failed || 0} failed · ${st.nodes || 0} entities · ${st.edges || 0} links</span>`;
  if (res.graph && (res.graph.nodes || []).length) {
    const gb = el("button", "chip", "View graph →");
    gb.onclick = showGraph; bar.appendChild(gb);
  }
  c.appendChild(bar);

  // map (if any module returned a point)
  const mapPoint = collectMapPoint(res);
  if (mapPoint) c.appendChild(mapTile(mapPoint));

  const wrap = el("div", "results");
  const mods = (res.modules || []).slice().sort((a, b) => (b.ok - a.ok) || (b.findings.length - a.findings.length));
  if (!mods.length) wrap.innerHTML = emptyState("Nothing ran", "No modules matched this input on your plan.");
  for (const m of mods) wrap.appendChild(resultCard(m));
  c.appendChild(wrap);

  if (res.skipped && res.skipped.length) {
    const note = el("div", "section-h");
    note.innerHTML = `<span class="hint">🔒 ${res.skipped.length} module(s) need a higher plan</span><span class="rule"></span>`;
    note.style.cursor = "pointer"; note.onclick = showPricing;
    c.appendChild(note);
  }
}

function resultCard(m) {
  const meta = state.modules.find((x) => x.id === m.module) || {};
  const cat = meta.category || "intel";
  const card = el("div", "card" + (m.ok ? "" : " err"));
  const head = el("div", "card-head");
  head.innerHTML = `
    <span class="card-dot" style="background:${CAT_META[cat]?.color || "var(--info)"}"></span>
    <span class="card-title">${esc(meta.name || m.module)}</span>
    <span class="card-sum">${esc(m.summary || (m.ok ? "" : m.error || "error"))}</span>
    <span class="card-meta">${m.elapsed_ms ?? 0}ms${m.extra && m.extra.cached ? " · cached" : ""}</span>
    <svg class="card-chev" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="width:16px;height:16px"><path d="M9 6l6 6-6 6"/></svg>`;
  head.onclick = () => card.classList.toggle("open");
  card.appendChild(head);

  const body = el("div", "card-body");
  if (!m.ok) {
    body.innerHTML = `<table class="rec"><tr><td class="k">error</td><td class="v">${esc(m.error)}</td></tr></table>`;
  } else if (!(m.findings || []).length) {
    body.innerHTML = `<table class="rec"><tr><td class="v" style="color:var(--text-3)">No findings.</td></tr></table>`;
  } else {
    const tbl = el("table", "rec");
    for (const f of m.findings) tbl.appendChild(findingRow(f));
    body.appendChild(tbl);
    // embedded image (ELA etc.)
    if (m.extra && m.extra.image_b64) {
      const img = el("img"); img.src = m.extra.image_b64;
      img.style.cssText = "width:100%;border-radius:8px;margin-top:12px";
      body.appendChild(img);
    }
  }
  card.appendChild(body);
  // auto-open the first few informative cards
  if (m.ok && (m.findings || []).length) card.classList.add("open");
  return card;
}

function findingRow(f) {
  const tr = el("tr");
  const val = f.link
    ? `<a href="${esc(f.link)}" target="_blank" rel="noopener">${esc(f.value)}</a>`
    : esc(f.value);
  const pivot = f.pivot ? `<span class="pivot" data-pivot="${esc(f.pivot)}">↳ pivot</span>` : "";
  tr.innerHTML = `<td class="k">${esc(f.key)} <span class="pill ${f.confidence}">${f.confidence}</span></td>
    <td class="v">${val}${pivot}</td>`;
  const pv = tr.querySelector(".pivot");
  if (pv) pv.onclick = () => { const i = ensureInput(); i.value = pv.dataset.pivot; onNav("home"); setTimeout(() => { $("#target").value = pv.dataset.pivot; runAll(); }, 50); };
  return tr;
}
function ensureInput() { if (!$("#target")) showHome(); return $("#target"); }

// ---------------------------------------------------------------- GRAPH view
function showGraph() {
  state.view = "graph";
  $("#topbar-title").textContent = "Entity graph";
  syncTabs("graph");
  const c = $("#content");
  c.className = "content view";
  c.innerHTML = "";
  const g = state.lastResult && state.lastResult.graph;
  if (!g || !g.nodes.length) {
    c.innerHTML = emptyState("Empty graph", "Run a target — discovered entities and their links appear here.");
    return;
  }
  const wrap = el("div", "graph-wrap");
  wrap.innerHTML = `<canvas id="graph"></canvas><div class="graph-legend" id="legend"></div>`;
  c.appendChild(wrap);
  // legend
  const types = [...new Set(g.nodes.map((n) => n.type))];
  $("#legend").innerHTML = types.map((t) =>
    `<span class="leg"><i style="background:var(--n-${t},#6d6b7e)"></i>${t}</span>`).join("");
  if (state.graphInstance) state.graphInstance.stop();
  requestAnimationFrame(() => { state.graphInstance = renderGraph($("#graph"), g); });
}

// ---------------------------------------------------------------- MAP
function collectMapPoint(res) {
  for (const m of res.modules || []) {
    if (m.extra && m.extra.map) return m.extra.map;
  }
  return null;
}
function mapTile(point) {
  const box = el("div");
  box.style.marginBottom = "var(--s3)";
  box.innerHTML = `<div id="map"></div>`;
  requestAnimationFrame(() => {
    if (!window.L) return;
    const map = L.map("map", { attributionControl: false, zoomControl: true }).setView([point.lat, point.lon], 11);
    L.tileLayer("https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}.png", { maxZoom: 19 }).addTo(map);
    L.circleMarker([point.lat, point.lon], { radius: 9, color: "#8b7cff", fillColor: "#8b7cff", fillOpacity: .5 })
      .addTo(map).bindPopup(point.label || "location").openPopup();
  });
  return box;
}

// ---------------------------------------------------------------- PRICING
function showPricing() {
  state.view = "pricing";
  $("#topbar-title").textContent = "Plans";
  syncTabs("pricing");
  const c = $("#content");
  c.className = "content view";
  c.innerHTML = `<div class="section-h"><h2>Plans</h2><span class="rule"></span><span class="hint">crypto & PayPal · on-chain confirmation</span></div>`;
  const grid = el("div", "plans");
  for (const t of state.tiers) {
    const cur = t.id === state.plan;
    const p = el("div", "plan" + (cur ? " cur" : ""));
    const n = (state.byCat && Object.values(state.byCat).flat().filter((m) => tierIndex(m.tier) <= tierIndex(t.id)).length) || 0;
    p.innerHTML = `
      <div class="plan-name">${t.name}</div>
      <div class="plan-price">$${t.price_usd}<small>/mo</small></div>
      <div class="plan-blurb">${esc(t.blurb)}</div>
      <div class="plan-blurb" style="color:var(--text-3)">${n} modules unlocked</div>
      <button class="plan-btn">${cur ? "Current plan" : (t.price_usd === 0 ? "Switch to free" : "Upgrade")}</button>`;
    p.querySelector(".plan-btn").onclick = () => {
      if (cur) return;
      if (t.price_usd === 0) { setPlan("base"); toast("Switched to Base"); showPricing(); }
      else openCheckout(t);
    };
    grid.appendChild(p);
  }
  c.appendChild(grid);
}

// ---------------------------------------------------------------- overlays
function overlay(html, opts = {}) {
  const o = el("div", "overlay" + (opts.center ? " center" : ""));
  o.innerHTML = html;
  o.addEventListener("click", (e) => { if (e.target === o) o.remove(); });
  $("#overlays").appendChild(o);
  return o;
}

function openCheckout(tier) {
  let asset = "BTC";
  const o = overlay(`<div class="panel"><div class="panel-head"><h3>Upgrade to ${tier.name}</h3><button class="close-x">✕</button></div>
    <div class="panel-body">
      <div class="pay-assets">
        ${["BTC", "ETH", "USDT"].map((a) => `<div class="pay-asset ${a === "BTC" ? "on" : ""}" data-a="${a}">${a}</div>`).join("")}
      </div>
      <div id="pay-area"><div class="skel"></div></div>
    </div></div>`, { center: true });
  o.querySelector(".close-x").onclick = () => o.remove();
  o.querySelectorAll(".pay-asset").forEach((b) => b.onclick = () => {
    o.querySelectorAll(".pay-asset").forEach((x) => x.classList.remove("on"));
    b.classList.add("on"); asset = b.dataset.a; createInvoice();
  });

  let pollTimer = null;
  async function createInvoice() {
    const area = o.querySelector("#pay-area");
    area.innerHTML = `<div class="skel"></div>`;
    const inv = await fetch("/api/pay/create", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ plan: tier.id, asset }),
    }).then((r) => r.json());
    area.innerHTML = `
      <div class="pay-box">
        <div class="pay-row"><span class="lab">Plan</span><span>${tier.name} · $${inv.price_usd}</span></div>
        <div class="pay-row"><span class="lab">Amount</span><span>${inv.amount} ${inv.asset}</span></div>
        <div class="pay-row"><span class="lab">Rate</span><span>1 ${inv.asset} ≈ $${Math.round(inv.rate_usd).toLocaleString()}</span></div>
        <div class="pay-row"><span class="lab">Send to</span><span></span></div>
        <div class="pay-addr">${esc(inv.address)}</div>
      </div>
      ${inv.paypal ? `<a class="btn ghost full" style="display:block;text-align:center;margin-top:12px;text-decoration:none" href="${esc(inv.paypal)}" target="_blank">Pay $${inv.price_usd} with PayPal</a>` : ""}
      ${inv.demo ? `<div class="pw-note">Demo mode — no receiving wallet configured. Verifying will unlock instantly so you can test the flow.</div>` : `<div class="pw-note">Send the exact amount, then tap verify. We confirm it directly on the public blockchain — no third-party processor.</div>`}
      <button class="btn full" id="verify-btn" style="margin-top:12px">I've paid — verify</button>
      <div class="pay-status pending" id="pay-status" hidden>Waiting for confirmation…</div>`;
    o.querySelector("#verify-btn").onclick = () => verify(inv.id);
  }
  async function verify(id) {
    const stat = o.querySelector("#pay-status");
    stat.hidden = false; stat.className = "pay-status pending"; stat.textContent = "Checking blockchain…";
    const r = await fetch("/api/pay/verify?invoice=" + id).then((x) => x.json());
    if (r.status === "paid") {
      stat.className = "pay-status paid"; stat.textContent = "✓ Payment confirmed — plan unlocked";
      setPlan(tier.id);
      setTimeout(() => { o.remove(); showPricing(); toast(`Upgraded to ${tier.name}`); }, 1100);
    } else {
      stat.className = "pay-status pending";
      stat.textContent = "Not seen yet — try again in a moment.";
    }
  }
  createInvoice();
}

function openPwCheck() {
  const o = overlay(`<div class="panel"><div class="panel-head"><h3>Password exposure check</h3><button class="close-x">✕</button></div>
    <div class="panel-body">
      <input type="password" class="pw-input" id="pw-in" placeholder="type a password to test…" autocomplete="off">
      <button class="btn full" id="pw-go" style="margin-top:12px">Check safely</button>
      <div class="pw-note">🔒 k-anonymity: your browser hashes the password with SHA-1 and sends only the first <b>5 characters</b> of that hash to the public range API. The password itself never leaves this device.</div>
      <div id="pw-out"></div>
    </div></div>`, { center: true });
  o.querySelector(".close-x").onclick = () => o.remove();
  const go = async () => {
    const pw = o.querySelector("#pw-in").value;
    if (!pw) return;
    const out = o.querySelector("#pw-out");
    out.innerHTML = `<div class="skel" style="margin-top:16px"></div>`;
    try {
      const buf = await crypto.subtle.digest("SHA-1", new TextEncoder().encode(pw));
      const hash = [...new Uint8Array(buf)].map((b) => b.toString(16).padStart(2, "0")).join("").toUpperCase();
      const prefix = hash.slice(0, 5), suffix = hash.slice(5);
      const txt = await fetch("https://api.pwnedpasswords.com/range/" + prefix).then((r) => r.text());
      const line = txt.split("\n").find((l) => l.split(":")[0] === suffix);
      const count = line ? parseInt(line.split(":")[1]) : 0;
      out.innerHTML = count
        ? `<div class="pw-result pwned">⚠ Seen ${count.toLocaleString()} times in breaches — do not use it.</div>`
        : `<div class="pw-result safe">✓ Not found in known breaches.</div>`;
    } catch (e) {
      out.innerHTML = `<div class="pw-result pwned">Check failed: ${esc(e)}</div>`;
    }
  };
  o.querySelector("#pw-go").onclick = go;
  o.querySelector("#pw-in").addEventListener("keydown", (e) => { if (e.key === "Enter") go(); });
  setTimeout(() => o.querySelector("#pw-in").focus(), 50);
}

// command palette
function openCmdk() {
  const o = overlay(`<div class="panel"><div class="panel-body" style="padding-top:20px">
    <input class="cmdk-input" id="cmdk-in" placeholder="jump to a module…" autocomplete="off">
    <div class="cmdk-list" id="cmdk-list"></div>
  </div></div>`);
  const list = o.querySelector("#cmdk-list");
  const inp = o.querySelector("#cmdk-in");
  const render = (q = "") => {
    const items = state.modules.filter((m) => (m.name + m.description + m.category).toLowerCase().includes(q.toLowerCase())).slice(0, 40);
    list.innerHTML = items.map((m) => `<div class="cmdk-i" data-id="${m.id}"><span class="nav-dot" style="background:${CAT_META[m.category]?.color}"></span><span class="n">${esc(m.name)}</span><span class="d">${m.tier}</span></div>`).join("");
    list.querySelectorAll(".cmdk-i").forEach((it) => it.onclick = () => {
      o.remove();
      const t = $("#target");
      if (t && t.value.trim()) runSingle(it.dataset.id);
      else { showHome(state.modules.find((m) => m.id === it.dataset.id)?.category); toast("Enter a target, then tap the module"); }
    });
  };
  inp.addEventListener("input", () => render(inp.value));
  render();
  setTimeout(() => inp.focus(), 50);
}

// ---------------------------------------------------------------- helpers
function emptyState(title, sub) {
  return `<div class="card"><div class="card-body" style="display:block"><div style="text-align:center;padding:48px 16px;color:var(--text-3)">
    <div style="font-size:16px;color:var(--text-2);margin-bottom:6px">${esc(title)}</div><div style="font-size:13px">${esc(sub)}</div></div></div></div>`;
}
function tierIndex(t) { const order = ["base", "premium", "elite", "master"]; return order.indexOf(t) < 0 ? 0 : order.indexOf(t); }
function setPlan(p) { state.plan = p; localStorage.setItem("plan", p); renderNav(); }
function toast(msg) {
  const t = el("div", "toast", esc(msg));
  document.body.appendChild(t);
  setTimeout(() => t.remove(), 2600);
}
function syncTabs(view) { $$(".tab").forEach((t) => t.classList.toggle("active", t.dataset.view === view)); }
function closeSidebar() { $("#sidebar").classList.remove("open"); $(".sidebar-backdrop")?.remove(); }
function openSidebar() {
  $("#sidebar").classList.add("open");
  const b = el("div", "sidebar-backdrop"); b.onclick = closeSidebar;
  document.body.appendChild(b);
}

// ---------------------------------------------------------------- wire up
function wireGlobal() {
  $("#menu-btn").onclick = openSidebar;
  $("#sidebar-x").onclick = closeSidebar;
  $("#cmdk-btn").onclick = openCmdk;
  document.addEventListener("keydown", (e) => {
    if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") { e.preventDefault(); openCmdk(); }
    if (e.key === "Escape") $(".overlay")?.remove();
  });
  $$(".tab").forEach((t) => t.onclick = () => onNav(t.dataset.view === "home" ? "home" : t.dataset.view));
  // image upload
  $("#file-input").addEventListener("change", async (e) => {
    const file = e.target.files[0]; if (!file) return;
    toast("Uploading image…");
    const fd = new FormData(); fd.append("file", file);
    const r = await fetch("/api/upload", { method: "POST", body: fd }).then((x) => x.json());
    if (r.upload) {
      state.upload = r.upload; state.uploadName = r.filename;
      const chip = $("#chip-upload");
      if (chip) { chip.classList.add("on"); chip.lastChild.textContent = ` ${r.filename.slice(0, 18)}`; }
      $("#type-pill") && ($("#type-pill").textContent = "image");
      toast("Image staged — tap Correlate or an image module");
    }
  });
}

// ---------------------------------------------------------------- init
(async function init() {
  wireGlobal();
  const count = await loadData().catch(() => 0);
  renderNav();
  onNav("home");
  await playBoot(count);
  // register PWA service worker
  if ("serviceWorker" in navigator) navigator.serviceWorker.register("/sw.js").catch(() => {});
})();
