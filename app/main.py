"""main.py — the FastAPI application that wires the engine to the web console.

Endpoints (all JSON unless noted):
  GET  /                     → the single-page console (index.html)
  GET  /api/health           → liveness + module count
  GET  /api/modules          → module manifests + tier metadata
  GET  /api/detect?q=        → classify a target string
  POST /api/run              → run all applicable modules for a target
  POST /api/run_module       → run one module by id
  POST /api/upload           → accept an image, return a token to run image modules
  POST /api/pay/create       → create a crypto/PayPal invoice for a plan
  GET  /api/pay/verify       → poll an invoice's on-chain status
  GET  /sw.js, /manifest.webmanifest, /static/*  → PWA assets
"""
from __future__ import annotations

import os
import time
import uuid
from pathlib import Path

from fastapi import FastAPI, UploadFile, File, Form, Request
from fastapi.responses import JSONResponse, FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

from . import __appname__, __version__, config, payments
from .core.base import InputType, RunContext
from .core.cache import DiskCache
from .core.detect import detect, TYPE_LABELS
from .core.orchestrator import Orchestrator
from .core.registry import Registry
from .core.net import close_client

BASE = Path(__file__).resolve().parent.parent
WEB = BASE / "web"
DATA = BASE / "data"
UPLOADS = DATA / "uploads"
UPLOADS.mkdir(parents=True, exist_ok=True)

# --- Singletons, created once at import -------------------------------------
registry = Registry()
registry.discover()
# SOCIAL-ONLY build: expose only social + identity modules (a person's public
# social footprint). All infrastructure / image / intel / phone tooling is
# dropped from the product. Flip SOCIAL_ONLY off to restore the full suite.
SOCIAL_ONLY = os.environ.get("SOCIAL_ONLY", "1") != "0"
if SOCIAL_ONLY:
    registry.restrict({"social", "identity"})
cache = DiskCache(DATA / "cache")
orchestrator = Orchestrator(cache)

app = FastAPI(title=f"{__appname__} — public-signal correlation console",
              version=__version__)

# In-memory map of upload token → file path (fine for a self-hosted console).
_uploads: dict[str, str] = {}


@app.get("/api/health")
async def health():
    return {"app": __appname__, "version": __version__, "status": "ok",
            "modules": len(registry), "payments_live": config.PAYMENTS_LIVE}


@app.get("/api/modules")
async def modules():
    return {"modules": registry.manifests(),
            "tiers": [{"id": t, **config.TIER_META[t]} for t in config.TIER_ORDER]}


@app.get("/api/detect")
async def detect_endpoint(q: str = ""):
    it = detect(q)
    applicable = [m.id for m in registry.for_input(it)]
    return {"input_type": it.value, "label": TYPE_LABELS.get(it, "—"),
            "applicable": applicable}


def _allowed(module, plan: str) -> bool:
    return config.tier_index(module.tier) <= config.tier_index(plan)


@app.post("/api/run")
async def run(request: Request):
    body = await request.json()
    target = (body.get("target") or "").strip()
    plan = body.get("plan", "base")
    deep = bool(body.get("deep", False))
    authorized = bool(body.get("authorized", False))
    upload_token = body.get("upload")

    if upload_token:
        it = InputType.IMAGE
        path = _uploads.get(upload_token)
        target = target or "uploaded image"
    else:
        it = detect(target)
        path = None
    if not target:
        return JSONResponse({"error": "empty target"}, status_code=400)

    ctx = RunContext(target=target, input_type=it, deep=deep,
                     authorized=authorized, upload_path=path)

    # Pick applicable modules the user's plan unlocks; skip auth-gated ones
    # unless the user explicitly confirmed scope.
    mods = []
    for m in registry.for_input(it):
        if not _allowed(m, plan):
            continue
        if m.requires_authorized and not authorized:
            continue
        mods.append(m)

    result = await orchestrator.run(mods, ctx)
    result["skipped"] = [m.id for m in registry.for_input(it) if not _allowed(m, plan)]
    return result


@app.post("/api/run_stream")
async def run_stream(request: Request):
    """Server-Sent Events: emit each module result as soon as it completes, then
    a final 'done' event with the merged graph + stats. Makes the UI feel instant."""
    import json as _json
    from fastapi.responses import StreamingResponse

    body = await request.json()
    target = (body.get("target") or "").strip()
    plan = body.get("plan", "base")
    deep = bool(body.get("deep", False))
    authorized = bool(body.get("authorized", False))
    upload_token = body.get("upload")

    if upload_token:
        it = InputType.IMAGE
        path = _uploads.get(upload_token)
        target = target or "uploaded image"
    else:
        it = detect(target)
        path = None

    ctx = RunContext(target=target, input_type=it, deep=deep,
                     authorized=authorized, upload_path=path)
    mods = [m for m in registry.for_input(it)
            if _allowed(m, plan) and (not m.requires_authorized or authorized)]
    skipped = [m.id for m in registry.for_input(it) if not _allowed(m, plan)]

    async def gen():
        from .core.graph import EntityGraph
        from .core.base import GraphNode, GraphEdge
        graph = EntityGraph()
        all_mods: list[dict] = []
        seen_targets = {target.lower()}

        def ingest(d):
            nodes = [GraphNode(type=n["type"], value=n["value"], label=n.get("label"),
                               meta=n.get("meta", {})) for n in d.get("nodes", [])]
            edges = [GraphEdge(**e) for e in d.get("edges", [])]
            graph.ingest(nodes, edges)

        # Deep mode adds a second, bounded correlation hop: we follow the most
        # connected infrastructure entities we just discovered (subdomains, IPs,
        # related domains) and re-run a small, fast recon set on each — turning a
        # flat scan into a real multi-hop attack-surface graph. Purely public
        # infrastructure OSINT; never person-level.
        est = len(mods) + (40 if deep and it.value != "image" else 0)
        yield _sse("meta", {"target": target, "input_type": it.value,
                            "total": est, "skipped": skipped, "deep": deep})

        async for kind, payload in orchestrator.run_stream(mods, ctx):
            if kind == "module":
                all_mods.append(payload); ingest(payload)
                yield _sse("module", payload)

        # Recursive multi-hop expansion: hop 1 follows the target's discovered
        # infra, hop 2 follows what THAT uncovered — a genuinely deep, bounded
        # attack-surface crawl. Each hop widens the graph, all public infra OSINT.
        if deep and it.value != "image":
            for hop, limit in enumerate((6, 3), start=1):
                pivots = _pick_pivots(graph, seen_targets, limit)
                if not pivots:
                    break
                for ptarget, pit in pivots:
                    seen_targets.add(ptarget.lower())
                    pmods = [registry.get(mid) for mid in _DEEP_SET.get(pit.value, [])]
                    pmods = [m for m in pmods if m and _allowed(m, plan)]
                    if not pmods:
                        continue
                    pctx = RunContext(target=ptarget, input_type=pit, deep=False)
                    async for kind, payload in orchestrator.run_stream(pmods, pctx):
                        if kind == "module":
                            payload["pivot_from"] = ptarget
                            payload["hop"] = hop
                            all_mods.append(payload); ingest(payload)
                            yield _sse("module", payload)

        ok = sum(1 for d in all_mods if d["ok"])
        gd = graph.to_dict()
        yield _sse("done", {"target": target, "input_type": it.value,
                            "graph": gd,
                            "stats": {"total": len(all_mods), "ok": ok,
                                      "failed": len(all_mods) - ok,
                                      "nodes": len(gd["nodes"]), "edges": len(gd["edges"])}})

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# Fast, cheap recon run on each pivoted entity during a deep scan.
_DEEP_SET = {
    "domain": ["dns_records", "http_probe", "tls_certificate", "ip_geo"],
    "ip": ["ip_geo", "reverse_dns", "shodan_internetdb"],
}


def _pick_pivots(graph, seen, limit: int = 6):
    """Choose the most-connected new infra entities to expand one more hop."""
    gd = graph.to_dict()
    cands = []
    for n in gd["nodes"]:
        if n["type"] in ("subdomain", "domain", "ip") and n["value"].lower() not in seen:
            cands.append(n)
    cands.sort(key=lambda n: n.get("degree", 0), reverse=True)
    out = []
    for n in cands[:limit]:
        pit = InputType.IP if n["type"] == "ip" else InputType.DOMAIN
        out.append((n["value"], pit))
    return out


def _sse(event: str, data) -> bytes:
    import json as _json
    return f"event: {event}\ndata: {_json.dumps(data)}\n\n".encode()


@app.post("/api/run_module")
async def run_module(request: Request):
    body = await request.json()
    module_id = body.get("module")
    target = (body.get("target") or "").strip()
    plan = body.get("plan", "base")
    deep = bool(body.get("deep", False))
    upload_token = body.get("upload")

    m = registry.get(module_id)
    if not m:
        return JSONResponse({"error": "unknown module"}, status_code=404)
    if not _allowed(m, plan):
        return JSONResponse({"error": "locked", "tier": m.tier}, status_code=402)

    if upload_token:
        it = InputType.IMAGE
        path = _uploads.get(upload_token)
    else:
        it = detect(target)
        path = None
    ctx = RunContext(target=target, input_type=it, deep=deep,
                     authorized=bool(body.get("authorized")), upload_path=path)
    result = await orchestrator.run([m], ctx)
    return result


@app.post("/api/upload")
async def upload(file: UploadFile = File(...)):
    token = uuid.uuid4().hex
    dest = UPLOADS / f"{token}_{file.filename}"
    data = await file.read()
    if len(data) > 25 * 1024 * 1024:
        return JSONResponse({"error": "file too large (max 25MB)"}, status_code=413)
    dest.write_bytes(data)
    _uploads[token] = str(dest)
    return {"upload": token, "filename": file.filename, "size": len(data)}


# --- Payments ---------------------------------------------------------------
@app.post("/api/pay/create")
async def pay_create(request: Request):
    body = await request.json()
    plan = body.get("plan", "premium")
    asset = body.get("asset", "BTC")
    if plan not in config.TIER_META:
        return JSONResponse({"error": "unknown plan"}, status_code=400)
    inv = await payments.create_invoice(plan, asset)
    return inv


@app.get("/api/pay/verify")
async def pay_verify(invoice: str):
    return await payments.verify_invoice(invoice)


@app.post("/api/redeem")
async def redeem(request: Request):
    """Owner-issued license keys: enter a code, unlock its tier. Reusable forever."""
    from . import admin
    body = await request.json()
    code = (body.get("key") or "").strip()
    tier = admin.all_keys().get(code)
    if not tier:
        return JSONResponse({"ok": False, "error": "invalid key"}, status_code=404)
    ip = request.headers.get("x-forwarded-for", request.client.host if request.client else "?").split(",")[0].strip()
    admin.log_redemption(code, tier, ip)
    return {"ok": True, "plan": tier, "name": config.TIER_META[tier]["name"]}


# --- Owner panel (token-gated) ---------------------------------------------
@app.post("/api/admin/state")
async def admin_state(request: Request):
    from . import admin
    body = await request.json()
    if not admin.check_token(body.get("token", "")):
        return JSONResponse({"ok": False, "error": "unauthorized"}, status_code=401)
    ip = request.headers.get("x-forwarded-for", request.client.host if request.client else "?").split(",")[0].strip()
    return {"ok": True, "your_ip": ip, **admin.state()}


@app.post("/api/admin/keygen")
async def admin_keygen(request: Request):
    from . import admin
    body = await request.json()
    if not admin.check_token(body.get("token", "")):
        return JSONResponse({"ok": False, "error": "unauthorized"}, status_code=401)
    code = admin.add_key(body.get("tier", ""))
    if not code:
        return JSONResponse({"ok": False, "error": "bad tier"}, status_code=400)
    return {"ok": True, "code": code}


@app.post("/api/admin/revoke")
async def admin_revoke(request: Request):
    from . import admin
    body = await request.json()
    if not admin.check_token(body.get("token", "")):
        return JSONResponse({"ok": False, "error": "unauthorized"}, status_code=401)
    return {"ok": admin.revoke_key(body.get("code", ""))}


@app.get("/admin")
async def admin_page():
    return FileResponse(WEB / "admin.html")


# --- PWA + static -----------------------------------------------------------
@app.get("/sw.js")
async def sw():
    return FileResponse(WEB / "sw.js", media_type="application/javascript")


@app.get("/manifest.webmanifest")
async def manifest():
    return FileResponse(WEB / "manifest.webmanifest",
                        media_type="application/manifest+json")


@app.get("/")
async def index():
    return FileResponse(WEB / "index.html")


@app.get("/landing")
async def landing():
    return FileResponse(WEB / "landing.html")


app.mount("/static", StaticFiles(directory=str(WEB / "static")), name="static")


@app.on_event("shutdown")
async def _shutdown():
    await close_client()
