# OSINT Correlation Engine

A self-hosted, **mobile-first PWA** that runs public-data, infrastructure-focused
OSINT modules under one **correlation engine** — and stitches their output into a
single typed **entity graph**. Three investigative domains:

1. **Infrastructure / attack-surface** (DNS, WHOIS/RDAP, TLS, subdomains, hosting…)
2. **Blockchain** on-chain analysis (public Bitcoin/EVM ledgers)
3. **Image geolocation / forensics** (EXIF/GPS → map, metadata, sun-angle, stego…)

…plus **username-presence** and **self-exposure** checks.

> ⚖️ **Scope & ethics.** Public data and official/public APIs only: infrastructure,
> on-chain, and *your own* files. The username/email modules check **presence /
> exposure only** — they are NOT, and must never be wired to, deanonymise a
> person. See **Guardrails** below.

---

## Quick start

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # optional: add API keys to unlock extra modules
./run.sh                      # serves on http://0.0.0.0:8000
```

Open <http://localhost:8000>. Install it as a PWA from your browser's menu.

### Public preview URL (this cloud environment)

This container has **no direct outbound network** — all traffic goes through an
HTTPS `CONNECT` proxy, so tools like `cloudflared`/`ngrok` (which dial their edge
directly) can't connect. `tunnel.py` solves this with a **pure-Python SSH reverse
tunnel** (paramiko) to a free [pinggy.io](https://pinggy.io) relay, run *inside
TLS on port 443* and routed through the proxy's `CONNECT`. It writes the live URL
to `data/public_url.txt` and auto-reconnects.

```bash
./run.sh &            # start the app
python3 tunnel.py     # prints "PUBLIC_URL https://<random>.free.pinggy.net"
```

> The free pinggy tunnel rotates roughly hourly and shows a one-time
> "continue" splash on first visit. For a **stable** URL, put a pinggy access
> token in `.env` (the script can be extended to send it), or self-host any
> reverse proxy.

---

## Architecture (the backbone)

```
  Browser (PWA: index.html + modular CSS/JS, Leaflet map, canvas graph)
      │  fetch /api/*
      ▼
  FastAPI (app/main.py)  ── serves the PWA + a small JSON API
      │
      ▼
  Orchestrator (app/core/orchestrator.py)
      │   routes an input to ALL compatible modules, runs them concurrently
      │   with per-module timeouts, isolates errors, rate-limits per host
      ├── Registry (app/core/registry.py)  auto-discovers app/modules/*
      ├── Modules  (app/modules/*.py)      each returns a uniform ModuleResult
      └── EntityGraph (app/core/graph.py)  dedupes nodes/edges → correlation
```

### Key ideas

- **`BaseModule`** (`app/core/base.py`) — every capability subclasses this and
  declares `key`, `name`, `category`, `accepts` (input types), `needs_network`,
  `requires_authorized_target`, and implements `async run(value, ctx)`.
- **Uniform output** — every module returns a `ModuleResult` (`source`,
  `findings`, `confidence`, `source_url`, `raw`, plus graph `nodes`/`edges`).
  Uniformity is what lets the UI and the graph treat all modules identically.
- **Auto-discovery** — drop a new file in `app/modules/` and it's live. No wiring.
- **Input detection** (`app/core/detect.py`) — one input box; the engine guesses
  whether you typed a domain, IP, URL, BTC/ETH address, hash, email or username.
- **Entity graph** — typed nodes (`domain`, `ip`, `btc_address`, `geo`, …) and
  edges (`resolves_to`, `funds_flow_to`, `located_at`, …). A node's identity is
  `type:value`, so two modules naming the same IP automatically merge — that
  cross-module linkage is the "engine".

### Project layout

```
app/
  main.py            FastAPI app + API routes + static/PWA serving
  core/
    base.py          BaseModule, ModuleResult, InputType, Category, RunContext
    detect.py        raw text  ->  InputType
    registry.py      auto-discovery of modules
    orchestrator.py  concurrent routing, timeouts, error isolation, rate-limit
    graph.py         the entity/correlation graph
    cache.py         tiny on-disk response cache (politeness + speed)
  modules/           one file per capability (auto-discovered)
web/
  index.html         the suite shell
  static/css/        tokens (design system) + layout + components
  static/js/         util, graph (canvas force layout), app (controller)
  static/sw.js       service worker (installable + offline shell)
  static/manifest.webmanifest
tunnel.py            pure-Python SSH-over-TLS reverse tunnel for the preview URL
run.sh               start uvicorn on 0.0.0.0
```

---

## Modules (current)

| Module | Category | Input | What it does |
|---|---|---|---|
| `dns_full` | infrastructure | domain | A/AAAA/MX/TXT/NS/CNAME/SOA + SPF/DMARC + DNSSEC |
| `whois` | infrastructure | domain | Registrar/dates/status via RDAP |
| `username` | identity | username | Presence across ~25 sites (status **or** not-found-string logic) |
| `btc_explorer` | blockchain | btc address / txid | Balance, totals, recent tx (mempool.space) |
| `exif_gps` | image | uploaded image | EXIF + GPS → Leaflet map + reverse-geocode |

More land in later phases (subdomains, live hosts, TLS/SAN pivot, favicon hash,
ASN, reverse-IP, chain-following + clustering, forensics, exposure score, report).

---

## Guardrails (hard limits — will not be added)

- **Public data only**: infrastructure, on-chain, and your own files. Modules with
  `requires_authorized_target=True` (e.g. port scans) show a scope-confirmation
  gate before running.
- **No deanonymisation.** No people-search / phone-owner / address / vehicle
  lookups; no stealer-log or breach-dump retrieval of third parties; no
  social-media profiling of individuals. The username/email modules check
  presence/exposure **only**.
- **No exploitation.** No credential brute-forcing, no payloads. Recon + analysis.
- **Secrets** live in `.env` only.

---

## Configuration

All keys are **optional** (the engine runs fully without them):

| Key | Unlocks |
|---|---|
| `ETHERSCAN_API_KEY` | `eth_explorer` (EVM on-chain) |
| `HIBP_API_KEY` | breach lookup for *your own / authorized* email |

The HIBP k-anonymity password check needs **no** key.
