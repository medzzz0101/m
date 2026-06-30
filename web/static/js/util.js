/* ==========================================================================
   util.js — tiny shared helpers (no framework, just ES modules).
   Exported so app.js and graph.js can reuse them.
   ========================================================================== */

/** Shorthand DOM query. */
export const $  = (sel, root = document) => root.querySelector(sel);
export const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];

/** Create an element with attrs + children in one call (mini hyperscript). */
export function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") node.className = v;
    else if (k === "html") node.innerHTML = v;
    else if (k.startsWith("on") && typeof v === "function")
      node.addEventListener(k.slice(2).toLowerCase(), v);
    else if (v !== null && v !== undefined && v !== false)
      node.setAttribute(k, v === true ? "" : v);
  }
  for (const c of children.flat()) {
    if (c == null || c === false) continue;
    node.append(c.nodeType ? c : document.createTextNode(String(c)));
  }
  return node;
}

/** Escape text for safe innerHTML insertion (we mostly use textNodes, but the
    JSON drawer + a few spots need this). */
export function esc(s) {
  return String(s).replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}

/** Fetch JSON with a friendly error throw. */
export async function api(path, opts = {}) {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json" }, ...opts,
  });
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json();
}

/** Copy text to clipboard, then fire a toast. */
export async function copy(text) {
  try {
    await navigator.clipboard.writeText(text);
    toast("Copied", true);
  } catch {
    // Fallback for non-secure contexts.
    const ta = el("textarea", {}, text);
    document.body.append(ta); ta.select();
    document.execCommand("copy"); ta.remove();
    toast("Copied", true);
  }
}

/** Transient toast notification. */
export function toast(msg, ok = false) {
  const host = $("#toast-host");
  const t = el("div", { class: "toast" },
    ok ? el("span", { class: "tick" }, "✓") : null, msg);
  host.append(t);
  setTimeout(() => {
    t.style.opacity = "0";
    t.style.transition = "opacity 200ms";
    setTimeout(() => t.remove(), 220);
  }, 1600);
}

/** Debounce a function (used for the live type-detect + cmdk search). */
export function debounce(fn, ms = 200) {
  let h;
  return (...a) => { clearTimeout(h); h = setTimeout(() => fn(...a), ms); };
}

/** Map a node/module category to a small line-style glyph. */
export const ICONS = {
  infrastructure: "▤", blockchain: "⬡", image: "▦", identity: "◐", intel: "◈",
  // per-module overrides
  dns_full: "⌁", whois: "✦", username: "◐", btc_explorer: "⬡", exif_gps: "⌖",
  subdomains: "⋔", live_hosts: "◉", tls_certs: "▒", favicon_hash: "❖",
  asn: "▦", ip_geo: "⌖", reverse_ip: "↺", tech_fingerprint: "⚙",
};
export const icon = (k, cat) => ICONS[k] || ICONS[cat] || "•";
