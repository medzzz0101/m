/* ==========================================================================
   graph.js — the interactive correlation graph view.
   A small, dependency-free force-directed layout drawn on a <canvas>:
     * nodes coloured by type (colours come from CSS tokens),
     * labelled edges,
     * pan (drag background) + zoom (wheel / pinch),
     * click a node to see its findings in a side popover.
   A full graph lib would be heavier; a few hundred lines of canvas keeps the
   bundle tiny and teaches the underlying physics. Phase 2 wires it to live data.
   ========================================================================== */

import { el } from "./util.js";

// Pull node colours straight from the CSS variables so the graph and the rest
// of the UI never drift apart.
function nodeColor(type) {
  const css = getComputedStyle(document.documentElement);
  return css.getPropertyValue(`--n-${type}`).trim() ||
         css.getPropertyValue("--n-default").trim();
}

export class GraphView {
  constructor(canvasHost) {
    this.host = canvasHost;
    this.canvas = el("canvas", { class: "graph-gl" });
    this.canvas.style.cssText = "width:100%;height:100%;display:block;cursor:grab;";
    this.host.innerHTML = "";
    this.host.append(this.canvas);
    this.ctx = this.canvas.getContext("2d");

    this.nodes = [];           // {id,type,label,x,y,vx,vy,degree,findings}
    this.edges = [];           // {src,dst,label}
    this.scale = 1;
    this.offset = { x: 0, y: 0 };
    this.dragging = null;      // node being dragged or 'pan'
    this.hover = null;
    this.onNodeClick = null;   // callback set by app.js

    this._bindEvents();
    this._resize();
    window.addEventListener("resize", () => this._resize());
    this._raf = requestAnimationFrame(() => this._tick());
  }

  /** Load a {nodes, edges} payload (from /api/run), replacing the graph. */
  setData(graph) {
    this.nodes = [];
    this.edges = [];
    this._byId = new Map();
    this.mergeData(graph);
    this._fit();
  }

  /** MERGE a subgraph into the current one (used by pivot expansion). Existing
      nodes keep their positions; only genuinely new nodes/edges are added. */
  mergeData(graph) {
    const W = this.canvas.clientWidth, H = this.canvas.clientHeight;
    this._byId = this._byId || new Map();
    let added = 0;
    for (const n of graph.nodes) {
      if (this._byId.has(n.id)) {
        // Refresh findings/degree on an already-placed node.
        Object.assign(this._byId.get(n.id), {
          findings: n.findings || this._byId.get(n.id).findings,
          degree: Math.max(this._byId.get(n.id).degree || 0, n.degree || 0),
        });
        continue;
      }
      const node = {
        ...n,
        x: W / 2 + (Math.random() - 0.5) * 260,
        y: H / 2 + (Math.random() - 0.5) * 260,
        vx: 0, vy: 0,
        r: 6 + Math.min(10, (n.degree || 0) * 1.5),
        born: performance.now(),   // for the scale-in entrance animation
      };
      this._byId.set(n.id, node);
      this.nodes.push(node);
      added++;
    }
    const seen = new Set(this.edges.map((e) => `${e.src}|${e.dst}|${e.label}`));
    for (const e of graph.edges) {
      const key = `${e.src}|${e.dst}|${e.label}`;
      if (seen.has(key)) continue;
      if (this._byId.has(e.src) && this._byId.has(e.dst)) {
        this.edges.push({ ...e, a: this._byId.get(e.src), b: this._byId.get(e.dst) });
        seen.add(key);
      }
    }
    return added;
  }

  // ---- physics: a simple spring/charge model -----------------------------
  _physics() {
    const nodes = this.nodes, edges = this.edges;
    const REPULSE = 5200, SPRING = 0.012, LEN = 90, DAMP = 0.86, CENTER = 0.002;
    const W = this.canvas.clientWidth, H = this.canvas.clientHeight;
    for (let i = 0; i < nodes.length; i++) {
      const a = nodes[i];
      // Charge: every pair of nodes repels (Coulomb-ish).
      for (let j = i + 1; j < nodes.length; j++) {
        const b = nodes[j];
        let dx = a.x - b.x, dy = a.y - b.y;
        let d2 = dx * dx + dy * dy || 0.01;
        const f = REPULSE / d2;
        const d = Math.sqrt(d2);
        const fx = (dx / d) * f, fy = (dy / d) * f;
        a.vx += fx; a.vy += fy; b.vx -= fx; b.vy -= fy;
      }
      // Gentle pull toward centre so disconnected bits don't fly off.
      a.vx += (W / 2 - a.x) * CENTER;
      a.vy += (H / 2 - a.y) * CENTER;
    }
    // Springs: connected nodes attract toward a rest length.
    for (const e of edges) {
      const dx = e.b.x - e.a.x, dy = e.b.y - e.a.y;
      const d = Math.sqrt(dx * dx + dy * dy) || 0.01;
      const f = (d - LEN) * SPRING;
      const fx = (dx / d) * f, fy = (dy / d) * f;
      e.a.vx += fx; e.a.vy += fy; e.b.vx -= fx; e.b.vy -= fy;
    }
    for (const n of nodes) {
      if (n === this.dragging) continue;
      n.vx *= DAMP; n.vy *= DAMP;
      n.x += n.vx; n.y += n.vy;
    }
  }

  // ---- render ------------------------------------------------------------
  _tick() {
    this._physics();
    const ctx = this.ctx;
    const W = this.canvas.width, H = this.canvas.height;
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.clearRect(0, 0, W, H);
    ctx.save();
    ctx.translate(this.offset.x, this.offset.y);
    ctx.scale(this.scale * devicePixelRatio, this.scale * devicePixelRatio);

    // When hovering a node, compute its direct neighbours to highlight.
    let near = null;
    if (this.hover) {
      near = new Set([this.hover.id]);
      for (const e of this.edges) {
        if (e.a === this.hover) near.add(e.b.id);
        if (e.b === this.hover) near.add(e.a.id);
      }
    }

    // edges
    ctx.lineWidth = 1;
    ctx.font = "9px ui-monospace, monospace";
    for (const e of this.edges) {
      const lit = near && (e.a === this.hover || e.b === this.hover);
      const dim = near && !lit;
      ctx.strokeStyle = lit ? "rgba(139,124,255,0.55)"
        : dim ? "rgba(255,255,255,0.03)" : "rgba(255,255,255,0.10)";
      ctx.lineWidth = lit ? 1.6 : 1;
      ctx.beginPath(); ctx.moveTo(e.a.x, e.a.y); ctx.lineTo(e.b.x, e.b.y); ctx.stroke();
      // edge label at midpoint (only when not dimmed, to reduce clutter)
      if (!dim) {
        const mx = (e.a.x + e.b.x) / 2, my = (e.a.y + e.b.y) / 2;
        ctx.fillStyle = lit ? "rgba(200,196,255,0.85)" : "rgba(168,166,184,0.45)";
        ctx.fillText(e.label, mx + 2, my - 2);
      }
    }
    this._near = near;
    // nodes  (reuse the `near` set computed above for the edge highlight)
    const now = performance.now();
    for (const n of this.nodes) {
      const c = nodeColor(n.type);
      // Entrance: scale + fade in over 400ms from when the node was born.
      const age = Math.min(1, (now - (n.born || 0)) / 400);
      const grow = 0.4 + 0.6 * (1 - Math.pow(1 - age, 3));
      const r = n.r * grow;
      // Dim nodes not connected to the hovered one.
      ctx.globalAlpha = age * (near && !near.has(n.id) ? 0.2 : 1);
      ctx.beginPath(); ctx.arc(n.x, n.y, r, 0, Math.PI * 2);
      ctx.fillStyle = c;
      ctx.shadowColor = c; ctx.shadowBlur = n === this.hover ? 18 : 6;
      ctx.fill(); ctx.shadowBlur = 0;
      if (n === this.hover) { ctx.lineWidth = 2; ctx.strokeStyle = "#fff"; ctx.stroke(); }
      // label
      ctx.fillStyle = "rgba(236,235,242,0.92)";
      ctx.font = "10px ui-monospace, monospace";
      const label = (n.label || n.value || "").slice(0, 22);
      ctx.fillText(label, n.x + r + 4, n.y + 3);
      ctx.globalAlpha = 1;
    }
    ctx.restore();
    this._raf = requestAnimationFrame(() => this._tick());
  }

  // ---- interaction -------------------------------------------------------
  _toWorld(px, py) {
    const rect = this.canvas.getBoundingClientRect();
    const x = ((px - rect.left) * devicePixelRatio - this.offset.x) /
              (this.scale * devicePixelRatio);
    const y = ((py - rect.top) * devicePixelRatio - this.offset.y) /
              (this.scale * devicePixelRatio);
    return { x, y };
  }
  _hitNode(px, py) {
    const p = this._toWorld(px, py);
    for (const n of this.nodes) {
      const dx = n.x - p.x, dy = n.y - p.y;
      if (dx * dx + dy * dy <= (n.r + 4) ** 2) return n;
    }
    return null;
  }
  _bindEvents() {
    const c = this.canvas;
    let last = null;
    c.addEventListener("pointerdown", (e) => {
      c.setPointerCapture(e.pointerId);
      const n = this._hitNode(e.clientX, e.clientY);
      this.dragging = n || "pan";
      last = { x: e.clientX, y: e.clientY };
      this._moved = false;
      c.style.cursor = "grabbing";
    });
    c.addEventListener("pointermove", (e) => {
      this.hover = this._hitNode(e.clientX, e.clientY);
      c.style.cursor = this.dragging ? "grabbing" : (this.hover ? "pointer" : "grab");
      if (!this.dragging || !last) return;
      const dx = e.clientX - last.x, dy = e.clientY - last.y;
      if (Math.abs(dx) + Math.abs(dy) > 3) this._moved = true;
      if (this.dragging === "pan") {
        this.offset.x += dx * devicePixelRatio;
        this.offset.y += dy * devicePixelRatio;
      } else {
        const w = this._toWorld(e.clientX, e.clientY);
        this.dragging.x = w.x; this.dragging.y = w.y;
        this.dragging.vx = this.dragging.vy = 0;
      }
      last = { x: e.clientX, y: e.clientY };
    });
    c.addEventListener("pointerup", (e) => {
      if (this.dragging && this.dragging !== "pan" && !this._moved && this.onNodeClick)
        this.onNodeClick(this.dragging);
      this.dragging = null; last = null; c.style.cursor = "grab";
    });
    c.addEventListener("wheel", (e) => {
      e.preventDefault();
      const f = e.deltaY < 0 ? 1.1 : 0.9;
      this.scale = Math.min(3, Math.max(0.2, this.scale * f));
    }, { passive: false });
  }

  _fit() { this.scale = 1; this.offset = { x: 0, y: 0 }; }
  _resize() {
    const r = this.host.getBoundingClientRect();
    this.canvas.width = r.width * devicePixelRatio;
    this.canvas.height = r.height * devicePixelRatio;
  }
  destroy() { cancelAnimationFrame(this._raf); }
}
