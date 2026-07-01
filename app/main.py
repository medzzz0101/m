"""
app/main.py
===========
The HTTP surface. FastAPI app that:
  * serves the PWA (index.html + static assets + manifest + service worker),
  * exposes a small JSON API the frontend calls,
  * owns the shared singletons (httpx client, cache, registry, orchestrator).

Architecture recap (top-down):
    browser (PWA)  ->  FastAPI routes (here)  ->  Orchestrator
                                                    -> Registry (modules)
                                                    -> EntityGraph (correlation)
Each module is independent and self-describing; this file just wires the shared
plumbing and translates HTTP <-> engine calls.
"""

from __future__ import annotations

import os
import uuid
from pathlib import Path

import httpx
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.core.base import RunContext
from app.core.cache import DiskCache
from app.core.detect import detect, TYPE_LABELS
from app.core.orchestrator import HostRateLimiter, Orchestrator
from app.core.registry import Registry

# --- Paths -----------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent.parent
WEB_DIR = BASE_DIR / "web"
DATA_DIR = BASE_DIR / "data"
CACHE_DIR = DATA_DIR / "cache"
UPLOAD_DIR = DATA_DIR / "uploads"
for d in (CACHE_DIR, UPLOAD_DIR):
    d.mkdir(parents=True, exist_ok=True)

# --- Load .env (tiny parser; avoids an extra dependency) -------------------
def _load_env() -> dict[str, str]:
    cfg = dict(os.environ)
    env_file = BASE_DIR / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                cfg.setdefault(k.strip(), v.strip())
    return cfg


CONFIG = _load_env()

# --- Shared singletons -----------------------------------------------------
# One async HTTP client for the whole app (connection pooling = speed +
# politeness). Sensible timeouts so no single call hangs the event loop.
HTTP = httpx.AsyncClient(
    timeout=httpx.Timeout(12.0, connect=6.0),
    follow_redirects=False,
    headers={"User-Agent": "osint-correlation-engine/1.0"},
    limits=httpx.Limits(max_connections=40, max_keepalive_connections=20),
)
CACHE = DiskCache(CACHE_DIR, default_ttl=3600)
RATE = HostRateLimiter(per_host=4)
REGISTRY = Registry().discover("app.modules")

# --- Subscription tiers -----------------------------------------------------
# A product-style tiering: each plan unlocks progressively more (and more
# powerful) modules. Ordered from lowest to highest. Any module not listed
# defaults to "elite". This is organisational gating, not a security boundary.
TIER_ORDER = ["base", "premium", "elite", "mega", "ultra", "master"]
TIER_MAP = {
    # Base — the everyday essentials.
    "base": ["dns_full", "whois", "ip_geo", "http_probe", "username",
             "wayback", "geo_checklist", "exif_gps"],
    # Premium — solid recon + first identity/blockchain/image depth.
    "premium": ["subdomains", "asn", "security_headers", "tls_certs",
                "http_methods", "telegram", "image_meta", "btc_explorer",
                "email_exposure", "google_dorks"],
    # Elite — full fingerprinting + more social + more forensics.
    "elite": ["tech_fingerprint", "waf_cdn_detect", "favicon_hash", "reverse_ip",
              "tls_scan", "cors_check", "wellknown", "site_intel", "eth_explorer",
              "image_phash", "sun_calc"],
    # Mega — passive exposure, CVEs, scoring, deep social.
    "mega": ["shodan_internetdb", "cve_lookup", "exposure_score",
             "subdomain_brute", "threat_feeds", "tiktok", "discord",
             "telegram_channel", "github_user", "steam"],
    # Ultra — heavy attack-surface + advanced blockchain/forensics.
    "ultra": ["exposed_files", "subdomain_takeover", "cloud_buckets",
              "web_screenshot", "typosquat", "image_ela", "btc_trace",
              "urlscan", "file_forensics"],
    # Master — everything, including the one ACTIVE module.
    "master": ["port_services"],
}
_KEY_TO_TIER = {k: tier for tier, keys in TIER_MAP.items() for k in keys}
for _m in REGISTRY.all():
    _m.tier = _KEY_TO_TIER.get(_m.key, "elite")


def _ctx_factory() -> RunContext:
    """Fresh RunContext per run, sharing the long-lived services."""
    return RunContext(
        http=HTTP, cache=CACHE, config=CONFIG,
        extra={"rate_limiter": RATE},
    )


ORCH = Orchestrator(REGISTRY, _ctx_factory)

# --- FastAPI app -----------------------------------------------------------
app = FastAPI(title="OSINT Correlation Engine", docs_url="/api/docs")


@app.get("/api/health")
async def health():
    return {"status": "ok", "modules": len(REGISTRY.modules)}


@app.get("/api/modules")
async def modules():
    """The module catalog — powers the sidebar/registry in the UI."""
    return {"modules": REGISTRY.manifest(), "tiers": TIER_ORDER}


@app.get("/api/detect")
async def detect_type(value: str):
    """Tell the UI what an input looks like, and which modules apply."""
    itype = detect(value)
    compatible = [m.key for m in REGISTRY.for_type(itype)]
    return {
        "value": value,
        "input_type": itype.value,
        "label": TYPE_LABELS.get(itype, itype.value),
        "compatible_modules": compatible,
    }


@app.post("/api/run")
async def run_all(payload: dict):
    """Run every compatible module for a value and return results + graph.

    Body: {value, authorized?, only?:[keys]}
    """
    value = (payload.get("value") or "").strip()
    if not value:
        raise HTTPException(400, "Missing 'value'.")
    itype = detect(value)
    out = await ORCH.run_all(
        value, itype,
        authorized=bool(payload.get("authorized")),
        only=payload.get("only"),
    )
    return out


@app.post("/api/run_module")
async def run_module(payload: dict):
    """Run a single module by key (powers per-card refresh / targeted runs)."""
    key = payload.get("key")
    value = (payload.get("value") or "").strip()
    if not key or not value:
        raise HTTPException(400, "Need 'key' and 'value'.")
    itype = detect(value)
    return await ORCH.run_module(
        key, value, authorized=bool(payload.get("authorized")),
        input_type=itype,
    )


@app.post("/api/upload")
async def upload(file: UploadFile = File(...), key: str = Form("exif_gps"),
                 authorized: str = Form("false")):
    """Accept an image/file, persist it, run the chosen image/forensics module."""
    suffix = Path(file.filename or "upload").suffix
    saved = UPLOAD_DIR / f"{uuid.uuid4().hex}{suffix}"
    saved.write_bytes(await file.read())
    result = await ORCH.run_module(
        key, file.filename or saved.name,
        authorized=authorized.lower() == "true",
        upload_path=str(saved),
    )
    return JSONResponse(result)


# --- Static / PWA serving --------------------------------------------------
# Service worker MUST be served from the root scope to control the whole app.
@app.get("/sw.js")
async def service_worker():
    return FileResponse(WEB_DIR / "static" / "sw.js", media_type="application/javascript")


@app.get("/manifest.webmanifest")
async def manifest():
    return FileResponse(WEB_DIR / "static" / "manifest.webmanifest",
                        media_type="application/manifest+json")


# Mount the static assets (css/js/icons) under /static.
app.mount("/static", StaticFiles(directory=WEB_DIR / "static"), name="static")


@app.get("/")
async def index():
    return FileResponse(WEB_DIR / "index.html")
