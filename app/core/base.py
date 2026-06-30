"""
core/base.py
============
The vocabulary of the whole engine. Everything else (modules, orchestrator,
graph) is built on the small set of types defined here.

Read this file first — once these ideas click, the rest of the codebase is
just "many small modules that all speak this language".

Key ideas
---------
* InputType  : what *kind* of thing the user typed (a domain? a bitcoin
               address? an image?). Modules declare which input types they can
               handle, so the orchestrator can route automatically.
* Category   : which investigative domain a module belongs to (infrastructure /
               blockchain / image / identity / intel). Drives the sidebar UI.
* ModuleResult: the SINGLE shape every module returns. Uniform output is what
               makes a "correlation engine" possible — the graph and the UI can
               treat every module's output identically.
* BaseModule : the abstract class every module subclasses. It declares metadata
               (key/name/category/accepts/...) and implements one async method:
               `run(value, ctx) -> ModuleResult`.
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any


# ---------------------------------------------------------------------------
# 1. The kinds of input the engine understands.
#    `detect.py` inspects raw user text and decides which of these it is.
# ---------------------------------------------------------------------------
class InputType(str, Enum):
    USERNAME = "username"
    EMAIL = "email"
    DOMAIN = "domain"
    IP = "ip"
    URL = "url"
    BTC_ADDRESS = "btc_address"
    ETH_ADDRESS = "eth_address"
    IMAGE = "image"
    FILE = "file"
    TEXT = "text"
    HASH = "hash"


# ---------------------------------------------------------------------------
# 2. The investigative domains. Used to GROUP modules in the sidebar.
# ---------------------------------------------------------------------------
class Category(str, Enum):
    INFRASTRUCTURE = "infrastructure"   # attack surface / DNS / TLS / hosting
    BLOCKCHAIN = "blockchain"           # public on-chain ledger analysis
    IMAGE = "image"                     # geolocation / metadata / forensics
    IDENTITY = "identity"               # presence + self-exposure (legal only)
    INTEL = "intel"                     # correlation, scoring, reporting


# ---------------------------------------------------------------------------
# 3. Confidence — every finding carries an honest confidence level. OSINT is
#    full of false positives, so we never pretend a weak signal is a fact.
# ---------------------------------------------------------------------------
class Confidence(str, Enum):
    HIGH = "high"          # authoritative source, deterministic
    MEDIUM = "medium"      # strong heuristic / corroborated
    LOW = "low"            # suggestive only — treat as a lead, not proof
    INFO = "info"          # neutral context, not a claim


# ---------------------------------------------------------------------------
# 4. Graph contributions. A module can return nodes/edges to merge into the
#    shared entity graph. Defined as light dataclasses so modules stay terse.
# ---------------------------------------------------------------------------
@dataclass
class GraphNode:
    """A typed entity, e.g. ('domain', 'example.com')."""
    type: str                       # see graph.NODE_TYPES
    value: str                      # canonical identifier (lowercased where apt)
    label: str | None = None        # nicer display label (defaults to value)
    props: dict[str, Any] = field(default_factory=dict)

    @property
    def id(self) -> str:
        # A node's identity = its type + value. This is how we DEDUPE: two
        # modules that both mention example.com produce the same id and merge.
        return f"{self.type}:{self.value}".lower()


@dataclass
class GraphEdge:
    """A typed relationship between two nodes, e.g. domain -resolves_to-> ip."""
    src: str                        # source node id
    dst: str                        # destination node id
    label: str                      # see graph.EDGE_TYPES (resolves_to, ...)
    props: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# 5. The universal module output. Uniformity here is the whole point.
# ---------------------------------------------------------------------------
@dataclass
class ModuleResult:
    module: str                              # module key that produced this
    source: str                              # human label for the data source
    findings: list[dict[str, Any]] = field(default_factory=list)
    confidence: Confidence = Confidence.INFO
    source_url: str | None = None            # where a human can verify it
    raw: Any = None                          # raw upstream payload (JSON drawer)
    nodes: list[GraphNode] = field(default_factory=list)
    edges: list[GraphEdge] = field(default_factory=list)
    error: str | None = None                 # set when the module failed
    started_at: float = field(default_factory=time.time)
    finished_at: float | None = None

    def to_dict(self) -> dict[str, Any]:
        """JSON-serialisable form sent to the frontend."""
        d = asdict(self)
        d["confidence"] = self.confidence.value
        d["duration_ms"] = (
            int(((self.finished_at or time.time()) - self.started_at) * 1000)
        )
        return d


# ---------------------------------------------------------------------------
# 6. Run context. Passed to every module's run(). Holds shared services
#    (HTTP client, cache, config) plus a flag that the user confirmed scope for
#    `requires_authorized_target` modules.
# ---------------------------------------------------------------------------
@dataclass
class RunContext:
    http: Any                                # shared httpx.AsyncClient
    cache: Any                               # core.cache.DiskCache
    config: dict[str, Any]                   # env-derived settings (API keys…)
    input_type: InputType | None = None      # detected type of `value`
    authorized: bool = False                 # user ticked the scope gate
    upload_path: str | None = None           # local path for IMAGE/FILE inputs
    extra: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# 7. The abstract module. Every file in app/modules/ subclasses this.
# ---------------------------------------------------------------------------
class BaseModule(ABC):
    # --- Required metadata (subclasses override as plain class attributes) ---
    key: str = "base"                        # unique id, e.g. "dns_full"
    name: str = "Base Module"                # display name
    category: Category = Category.INTEL
    subtitle: str = ""                       # tiny sidebar caption
    accepts: tuple[InputType, ...] = ()      # input types this module handles
    needs_network: bool = True               # does it hit the internet?
    requires_authorized_target: bool = False # gate before running (active recon)
    description: str = ""                     # longer help text for the UI

    # ----------------------------------------------------------------------
    # The one method every module MUST implement. Given a value (already known
    # to be a compatible InputType) and the shared context, do the work and
    # return a ModuleResult. Should NOT raise for "expected" failures — return
    # a result with `error` set instead; the orchestrator isolates crashes too.
    # ----------------------------------------------------------------------
    @abstractmethod
    async def run(self, value: str, ctx: RunContext) -> ModuleResult:
        ...

    # --- Convenience helpers so modules stay short --------------------------
    def result(self, **kwargs) -> ModuleResult:
        """Factory that stamps the module key/source automatically."""
        kwargs.setdefault("module", self.key)
        kwargs.setdefault("source", self.name)
        return ModuleResult(**kwargs)

    def accepts_type(self, itype: InputType) -> bool:
        return itype in self.accepts

    def manifest(self) -> dict[str, Any]:
        """Metadata blob the frontend uses to render the sidebar/registry."""
        return {
            "key": self.key,
            "name": self.name,
            "category": self.category.value,
            "subtitle": self.subtitle,
            "description": self.description,
            "accepts": [t.value for t in self.accepts],
            "needs_network": self.needs_network,
            "requires_authorized_target": self.requires_authorized_target,
        }
