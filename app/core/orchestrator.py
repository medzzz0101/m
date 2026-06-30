"""
core/orchestrator.py
====================
The conductor. Given a value + its detected type, the orchestrator:

  1. selects every compatible module from the registry,
  2. runs them CONCURRENTLY (asyncio.gather) — OSINT is I/O bound, so we wait
     on many network calls at once instead of one-by-one,
  3. enforces a PER-MODULE TIMEOUT so one slow API can't hang the whole run,
  4. ISOLATES errors — a crashing module returns an error result, never takes
     the run down with it,
  5. RATE-LIMITS per upstream host so we stay polite to free APIs,
  6. merges each module's nodes/edges into the shared EntityGraph.

It can run a single named module (for the per-module UI cards) or the full
"scan everything" sweep that builds the correlation graph.
"""

from __future__ import annotations

import asyncio
import time
from collections import defaultdict
from typing import Any

from .base import BaseModule, Confidence, ModuleResult, RunContext, InputType
from .graph import EntityGraph
from .registry import Registry

# Per-module wall-clock budget. Generous enough for crt.sh on a cold day,
# short enough that the UI never feels stuck.
DEFAULT_TIMEOUT = 25.0


class HostRateLimiter:
    """Allows at most N concurrent in-flight requests per upstream host.

    The shared httpx client is handed this so individual modules don't each
    need to know about politeness — they just `async with limiter.slot(host)`.
    """

    def __init__(self, per_host: int = 4):
        self._sems: dict[str, asyncio.Semaphore] = defaultdict(
            lambda: asyncio.Semaphore(per_host)
        )

    def slot(self, host: str) -> asyncio.Semaphore:
        return self._sems[host]


class Orchestrator:
    def __init__(self, registry: Registry, ctx_factory):
        self.registry = registry
        # ctx_factory() -> RunContext, called per run so each run gets fresh
        # state (authorized flag, upload path, etc.).
        self.ctx_factory = ctx_factory

    # ----------------------------------------------------------------------
    async def _run_one(
        self, module: BaseModule, value: str, ctx: RunContext
    ) -> ModuleResult:
        """Run a single module with timeout + error isolation."""
        start = time.time()
        try:
            # Gate active-recon modules behind the authorization flag.
            if module.requires_authorized_target and not ctx.authorized:
                return module.result(
                    confidence=Confidence.INFO,
                    error="Blocked: this module needs explicit target "
                          "authorization (scope gate not confirmed).",
                    started_at=start,
                    finished_at=time.time(),
                )
            res = await asyncio.wait_for(
                module.run(value, ctx), timeout=DEFAULT_TIMEOUT
            )
            if res.finished_at is None:
                res.finished_at = time.time()
            return res
        except asyncio.TimeoutError:
            return module.result(
                error=f"Timed out after {DEFAULT_TIMEOUT:.0f}s",
                started_at=start,
                finished_at=time.time(),
            )
        except Exception as exc:  # noqa: BLE001 — deliberate catch-all isolation
            return module.result(
                error=f"{type(exc).__name__}: {exc}",
                started_at=start,
                finished_at=time.time(),
            )

    # ----------------------------------------------------------------------
    async def run_module(
        self, key: str, value: str, *, authorized: bool = False,
        upload_path: str | None = None, input_type: InputType | None = None,
    ) -> dict[str, Any]:
        """Run ONE module by key. Used by the per-card UI."""
        module = self.registry.get(key)
        if module is None:
            return {"error": f"Unknown module: {key}"}
        ctx = self.ctx_factory()
        ctx.authorized = authorized
        ctx.upload_path = upload_path
        ctx.input_type = input_type
        res = await self._run_one(module, value, ctx)
        return res.to_dict()

    # ----------------------------------------------------------------------
    async def run_all(
        self, value: str, input_type: InputType, *, authorized: bool = False,
        upload_path: str | None = None, only: list[str] | None = None,
    ) -> dict[str, Any]:
        """Run every compatible module concurrently and build the graph.

        `only` optionally restricts to a subset of module keys.
        Returns {results: [...], graph: {...}}.
        """
        modules = self.registry.for_type(input_type)
        if only:
            modules = [m for m in modules if m.key in only]

        ctx = self.ctx_factory()
        ctx.authorized = authorized
        ctx.upload_path = upload_path
        ctx.input_type = input_type

        # Fire them all off at once; gather preserves order.
        results = await asyncio.gather(
            *(self._run_one(m, value, ctx) for m in modules)
        )

        # Build the correlation graph by merging every module's contribution.
        graph = EntityGraph()
        for res in results:
            graph.ingest(res.nodes, res.edges)
            # Tie each module's headline finding to its primary node(s).
            for node in res.nodes:
                summary = (
                    res.findings[0].get("summary")
                    if res.findings and isinstance(res.findings[0], dict)
                    else None
                )
                if summary:
                    graph.attach_finding(node.id, res.module, summary)

        return {
            "value": value,
            "input_type": input_type.value,
            "results": [r.to_dict() for r in results],
            "graph": graph.to_dict(),
        }
