/* graph.js — a tiny canvas force-directed renderer for the entity graph.
   No dependencies. Nodes repel, edges pull, everything settles into a layout
   you can drag and pan. Colours come from the node `type` (see tokens.css). */

const NODE_COLORS = {
  username: "#8b7cff", profile: "#a99bff", email: "#e8c468",
  domain: "#7fb6f0", subdomain: "#9ecbf5", ip: "#5ad6a0",
  geo: "#f08a8a", tech: "#e892d0", org: "#ffffff", url: "#c0c6d0",
  btc: "#f7931a",
};
const col = (t) => NODE_COLORS[t] || "#6d6b7e";

// --- public avatars on the board ------------------------------------------
// Faces come only from PUBLIC profile pictures: the avatar a person published
// themselves. `meta.img` is a real URL the backend already resolved (e.g. the
// GitHub avatar); otherwise we ask unavatar.io — a public avatar CDN — for the
// picture of a known platform handle. No private data, just public pictures.
const UNAVATAR = {
  github: "github", twitter: "twitter", x: "twitter", instagram: "instagram",
  telegram: "telegram", youtube: "youtube", tiktok: "tiktok", reddit: "reddit",
  soundcloud: "soundcloud", dribbble: "dribbble", medium: "medium",
  substack: "substack", gravatar: "gravatar",
};
function providerFor(label) {
  const s = (label || "").toLowerCase();
  for (const k in UNAVATAR) if (s.includes(k)) return UNAVATAR[k];
  return null;
}
function avatarURL(n) {
  if (n.meta && n.meta.img) return n.meta.img;                 // real, backend-resolved
  if (n.type === "username" && n.value)
    return `https://unavatar.io/github/${encodeURIComponent(n.value)}?fallback=false`;
  if (n.type === "profile" && typeof n.value === "string") {
    const prov = providerFor(n.label);
    const user = n.value.slice(n.value.indexOf(":") + 1);
    if (prov && user) return `https://unavatar.io/${prov}/${encodeURIComponent(user)}?fallback=false`;
  }
  return null;
}

// onSelect(node) fires when a node is clicked — the app opens an inspector panel.
export function renderGraph(canvas, data, onSelect) {
  const ctx = canvas.getContext("2d");
  const dpr = window.devicePixelRatio || 1;
  function resize() {
    canvas.width = canvas.clientWidth * dpr;
    canvas.height = canvas.clientHeight * dpr;
  }
  resize();
  window.addEventListener("resize", resize);

  const W = () => canvas.width, H = () => canvas.height;
  const nodes = data.nodes.map((n, i) => ({
    ...n,
    x: W() / 2 + Math.cos(i) * 120 * dpr + (Math.random() - .5) * 40,
    y: H() / 2 + Math.sin(i) * 120 * dpr + (Math.random() - .5) * 40,
    vx: 0, vy: 0,
    r: (6 + Math.min(n.degree || 0, 6) * 2) * dpr,
  }));
  // kick off async avatar loads — image is tainted-but-drawable (we never read
  // pixels back), so we deliberately do NOT set crossOrigin.
  for (const n of nodes) {
    const url = avatarURL(n);
    if (!url) continue;
    const im = new Image();
    im.onload = () => { n._av = im; n.r = Math.max(n.r, 15 * dpr); };
    im.onerror = () => {};
    im.src = url;
  }
  const idx = Object.fromEntries(nodes.map((n, i) => [n.id, i]));
  const edges = data.edges
    .filter((e) => idx[e.source] !== undefined && idx[e.target] !== undefined)
    .map((e) => ({ s: idx[e.source], t: idx[e.target], kind: e.kind }));

  let pan = { x: 0, y: 0 }, drag = null, hover = null;

  function step() {
    // repulsion
    for (let i = 0; i < nodes.length; i++) {
      for (let j = i + 1; j < nodes.length; j++) {
        const a = nodes[i], b = nodes[j];
        let dx = a.x - b.x, dy = a.y - b.y;
        let d2 = dx * dx + dy * dy || 1;
        const f = (9000 * dpr * dpr) / d2;
        const d = Math.sqrt(d2);
        a.vx += (dx / d) * f; a.vy += (dy / d) * f;
        b.vx -= (dx / d) * f; b.vy -= (dy / d) * f;
      }
    }
    // springs
    for (const e of edges) {
      const a = nodes[e.s], b = nodes[e.t];
      let dx = b.x - a.x, dy = b.y - a.y;
      const d = Math.sqrt(dx * dx + dy * dy) || 1;
      const f = (d - 110 * dpr) * 0.015;
      a.vx += (dx / d) * f; a.vy += (dy / d) * f;
      b.vx -= (dx / d) * f; b.vy -= (dy / d) * f;
    }
    // centering + integrate
    for (const n of nodes) {
      n.vx += (W() / 2 - n.x) * 0.0009;
      n.vy += (H() / 2 - n.y) * 0.0009;
      n.vx *= 0.86; n.vy *= 0.86;
      if (n !== drag) { n.x += n.vx; n.y += n.vy; }
    }
  }

  function draw() {
    ctx.clearRect(0, 0, W(), H());
    ctx.save();
    ctx.translate(pan.x, pan.y);
    // edges — VERIFIED "same person" links (same_as) render as solid violet;
    // mere presence / relation links stay a faint cyan. This reads confidence
    // at a glance: bright = provably the same person, faint = a profile exists.
    for (const e of edges) {
      const a = nodes[e.s], b = nodes[e.t];
      const lit = hover && (a === hover || b === hover);
      const verified = e.kind === "same_as";
      if (verified) {
        ctx.strokeStyle = lit ? "rgba(139,124,247,0.85)" : "rgba(139,124,247,0.42)";
        ctx.shadowColor = "rgba(139,124,247,0.6)"; ctx.shadowBlur = lit ? 10 * dpr : 3 * dpr;
        ctx.lineWidth = 1.6 * dpr;
      } else {
        ctx.strokeStyle = lit ? "rgba(30,230,207,0.5)" : "rgba(30,230,207,0.13)";
        ctx.shadowColor = "rgba(30,230,207,0.5)"; ctx.shadowBlur = lit ? 8 * dpr : 0;
        ctx.lineWidth = dpr;
      }
      ctx.beginPath(); ctx.moveTo(a.x, a.y); ctx.lineTo(b.x, b.y); ctx.stroke();
      ctx.shadowBlur = 0;
    }
    // nodes
    ctx.font = `${11 * dpr}px ui-monospace, monospace`;
    for (const n of nodes) {
      const c = col(n.type);
      // hovered node gets a ring
      if (n === hover) {
        ctx.beginPath(); ctx.arc(n.x, n.y, n.r + 5 * dpr, 0, Math.PI * 2);
        ctx.strokeStyle = c; ctx.lineWidth = 1.5 * dpr; ctx.globalAlpha = .5; ctx.stroke(); ctx.globalAlpha = 1;
      }
      if (n._av) {
        // clip a circle and paint the public avatar inside it
        ctx.save();
        ctx.beginPath(); ctx.arc(n.x, n.y, n.r, 0, Math.PI * 2); ctx.closePath(); ctx.clip();
        ctx.drawImage(n._av, n.x - n.r, n.y - n.r, n.r * 2, n.r * 2);
        ctx.restore();
        // coloured ring so the entity type still reads at a glance
        ctx.beginPath(); ctx.arc(n.x, n.y, n.r, 0, Math.PI * 2);
        ctx.strokeStyle = c; ctx.lineWidth = (n === hover ? 2 : 1.5) * dpr;
        ctx.shadowColor = c; ctx.shadowBlur = (n === hover ? 18 : 7) * dpr;
        ctx.stroke(); ctx.shadowBlur = 0;
      } else {
        ctx.beginPath(); ctx.arc(n.x, n.y, n.r, 0, Math.PI * 2);
        ctx.fillStyle = c; ctx.shadowColor = c; ctx.shadowBlur = (n === hover ? 18 : 7) * dpr;
        ctx.fill(); ctx.shadowBlur = 0;
      }
      // label: always for meaningful nodes, or on hover
      if (n === hover || (n.degree || 0) >= 1 || nodes.length <= 12) {
        const label = (n.label || n.value || "").slice(0, 24);
        ctx.fillStyle = n === hover ? "#f0f2f5" : "#aab0bb";
        ctx.fillText(label, n.x + n.r + 5 * dpr, n.y + 4 * dpr);
      }
    }
    ctx.restore();
  }

  let running = true;
  function loop() { if (!running) return; step(); draw(); requestAnimationFrame(loop); }
  loop();

  // interaction
  function at(ev) {
    const rect = canvas.getBoundingClientRect();
    const x = (ev.clientX - rect.left) * dpr - pan.x;
    const y = (ev.clientY - rect.top) * dpr - pan.y;
    return nodes.find((n) => (x - n.x) ** 2 + (y - n.y) ** 2 < (n.r + 4 * dpr) ** 2);
  }
  let downPos = null, downNode = null;
  canvas.onmousedown = (ev) => {
    downPos = { x: ev.clientX, y: ev.clientY };
    downNode = at(ev);
    drag = downNode || { pan: true, sx: ev.clientX - pan.x, sy: ev.clientY - pan.y };
  };
  canvas.onmousemove = (ev) => {
    hover = at(ev);
    canvas.style.cursor = hover ? "pointer" : "grab";
    if (drag && drag.pan) { pan.x = ev.clientX - drag.sx; pan.y = ev.clientY - drag.sy; }
    else if (drag) {
      const rect = canvas.getBoundingClientRect();
      drag.x = (ev.clientX - rect.left) * dpr - pan.x;
      drag.y = (ev.clientY - rect.top) * dpr - pan.y;
    }
  };
  canvas.onmouseup = (ev) => {
    // A click (little movement) on a node = select it → open the inspector.
    if (downNode && downPos && Math.hypot(ev.clientX - downPos.x, ev.clientY - downPos.y) < 5) {
      const neighbours = edges.filter((e) => nodes[e.s] === downNode || nodes[e.t] === downNode)
        .map((e) => (nodes[e.s] === downNode ? nodes[e.t] : nodes[e.s]));
      if (onSelect) onSelect(downNode, neighbours);
    }
    drag = null; downNode = null; downPos = null;
  };
  // touch support
  canvas.ontouchstart = (ev) => { const t = ev.touches[0]; canvas.onmousedown({ clientX: t.clientX, clientY: t.clientY }); };
  canvas.ontouchmove = (ev) => { const t = ev.touches[0]; canvas.onmousemove({ clientX: t.clientX, clientY: t.clientY }); ev.preventDefault(); };
  canvas.ontouchend = (ev) => { const t = ev.changedTouches[0]; canvas.onmouseup({ clientX: t.clientX, clientY: t.clientY }); };
  canvas.onmouseleave = () => { drag = null; hover = null; };

  return { stop() { running = false; } };
}
