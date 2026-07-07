/* app.js — the LIMBO console front-end.
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

// Small inline icons per category (stroke inherits the category colour).
const CAT_ICON = {
  social: `<path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 0 0-3-3.87M16 3.13a4 4 0 0 1 0 7.75"/>`,
  identity: `<path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/>`,
  infrastructure: `<rect x="2" y="2" width="20" height="8" rx="2"/><rect x="2" y="14" width="20" height="8" rx="2"/><path d="M6 6h.01M6 18h.01"/>`,
  image: `<rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="8.5" cy="8.5" r="1.5"/><path d="M21 15l-5-5L5 21"/>`,
  intel: `<circle cx="11" cy="11" r="7"/><path d="M21 21l-4-4"/>`,
};
const catSvg = (cat) => `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">${CAT_ICON[cat] || ""}</svg>`;

const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
const el = (tag, cls, html) => { const e = document.createElement(tag); if (cls) e.className = cls; if (html != null) e.innerHTML = html; return e; };
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

// ---------------------------------------------------------------- boot
const BOOT_LINES = [
  ["loading modules", null],
  ["correlation core", "ready"],
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
// Fetch with a few retries — preview tunnels can hiccup or rotate.
async function fetchRetry(url, opts, tries = 3) {
  let lastErr;
  for (let i = 0; i < tries; i++) {
    try {
      const r = await fetch(url, opts);
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      return r;
    } catch (e) {
      lastErr = e;
      await new Promise((res) => setTimeout(res, 400 * (i + 1)));
    }
  }
  throw lastErr;
}

async function loadData() {
  let m;
  try {
    const r = await fetchRetry("/api/modules", {}, 4);
    m = await r.json();
  } catch (e) {
    state.offline = true;
    return 0;
  }
  const h = await fetch("/api/health").then((r) => r.json()).catch(() => null);
  state.offline = false;
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

// ---------------------------------------------------------------- HOME (simple)
// Three focused lookups. Each just searches the LEGAL, public-data sources for
// that input type; the engine picks the right modules automatically.
// Social-only: a person's public social footprint. Username + Email.
const MODES = {
  username: {
    label: "Username", icon: `<path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/>`,
    ph: "@username or social handle…", ex: ["octocat", "torvalds", "jack"],
    checks: ["Public profiles across 660+ platforms", "Which social & messaging accounts exist", "Public bio, links & self-declared identity"],
  },
  email: {
    label: "Email", icon: `<rect x="3" y="5" width="18" height="14" rx="2"/><path d="M3 7l9 6 9-6"/>`,
    ph: "name@example.com…", ex: ["someone@example.com"],
    checks: ["Public Gravatar profile & linked social accounts", "Which public breaches list it — names only, no passwords", "Self-exposure score"],
  },
};

function showHome() {
  state.view = "home";
  state.mode = state.mode || "username";
  $("#topbar-title").textContent = "Search";
  syncTabs("home");
  const c = $("#content");
  c.className = "content view";
  c.innerHTML = "";

  const wrap = el("div", "lookup");
  wrap.innerHTML = `
    <div class="lk-eyebrow">public-footprint osint · public data only</div>
    <h1 class="lk-title">Search a person's <span class="tt">public</span> footprint.</h1>
    <div class="seg" id="seg">
      ${Object.entries(MODES).map(([k, m]) => `<button class="seg-b ${k === state.mode ? "on" : ""}" data-m="${k}">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">${m.icon}</svg>${m.label}</button>`).join("")}
    </div>
    <div class="lk-row">
      <div class="input-wrap">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="7"/><path d="M21 21l-4-4"/></svg>
        <input id="target" placeholder="${MODES[state.mode].ph}" autocomplete="off" spellcheck="false">
        <span class="type-pill" id="type-pill">—</span>
      </div>
      <button class="run-btn" id="run-btn"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4"><path d="M5 12h14M13 6l6 6-6 6"/></svg> Search</button>
    </div>
    <div class="lk-ex" id="lk-ex"></div>
    <div class="lk-recent" id="lk-recent"></div>
    <div class="lk-checks" id="lk-checks"></div>`;
  c.appendChild(wrap);
  renderMode();
  renderRecent();
  bindCommandBar();
  $$("#seg .seg-b").forEach((b) => b.onclick = () => {
    state.mode = b.dataset.m;
    $$("#seg .seg-b").forEach((x) => x.classList.toggle("on", x === b));
    const inp = $("#target"); inp.placeholder = MODES[state.mode].ph; inp.value = "";
    $("#type-pill").textContent = "—";
    renderMode();
  });
}

function renderMode() {
  const m = MODES[state.mode];
  const ex = $("#lk-ex");
  ex.innerHTML = `<span class="ex-label">try</span>` +
    m.ex.map((e) => `<button class="ex" data-ex="${esc(e)}">${esc(e)}</button>`).join("");
  ex.querySelectorAll(".ex").forEach((b) => b.onclick = () => {
    const inp = $("#target"); inp.value = b.dataset.ex; inp.dispatchEvent(new Event("input")); runAll();
  });
  $("#lk-checks").innerHTML = `<div class="lk-checks-h">What we check</div>` +
    m.checks.map((t) => `<div class="lk-check"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4"><path d="M20 6 9 17l-5-5"/></svg>${esc(t)}</div>`).join("");
}

// --- recent searches (local, private to this browser) ----------------------
function recentGet() { try { return JSON.parse(localStorage.getItem("recent") || "[]"); } catch { return []; } }
function recentAdd(q, mode) {
  if (!q) return;
  let list = recentGet().filter((r) => !(r.q === q && r.mode === mode));
  list.unshift({ q, mode, t: Date.now() });
  localStorage.setItem("recent", JSON.stringify(list.slice(0, 8)));
}
function renderRecent() {
  const box = $("#lk-recent"); if (!box) return;
  const list = recentGet();
  if (!list.length) { box.innerHTML = ""; return; }
  box.innerHTML = `<span class="ex-label">recent</span>` +
    list.map((r) => `<button class="rec-chip" data-q="${esc(r.q)}" data-m="${esc(r.mode)}" title="${esc(r.mode)}">${esc(r.q)}</button>`).join("") +
    `<button class="rec-clear" id="rec-clear" title="clear">✕</button>`;
  box.querySelectorAll(".rec-chip").forEach((b) => b.onclick = () => {
    if (b.dataset.m && MODES[b.dataset.m]) {
      state.mode = b.dataset.m;
      $$("#seg .seg-b").forEach((x) => x.classList.toggle("on", x.dataset.m === state.mode));
      renderMode();
    }
    const inp = $("#target"); inp.value = b.dataset.q; inp.dispatchEvent(new Event("input")); runAll();
  });
  const clr = $("#rec-clear");
  if (clr) clr.onclick = () => { localStorage.removeItem("recent"); renderRecent(); };
}

function commandBar() {
  const wrap = el("div", "command");
  wrap.innerHTML = `
    <div class="command-eyebrow">people · public-footprint osint</div>
    <h1 class="command-title">Map anyone's <span class="tt">public</span> footprint.</h1>
    <p class="command-lede">Give a username, handle or email — see where a person is publicly present online and how exposed they are. Public data only.</p>
    <div class="command-row">
      <div class="input-wrap">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="7"/><path d="M21 21l-4-4"/></svg>
        <input id="target" placeholder="@username, social handle or email…" autocomplete="off" spellcheck="false">
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
    </div>
    <div class="examples">
      <span class="ex-label">try</span>
      ${["octocat", "torvalds", "jack", "someone@example.com"].map((e) => `<button class="ex" data-ex="${esc(e)}">${esc(e)}</button>`).join("")}
    </div>`;
  return wrap;
}

function statStrip() {
  const s = el("div", "stats");
  const social = (state.byCat.social || []).length + (state.byCat.identity || []).length;
  const cells = [
    [state.modules.length, "Modules"],
    [social, "People signals"],
    [40, "Platforms"],
    ["100%", "Public data"],
  ];
  s.innerHTML = cells.map(([n, l]) => {
    const num = typeof n === "number";
    return `<div class="stat"><div class="stat-n" ${num ? `data-count="${n}"` : ""}>${num ? "0" : n}</div><div class="stat-l">${l}</div></div>`;
  }).join("");
  requestAnimationFrame(() => $$(".stat-n[data-count]", s).forEach(countUp));
  return s;
}

// Animate a number from 0 to its data-count over ~600ms.
function countUp(node) {
  const target = parseInt(node.dataset.count, 10);
  const start = performance.now(), dur = 650;
  function tick(now) {
    const p = Math.min((now - start) / dur, 1);
    const eased = 1 - Math.pow(1 - p, 3);
    node.textContent = Math.round(target * eased);
    if (p < 1) requestAnimationFrame(tick);
  }
  requestAnimationFrame(tick);
}

function moduleTile(mod) {
  const t = el("div", "mod");
  t.style.setProperty("--cat", CAT_META[mod.category].color);
  const locked = tierIndex(mod.tier) > tierIndex(state.plan);
  const cc = CAT_META[mod.category].color;
  t.innerHTML = `
    <div class="mod-top">
      <span class="mod-ico" style="color:${cc}">${catSvg(mod.category)}</span>
      <span class="mod-name">${esc(mod.name)}</span>
      <span class="mod-tier ${locked ? "locked" : ""}">${locked ? "🔒 " : ""}${mod.tier}</span>
    </div>
    <div class="mod-desc">${esc(mod.description)}</div>
    <div class="mod-go">Run <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4"><path d="M5 12h14M13 6l6 6-6 6"/></svg></div>`;
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
  const rb = $("#run-btn"); if (rb) rb.onclick = runAll;
  // Optional controls (present only on the advanced command bar).
  const cd = $("#chip-deep"); if (cd) cd.onclick = (e) => { state.deep = !state.deep; e.currentTarget.classList.toggle("on", state.deep); };
  const cu = $("#chip-upload"); if (cu) cu.onclick = () => $("#file-input").click();
  const cp = $("#chip-pw"); if (cp) cp.onclick = openPwCheck;
}

// ---------------------------------------------------------------- RUN
function setProgress(on) { $("#progress").classList.toggle("on", on); if (on) $("#progress").style.width = "35%"; else $("#progress").style.width = "0"; }

async function runAll() {
  const target = $("#target")?.value.trim();
  if (!target && !state.upload) return toast("Enter a target first");
  if (target) recentAdd(target, state.mode);
  setProgress(true);
  state.view = "results";
  syncTabs("results");
  $("#topbar-title").textContent = "Results";

  // progressive result scaffold
  const c = $("#content");
  c.className = "content view";
  c.innerHTML = `<div class="rtoolbar">
      <span class="target">${esc(target || "image")}</span>
      <span class="rstat" id="live-stat">starting…</span></div>
    <div class="scanning" id="scanbar"><span class="scan-dot"></span> <span id="scan-txt">Correlating…</span></div>
    <div class="dash" id="live-dash"></div>
    <div class="results" id="live-results"></div>`;
  const live = { modules: [], graph: { nodes: [], edges: [] }, stats: {}, target, input_type: "" };
  let expected = 0, doneCount = 0;

  const body = { target, plan: state.plan, deep: state.deep, authorized: state.authorized };
  if (state.upload) body.upload = state.upload;

  try {
    const resp = await fetch("/api/run_stream", {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
    });
    if (!resp.ok || !resp.body) throw new Error("HTTP " + resp.status);

    const reader = resp.body.getReader();
    const dec = new TextDecoder();
    let buf = "";
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buf += dec.decode(value, { stream: true });
      const chunks = buf.split("\n\n");
      buf = chunks.pop();
      for (const chunk of chunks) {
        const ev = parseSSE(chunk);
        if (!ev) continue;
        if (ev.event === "meta") {
          expected = ev.data.total;
          live.input_type = ev.data.input_type;
          live.skipped = ev.data.skipped;
          $("#scan-txt").textContent = `Correlating ${expected} modules…`;
          $("#progress").style.width = "15%";
        } else if (ev.event === "module") {
          live.modules.push(ev.data);
          doneCount++;
          appendLiveCard(ev.data);
          updateLiveStats(live, doneCount, expected);
          $("#progress").style.width = Math.min(15 + (doneCount / Math.max(expected, 1)) * 80, 96) + "%";
        } else if (ev.event === "done") {
          live.graph = ev.data.graph;
          live.stats = ev.data.stats;
          state.lastResult = live;
          finalizeLive(live);
        }
      }
    }
  } catch (e) {
    $("#content").innerHTML = `<div class="card err open">
      <div class="card-head"><span class="card-dot" style="background:var(--bad)"></span>
        <span class="card-title">Couldn't reach the server</span></div>
      <div class="card-body"><table class="rec">
        <tr><td class="k">reason</td><td class="v">${esc(String(e && e.message || e))}</td></tr>
        <tr><td class="k">likely cause</td><td class="v">the preview link may have rotated — reload, get the current link, or deploy to a permanent host</td></tr>
      </table><div style="padding:12px 16px"><button class="btn" onclick="location.reload()">Reload</button></div>
      </div></div>`;
  } finally {
    $("#progress").style.width = "100%";
    setTimeout(() => setProgress(false), 300);
  }
}

function parseSSE(chunk) {
  let event = "message", data = "";
  for (const line of chunk.split("\n")) {
    if (line.startsWith("event:")) event = line.slice(6).trim();
    else if (line.startsWith("data:")) data += line.slice(5).trim();
  }
  if (!data) return null;
  try { return { event, data: JSON.parse(data) }; } catch { return null; }
}

function appendLiveCard(m) {
  const wrap = $("#live-results");
  if (!wrap) return;
  // only surface cards that actually found something first; keep failures last
  const card = resultCard(m);
  if (!m.ok || !(m.findings || []).length) card.classList.add("muted");
  wrap.appendChild(card);
}

function updateLiveStats(live, done, expected) {
  const findings = live.modules.reduce((a, m) => a + (m.findings || []).length, 0);
  const hits = live.modules.filter((m) => m.ok && (m.findings || []).length).length;
  const ls = $("#live-stat");
  if (ls) ls.textContent = `${done}/${expected} modules · ${findings} findings`;
  const dash = $("#live-dash");
  if (dash) dash.innerHTML = [[hits, "with data"], [findings, "findings"], [done, "done"], [expected - done, "pending"]]
    .map(([n, l]) => `<div class="dash-cell"><div class="dash-n">${n}</div><div class="dash-l">${l}</div></div>`).join("");
}

function finalizeLive(live) {
  const sb = $("#scanbar"); if (sb) sb.remove();
  updateLiveStats(live, live.stats.total, live.stats.total);
  // re-render sorted (hits first) + add graph/map/export via the standard renderer
  renderResults(live);
  toast(`${live.stats.ok} modules · ${live.stats.nodes} entities`);
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

// Pull the highest-signal facts across modules into a dossier summary.
function buildHighlights(res) {
  const out = [];
  const mod = (id) => (res.modules || []).find((m) => m.module === id);
  const find = (m, key) => m && (m.findings || []).find((f) => f.key === key || f.key.startsWith(key));

  // public profiles found
  let profiles = 0;
  for (const id of ["username_scan", "username_presence"]) {
    const m = mod(id); if (m && m.extra && m.extra.found != null) profiles = Math.max(profiles, m.extra.found);
  }
  if (profiles) out.push({ k: "profiles", v: `${profiles} public`, kind: "accent" });

  // breach exposure (email)
  const eb = mod("email_exposure");
  if (eb && eb.extra && eb.extra.breach_count != null)
    out.push({ k: "breaches", v: `${eb.extra.breach_count} lists`, kind: eb.extra.breach_count ? "warn" : "good" });

  // name / masked email from identity card or github
  const ic = mod("identity_card") || mod("github_profile");
  const nm = find(ic, "Name");
  if (nm) out.push({ k: "name", v: nm.value.slice(0, 40), kind: "" });
  const em = find(ic, "Public email");
  if (em) out.push({ k: "email", v: em.value, kind: "" });

  // location (ip)
  const geo = mod("ip_geo");
  const loc = find(geo, "Location");
  if (loc && loc.value !== "—") out.push({ k: "location", v: loc.value.slice(0, 36), kind: "" });

  // phone metadata
  const ph = mod("phone_info");
  const reg = find(ph, "Region"); const car = find(ph, "Carrier");
  if (reg && reg.value !== "—") out.push({ k: "region", v: reg.value.slice(0, 30), kind: "" });
  if (car && car.value && car.value !== "—") out.push({ k: "carrier", v: car.value.slice(0, 24), kind: "" });

  // subdomains / attack surface
  for (const id of ["subdomain_enum", "subdomains_ct"]) {
    const m = mod(id); if (m && m.extra && m.extra.count) { out.push({ k: "subdomains", v: `${m.extra.count}`, kind: "accent" }); break; }
  }
  return out.slice(0, 7);
}

// A visual subject header: the person's public face + how far their handle reaches.
function buildHero(res) {
  const kind = res.input_type || "";
  if (kind !== "username" && kind !== "email") return null;
  const isEmail = kind === "email";
  const handle = String(res.target || "").replace(/^@+/, "").trim();
  if (!handle) return null;
  const mods = res.modules || [];
  const g = res.graph || { nodes: [] };

  // real avatar the backend resolved (GitHub / Gravatar…), else the public CDN
  const central = (g.nodes || []).find((n) =>
    (isEmail ? n.type === "email" : n.type === "username") && n.value === handle);
  const realImg = central && central.meta && central.meta.img;
  const av = realImg
    || (isEmail ? `https://unavatar.io/${encodeURIComponent(handle)}?fallback=false`
                : `https://unavatar.io/github/${encodeURIComponent(handle)}?fallback=false`);

  // counts
  let profiles = 0;
  for (const id of ["username_scan", "username_presence"]) {
    const m = mods.find((x) => x.module === id);
    if (m && m.extra && m.extra.found != null) profiles = Math.max(profiles, m.extra.found);
  }
  if (!profiles) profiles = (g.nodes || []).filter((n) => n.type === "profile").length;
  // self-declared / self-verified account links, from any module (identity card,
  // Gravatar verified accounts, Lobsters/GitHub self-links…)
  let linked = 0;
  for (const m of mods) for (const f of (m.findings || []))
    if (f.pivot && (f.key.startsWith("Linked:") || /self-linked|self-declared|verified|self-listed/i.test(f.key))) linked++;
  const nameF = (() => {
    for (const m of mods) for (const f of (m.findings || []))
      if (/^Name/i.test(f.key || "") && f.value) return f;
    return null;
  })();
  // public bio from whichever official API returned one
  let bio = "";
  for (const m of mods) for (const f of (m.findings || []))
    if (!bio && /^Bio/i.test(f.key || "") && f.value) bio = f.value;

  // top platforms with a found profile
  const seen = new Set(); const plats = [];
  for (const m of mods) for (const f of (m.findings || [])) {
    if (f.link && f.pivot && f.key && !f.key.startsWith("Linked") && !f.key.startsWith("Scope")) {
      const k = f.key.slice(0, 18); if (!seen.has(k)) { seen.add(k); plats.push(k); }
    }
  }
  // a little wall of faces — real avatars from official APIs + platform CDNs.
  // each face carries the handle it belongs to, so a click traces that account.
  const faces = []; const fseen = new Set();
  for (const n of (g.nodes || [])) {
    const im = n.meta && n.meta.img;
    if (im && !fseen.has(im)) { fseen.add(im); faces.push({ u: im, h: n.value }); }
  }
  for (const m of mods) for (const f of (m.findings || [])) {
    const u = rowAvatarURL(f);
    if (u && !fseen.has(u)) { fseen.add(u); faces.push({ u, h: f.pivot }); }
  }

  const ini = ((isEmail ? handle.split("@")[0] : handle).match(/[a-z0-9]/gi) || ["?"])
    .slice(0, 2).join("").toUpperCase();
  // breach-list count (email) — names of lists only, never contents
  let breaches = null;
  const ebx = mods.find((m) => m.module === "email_exposure");
  if (ebx && ebx.extra && ebx.extra.breach_count != null) breaches = ebx.extra.breach_count;

  const hero = el("div", "hero");
  const sub = [
    profiles ? `${profiles} public profile${profiles === 1 ? "" : "s"}` : null,
    linked ? `${linked} ${isEmail ? "verified account" : "self-declared link"}${linked === 1 ? "" : "s"}` : null,
    breaches != null ? `${breaches} breach list${breaches === 1 ? "" : "s"}` : null,
  ].filter(Boolean).join(" · ") || "public footprint";
  hero.innerHTML = `
    <div class="hero-av"><span class="hero-ini">${esc(ini)}</span>
      <img src="${esc(av)}" alt="" onerror="this.remove()"></div>
    <div class="hero-meta">
      <div class="hero-h">${isEmail ? esc(handle) : "@" + esc(handle)}${nameF ? `<span class="hero-name">${esc(nameF.value.slice(0, 40))}</span>` : ""}</div>
      <div class="hero-sub">${esc(sub)}</div>
      ${bio ? `<div class="hero-bio">${esc(bio.slice(0, 160))}</div>` : ""}
      ${faces.length ? `<div class="hero-gallery">${faces.slice(0, 16).map((f) => `<img class="ga" src="${esc(f.u)}" alt="" title="trace ${esc(f.h || "")}" data-trace="${esc(f.h || "")}" loading="lazy" onerror="this.remove()">`).join("")}</div>` : ""}
      <div class="hero-chips">${plats.slice(0, 6).map((p) => `<span class="hchip">${esc(p)}</span>`).join("")}</div>
    </div>`;
  hero.querySelectorAll(".ga[data-trace]").forEach((img) => {
    if (img.dataset.trace) img.onclick = () => traceHandle(img.dataset.trace);
  });
  return hero;
}

// ---------------------------------------------------------------- RESULTS view
function showResults(loading = false) {
  state.view = "results";
  $("#topbar-title").textContent = "Results";
  syncTabs("results");
  const c = $("#content");
  c.className = "content view";
  if (loading) {
    c.innerHTML = `<div class="scanning"><span class="scan-dot"></span> Correlating public signals across ${state.modules.length} modules…</div>
      <div class="results">${'<div class="skel"></div>'.repeat(5)}</div>`;
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
  const totalFindings = (res.modules || []).reduce((a, m) => a + (m.findings || []).length, 0);
  // toolbar
  const bar = el("div", "rtoolbar");
  bar.innerHTML = `<span class="target">${esc(res.target || "—")}</span>
    <span class="rstat">${st.ok || 0} ok · ${st.failed || 0} failed · ${st.nodes || 0} entities · ${st.edges || 0} links</span>`;
  if (res.graph && (res.graph.nodes || []).length) {
    const gb = el("button", "chip", "Graph →");
    gb.onclick = showGraph; bar.appendChild(gb);
  }
  const ex = el("button", "chip", "⬇ Export");
  ex.onclick = () => exportReport(res); bar.appendChild(ex);
  c.appendChild(bar);

  // hero dossier — a face for the subject + at-a-glance reach
  const hero = buildHero(res);
  if (hero) c.appendChild(hero);

  // dashboard: quick metric tiles for the current target
  const dash = el("div", "dash");
  const mm = [
    [st.ok || 0, "modules hit"],
    [totalFindings, "findings"],
    [st.nodes || 0, "entities"],
    [st.edges || 0, "links"],
  ];
  dash.innerHTML = mm.map(([n, l]) => `<div class="dash-cell"><div class="dash-n">${n}</div><div class="dash-l">${l}</div></div>`).join("");
  c.appendChild(dash);

  // dossier summary — the key facts pulled to the top
  const hl = buildHighlights(res);
  if (hl.length) {
    const box = el("div", "dossier");
    box.innerHTML = `<div class="dossier-h">Dossier summary</div>
      <div class="dossier-chips">${hl.map((h) => `<span class="dchip ${h.kind}"><span class="dk">${esc(h.k)}</span>${esc(h.v)}</span>`).join("")}</div>`;
    c.appendChild(box);
  }

  // map (if any module returned a point)
  const mapPoint = collectMapPoint(res);
  if (mapPoint) c.appendChild(mapTile(mapPoint));

  const wrap = el("div", "results");
  // The public identity card leads the dossier; then ok + richest first.
  const lead = (m) => (m.module === "identity_card" ? 2 : 0);
  const mods = (res.modules || []).slice().sort((a, b) =>
    (lead(b) - lead(a)) || (b.ok - a.ok) || (b.findings.length - a.findings.length));
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
    <span class="card-title">${esc(meta.name || m.module)}${m.pivot_from ? `<span class="pivot-badge">↳ ${esc(m.pivot_from)}</span>` : ""}</span>
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

// Public-avatar lookup for a result row — a face for the "wall of faces" table.
// Same rule as the graph: public profile pictures only, via the unavatar CDN.
const ROW_UNAVATAR = {
  github: "github", twitter: "twitter", x: "twitter", instagram: "instagram",
  telegram: "telegram", youtube: "youtube", tiktok: "tiktok", reddit: "reddit",
  soundcloud: "soundcloud", dribbble: "dribbble", medium: "medium",
  substack: "substack", gravatar: "gravatar",
};
function rowAvatarURL(f) {
  if (!f.pivot) return null;
  const s = (f.key || "").toLowerCase();
  let prov = null;
  for (const k in ROW_UNAVATAR) if (s.includes(k)) { prov = ROW_UNAVATAR[k]; break; }
  if (!prov) return null;
  return `https://unavatar.io/${prov}/${encodeURIComponent(f.pivot)}?fallback=false`;
}
function findingRow(f) {
  const tr = el("tr");
  const val = f.link
    ? `<a href="${esc(f.link)}" target="_blank" rel="noopener">${esc(f.value)}</a>`
    : esc(f.value);
  const av = rowAvatarURL(f);
  const thumb = av
    ? `<img class="row-av" src="${esc(av)}" alt="" loading="lazy" onerror="this.remove()">`
    : "";
  const pivot = f.pivot ? `<span class="pivot" data-pivot="${esc(f.pivot)}">↳ trace accounts</span>` : "";
  tr.innerHTML = `<td class="k">${esc(f.key)} <span class="pill ${f.confidence}">${f.confidence}</span></td>
    <td class="v">${thumb}${val}${pivot}</td>`;
  const pv = tr.querySelector(".pivot");
  if (pv) pv.onclick = () => traceHandle(pv.dataset.pivot);
  return tr;
}
// Click a discovered handle → search it as a person and reveal their accounts.
function traceHandle(handle) {
  state.mode = "username";
  showHome();
  setTimeout(() => { const i = $("#target"); if (i) { i.value = handle; i.dispatchEvent(new Event("input")); } runAll(); }, 40);
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
  const head = el("div", "section-h");
  head.innerHTML = `<h2>Investigation board</h2><span class="rule"></span><span class="hint">${g.nodes.length} entities · ${g.edges.length} links · tap a node to inspect</span>`;
  c.appendChild(head);
  const wrap = el("div", "graph-wrap board");
  wrap.innerHTML = `<canvas id="graph"></canvas>
    <div class="graph-legend" id="legend"></div>
    <div class="node-panel" id="node-panel" hidden></div>`;
  c.appendChild(wrap);
  // legend — node types + the two edge kinds (verified vs presence)
  const types = [...new Set(g.nodes.map((n) => n.type))];
  const hasVerified = (g.edges || []).some((e) => e.kind === "same_as");
  $("#legend").innerHTML = types.map((t) =>
    `<span class="leg"><i style="background:var(--n-${t},#6d6b7e)"></i>${t}</span>`).join("")
    + (hasVerified ? `<span class="leg edge"><i class="ln verified"></i>same person</span>` : "")
    + `<span class="leg edge"><i class="ln presence"></i>presence</span>`;
  if (state.graphInstance) state.graphInstance.stop();

  const pivot = (value) => { ensureInput(); onNav("home"); setTimeout(() => { $("#target").value = value; runAll(); }, 50); };
  const onSelect = (node, neighbours) => {
    const p = $("#node-panel");
    const color = `var(--n-${node.type}, #6d6b7e)`;
    const nb = (neighbours || []).slice(0, 12);
    const link = node.type === "url" ? node.value
      : node.type === "domain" || node.type === "subdomain" ? `https://${node.value}` : null;
    p.hidden = false;
    p.innerHTML = `
      <div class="np-head">
        <span class="np-dot" style="background:${color}"></span>
        <span class="np-type">${esc(node.type)}</span>
        <button class="np-x" id="np-x">✕</button>
      </div>
      <div class="np-val">${esc(node.label || node.value)}</div>
      ${link ? `<a class="np-link" href="${esc(link)}" target="_blank" rel="noopener">open ↗</a>` : ""}
      <div class="np-sec">Connections · ${(neighbours || []).length}</div>
      <div class="np-conns">${nb.map((n) => `<span class="np-conn" style="border-color:var(--n-${n.type},#333)">${esc(n.label || n.value)}</span>`).join("") || `<span class="np-muted">none</span>`}</div>
      <button class="btn np-expand" id="np-expand" style="width:100%;margin-top:14px">⤢ Expand on board</button>
      <button class="np-pivot2" id="np-pivot" style="width:100%;margin-top:8px">Search this ↳</button>`;
    p.querySelector("#np-x").onclick = () => { p.hidden = true; };
    p.querySelector("#np-pivot").onclick = () => pivot(node.value);
    p.querySelector("#np-expand").onclick = () => expandNode(node, p.querySelector("#np-expand"));
  };
  requestAnimationFrame(() => { state.graphInstance = renderGraph($("#graph"), g, onSelect); });
}

// Maltego-style transform: run modules on a node and MERGE them into the board.
const EXPANDABLE = new Set(["username", "domain", "subdomain", "ip", "email", "url"]);
async function expandNode(node, btn) {
  if (!EXPANDABLE.has(node.type)) { toast("This node type can't be expanded"); return; }
  const target = node.value;
  btn.textContent = "Expanding…"; btn.disabled = true;
  try {
    const res = await fetch("/api/run", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ target, plan: state.plan, deep: false }),
    }).then((r) => r.json());
    mergeIntoResult(res, target);
    const inst = state.graphInstance;      // keep panel? simplest: re-render board
    showGraph();
    toast(`+${(res.stats && res.stats.ok) || 0} findings on ${target}`);
  } catch {
    toast("Expand failed"); btn.disabled = false; btn.textContent = "⤢ Expand on board";
  }
}

function mergeIntoResult(newRes, from) {
  const cur = state.lastResult;
  if (!cur) { state.lastResult = newRes; return; }
  // modules (tag provenance)
  for (const m of newRes.modules || []) { m.pivot_from = from; cur.modules.push(m); }
  // graph nodes (dedupe by id)
  const g = cur.graph || (cur.graph = { nodes: [], edges: [] });
  const nodeById = new Map(g.nodes.map((n) => [n.id, n]));
  for (const n of (newRes.graph && newRes.graph.nodes) || []) {
    if (!nodeById.has(n.id)) { nodeById.set(n.id, n); g.nodes.push(n); }
  }
  const edgeKey = (e) => `${e.source}|${e.target}|${e.kind}`;
  const seen = new Set(g.edges.map(edgeKey));
  for (const e of (newRes.graph && newRes.graph.edges) || []) {
    if (!seen.has(edgeKey(e))) { seen.add(edgeKey(e)); g.edges.push(e); }
  }
  // recompute degree for sizing
  const deg = {}; g.edges.forEach((e) => { deg[e.source] = (deg[e.source] || 0) + 1; deg[e.target] = (deg[e.target] || 0) + 1; });
  g.nodes.forEach((n) => { n.degree = deg[n.id] || 0; });
  // stats
  cur.stats = { ...(cur.stats || {}), nodes: g.nodes.length, edges: g.edges.length,
    ok: (cur.modules || []).filter((m) => m.ok).length, total: (cur.modules || []).length };
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
const TIER_FEATURES = {
  base:    ["Username presence · 40+ platforms", "DNS · WHOIS/RDAP · IP geo", "Email breach names · password k-anon", "EXIF/GPS · geolocation checklist"],
  premium: ["Everything in Base", "Public profiles: Telegram · Discord · Steam", "Subdomains (CT) · TLS · tech fingerprint", "Self-exposure score · phone metadata"],
  elite:   ["Everything in Premium", "Threat feeds · GreyNoise · URLhaus", "Reverse-IP co-hosting · Spamhaus", "Image ELA forensics · Keybase proofs"],
  master:  ["Everything in Elite", "All 63 modules unlocked", "Max concurrency · priority runs", "Full entity graph + report export"],
};
function showPricing() {
  state.view = "pricing";
  $("#topbar-title").textContent = "Plans";
  syncTabs("pricing");
  const c = $("#content");
  c.className = "content view";
  const all = state.byCat ? Object.values(state.byCat).flat() : [];
  c.innerHTML = `
    <div class="price-hero">
      <div class="price-mark"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><circle cx="12" cy="12" r="9.5"/><circle cx="12" cy="12" r="5"/><circle cx="12" cy="12" r="1.3" fill="currentColor" stroke="none"/></svg></div>
      <h1 class="price-title">Go deeper into the <span class="grad">signal</span>.</h1>
      <p class="price-sub">Unlock more of the console. Pay in BTC, ETH or USDT — confirmed directly on-chain, no processor — or PayPal.</p>
    </div>
    <div class="plans" id="plans-grid"></div>
    <div class="price-note">All plans use public data only. Cancel anytime — it's your self-hosted instance.</div>`;
  const grid = $("#plans-grid");
  state.tiers.forEach((t, i) => {
    const cur = t.id === state.plan;
    const featured = t.id === "elite";
    const n = all.filter((m) => tierIndex(m.tier) <= tierIndex(t.id)).length;
    const p = el("div", "plan" + (cur ? " cur" : "") + (featured ? " featured" : ""));
    p.style.animationDelay = i * 70 + "ms";
    p.innerHTML = `
      ${featured ? `<div class="plan-tag">Most popular</div>` : ""}
      <div class="plan-name">${t.name}</div>
      <div class="plan-price"><span class="cur-sym">$</span><span class="cur-val" data-count="${t.price_usd}">0</span><small>/mo</small></div>
      <div class="plan-blurb">${esc(t.blurb)}</div>
      <ul class="plan-feats">${(TIER_FEATURES[t.id] || []).map((f) => `<li><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4"><path d="M20 6 9 17l-5-5"/></svg>${esc(f)}</li>`).join("")}</ul>
      <div class="plan-count">${n} modules unlocked</div>
      <button class="plan-btn">${cur ? "✓ Current plan" : (t.price_usd === 0 ? "Switch to free" : `Get ${t.name}`)}</button>`;
    p.querySelector(".plan-btn").onclick = () => {
      if (cur) return;
      if (t.price_usd === 0) { setPlan("base"); toast("Switched to Base"); showPricing(); }
      else openCheckout(t);
    };
    grid.appendChild(p);
  });
  requestAnimationFrame(() => $$(".cur-val[data-count]", c).forEach(countUp));
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
        ${["BTC", "ETH", "USDC"].map((a) => `<div class="pay-asset ${a === "BTC" ? "on" : ""}" data-a="${a}">${a}</div>`).join("")}
      </div>
      <div id="pay-area"><div class="skel"></div></div>
      <div class="redeem">
        <input class="redeem-in" id="redeem-in" placeholder="or paste a license key…" autocomplete="off">
        <button class="btn ghost" id="redeem-go">Redeem</button>
      </div>
      <div id="redeem-out"></div>
    </div></div>`, { center: true });
  o.querySelector(".close-x").onclick = () => o.remove();
  const doRedeem = async () => {
    const key = o.querySelector("#redeem-in").value.trim();
    if (!key) return;
    const out = o.querySelector("#redeem-out");
    out.innerHTML = `<div class="skel" style="margin-top:10px"></div>`;
    try {
      const r = await fetch("/api/redeem", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ key }) });
      const d = await r.json();
      if (d.ok) { setPlan(d.plan); o.remove(); paymentSuccess({ id: d.plan, name: d.name }); }
      else { out.innerHTML = `<div class="redeem-err">Invalid key.</div>`; }
    } catch { out.innerHTML = `<div class="redeem-err">Couldn't reach the server.</div>`; }
  };
  o.querySelector("#redeem-go").onclick = doRedeem;
  o.querySelector("#redeem-in").addEventListener("keydown", (e) => { if (e.key === "Enter") doRedeem(); });
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
      stat.className = "pay-status paid"; stat.textContent = "✓ Confirmed on-chain";
      setPlan(tier.id);
      setTimeout(() => { o.remove(); paymentSuccess(tier); }, 500);
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

// The payment-success moment: a drawn checkmark, a ring burst, a cyan/magenta
// confetti shower, and the tier reveal. Fast, celebratory, reduced-motion aware.
function paymentSuccess(tier) {
  const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;
  const o = el("div", "success-overlay");
  o.innerHTML = `
    <canvas class="confetti" id="confetti"></canvas>
    <div class="success-card">
      <div class="success-ring">
        <svg viewBox="0 0 120 120" class="success-mark">
          <circle class="sm-ring" cx="60" cy="60" r="52"/>
          <path class="sm-check" d="M38 62 L54 78 L84 44"/>
        </svg>
      </div>
      <div class="success-kicker">payment confirmed · on-chain</div>
      <h2 class="success-title">Welcome to <span class="grad">${esc(tier.name)}</span></h2>
      <p class="success-sub">Your plan is live. Every ${tier.name} module is unlocked across the console.</p>
      <button class="btn success-cta" id="success-cta">Enter the console</button>
    </div>`;
  document.body.appendChild(o);
  const done = () => { o.classList.add("out"); setTimeout(() => { o.remove(); showPricing(); }, 320); };
  o.querySelector("#success-cta").onclick = done;
  if (!reduce) confettiBurst(o.querySelector("#confetti"));
  // haptic nod on supporting devices
  if (navigator.vibrate) navigator.vibrate([12, 40, 18]);
  setTimeout(done, 6000); // auto-continue if they linger
}

function confettiBurst(canvas) {
  const dpr = window.devicePixelRatio || 1;
  canvas.width = innerWidth * dpr; canvas.height = innerHeight * dpr;
  const ctx = canvas.getContext("2d");
  const colors = ["#1ee6cf", "#5cf5e4", "#ff5c9e", "#ff87b8", "#3aa0ff", "#ffffff"];
  const cx = canvas.width / 2, cy = canvas.height * 0.34;
  const parts = Array.from({ length: 130 }, () => {
    const a = Math.random() * Math.PI * 2, sp = (4 + Math.random() * 9) * dpr;
    return { x: cx, y: cy, vx: Math.cos(a) * sp, vy: Math.sin(a) * sp - 4 * dpr,
      r: (3 + Math.random() * 5) * dpr, rot: Math.random() * 6, vr: (Math.random() - .5) * .4,
      c: colors[(Math.random() * colors.length) | 0], life: 1 };
  });
  let raf, t0 = performance.now();
  (function frame(now) {
    const dt = Math.min((now - t0) / 16.7, 2); t0 = now;
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    let alive = false;
    for (const p of parts) {
      p.vy += 0.28 * dpr * dt; p.vx *= 0.99; p.x += p.vx * dt; p.y += p.vy * dt;
      p.rot += p.vr * dt; p.life -= 0.007 * dt;
      if (p.life > 0 && p.y < canvas.height + 40) {
        alive = true;
        ctx.save(); ctx.translate(p.x, p.y); ctx.rotate(p.rot); ctx.globalAlpha = Math.max(p.life, 0);
        ctx.fillStyle = p.c; ctx.fillRect(-p.r, -p.r * .6, p.r * 2, p.r * 1.2); ctx.restore();
      }
    }
    if (alive) raf = requestAnimationFrame(frame); else cancelAnimationFrame(raf);
  })(t0);
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

// Build and download a Markdown report of the current result.
function exportReport(res) {
  const lines = [`# LIMBO report — ${res.target}`, "",
    `Generated ${new Date().toISOString()}`,
    `Type: ${res.input_type} · ${res.stats?.ok || 0} modules · ${res.stats?.nodes || 0} entities`, ""];
  for (const m of res.modules || []) {
    if (!m.ok || !(m.findings || []).length) continue;
    const meta = state.modules.find((x) => x.id === m.module) || {};
    lines.push(`## ${meta.name || m.module}`, `_${m.summary || ""}_`, "");
    for (const f of m.findings) lines.push(`- **${f.key}**: ${f.value}${f.link ? ` (${f.link})` : ""}`);
    lines.push("");
  }
  lines.push("---", "_All data from public sources. Public-data OSINT only._");
  const blob = new Blob([lines.join("\n")], { type: "text/markdown" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = `limbo-${(res.target || "report").replace(/[^\w.-]/g, "_")}.md`;
  a.click();
  toast("Report downloaded");
}

// ---------------------------------------------------------------- helpers
function emptyState(title, sub) {
  return `<div class="empty">
    <div class="empty-mark"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.4"><circle cx="12" cy="12" r="9.5"/><circle cx="12" cy="12" r="5"/><circle cx="12" cy="12" r="1.3" fill="currentColor" stroke="none"/></svg></div>
    <div class="empty-title">${esc(title)}</div>
    <div class="empty-sub">${esc(sub)}</div></div>`;
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
  if (state.offline) showOffline();
  else onNav("home");
  await playBoot(count);
  // register PWA service worker
  if ("serviceWorker" in navigator) navigator.serviceWorker.register("/sw.js").catch(() => {});
})();

// Shown when the API can't be reached — usually a rotated/expired preview link.
function showOffline() {
  $("#topbar-title").textContent = "Offline";
  const c = $("#content");
  c.className = "content view";
  c.innerHTML = `<div class="offline-card">
    <div class="offline-ico">⚠</div>
    <h2>Can't reach the server</h2>
    <p>The API isn't responding. If you're on a temporary preview link it may have
    expired or rotated to a new address. Ask for the current link, or deploy LIMBO
    to a permanent host.</p>
    <button class="btn" id="retry-btn">Retry connection</button>
  </div>`;
  $("#retry-btn").onclick = async () => {
    $("#retry-btn").textContent = "Connecting…";
    const count = await loadData().catch(() => 0);
    if (!state.offline) { renderNav(); onNav("home"); toast("Reconnected"); }
    else { $("#retry-btn").textContent = "Retry connection"; toast("Still unreachable"); }
  };
}
