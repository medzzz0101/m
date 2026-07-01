/* graph.js — a tiny canvas force-directed renderer for the entity graph.
   No dependencies. Nodes repel, edges pull, everything settles into a layout
   you can drag and pan. Colours come from the node `type` (see tokens.css). */

const NODE_COLORS = {
  username: "#8b7cff", profile: "#a99bff", email: "#e8c468",
  domain: "#7fb6f0", subdomain: "#9ecbf5", ip: "#5ad6a0",
  geo: "#f08a8a", tech: "#e892d0", org: "#ffffff", url: "#c0c6d0",
};
const col = (t) => NODE_COLORS[t] || "#6d6b7e";

export function renderGraph(canvas, data) {
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
    // edges
    ctx.lineWidth = dpr;
    for (const e of edges) {
      const a = nodes[e.s], b = nodes[e.t];
      ctx.strokeStyle = "rgba(255,255,255,0.10)";
      ctx.beginPath(); ctx.moveTo(a.x, a.y); ctx.lineTo(b.x, b.y); ctx.stroke();
    }
    // nodes
    ctx.font = `${11 * dpr}px ui-monospace, monospace`;
    for (const n of nodes) {
      const c = col(n.type);
      ctx.beginPath(); ctx.arc(n.x, n.y, n.r, 0, Math.PI * 2);
      ctx.fillStyle = c; ctx.shadowColor = c; ctx.shadowBlur = (n === hover ? 16 : 6) * dpr;
      ctx.fill(); ctx.shadowBlur = 0;
      if (n === hover || n.r > 9 * dpr) {
        ctx.fillStyle = "#cdd2da";
        const label = (n.label || n.value || "").slice(0, 22);
        ctx.fillText(label, n.x + n.r + 4 * dpr, n.y + 4 * dpr);
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
  canvas.onmousedown = (ev) => { drag = at(ev); if (!drag) drag = { pan: true, sx: ev.clientX - pan.x, sy: ev.clientY - pan.y }; };
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
  canvas.onmouseup = () => { drag = null; };
  canvas.onmouseleave = () => { drag = null; hover = null; };

  return { stop() { running = false; } };
}
