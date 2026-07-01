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


app.mount("/static", StaticFiles(directory=str(WEB / "static")), name="static")


@app.on_event("shutdown")
async def _shutdown():
    await close_client()
