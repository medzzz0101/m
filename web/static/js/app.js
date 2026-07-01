/* ==========================================================================
   app.js — the controller. Wires the shell together:
     * loads the module catalog -> renders sidebar + tab bar + command palette
     * live input-type detection
     * runs a target, streams result cards in (skeleton -> real, staggered)
     * renders findings, pills, copy buttons, JSON drawers, inline maps
     * graph view hand-off
   No framework — just modules + the DOM. Heavily commented for learning.
   ========================================================================== */

import { $, $$, el, api, copy, toast, debounce, icon } from "./util.js";
import { GraphView } from "./graph.js";

const state = {
  modules: [],          // catalog from /api/modules
  byCat: {},            // category -> [modules]
  lastRun: null,        // last /api/run payload (for graph view)
  graph: null,          // GraphView instance
  cmdkIndex: 0,
};

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
  await loadModules();
  bindUI();
  registerSW();
  pingHealth();
}

async function loadModules() {
  try {
    const data = await api("/api/modules");
    state.modules = data.modules;
    state.byCat = {};
    for (const m of state.modules)
      (state.byCat[m.category] ||= []).push(m);
    renderSidebar();
    renderTabbar();
    renderStats();
    renderDeck();
  } catch (e) {
    toast("Failed to load modules");
  }
}

// Small dashboard of headline numbers on the landing.
function renderStats() {
  const strip = $("#stat-strip");
  if (!strip) return;
  const cats = Object.keys(state.byCat).length;
  const sources = new Set(state.modules.map((m) => m.name)).size;
  strip.innerHTML = "";
  const items = [
    [String(state.modules.length), "Modules"],
    [String(cats), "Domains"],
    [String(sources), "Data sources"],
    ["100%", "Public data"],
  ];
  for (const [num, label] of items) {
    strip.append(el("div", { class: "stat" },
      el("div", { class: "stat-num", html: num.replace("%", '<span class="accent">%</span>') }),
      el("div", { class: "stat-label" }, label)));
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
  const card = el("div", {
    class: "deck-card", title: m.description, "data-cat": m.category,
    onclick: () => pickModule(m),
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
  return card;
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

  // Example chips fill the input (and image chip opens the picker).
  $$(".chip[data-fill]").forEach((c) =>
    c.addEventListener("click", () => {
      $("#target-input").value = c.dataset.fill;
      onType(); $("#clear-btn").hidden = false; $("#target-input").focus();
    }));
  $("#chip-upload").addEventListener("click", () => {
    $("#upload-row").hidden = false; $("#file-input").click();
  });

  $("#menu-btn")?.addEventListener("click", toggleSidebar);
  $("#cmdk-trigger").addEventListener("click", openCmdk);
  $("#view-graph-btn").addEventListener("click", openGraph);
  $("#graph-back").addEventListener("click", () => showView("workspace"));
  $("#node-pop-close").addEventListener("click", () => ($("#node-pop").hidden = true));

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

    // Detect type, learn which modules will run, lay down skeletons.
    const det = await api(`/api/detect?value=${encodeURIComponent(value)}`);
    $("#results-summary").textContent =
      `${det.label} · ${det.compatible_modules.length} module(s)`;
    const skeletons = {};
    det.compatible_modules.forEach((k) => {
      const m = state.modules.find((x) => x.key === k);
      skeletons[k] = addSkeleton(grid, m?.name || k);
    });

    // Run everything server-side (concurrent) and swap skeletons for cards.
    const out = await api("/api/run", {
      method: "POST",
      body: JSON.stringify({ value, authorized }),
    });
    state.lastRun = out;

    out.results.forEach((res, i) => {
      const sk = skeletons[res.module];
      const card = renderCard(res, i);
      if (sk) sk.replaceWith(card); else grid.append(card);
    });

    // Graph hint.
    const g = out.graph?.stats;
    if (g) $("#results-summary").textContent =
      `${det.label} · ${out.results.length} modules · ${g.node_count} nodes / ${g.edge_count} edges`;
  } catch (e) {
    toast("Run failed: " + e.message);
  } finally {
    progress(false);
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
  const card = el("div", { class: "card", "data-cat": cat,
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
    for (const f of res.findings) body.append(renderFinding(f));
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
  const row = el("div", { class: "finding" });
  if (f.label) row.append(el("div", { class: "finding-label" }, f.label));
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
  if (on) { bar.classList.add("active"); bar.style.width = "85%"; }
  else { bar.style.width = "100%"; setTimeout(() => {
    bar.classList.remove("active"); bar.style.width = "0"; }, 250); }
}
function toggleSidebar() { $("#sidebar").classList.toggle("open"); }
function closeSidebar() { $("#sidebar").classList.remove("open"); }

// Return to the landing (hero + deck + stats), clearing the last run.
function resetToLanding() {
  document.body.classList.remove("has-results");
  $("#results").innerHTML = "";
  $("#results-head").hidden = true;
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
