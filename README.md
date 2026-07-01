# LATTICE — public-signal correlation console

A **hosted** OSINT console (mobile + desktop, installable PWA) that runs many
public-data modules under one **correlation engine** and stitches their output
into a single typed **entity graph**. Focused on **social & messaging presence**,
plus infrastructure, image geolocation, and self-exposure checks.

> Not a toy: 50+ modules, concurrent orchestration, per-module timeouts, error
> isolation, disk caching, a live entity graph, and a dark map — all from
> **public data / official public APIs only**.

---

## ⚖️ Scope & ethics (hard guardrails)

Public data and official/public APIs **only**. Every module either checks
**public presence** (does a public profile with this handle exist?) or reads
**public records** (DNS, WHOIS/RDAP, TLS, geo-IP, threat feeds) or works on
**your own** uploaded files (image EXIF/forensics).

This project does **not**, and must never be wired to:

- resolve a username / email / phone / handle / wallet to a **private person's**
  real identity, home, or contact details;
- perform people-search, phone-owner, address or vehicle lookups;
- retrieve stealer-log or breach-dump **contents** of third parties (email
  exposure reports breach **names only** — never passwords or private data);
- scrape a person's private life.

The password check uses **k-anonymity**: your browser hashes locally and sends
only the first 5 hash characters — the password never leaves your device.

---

## Deploy it as a real website (no self-host, no tunnel)

The app serves its own frontend on relative paths, binds to `$PORT`, and needs
no configuration to run. Pick any host:

### Render (easiest)
1. Push this repo to GitHub.
2. Render → **New +** → **Blueprint** → select the repo.
   `render.yaml` builds the Docker image and gives you a permanent
   `https://lattice-xxxx.onrender.com` URL.

### Fly.io
```bash
flyctl launch --no-deploy   # accept the included fly.toml
flyctl deploy
```

### Docker (any VPS / Cloud Run / Railway)
```bash
docker build -t lattice .
docker run -p 8000:8000 lattice     # → http://localhost:8000
```

### Local dev
```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

All API keys / payment addresses are **optional** env vars (see `.env.example`).
Without them the app runs fully; payments fall back to a safe demo mode.

---

## Payments (self-hosted, on-chain confirmation)

Tiered plans: **base / premium / elite / master**. Users can pay with **BTC,
ETH, USDT** (verified directly on the public blockchain — no third-party
processor) or **PayPal**. Configure receiving addresses in env to go live:

```
PAY_ADDRESS_BTC=bc1...
PAY_ADDRESS_ETH=0x...        # also receives USDT (ERC-20)
PAYPAL_ME=yourname
```

---

## Architecture

```
app/
  core/         # the tiny framework
    base.py         # InputType, Category, Confidence, GraphNode/Edge, BaseModule
    detect.py       # classify a raw target string
    net.py          # one shared async HTTP client (auto-adapts to any host)
    cache.py        # disk cache
    graph.py        # merge modules' nodes/edges into one entity graph
    registry.py     # auto-discover every BaseModule subclass
    orchestrator.py # run modules concurrently, safely
  modules/      # one capability per class, auto-discovered
    social.py identity.py infra.py image.py intel.py more.py
  config.py     # tiers + payment settings
  payments.py   # crypto invoices + on-chain verification
  main.py       # FastAPI app + web console
web/            # the dark console UI (vanilla ES modules, no framework)
```

**Add a module:** drop a `BaseModule` subclass in `app/modules/` — it appears in
the API and UI automatically. That's the whole extension model.
