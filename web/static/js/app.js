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
  } catch (e) {
    toast("Failed to load modules");
  }
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
    class: "nav-item", title: m.description,
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

// When a sidebar/module entry is tapped, focus the input (and hint the type).
function quickPick(m) {
  closeSidebar();
  showView("workspace");
  const inp = $("#target-input");
  inp.focus();
  toast(`${m.name} · accepts ${m.accepts.join(", ")}`);
  // Toggle the upload affordance if this is an image/file module.
  const isImg = m.accepts.includes("image") || m.accepts.includes("file");
  $("#upload-row").style.display = isImg ? "flex" : "none";
}

// ----------------------------------------------------------------- UI bind --
function bindUI() {
  $("#run-btn").addEventListener("click", runTarget);
  $("#target-input").addEventListener("keydown", (e) => {
    if (e.key === "Enter") runTarget();
  });
  $("#target-input").addEventListener("input", debounce(onType, 220));

  $("#menu-btn")?.addEventListener("click", toggleSidebar);
  $("#cmdk-trigger").addEventListener("click", openCmdk);
  $("#view-graph-btn").addEventListener("click", openGraph);
  $("#graph-back").addEventListener("click", () => showView("workspace"));

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

  // Reveal results area, hide empty state.
  $("#empty-state").hidden = true;
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
  const card = el("div", { class: "card", style: `--i:${i}` });

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
  state.graph.onNodeClick = (n) => {
    const fs = (n.findings || []).map((f) => `${f.module}: ${f.summary}`).join("\n");
    toast(`${n.type} · ${n.label}`);
    if (fs) setTimeout(() => alertNode(n), 0);
  };
  const s = state.lastRun.graph.stats;
  $("#graph-stats").textContent = `${s.node_count} nodes · ${s.edge_count} edges`;
}
function alertNode(n) {
  const lines = (n.findings || []).map((f) => `• ${f.module}: ${f.summary}`);
  toast(`${n.label}: ${lines.length} finding(s)`);
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
