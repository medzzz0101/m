"""base.py — the vocabulary of the whole engine.

Every module speaks in the same nouns defined here:
  * InputType   — what KIND of target the user gave us (username, email, ...).
  * Category    — which investigative domain a module belongs to.
  * Confidence  — how sure a single finding is.
  * GraphNode / GraphEdge — typed entities and the links between them.
  * Finding     — one row of evidence (key/value + confidence) for the table UI.
  * ModuleResult — everything one module returns for one run.
  * RunContext  — shared, read-only run info handed to every module.
  * BaseModule  — the abstract class each capability subclasses.

Keeping this vocabulary tiny is what makes the suite genuinely modular: the
orchestrator, the graph, and the UI only ever deal with these shapes, never with
the specifics of any one module.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any, Optional


# ---------------------------------------------------------------------------
# What kind of thing did the user type in?  The detector (detect.py) maps a raw
# string to one of these so we can offer only the modules that make sense.
# ---------------------------------------------------------------------------
class InputType(str, Enum):
    USERNAME = "username"     # a social handle, e.g. @jack
    EMAIL    = "email"        # someone@example.com
    DOMAIN   = "domain"       # example.com
    IP       = "ip"           # 8.8.8.8 or an IPv6 literal
    URL      = "url"          # https://example.com/path
    PHONE    = "phone"        # +14155552671 (metadata only, never owner)
    IMAGE    = "image"        # an uploaded picture (EXIF / geolocation)
    HASH     = "hash"         # md5/sha1/sha256 or a favicon mmh3 hash
    TEXT     = "text"         # free text (fallback: dorks, decoders)
    UNKNOWN  = "unknown"


# ---------------------------------------------------------------------------
# Investigative domains.  These drive the sidebar grouping and card colours.
# ---------------------------------------------------------------------------
class Category(str, Enum):
    SOCIAL         = "social"          # username presence, public profiles, channels
    IDENTITY       = "identity"        # email exposure, self-exposure scoring
    INFRASTRUCTURE = "infrastructure"  # domains, IPs, DNS, TLS, ASN
    IMAGE          = "image"           # EXIF/GPS, forensics, geolocation aid
    INTEL          = "intel"           # aggregation, dorks, wayback, misc lookups


# How confident is a single finding?  Purely descriptive; the UI colours pills.
class Confidence(str, Enum):
    CONFIRMED = "confirmed"   # verified by an authoritative source
    LIKELY    = "likely"      # strong signal, not authoritative
    POSSIBLE  = "possible"    # weak / heuristic signal
    INFO      = "info"        # neutral context, no claim


# ---------------------------------------------------------------------------
# The entity graph vocabulary.  Nodes are deduplicated by (type, value).
# ---------------------------------------------------------------------------
@dataclass
class GraphNode:
    type: str                 # e.g. "username", "email", "domain", "ip"
    value: str                # the canonical value (already normalised)
    label: Optional[str] = None
    meta: dict[str, Any] = field(default_factory=dict)

    @property
    def id(self) -> str:
        return f"{self.type}:{self.value}"


@dataclass
class GraphEdge:
    source: str               # a GraphNode.id
    target: str               # a GraphNode.id
    kind: str = "related"     # relationship label, e.g. "resolves_to", "found_on"


@dataclass
class Finding:
    """One row of evidence — the atom the dense-table UI renders.

    `key`/`value` are the human columns; `confidence` colours a pill; `link`
    (optional) makes the value clickable; `pivot` (optional) is a raw target the
    user can re-run as a fresh investigation (e.g. an IP discovered from a host).
    """
    key: str
    value: str
    confidence: Confidence = Confidence.INFO
    link: Optional[str] = None
    pivot: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["confidence"] = self.confidence.value
        return d


@dataclass
class ModuleResult:
    """Everything a module produces for a single run."""
    module: str                                   # the module's id
    ok: bool = True                               # did it complete without error?
    summary: str = ""                             # one-line human takeaway
    findings: list[Finding] = field(default_factory=list)
    nodes: list[GraphNode] = field(default_factory=list)
    edges: list[GraphEdge] = field(default_factory=list)
    error: Optional[str] = None                   # populated when ok is False
    started: float = 0.0
    elapsed_ms: int = 0
    extra: dict[str, Any] = field(default_factory=dict)  # module-specific payloads (map points, etc.)

    def add(self, key: str, value: Any, confidence: Confidence = Confidence.INFO,
            link: str | None = None, pivot: str | None = None) -> None:
        """Convenience: append a Finding without importing Finding everywhere."""
        self.findings.append(Finding(key=key, value=str(value),
                                     confidence=confidence, link=link, pivot=pivot))

    def node(self, type: str, value: str, label: str | None = None, **meta: Any) -> GraphNode:
        n = GraphNode(type=type, value=value, label=label, meta=meta)
        self.nodes.append(n)
        return n

    def edge(self, source: str, target: str, kind: str = "related") -> None:
        self.edges.append(GraphEdge(source=source, target=target, kind=kind))

    def to_dict(self) -> dict[str, Any]:
        return {
            "module": self.module,
            "ok": self.ok,
            "summary": self.summary,
            "findings": [f.to_dict() for f in self.findings],
            "nodes": [asdict(n) for n in self.nodes],
            "edges": [asdict(e) for e in self.edges],
            "error": self.error,
            "elapsed_ms": self.elapsed_ms,
            "extra": self.extra,
        }


@dataclass
class RunContext:
    """Read-only info shared with every module during a run.

    `target` is the raw string; `input_type` is the detected InputType; `deep`
    asks modules to do heavier work; `authorized` is the user's explicit
    confirmation that they own / are permitted to probe the target (gates the
    small number of modules that touch a target more actively).
    """
    target: str
    input_type: InputType
    deep: bool = False
    authorized: bool = False
    upload_path: Optional[str] = None   # filesystem path when an image was uploaded


class BaseModule:
    """Subclass this to add a capability. The registry auto-discovers subclasses.

    A module declares WHAT it is (id/name/category/inputs/tier) and implements
    ONE method: `run(ctx) -> ModuleResult`. The orchestrator handles timeouts,
    caching, rate-limiting, and error isolation, so a module can stay focused on
    turning a target into findings.
    """

    id: str = ""                              # unique slug, e.g. "username_presence"
    name: str = ""                            # human title for the UI
    description: str = ""                     # one sentence, shown in the grid
    category: Category = Category.INTEL
    inputs: tuple[InputType, ...] = ()        # which InputTypes this accepts
    tier: str = "base"                        # plan gate (see main.TIER_ORDER)
    requires_authorized: bool = False         # show a scope gate before running
    timeout: float = 15.0                     # per-run seconds before it's cancelled

    # --- Hard guardrail, enforced by design across the whole suite ------------
    # Modules here investigate PUBLIC presence/exposure and PUBLIC infrastructure
    # only. No module resolves a handle/email/phone to a private person's real
    # identity, home, or contact details; none retrieves third-party breach
    # contents, stealer logs, or scrapes a person's private life. This attribute
    # documents that contract for every module that renders it in the UI.
    public_data_only: bool = True

    async def run(self, ctx: RunContext) -> ModuleResult:  # pragma: no cover
        raise NotImplementedError

    # Convenience factory so modules write `self.result()` and start filling it.
    def result(self) -> ModuleResult:
        return ModuleResult(module=self.id, started=time.time())

    def manifest(self) -> dict[str, Any]:
        """The JSON the UI uses to render this module in the grid/sidebar."""
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "category": self.category.value,
            "inputs": [i.value for i in self.inputs],
            "tier": self.tier,
            "requires_authorized": self.requires_authorized,
            "public_data_only": self.public_data_only,
        }
