/* ==========================================================================
   app.js — the controller. Wires the shell together:
     * loads the module catalog -> renders sidebar + tab bar + command palette
     * live input-type detection
     * runs a target, streams result cards in (skeleton -> real, staggered)
     * renders findings, pills, copy buttons, JSON drawers, inline maps
     * graph view hand-off
   No framework — just modules + the DOM. Heavily commented for learning.
   ========================================================================== */

import { $, $$, el, esc, api, copy, toast, debounce, icon } from "./util.js";
import { GraphView } from "./graph.js";

const state = {
  modules: [],          // catalog from /api/modules
  byCat: {},            // category -> [modules]
  lastRun: null,        // last /api/run payload (for graph view)
  graph: null,          // GraphView instance
  cmdkIndex: 0,
  tiers: [],            // tier order from backend
  plan: localStorage.getItem("plan") || "base",
};

// Subscription tiers — display metadata (name, accent colour, "power" level).
const TIER_META = {
  base:    { name: "Base",    color: "#7fb6f0", power: 1, blurb: "Everyday essentials" },
  premium: { name: "Premium", color: "#8b7cff", power: 2, blurb: "Solid recon depth" },
  elite:   { name: "Elite",   color: "#5ad6a0", power: 3, blurb: "Full fingerprinting" },
  mega:    { name: "Mega",    color: "#e8c468", power: 4, blurb: "Exposure + deep social" },
  ultra:   { name: "Ultra",   color: "#e892d0", power: 5, blurb: "Heavy attack-surface" },
  master:  { name: "Master",  color: "#f7c948", power: 6, blurb: "Everything, incl. active" },
};
// Colour themes — each re-skins the whole app's accent family. Original palettes.
const THEMES = {
  violet:  { name: "Console",  accent: "#8b7cff", rgb: "139,124,255" },
  green:   { name: "Terminal", accent: "#3ddc84", rgb: "61,220,132" },
  cyan:    { name: "Cyber",    accent: "#22d3ee", rgb: "34,211,238" },
  amber:   { name: "Ops",      accent: "#f5a623", rgb: "245,166,35" },
  crimson: { name: "Red team", accent: "#ff5c72", rgb: "255,92,114" },
  magenta: { name: "Neon",     accent: "#e879f9", rgb: "232,121,249" },
};
state.theme = localStorage.getItem("theme") || "violet";

function applyTheme(t) {
  const th = THEMES[t] || THEMES.violet;
  state.theme = t;
  localStorage.setItem("theme", t);
  const r = document.documentElement.style;
  r.setProperty("--accent", th.accent);
  r.setProperty("--accent-soft", `rgba(${th.rgb},0.14)`);
  r.setProperty("--accent-line", `rgba(${th.rgb},0.40)`);
  r.setProperty("--accent-glow", `rgba(${th.rgb},0.30)`);
  r.setProperty("--n-domain", th.accent);
}

function renderThemeBox() {
  const box = $("#theme-box");
  if (!box) return;
  box.innerHTML = "";
  box.append(el("div", { class: "plan-label" }, "Theme"));
  const row = el("div", { class: "theme-row" });
  for (const [key, th] of Object.entries(THEMES)) {
    row.append(el("button", {
      class: "theme-dot" + (key === state.theme ? " active" : ""),
      title: th.name, style: `--tc:${th.accent}`,
      onclick: () => {
        applyTheme(key);
        $$("#theme-box .theme-dot").forEach((d) => d.classList.remove("active"));
        row.children[Object.keys(THEMES).indexOf(key)].classList.add("active");
        toast(`${th.name} theme`);
      },
    }));
  }
  box.append(row);
}

// Deep Scan: after a run, auto-pivot the top nodes. How many expansions is
// gated by the plan (more power on higher tiers).
state.deep = localStorage.getItem("deep") === "1";
const DEEP_BUDGET = { base: 0, premium: 2, elite: 3, mega: 5, ultra: 7, master: 10 };
const deepBudget = () => DEEP_BUDGET[state.plan] ?? 0;

const tierIdx = (t) => Math.max(0, state.tiers.indexOf(t));
const planIdx = () => tierIdx(state.plan);
const isUnlocked = (m) => tierIdx(m.tier || "base") <= planIdx();
const allowedKeys = () => new Set(state.modules.filter(isUnlocked).map((m) => m.key));

const CATS = [
  ["infrastructure", "Infrastructure"],
  ["blockchain", "Blockchain"],
  ["image", "Image / Geo"],
  ["identity", "Identity"],
  ["intel", "Intel"],
];

// Inline style that binds a card's --cat / --cat-soft to its category colour.
const catStyle = (cat) =>
  `--cat:var(--cat-${cat});--cat-soft:var(--cat-${cat}-soft)`;

// ------------------------------------------------------------------ boot ----
init();
async function init() {
  playBoot();
  await loadModules();
  bindUI();
  handleCheckoutReturn();
  registerSW();
  pingHealth();
}

// One-time "console powering up" intro (per browser session).
function playBoot() {
  const boot = $("#boot");
  if (!boot) return;
  if (sessionStorage.getItem("booted")) { boot.remove(); return; }
  sessionStorage.setItem("booted", "1");
  const log = $("#boot-log");
  const lines = [
    "[ok] loading modules ............ 71",
    "[ok] correlation engine ......... ready",
    "[ok] entity graph ............... online",
    "[ok] input detectors ............ 11 types",
    "[ok] secure channel ............. established",
    "> ready_",
  ];
  const done = () => { boot.classList.add("boot-out");
    setTimeout(() => boot.remove(), 500); };
  boot.addEventListener("click", done);
  let i = 0;
  const step = () => {
    if (i >= lines.length) { setTimeout(done, 550); return; }
    log.append(el("div", { class: "boot-line" }, lines[i]));
    i++;
    setTimeout(step, 230);
  };
  setTimeout(step, 350);
}

async function loadModules() {
  try {
    const data = await api("/api/modules");
    state.modules = data.modules;
    state.tiers = data.tiers || ["base", "premium", "elite", "mega", "ultra", "master"];
    if (!state.tiers.includes(state.plan)) state.plan = state.tiers[0];
    state.byCat = {};
    for (const m of state.modules)
      (state.byCat[m.category] ||= []).push(m);
    applyTheme(state.theme);
    applyPlanColor();
    renderPlanBox();
    renderThemeBox();
    renderSidebar();
    renderTabbar();
    renderStats();
    renderHomeCats();
    renderDeck();
  } catch (e) {
    toast("Failed to load modules");
  }
}

// --- Subscription plan UI ---------------------------------------------------
function applyPlanColor() {
  const meta = TIER_META[state.plan] || {};
  const root = document.documentElement;
  root.style.setProperty("--tier", meta.color || "var(--accent)");
  root.style.setProperty("--tier-soft",
    `color-mix(in srgb, ${meta.color} 14%, transparent)`);
  root.style.setProperty("--tier-line",
    `color-mix(in srgb, ${meta.color} 40%, transparent)`);
}

function renderPlanBox() {
  const box = $("#plan-box");
  if (!box) return;
  const meta = TIER_META[state.plan] || {};
  const unlocked = state.modules.filter(isUnlocked).length;
  box.innerHTML = "";
  box.append(el("div", { class: "plan-label" }, "Subscription"));
  const current = el("div", { class: "plan-current", id: "plan-current" },
    el("span", { class: "plan-dot", style: `--pc:${meta.color}` }),
    `${meta.name} plan`,
    el("span", { class: "plan-power" }, "⚡".repeat(meta.power || 1)));
  box.append(current);

  // The expandable list of plans.
  const list = el("div", { class: "plan-list", id: "plan-list", hidden: true });
  for (const t of state.tiers) {
    const tm = TIER_META[t] || { name: t, color: "#888", power: 1 };
    const count = state.modules.filter((m) => (m.tier || "base") === t).length;
    const cumulative = state.modules.filter(
      (m) => tierIdx(m.tier || "base") <= tierIdx(t)).length;
    const opt = el("div", {
      class: "plan-opt" + (t === state.plan ? " active" : ""),
      style: `--pc:${tm.color}`, onclick: () => setPlan(t),
    },
      el("span", { class: "plan-dot", style: `--pc:${tm.color}` }),
      el("div", {}, el("div", {}, `${tm.name}  ${"⚡".repeat(tm.power)}`),
        el("div", { style: "font-size:10px;color:var(--text-3)" }, tm.blurb)),
      el("span", { class: "plan-count" }, `${cumulative} mods`));
    list.append(opt);
  }
  box.append(list);
  box.append(el("button", { class: "plan-upgrade", onclick: openPricing },
    "⬆ See plans & pricing"));
  current.addEventListener("click", () => { list.hidden = !list.hidden; });
  const cnt = $("#plan-label-count");
  if (cnt) cnt.textContent = unlocked;
}

function setPlan(t) {
  state.plan = t;
  localStorage.setItem("plan", t);
  applyPlanColor();
  renderPlanBox();
  renderStats();
  renderDeck();
  updateDeepHint();
  toast(`${TIER_META[t]?.name || t} plan — ${state.modules.filter(isUnlocked).length} modules unlocked`);
}

function updateDeepHint() {
  const b = deepBudget();
  $("#deep-hint").textContent = state.deep
    ? (b > 0 ? `auto-pivot ×${b} (${TIER_META[state.plan]?.name})`
             : `needs a paid plan`)
    : "auto-expand the graph";
}

// After a normal run, auto-pivot the highest-value pivotable nodes to grow the
// correlation graph — bounded by the plan's Deep-Scan budget.
async function autoDeepScan(out) {
  const budget = deepBudget();
  if (!state.deep || budget <= 0 || !out.graph) return;
  const PIVOTABLE = new Set(["domain", "subdomain", "ip"]);
  const done = new Set([out.value.toLowerCase()]);
  progress(true);
  try {
    let expansions = 0;
    // Rank nodes by degree; expand the most connected pivotable ones.
    const ranked = [...out.graph.nodes]
      .filter((n) => PIVOTABLE.has(n.type))
      .sort((a, b) => (b.degree || 0) - (a.degree || 0));
    for (const node of ranked) {
      if (expansions >= budget) break;
      if (done.has(node.value.toLowerCase())) continue;
      done.add(node.value.toLowerCase());
      try {
        const sub = await api("/api/run", {
          method: "POST",
          body: JSON.stringify({ value: node.value, only: [...allowedKeys()] }),
        });
        mergeIntoLastRun(sub);
        if (state.graph) state.graph.mergeData(sub.graph);
        expansions++;
        const g = state.lastRun.graph.stats;
        $("#results-summary").textContent =
          `deep scan · ${g.node_count} nodes / ${g.edge_count} edges · ${expansions} pivots`;
      } catch { /* skip a failed pivot */ }
    }
    if (expansions) toast(`⚡ Deep scan: +${expansions} pivots`);
  } finally {
    progress(false);
  }
}

// --- Pricing / upgrade page -------------------------------------------------
const TIER_PRICE = { base: 0, premium: 9, elite: 19, mega: 39, ultra: 79, master: 149 };
const TIER_TAGLINE = {
  base: "Get started with the essentials",
  premium: "Everyday investigations",
  elite: "Full-spectrum fingerprinting",
  mega: "Exposure intel + deep social",
  ultra: "Heavy attack-surface & forensics",
  master: "The complete arsenal",
};

function openPricing() { closeSidebar(); renderPricing(); $("#pricing").hidden = false; }
function closePricing() { $("#pricing").hidden = true; }

// Start a subscription checkout for a plan. Free = instant; a configured Stripe
// key redirects to Stripe's hosted checkout; otherwise a safe demo checkout.
async function startCheckout(t) {
  const price = TIER_PRICE[t] ?? 0;
  if (price === 0) { setPlan(t); closePricing(); toast(`Switched to ${TIER_META[t]?.name} ✓`); return; }
  try {
    const r = await api("/api/checkout", {
      method: "POST",
      body: JSON.stringify({ plan: t, origin: location.origin }),
    });
    if (r.url) { window.location.href = r.url; return; }   // real Stripe
    if (r.error) { toast("Checkout error: " + r.error); return; }
    demoCheckout(t);                                        // demo fallback
  } catch (e) { toast("Checkout failed: " + e.message); }
}

// Safe simulated checkout (no card data collected, no real charge).
function demoCheckout(t) {
  const tm = TIER_META[t] || {};
  const price = TIER_PRICE[t] ?? 0;
  const body = $("#co-body");
  $("#pricing").hidden = true;
  $("#checkout").hidden = false;
  body.innerHTML = "";
  body.append(
    el("div", { class: "co-plan" },
      el("span", { class: "plan-dot", style: `--pc:${tm.color}` }),
      el("div", {}, el("div", { class: "co-plan-name" }, `${tm.name} plan`),
        el("div", { class: "co-plan-sub" }, tm.blurb || ""))),
    el("div", { class: "co-amount" }, `€${price}`, el("span", { class: "price-per" }, "/mo")),
    el("div", { class: "co-demo-note" },
      "🔒 Demo checkout — no real payment is taken and no card data is collected. " +
      "Add a Stripe key in .env to enable live payments (card data is handled only " +
      "by Stripe, never by this app)."),
    el("button", { class: "btn-primary co-pay", id: "co-pay" },
      `Complete purchase (demo)`));
  $("#co-pay").addEventListener("click", () => {
    const btn = $("#co-pay");
    btn.disabled = true; btn.textContent = "Processing…";
    setTimeout(() => {
      body.innerHTML = `<div class="co-success">
        <div class="co-check">✓</div>
        <div class="co-success-title">${esc(tm.name)} plan activated</div>
        <div class="co-success-sub">Demo payment complete. Modules unlocked.</div></div>`;
      setPlan(t);
      setTimeout(() => { $("#checkout").hidden = true; }, 1400);
    }, 1500);
  });
}

// If we returned from a (real) Stripe checkout, apply the plan.
function handleCheckoutReturn() {
  const q = new URLSearchParams(location.search);
  if (q.get("checkout") === "success" && q.get("plan")) {
    setPlan(q.get("plan"));
    toast(`✓ ${TIER_META[q.get("plan")]?.name || "Plan"} activated`);
  }
  if (q.get("checkout")) history.replaceState({}, "", location.pathname);
}

function renderPricing() {
  const grid = $("#pricing-grid");
  grid.innerHTML = "";
  for (const t of state.tiers) {
    const tm = TIER_META[t] || {};
    const mods = state.modules.filter((m) => (m.tier || "base") === t);
    const cumulative = state.modules.filter(
      (m) => tierIdx(m.tier || "base") <= tierIdx(t)).length;
    const price = TIER_PRICE[t] ?? 0;
    const isCurrent = t === state.plan;
    // A few standout module names unlocked at this tier.
    const highlights = mods.slice(0, 4).map((m) => m.name);

    const card = el("div", {
      class: "price-card" + (isCurrent ? " current" : "") +
        (t === "master" ? " featured" : ""),
      style: `--pc:${tm.color}`,
    },
      t === "master" ? el("div", { class: "price-flag" }, "BEST VALUE") : null,
      el("div", { class: "price-name" },
        el("span", { class: "plan-dot", style: `--pc:${tm.color}` }), tm.name),
      el("div", { class: "price-tag" }, tm.blurb || ""),
      el("div", { class: "price-amount" },
        price === 0 ? el("span", {}, "Free")
          : el("span", {}, el("span", { class: "price-cur" }, "€"), String(price),
              el("span", { class: "price-per" }, "/mo"))),
      el("div", { class: "price-power" }, "⚡".repeat(tm.power || 1) +
        `  ·  ${cumulative} modules`),
      el("ul", { class: "price-feats" },
        ...highlights.map((h) => el("li", {}, h)),
        el("li", { class: "price-more" }, `+ everything in lower tiers`)),
      el("button", {
        class: isCurrent ? "btn-ghost price-btn" : "btn-primary price-btn",
        disabled: isCurrent || undefined,
        onclick: () => startCheckout(t),
      }, isCurrent ? "Current plan" : (price === 0 ? "Select" : `Choose ${tm.name}`)));
    grid.append(card);
  }
}

// Small dashboard of headline numbers on the landing.
function renderStats() {
  const strip = $("#stat-strip");
  if (!strip) return;
  const cats = Object.keys(state.byCat).length;
  const unlocked = state.modules.filter(isUnlocked).length;
  strip.innerHTML = "";
  const items = [
    [`${unlocked}`, "Unlocked"],
    [String(state.modules.length), "Total modules"],
    [String(cats), "Domains"],
    ["100%", "Public data"],
  ];
  for (const [num, label] of items) {
    const numEl = el("div", { class: "stat-num" });
    strip.append(el("div", { class: "stat" }, numEl,
      el("div", { class: "stat-label" }, label)));
    countUp(numEl, num);
  }
}

// Animate a number from 0 → target (keeps a trailing % / suffix).
function countUp(node, text) {
  const m = String(text).match(/^(\d+)(.*)$/);
  if (!m) { node.textContent = text; return; }
  const target = parseInt(m[1], 10), suffix = m[2];
  const dur = 750, t0 = performance.now();
  const tick = (t) => {
    const p = Math.min(1, (t - t0) / dur);
    const eased = 1 - Math.pow(1 - p, 3);        // easeOutCubic
    const val = Math.round(target * eased);
    node.innerHTML = val + (suffix === "%"
      ? '<span class="accent">%</span>' : esc(suffix));
    if (p < 1) requestAnimationFrame(tick);
  };
  requestAnimationFrame(tick);
}

// Home category tiles — one bento tile per investigative domain, with count.
function renderHomeCats() {
  const host = $("#home-cats");
  if (!host) return;
  host.innerHTML = "";
  for (const [key, title] of CATS) {
    const mods = state.byCat[key] || [];
    if (!mods.length) continue;
    const unlocked = mods.filter(isUnlocked).length;
    host.append(el("div", {
      class: "hc-tile", "data-cat": key, style: catStyle(key),
      onclick: () => {
        const first = $(`.deck-card[data-cat="${key}"]`);
        if (first) first.scrollIntoView({ behavior: "smooth", block: "center" });
      },
    },
      el("div", { class: "hc-ico" }, icon(mods[0]?.key, key)),
      el("div", { class: "hc-name" }, title),
      el("div", { class: "hc-count mono" }, `${unlocked}/${mods.length} modules`)));
  }
}

// The capability deck — every module as a tappable card, grouped by category.
function renderDeck() {
  const deck = $("#deck");
  if (!deck) return;
  deck.innerHTML = "";
  for (const [key, title] of CATS) {
    const mods = state.byCat[key];
    if (!mods?.length) continue;
    deck.append(el("div", { class: "deck-cat-title", "data-cat": key,
      style: catStyle(key) }, title, el("span", { class: "deck-cat-count" },
      ` ${mods.length}`)));
    for (const m of mods) deck.append(deckCard(m));
  }
}
function deckCard(m) {
  const accepts = el("div", { class: "deck-accepts" },
    ...m.accepts.map((a) => el("span", {
      class: "type-tag" + (m.requires_authorized_target ? " gated" : ""),
    }, a)));
  const unlocked = isUnlocked(m);
  const tm = TIER_META[m.tier || "base"] || {};
  const card = el("div", {
    class: "deck-card" + (unlocked ? "" : " locked"),
    title: m.description, "data-cat": m.category,
    onclick: () => unlocked ? pickModule(m) : showUpgrade(m),
    onmousemove: (e) => {
      const r = card.getBoundingClientRect();
      card.style.setProperty("--mx", `${e.clientX - r.left}px`);
    },
  },
    el("div", { class: "deck-ico" }, icon(m.key, m.category)),
    el("div", { class: "deck-info" },
      el("div", { class: "deck-name" }, m.name),
      el("div", { class: "deck-sub" }, m.subtitle || m.description.slice(0, 70)),
      accepts));
  // Lock badge for modules above the current plan.
  if (!unlocked)
    card.append(el("div", { class: "deck-lock", style: `--tier-mark:${tm.color}` },
      "🔒 " + (tm.name || m.tier)));
  return card;
}

// Prompt to upgrade when a locked module is tapped.
function showUpgrade(m) {
  const tm = TIER_META[m.tier] || {};
  toast(`🔒 "${m.name}" needs the ${tm.name} plan`);
  const box = $("#plan-box");
  if (box) { box.scrollIntoView({ behavior: "smooth", block: "center" });
    $("#plan-list") && ($("#plan-list").hidden = false); }
}

// One canonical example value per input type, so tapping a card is instant.
const EXAMPLES = {
  domain: "example.com", ip: "1.1.1.1", url: "https://example.com",
  username: "torvalds", email: "test@example.com",
  btc_address: "1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa",
  eth_address: "0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045",
  hash: "5d41402abc4b2a76b9719d911017c592", image: "", file: "",
};
function pickModule(m) {
  closeSidebar();
  // Image modules: open the file picker instead of filling text.
  if (m.accepts.includes("image") || m.accepts.includes("file")) {
    $("#upload-row").hidden = false;
    $("#file-input").click();
    return;
  }
  const ex = m.accepts.map((a) => EXAMPLES[a]).find((v) => v);
  if (ex) { $("#target-input").value = ex; onType(); }
  $("#target-input").focus();
  $("#target-input").scrollIntoView({ behavior: "smooth", block: "center" });
  toast(`${m.name} · try ${ex || "an upload"}`);
}

// --------------------------------------------------------------- sidebar ----
function renderSidebar() {
  const nav = $("#module-nav");
  nav.innerHTML = "";
  for (const [key, title] of CATS) {
    const mods = state.byCat[key];
    if (!mods?.length) continue;
    nav.append(el("div", { class: "nav-group-title" }, title));
    for (const m of mods) nav.append(navItem(m));
  }
}
function navItem(m) {
  return el("div", {
    class: "nav-item", title: m.description, "data-cat": m.category,
    onclick: () => quickPick(m),
  },
    el("span", { class: "nav-ico" }, icon(m.key, m.category)),
    el("div", { class: "nav-text" },
      el("span", { class: "nav-label" }, m.name),
      el("span", { class: "nav-sub" }, m.subtitle || m.accepts.join(", "))));
}

function renderTabbar() {
  const bar = $("#tabbar");
  bar.innerHTML = "";
  const tabs = [
    ["work", "⌖", "Workspace", () => showView("workspace")],
    ["graph", "◈", "Graph", () => openGraph()],
    ["modules", "▤", "Modules", () => openCmdk()],
  ];
  for (const [id, ico, label, fn] of tabs) {
    bar.append(el("button", { class: "tab", "data-tab": id, onclick: fn },
      el("span", { class: "tab-ico" }, ico),
      el("span", {}, label)));
  }
  setActiveTab("work");
}
function setActiveTab(id) {
  $$("#tabbar .tab").forEach((t) =>
    t.classList.toggle("active", t.dataset.tab === id));
}

// When a sidebar entry is tapped, behave like tapping its deck card.
function quickPick(m) { showView("workspace"); pickModule(m); }

// ----------------------------------------------------------------- UI bind --
function bindUI() {
  $("#run-btn").addEventListener("click", runTarget);
  $("#target-input").addEventListener("keydown", (e) => {
    if (e.key === "Enter") runTarget();
  });
  $("#target-input").addEventListener("input", debounce(onType, 220));
  $("#target-input").addEventListener("input", () => {
    $("#clear-btn").hidden = !$("#target-input").value;
  });
  $("#clear-btn").addEventListener("click", resetToLanding);
  $("#new-search-btn").addEventListener("click", resetToLanding);

  // Results filter toolbar.
  $("#rt-search").addEventListener("input", (e) => {
    filterState.search = e.target.value.trim().toLowerCase(); applyResultFilters();
  });
  $("#rt-hide-empty").addEventListener("click", (e) => {
    const on = e.target.getAttribute("aria-pressed") === "true";
    e.target.setAttribute("aria-pressed", on ? "false" : "true");
    filterState.hideEmpty = !on; applyResultFilters();
  });

  // Example chips fill the input (and image chip opens the picker).
  $$(".chip[data-fill]").forEach((c) =>
    c.addEventListener("click", () => {
      $("#target-input").value = c.dataset.fill;
      onType(); $("#clear-btn").hidden = false; $("#target-input").focus();
    }));
  $("#chip-upload").addEventListener("click", () => {
    $("#upload-row").hidden = false; $("#file-input").click();
  });

  // Password exposure checker (k-anonymity, entirely on-device).
  // Deep Scan toggle.
  const deepBtn = $("#deep-toggle");
  deepBtn.setAttribute("aria-pressed", state.deep ? "true" : "false");
  updateDeepHint();
  deepBtn.addEventListener("click", () => {
    state.deep = !state.deep;
    localStorage.setItem("deep", state.deep ? "1" : "0");
    deepBtn.setAttribute("aria-pressed", state.deep ? "true" : "false");
    updateDeepHint();
  });

  $("#chip-pw").addEventListener("click", openPwCheck);
  $("#pw-close").addEventListener("click", () => ($("#pwcheck").hidden = true));
  $("#pwcheck").addEventListener("click", (e) => {
    if (e.target.id === "pwcheck") $("#pwcheck").hidden = true;
  });
  $("#pw-toggle").addEventListener("click", () => {
    const i = $("#pw-input"); i.type = i.type === "password" ? "text" : "password";
  });
  $("#pw-run").addEventListener("click", runPwCheck);
  $("#pw-input").addEventListener("keydown", (e) => {
    if (e.key === "Enter") runPwCheck();
  });

  $("#menu-btn")?.addEventListener("click", toggleSidebar);
  $("#sidebar-close")?.addEventListener("click", closeSidebar);
  $("#sidebar-backdrop")?.addEventListener("click", closeSidebar);
  $("#cmdk-trigger").addEventListener("click", openCmdk);
  $("#view-graph-btn").addEventListener("click", openGraph);
  $("#graph-back").addEventListener("click", () => showView("workspace"));
  $("#node-pop-close").addEventListener("click", () => ($("#node-pop").hidden = true));
  $("#pricing-close").addEventListener("click", closePricing);
  $("#pricing").addEventListener("click", (e) => { if (e.target.id === "pricing") closePricing(); });
  $("#co-close").addEventListener("click", () => ($("#checkout").hidden = true));
  $("#checkout").addEventListener("click", (e) => { if (e.target.id === "checkout") $("#checkout").hidden = true; });

  // Report export menu.
  $("#report-btn").addEventListener("click", (e) => {
    e.stopPropagation();
    $("#report-dropdown").hidden = !$("#report-dropdown").hidden;
  });
  $$("#report-dropdown button").forEach((b) =>
    b.addEventListener("click", () => {
      $("#report-dropdown").hidden = true; exportReport(b.dataset.fmt);
    }));
  document.addEventListener("click", () => ($("#report-dropdown").hidden = true));

  // File upload
  $("#file-input").addEventListener("change", onFile);

  // Command palette keyboard
  document.addEventListener("keydown", (e) => {
    if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
      e.preventDefault(); openCmdk();
    }
    if (e.key === "Escape") closeCmdk();
  });
  $("#cmdk").addEventListener("click", (e) => {
    if (e.target.id === "cmdk") closeCmdk();
  });
  $("#cmdk-input").addEventListener("input", () => renderCmdk($("#cmdk-input").value));
  $("#cmdk-input").addEventListener("keydown", cmdkNav);
}

// Live detect: ask the backend what the typed value looks like.
async function onType() {
  const v = $("#target-input").value.trim();
  const pill = $("#type-pill");
  const gate = $("#scope-gate");
  $("#clear-btn").hidden = !v;
  if (!v) { pill.textContent = "auto"; gate.hidden = true; return; }
  try {
    const d = await api(`/api/detect?value=${encodeURIComponent(v)}`);
    pill.textContent = d.label.toLowerCase();
    // Show scope gate if any compatible module needs authorization.
    const needsAuth = state.modules.some(
      (m) => d.compatible_modules.includes(m.key) && m.requires_authorized_target);
    gate.hidden = !needsAuth;
  } catch { pill.textContent = "auto"; }
}

// --------------------------------------------------------------- run flow ---
let uploadedFile = null;

function onFile(e) {
  uploadedFile = e.target.files[0] || null;
  $("#upload-name").textContent = uploadedFile ? uploadedFile.name : "";
  if (uploadedFile) $("#target-input").value = uploadedFile.name;
}

async function runTarget() {
  const value = $("#target-input").value.trim();
  if (!value && !uploadedFile) { toast("Enter a target first"); return; }

  // Switch from landing to results mode (hides hero/deck/stats via CSS).
  pivotDepth = 0;   // reset multi-hop expansion budget for a fresh target
  document.body.classList.add("has-results");
  $("#results-head").hidden = false;
  const grid = $("#results");
  grid.innerHTML = "";
  progress(true);

  const authorized = $("#scope-check")?.checked || false;

  try {
    // Image/file path: upload + run the image module(s).
    if (uploadedFile) {
      $("#results-summary").textContent = `image · ${uploadedFile.name}`;
      const fd = new FormData();
      fd.append("file", uploadedFile);
      fd.append("key", "exif_gps");
      fd.append("authorized", String(authorized));
      const sk = addSkeleton(grid, "EXIF & GPS");
      const res = await fetch("/api/upload", { method: "POST", body: fd })
        .then((r) => r.json());
      sk.replaceWith(renderCard(res, 0));
      progress(false);
      return;
    }

    // Detect type, then split compatible modules into unlocked vs locked (plan).
    const det = await api(`/api/detect?value=${encodeURIComponent(value)}`);
    const unlocked = allowedKeys();
    const runnable = det.compatible_modules.filter((k) => unlocked.has(k));
    const locked = det.compatible_modules.filter((k) => !unlocked.has(k));
    $("#results-summary").textContent =
      `${det.label} · ${runnable.length} module(s)` +
      (locked.length ? ` · ${locked.length} locked` : "");

    // Upgrade hint when this input has modules above the current plan.
    if (locked.length) {
      const nextTier = state.modules
        .filter((m) => locked.includes(m.key))
        .map((m) => m.tier)
        .sort((a, b) => tierIdx(a) - tierIdx(b))[0];
      grid.append(el("div", { class: "upgrade-note" },
        el("span", {}, "🔒"),
        el("span", {}, `${locked.length} more module(s) for this input are locked. `),
        el("button", { class: "btn-ghost", style: "margin-left:auto",
          onclick: () => setPlan(nextTier) },
          `Unlock with ${TIER_META[nextTier]?.name || nextTier}`)));
    }

    const skeletons = {};
    runnable.forEach((k) => {
      const m = state.modules.find((x) => x.key === k);
      skeletons[k] = addSkeleton(grid, m?.name || k);
    });

    // Run only the unlocked modules for this plan.
    const out = await api("/api/run", {
      method: "POST",
      body: JSON.stringify({ value, authorized, only: runnable }),
    });
    state.lastRun = out;

    out.results.forEach((res, i) => {
      const sk = skeletons[res.module];
      const card = renderCard(res, i);
      if (sk) sk.replaceWith(card); else grid.append(card);
    });

    // Graph hint + filter toolbar.
    const g = out.graph?.stats;
    if (g) $("#results-summary").textContent =
      `${det.label} · ${out.results.length} modules · ${g.node_count} nodes / ${g.edge_count} edges`;
    renderDashboard(out);
    setupResultsToolbar(out.results);
    autoDeepScan(out);   // power feature: auto-expand the graph (plan-gated)
  } catch (e) {
    toast("Run failed: " + e.message);
  } finally {
    progress(false);
  }
}

// ------------------------------------------------------------ bento dashboard --
// Build the summary tiles (target · score · alerts · graph) shown above the
// per-module result tiles — the SOC-style at-a-glance dashboard.
function renderDashboard(out) {
  const dash = $("#dash");
  dash.hidden = false;
  dash.innerHTML = "";
  const g = out.graph?.stats || {};
  const results = out.results || [];

  // Collect cross-module alerts (⚠ findings) and high-confidence hits.
  const alerts = [];
  let highCount = 0, findingCount = 0;
  let scoreVal = null, scoreBand = null;
  for (const r of results) {
    if (r.confidence === "high" && !r.error) highCount++;
    for (const f of (r.findings || [])) {
      findingCount++;
      if (typeof f.label === "string" && f.label.trim().startsWith("⚠"))
        alerts.push({ module: r.module, text: f.summary || (f.values || []).join(", ") });
    }
    if (r.module === "exposure_score" && r.findings?.[0]) {
      const m = String(r.findings[0].summary || "").match(/(\d+)\s*\/\s*100\s*·\s*(\w+)/);
      if (m) { scoreVal = m[1]; scoreBand = m[2]; }
    }
  }

  // 1) TARGET tile (wide).
  dash.append(tile("t-target", "wide",
    el("div", { class: "tile-k" }, "TARGET"),
    el("div", { class: "tile-target mono" }, out.value),
    el("div", { class: "tile-meta" },
      pillMini(out.input_type), ` ${results.length} modules · `,
      `${g.node_count || 0} nodes / ${g.edge_count || 0} edges`)));

  // 2) SCORE tile.
  const scoreColor = scoreVal == null ? "var(--text-3)"
    : (+scoreVal >= 75 ? "var(--bad)" : +scoreVal >= 50 ? "var(--warn)"
       : +scoreVal >= 25 ? "var(--info)" : "var(--good)");
  const bigNum = el("span", {});
  dash.append(tile("t-score", "", el("div", { class: "tile-k" }, "EXPOSURE"),
    el("div", { class: "tile-big", style: `color:${scoreColor}` }, bigNum,
      el("span", { class: "tile-big-sub" }, scoreVal != null ? "/100" : "high")),
    el("div", { class: "tile-meta" }, scoreBand || `${findingCount} findings`)));
  countUp(bigNum, String(scoreVal != null ? scoreVal : highCount));

  // 3) GRAPH tile (opens the graph view).
  const gt = tile("t-graph", "", el("div", { class: "tile-k" }, "GRAPH"),
    el("div", { class: "tile-graphviz", id: "tile-graphviz" }),
    el("div", { class: "tile-meta" }, `${g.node_count || 0} nodes · tap to open`));
  gt.classList.add("clickable");
  gt.addEventListener("click", openGraph);
  dash.append(gt);
  drawMiniGraph($("#tile-graphviz"), out.graph);

  // 4) MAP tile (wide) — every geolocation found in this run, if any.
  const geo = [];
  for (const n of (out.graph?.nodes || [])) {
    const la = n.props?.lat, lo = n.props?.lon;
    if (typeof la === "number" && typeof lo === "number")
      geo.push({ lat: la, lon: lo, label: n.label || n.value });
  }
  for (const r of results) for (const f of (r.findings || []))
    if (f.map && typeof f.map.lat === "number")
      geo.push({ lat: f.map.lat, lon: f.map.lon, label: f.map.label || r.module });
  if (geo.length) {
    dash.append(tile("t-map", "wide", el("div", { class: "tile-k" }, `MAP · ${geo.length} location(s)`),
      el("div", { class: "tile-map", id: "tile-map" })));
    requestAnimationFrame(() => drawMapTile($("#tile-map"), geo));
  }

  // 5) ALERTS tile (wide) — only if there are any.
  if (alerts.length) {
    dash.append(tile("t-alerts", "wide alert",
      el("div", { class: "tile-k" }, `⚠ ALERTS · ${alerts.length}`),
      el("div", { class: "tile-alerts" },
        ...alerts.slice(0, 6).map((a) =>
          el("div", { class: "tile-alert-row" },
            el("span", { class: "ta-mod mono" }, a.module), a.text)))));
  }
}

function tile(id, cls, ...kids) {
  return el("div", { class: `tile ${cls}`, id }, ...kids);
}
function pillMini(t) { return el("span", { class: "pill-mini" }, t); }

// A tiny static node-scatter preview of the graph (colour = node type).
function drawMiniGraph(host, graph) {
  if (!host || !graph) return;
  const css = getComputedStyle(document.documentElement);
  const nodes = (graph.nodes || []).slice(0, 60);
  const svgNS = "http://www.w3.org/2000/svg";
  const svg = document.createElementNS(svgNS, "svg");
  svg.setAttribute("viewBox", "0 0 100 60");
  svg.style.cssText = "width:100%;height:100%";
  nodes.forEach((n, i) => {
    const c = document.createElementNS(svgNS, "circle");
    const a = (i / nodes.length) * Math.PI * 2 * 3;
    const rad = 6 + (i % 5) * 5;
    c.setAttribute("cx", 50 + Math.cos(a) * rad);
    c.setAttribute("cy", 30 + Math.sin(a) * rad * 0.55);
    c.setAttribute("r", 1.3 + Math.min(2, (n.degree || 0) * 0.3));
    c.setAttribute("fill", css.getPropertyValue(`--n-${n.type}`).trim() ||
      css.getPropertyValue("--n-default").trim());
    svg.appendChild(c);
  });
  host.innerHTML = "";
  host.appendChild(svg);
}

// Leaflet map tile with every geolocation found in the run.
function drawMapTile(host, points) {
  if (!host || !window.L || !points.length) return;
  const map = L.map(host, { attributionControl: false, zoomControl: false });
  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", { maxZoom: 19 }).addTo(map);
  const latlngs = [];
  for (const p of points) {
    L.circleMarker([p.lat, p.lon], { radius: 6, color: "#8b7cff",
      fillColor: "#8b7cff", fillOpacity: 0.7, weight: 2 })
      .addTo(map).bindPopup(p.label);
    latlngs.push([p.lat, p.lon]);
  }
  if (latlngs.length === 1) map.setView(latlngs[0], 9);
  else map.fitBounds(latlngs, { padding: [24, 24] });
}

// ------------------------------------------------------------ result filters --
const filterState = { cats: new Set(), search: "", hideEmpty: false };

function setupResultsToolbar(results) {
  const bar = $("#results-toolbar");
  bar.hidden = false;
  // Categories present in this run, in canonical order.
  const present = CATS.map(([k]) => k).filter((k) =>
    results.some((r) => (state.modules.find((m) => m.key === r.module)?.category) === k));
  filterState.cats = new Set(present);
  filterState.search = "";
  filterState.hideEmpty = false;

  const wrap = $("#rt-filters");
  wrap.innerHTML = "";
  for (const cat of present) {
    const label = CATS.find(([k]) => k === cat)[1];
    const count = results.filter((r) =>
      state.modules.find((m) => m.key === r.module)?.category === cat).length;
    const chip = el("button", {
      class: "rt-chip", "aria-pressed": "true", "data-cat": cat,
      style: catStyle(cat),
      onclick: () => {
        const on = chip.getAttribute("aria-pressed") === "true";
        chip.setAttribute("aria-pressed", on ? "false" : "true");
        chip.classList.toggle("off", on);
        if (on) filterState.cats.delete(cat); else filterState.cats.add(cat);
        applyResultFilters();
      },
    }, el("span", { class: "rt-dot" }), `${label} ${count}`);
    wrap.append(chip);
  }
  $("#rt-search").value = "";
  $("#rt-hide-empty").setAttribute("aria-pressed", "false");
  applyResultFilters();
}

function applyResultFilters() {
  const q = filterState.search;
  for (const card of $$("#results .card")) {
    const catOk = filterState.cats.has(card.dataset.cat);
    const emptyOk = !filterState.hideEmpty || card.dataset.empty !== "1";
    const searchOk = !q || (card.dataset.search || "").includes(q);
    card.classList.toggle("filtered", !(catOk && emptyOk && searchOk));
  }
}

// ------------------------------------------------------------ result cards --
function addSkeleton(grid, title) {
  const sk = el("div", { class: "card skeleton" },
    el("div", { class: "card-head" },
      el("div", { class: "card-ico shimmer" }),
      el("div", { class: "card-titles" },
        el("div", { class: "sk-line shimmer w40" }))),
    el("div", { class: "card-body" },
      el("div", { class: "sk-line shimmer w90" }),
      el("div", { class: "sk-line shimmer w70" }),
      el("div", { class: "sk-line shimmer w90" })));
  grid.append(sk);
  return sk;
}

function renderCard(res, i) {
  const m = state.modules.find((x) => x.key === res.module);
  const conf = res.error ? "err" : (res.confidence || "info");
  const cat = m?.category || "intel";
  const isEmpty = !!res.error || !(res.findings || []).length;
  // Searchable text: module name + every finding's text.
  const searchText = [m?.name || res.module,
    ...(res.findings || []).flatMap((f) => [f.label, f.summary,
      ...(f.values || [])])].join(" ").toLowerCase();
  // Rich cards (maps, images, or many values) get a wider bento tile.
  const rich = (res.findings || []).some((f) => f.map || f.image ||
    (Array.isArray(f.values) && f.values.length > 6));
  const card = el("div", { class: "card" + (rich ? " span2" : ""),
    "data-cat": cat, "data-conf": conf,
    "data-empty": isEmpty ? "1" : "0", "data-search": searchText,
    style: `--i:${i};${catStyle(cat)}` });

  // head
  card.append(el("div", { class: "card-head" },
    el("div", { class: "card-ico" }, icon(res.module, m?.category)),
    el("div", { class: "card-titles" },
      el("div", { class: "card-title" }, m?.name || res.module),
      el("div", { class: "card-source mono" }, res.source || "")),
    el("span", { class: `pill ${conf}` }, res.error ? "error" : conf)));

  // body
  const body = el("div", { class: "card-body" });
  if (res.error) {
    body.append(el("div", { class: "finding" },
      el("div", { class: "finding-summary" }, res.error)));
  } else if (!res.findings?.length) {
    body.append(el("div", { class: "finding" },
      el("div", { class: "finding-summary" }, "No findings.")));
  } else {
    // "Data-sheet" layout: simple label→value findings render as a compact grid
    // of record cells; richer findings (lists, maps, images) render below.
    const simple = res.findings.filter((f) => f.summary && !f.values && !f.map
      && !f.image && !f.note && !(f.label || "").startsWith("⚠"));
    const rich = res.findings.filter((f) => !simple.includes(f));
    if (simple.length >= 3) {
      const grid = el("div", { class: "record-grid" });
      for (const f of simple)
        grid.append(el("div", { class: "record-cell" },
          el("div", { class: "record-k" }, f.label || ""),
          el("div", { class: "record-v mono" + (f.confidence === "high" ? " hot" : "") },
            f.summary)));
      body.append(grid);
      for (const f of rich) body.append(renderFinding(f));
    } else {
      for (const f of res.findings) body.append(renderFinding(f));
    }
  }
  card.append(body);

  // JSON drawer
  if (res.raw != null) card.append(jsonDrawer(res.raw));

  // footer
  card.append(el("div", { class: "card-foot" },
    el("span", {}, res.source_url
      ? el("a", { href: res.source_url, target: "_blank",
                  style: "color:var(--text-3)" }, "source ↗")
      : ""),
    el("span", {}, `${res.duration_ms ?? 0}ms`)));
  return card;
}

function renderFinding(f) {
  // Warning/critical findings (label starts with ⚠) get the red treatment.
  const warn = typeof f.label === "string" && f.label.trim().startsWith("⚠");
  const row = el("div", { class: "finding" + (warn ? " finding-warn" : "") });
  if (f.label) {
    const lbl = el("div", { class: "finding-label" }, f.label);
    // A green "N" badge when this finding carries a list of hits.
    if (Array.isArray(f.values) && f.values.length > 1)
      lbl.append(el("span", { class: "hit-badge" }, String(f.values.length)));
    row.append(lbl);
  }
  if (f.summary) row.append(el("div", { class: "finding-summary" }, f.summary));

  // list of values (each copyable)
  if (Array.isArray(f.values) && f.values.length) {
    const list = el("div", { class: "finding-values" });
    for (const v of f.values) {
      list.append(el("div", { class: "finding-value" },
        el("span", {}, String(v)),
        el("button", { class: "copy-btn", title: "Copy",
          onclick: () => copy(String(v)) }, "⧉")));
    }
    row.append(list);
  }
  if (f.note) row.append(el("div", { class: "finding-note" }, f.note));

  // inline image (ELA visualisation, screenshots…)
  if (f.image) {
    row.append(el("img", { class: "finding-img", src: f.image, loading: "lazy",
      alt: f.label || "image" }));
  }

  // inline map (EXIF GPS etc.)
  if (f.map && typeof f.map.lat === "number") {
    const mapEl = el("div", { class: "finding-map" });
    row.append(mapEl);
    // Leaflet may still be loading; defer until ready.
    requestAnimationFrame(() => initMap(mapEl, f.map));
  }
  return row;
}

function initMap(node, m) {
  if (!window.L) { setTimeout(() => initMap(node, m), 200); return; }
  const map = L.map(node, { attributionControl: false, zoomControl: true })
    .setView([m.lat, m.lon], 14);
  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 19,
  }).addTo(map);
  L.marker([m.lat, m.lon]).addTo(map).bindPopup(m.label || "location").openPopup();
}

function jsonDrawer(raw) {
  const body = el("div", { class: "json-body" },
    el("pre", {}, JSON.stringify(raw, null, 2)));
  const btn = el("button", { class: "json-toggle",
    onclick: () => {
      body.classList.toggle("open");
      btn.firstChild.textContent = body.classList.contains("open") ? "▾ " : "▸ ";
    } }, "▸ ", "raw JSON");
  return el("div", { class: "json-drawer" }, btn, body);
}

// -------------------------------------------------------------- graph view --
function openGraph() {
  showView("graph");
  setActiveTab("graph");
  const host = $("#graph-canvas");
  if (!state.lastRun?.graph) {
    host.innerHTML = '<div class="empty-state"><p>Run a target first to build the graph.</p></div>';
    return;
  }
  if (!state.graph) state.graph = new GraphView(host);
  state.graph.setData(state.lastRun.graph);
  state.graph.onNodeClick = showNodePop;
  const s = state.lastRun.graph.stats;
  $("#graph-stats").textContent = `${s.node_count} nodes · ${s.edge_count} edges`;
  $("#node-pop").hidden = true;
  renderLegend(s.by_type || {});
}

// Colour legend for the node types actually present in the graph.
function renderLegend(byType) {
  const host = $("#graph-legend");
  host.innerHTML = "";
  const css = getComputedStyle(document.documentElement);
  Object.entries(byType).sort((a, b) => b[1] - a[1]).forEach(([type, count]) => {
    const color = css.getPropertyValue(`--n-${type}`).trim() ||
      css.getPropertyValue("--n-default").trim();
    host.append(el("span", { class: "legend-item" },
      el("span", { class: "legend-dot", style: `background:${color};box-shadow:0 0 6px ${color}` }),
      `${type} ${count}`));
  });
}

// Node types we can pivot on (they map to a runnable input type).
const PIVOTABLE = new Set(["domain", "subdomain", "ip", "btc_address",
  "eth_address", "email", "username", "url", "host"]);
let pivotDepth = 0;
const PIVOT_MAX = 3;    // depth limit for multi-hop expansion

function showNodePop(n) {
  const pop = $("#node-pop");
  pop.hidden = false;
  $("#node-pop-type").textContent = n.type;
  $("#node-pop-title").textContent = n.label || n.value;
  const body = $("#node-pop-body");
  body.innerHTML = "";
  const findings = n.findings || [];
  if (findings.length) {
    for (const f of findings)
      body.append(el("div", { class: "npf" },
        el("b", {}, f.module + ": "), f.summary));
  } else {
    // Show a couple of node props if no findings attached.
    const props = Object.entries(n.props || {}).slice(0, 5);
    if (props.length) for (const [k, v] of props)
      body.append(el("div", { class: "npf" }, el("b", {}, k + ": "), String(v)));
    else body.append(el("div", { class: "npf" }, "No findings recorded for this node."));
  }
  const expandBtn = $("#node-pop-expand");
  const can = PIVOTABLE.has(n.type) && pivotDepth < PIVOT_MAX;
  expandBtn.hidden = !can;
  expandBtn.textContent = pivotDepth >= PIVOT_MAX
    ? `⤢ Max depth (${PIVOT_MAX}) reached`
    : `⤢ Expand ${n.type} → run its modules`;
  expandBtn.onclick = () => expandNode(n);
}

// PIVOT: run all compatible modules on this node's value and MERGE the results
// into the live graph (multi-hop expansion, depth-limited).
async function expandNode(n) {
  const btn = $("#node-pop-expand");
  btn.disabled = true; btn.textContent = "expanding…";
  progress(true);
  try {
    const out = await api("/api/run", {
      method: "POST", body: JSON.stringify({ value: n.value }),
    });
    const added = state.graph.mergeData(out.graph);
    pivotDepth++;
    // Merge into the stored graph too, so Report/JSON reflect the expansion.
    mergeIntoLastRun(out);
    const s = state.graph;
    $("#graph-stats").textContent =
      `${s.nodes.length} nodes · ${s.edges.length} edges · depth ${pivotDepth}`;
    toast(`+${added} nodes from ${n.label}`);
    $("#node-pop").hidden = true;
  } catch (e) {
    toast("Expand failed: " + e.message);
  } finally {
    btn.disabled = false; progress(false);
  }
}
function mergeIntoLastRun(out) {
  if (!state.lastRun) { state.lastRun = out; return; }
  const g = state.lastRun.graph;
  const ids = new Set(g.nodes.map((x) => x.id));
  for (const nn of out.graph.nodes) if (!ids.has(nn.id)) g.nodes.push(nn);
  const ek = new Set(g.edges.map((x) => `${x.src}|${x.dst}|${x.label}`));
  for (const ee of out.graph.edges)
    if (!ek.has(`${ee.src}|${ee.dst}|${ee.label}`)) g.edges.push(ee);
  state.lastRun.results.push(...out.results);
}

// ------------------------------------------------------------ report --------
// Build the target profile + findings + evidence log and export it.
function exportReport(fmt) {
  if (!state.lastRun) { toast("Run a target first"); return; }
  const run = state.lastRun;
  const stamp = new Date().toISOString();

  if (fmt === "json") {
    const blob = { generated: stamp, target: run.value, input_type: run.input_type,
      graph: run.graph, results: run.results };
    download(`osint_${safe(run.value)}.json`,
      new Blob([JSON.stringify(blob, null, 2)], { type: "application/json" }));
    toast("JSON report saved");
    return;
  }

  if (fmt === "csv") {
    // Flatten every finding into rows: module, confidence, label, detail, source.
    const rows = [["module", "confidence", "label", "detail", "source_url"]];
    for (const r of run.results) {
      for (const f of (r.findings || [])) {
        const detail = f.summary ||
          (Array.isArray(f.values) ? f.values.join(" | ") : "");
        rows.push([r.module, r.confidence, f.label || "", detail, r.source_url || ""]);
      }
      if (r.error) rows.push([r.module, "error", "error", r.error, r.source_url || ""]);
    }
    const csv = rows.map((row) => row.map(csvCell).join(",")).join("\n");
    download(`osint_${safe(run.value)}.csv`,
      new Blob([csv], { type: "text/csv" }));
    toast("CSV report saved");
    return;
  }

  if (fmt === "print") openPrintReport(run, stamp);
}
function csvCell(v) {
  const s = String(v ?? "").replace(/"/g, '""');
  return /[",\n]/.test(s) ? `"${s}"` : s;
}
function safe(s) { return String(s).replace(/[^a-z0-9.-]/gi, "_").slice(0, 40); }
function download(name, blob) {
  const url = URL.createObjectURL(blob);
  const a = el("a", { href: url, download: name });
  document.body.append(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
// A print-optimised HTML window → the phone's "Save as PDF".
function openPrintReport(run, stamp) {
  const g = run.graph?.stats || {};
  const esc2 = (s) => String(s ?? "").replace(/[&<>]/g,
    (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c]));
  let html = `<!doctype html><meta charset=utf-8>
  <title>OSINT report · ${esc2(run.value)}</title>
  <style>
    body{font:14px -apple-system,system-ui,sans-serif;color:#111;max-width:760px;
      margin:32px auto;padding:0 16px}
    h1{font-size:22px;margin:0 0 4px} .sub{color:#666;font-size:12px;margin-bottom:24px}
    .card{border:1px solid #ddd;border-radius:8px;padding:14px 16px;margin:0 0 14px}
    .m{font-weight:700}.c{font-size:10px;text-transform:uppercase;color:#7a5cff}
    .f{padding:6px 0;border-top:1px solid #eee} .l{font-size:11px;color:#888;
      text-transform:uppercase;letter-spacing:.05em} .v{font-family:monospace;
      font-size:12px;color:#333;word-break:break-all}
    .stat{display:inline-block;margin-right:20px;font-size:13px}
    @media print{.no-print{display:none}}
  </style>
  <h1>OSINT Report — ${esc2(run.value)}</h1>
  <div class=sub>Type: ${esc2(run.input_type)} · Generated ${esc2(stamp)} ·
    ${g.node_count || 0} nodes / ${g.edge_count || 0} edges · public-data OSINT</div>
  <button class=no-print onclick=print()>Save as PDF / Print</button><hr>`;
  for (const r of run.results) {
    html += `<div class=card><div><span class=m>${esc2(r.source || r.module)}</span>
      · <span class=c>${esc2(r.error ? "error" : r.confidence)}</span></div>`;
    if (r.error) html += `<div class=f>${esc2(r.error)}</div>`;
    for (const f of (r.findings || [])) {
      html += `<div class=f><div class=l>${esc2(f.label || "")}</div>`;
      if (f.summary) html += `<div>${esc2(f.summary)}</div>`;
      for (const v of (f.values || [])) html += `<div class=v>${esc2(v)}</div>`;
      html += `</div>`;
    }
    if (r.source_url) html += `<div class=f class=v>Source: ${esc2(r.source_url)}</div>`;
    html += `</div>`;
  }
  const w = window.open("", "_blank");
  if (!w) { toast("Allow pop-ups to print the report"); return; }
  w.document.write(html); w.document.close();
}

// ------------------------------------------------------------ password check --
// HIBP "Pwned Passwords" k-anonymity, done entirely in the browser: we SHA-1 the
// password locally, send ONLY the first 5 hex chars of the hash to the range API,
// then match the returned suffixes on-device. The password itself never leaves
// the phone — we never send it anywhere and never store it.
function openPwCheck() {
  closeSidebar();
  $("#pwcheck").hidden = false;
  $("#pw-input").value = "";
  $("#pw-result").innerHTML = "";
  setTimeout(() => $("#pw-input").focus(), 40);
}

async function sha1Hex(str) {
  const buf = await crypto.subtle.digest("SHA-1", new TextEncoder().encode(str));
  return [...new Uint8Array(buf)].map((b) => b.toString(16).padStart(2, "0"))
    .join("").toUpperCase();
}

async function runPwCheck() {
  const pw = $("#pw-input").value;
  const out = $("#pw-result");
  if (!pw) { out.innerHTML = ""; return; }
  out.innerHTML = '<span class="pw-loading mono">checking on-device…</span>';
  try {
    const hash = await sha1Hex(pw);
    const prefix = hash.slice(0, 5), suffix = hash.slice(5);
    // Only the 5-char prefix is sent. HIBP supports CORS for client-side use.
    const res = await fetch(`https://api.pwnedpasswords.com/range/${prefix}`, {
      headers: { "Add-Padding": "true" },
    });
    if (!res.ok) throw new Error("range API " + res.status);
    const text = await res.text();
    let count = 0;
    for (const line of text.split("\n")) {
      const [suf, c] = line.trim().split(":");
      if (suf === suffix) { count = parseInt(c, 10) || 0; break; }
    }
    if (count > 0) {
      out.className = "pw-result bad";
      out.innerHTML = `<div class="pw-verdict">⚠ Pwned</div>
        <div>This password has appeared in <b>${count.toLocaleString()}</b>
        known breaches. Do NOT use it anywhere — change it now.</div>`;
    } else {
      out.className = "pw-result good";
      out.innerHTML = `<div class="pw-verdict">✓ Not found</div>
        <div>This exact password isn't in the Pwned Passwords set. That's good, but
        it doesn't guarantee it's strong or unique.</div>`;
    }
  } catch (e) {
    out.className = "pw-result";
    out.innerHTML = `<span class="mono">Check failed: ${esc(e.message)}. Your phone
      must be able to reach api.pwnedpasswords.com.</span>`;
  }
}

// ------------------------------------------------------------ command pal ---
function actions() {
  // Modules + a couple of global actions.
  const acts = state.modules.map((m) => ({
    label: m.name, sub: m.category, ico: icon(m.key, m.category),
    run: () => { closeCmdk(); quickPick(m); },
  }));
  acts.unshift(
    { label: "Open graph view", sub: "intel", ico: "◈",
      run: () => { closeCmdk(); openGraph(); } });
  return acts;
}
function openCmdk() {
  $("#cmdk").hidden = false;
  $("#cmdk-input").value = "";
  state.cmdkIndex = 0;
  renderCmdk("");
  setTimeout(() => $("#cmdk-input").focus(), 30);
}
function closeCmdk() { $("#cmdk").hidden = true; }
function renderCmdk(q) {
  const list = $("#cmdk-list");
  list.innerHTML = "";
  const ql = q.toLowerCase();
  const filtered = actions().filter((a) =>
    a.label.toLowerCase().includes(ql) || a.sub.includes(ql));
  state._cmdk = filtered;
  filtered.forEach((a, i) => {
    list.append(el("div", {
      class: "cmdk-row" + (i === state.cmdkIndex ? " sel" : ""),
      onclick: a.run,
    },
      el("span", { class: "nav-ico" }, a.ico),
      el("span", {}, a.label),
      el("span", { class: "cmdk-cat" }, a.sub)));
  });
}
function cmdkNav(e) {
  const items = state._cmdk || [];
  if (e.key === "ArrowDown") { state.cmdkIndex = Math.min(items.length - 1, state.cmdkIndex + 1); renderCmdk($("#cmdk-input").value); e.preventDefault(); }
  else if (e.key === "ArrowUp") { state.cmdkIndex = Math.max(0, state.cmdkIndex - 1); renderCmdk($("#cmdk-input").value); e.preventDefault(); }
  else if (e.key === "Enter") { items[state.cmdkIndex]?.run(); }
}

// ------------------------------------------------------------ view + misc ---
function showView(name) {
  $("#view-workspace").hidden = name !== "workspace";
  $("#view-graph").hidden = name !== "graph";
  $("#topbar-title").textContent = name === "graph" ? "Correlation graph" : "Workspace";
  if (name === "workspace") setActiveTab("work");
}
function progress(on) {
  const bar = $("#progress-bar");
  document.body.classList.toggle("running", on);
  if (on) { bar.classList.add("active"); bar.style.width = "85%"; }
  else { bar.style.width = "100%"; setTimeout(() => {
    bar.classList.remove("active"); bar.style.width = "0"; }, 250); }
}
function toggleSidebar() {
  const open = $("#sidebar").classList.toggle("open");
  $("#sidebar-backdrop").hidden = !open;
}
function closeSidebar() {
  $("#sidebar").classList.remove("open");
  $("#sidebar-backdrop").hidden = true;
}

// Return to the landing (hero + deck + stats), clearing the last run.
function resetToLanding() {
  document.body.classList.remove("has-results");
  $("#results").innerHTML = "";
  $("#results-head").hidden = true;
  $("#results-toolbar").hidden = true;
  $("#dash").hidden = true;
  $("#dash").innerHTML = "";
  $("#target-input").value = "";
  $("#clear-btn").hidden = true;
  $("#type-pill").textContent = "auto";
  $("#scope-gate").hidden = true;
  $("#upload-row").hidden = true;
  uploadedFile = null;
  $("#upload-name").textContent = "";
  showView("workspace");
  $("#target-input").focus();
}

async function pingHealth() {
  try {
    const h = await api("/api/health");
    $("#conn-dot").classList.add("ok");
    $("#conn-text").textContent = `${h.modules} modules · ready`;
  } catch {
    $("#conn-dot").classList.add("err");
    $("#conn-text").textContent = "offline";
  }
}

function registerSW() {
  if ("serviceWorker" in navigator)
    navigator.serviceWorker.register("/sw.js").catch(() => {});
}
