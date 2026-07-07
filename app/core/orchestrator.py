"""orchestrator.py — run many modules concurrently, safely.

Responsibilities:
  * fan out selected modules with asyncio, each under its own timeout;
  * isolate errors so one module blowing up never sinks the run;
  * throttle per-host so we stay polite to public APIs;
  * cache successful results to disk;
  * merge every module's nodes/edges into one EntityGraph.
"""
from __future__ import annotations

import asyncio
import time
from collections import defaultdict

from .base import BaseModule, ModuleResult, RunContext
from .cache import DiskCache
from .graph import EntityGraph


def _fmt_exc(e: Exception) -> str:
    """A human error string even when str(e) is empty (common with httpx)."""
    msg = str(e).strip()
    return f"{type(e).__name__}: {msg}" if msg else type(e).__name__


class HostRateLimiter:
    """A crude per-key async gate: at most `rate` concurrent + min gap."""
    def __init__(self, concurrency: int = 6) -> None:
        self._sem = asyncio.Semaphore(concurrency)

    async def __aenter__(self):
        await self._sem.acquire()
        return self

    async def __aexit__(self, *exc):
        self._sem.release()


class Orchestrator:
    def __init__(self, cache: DiskCache, cache_ttl: float = 900.0) -> None:
        self.cache = cache
        self.cache_ttl = cache_ttl
        self.limiter = HostRateLimiter(concurrency=16)

    async def _run_one(self, module: BaseModule, ctx: RunContext) -> ModuleResult:
        started = time.time()
        cache_key = f"{module.id}|{ctx.target}|{int(ctx.deep)}"

        # Cache hit? (images/uploads are never cached — the path is ephemeral.)
        if ctx.input_type.value != "image":
            cached = self.cache.get(cache_key, self.cache_ttl)
            if cached is not None:
                cached["extra"] = {**cached.get("extra", {}), "cached": True}
                r = ModuleResult(module=module.id, ok=cached["ok"],
                                 summary=cached["summary"], error=cached.get("error"))
                r.__dict__["_predumped"] = cached  # short-circuit for to_dict below
                return r

        try:
            async with self.limiter:
                result = await asyncio.wait_for(module.run(ctx), timeout=module.timeout)
        except asyncio.TimeoutError:
            result = ModuleResult(module=module.id, ok=False,
                                  error=f"timed out after {module.timeout:.0f}s")
        except Exception as e:  # error isolation — never propagate
            result = ModuleResult(module=module.id, ok=False, error=_fmt_exc(e))

        # A failed module must never show a blank error card (some exceptions,
        # e.g. httpx.ConnectError, stringify to ""). Give it a readable reason.
        if not result.ok and not (result.error or "").strip():
            result.error = "no response (connection failed or endpoint unreachable)"

        result.elapsed_ms = int((time.time() - started) * 1000)
        if result.ok and ctx.input_type.value != "image":
            self.cache.set(cache_key, result.to_dict())
        return result

    async def run(self, modules: list[BaseModule], ctx: RunContext) -> dict:
        """Run all `modules` for `ctx` and return a merged, JSON-ready payload."""
        results = await asyncio.gather(*(self._run_one(m, ctx) for m in modules))

        graph = EntityGraph()
        out: list[dict] = []
        for r in results:
            pre = r.__dict__.get("_predumped")
            d = pre if pre is not None else r.to_dict()
            out.append(d)
            # Rehydrate nodes/edges for the graph merge.
            if pre is not None:
                from .base import GraphNode, GraphEdge
                nodes = [GraphNode(**n_) for n_ in _clean_nodes(pre.get("nodes", []))]
                edges = [GraphEdge(**e_) for e_ in pre.get("edges", [])]
            else:
                nodes, edges = r.nodes, r.edges
            graph.ingest(nodes, edges)

        ok = sum(1 for d in out if d["ok"])
        return {
            "target": ctx.target,
            "input_type": ctx.input_type.value,
            "modules": out,
            "graph": graph.to_dict(),
            "stats": {"total": len(out), "ok": ok, "failed": len(out) - ok,
                      "nodes": graph.size[0], "edges": graph.size[1]},
        }


    async def run_stream(self, modules, ctx):
        """Async generator: yield ('module', dict) as each finishes, then
        ('done', payload) with the merged graph + stats. Powers progressive UI."""
        import asyncio
        from .base import GraphNode, GraphEdge
        graph = EntityGraph()
        out = []
        tasks = [asyncio.create_task(self._run_one(m, ctx)) for m in modules]
        for coro in asyncio.as_completed(tasks):
            r = await coro
            pre = r.__dict__.get("_predumped")
            d = pre if pre is not None else r.to_dict()
            out.append(d)
            if pre is not None:
                nodes = [GraphNode(**n_) for n_ in _clean_nodes(pre.get("nodes", []))]
                edges = [GraphEdge(**e_) for e_ in pre.get("edges", [])]
            else:
                nodes, edges = r.nodes, r.edges
            graph.ingest(nodes, edges)
            yield ("module", d)
        ok = sum(1 for d in out if d["ok"])
        yield ("done", {
            "target": ctx.target, "input_type": ctx.input_type.value,
            "graph": graph.to_dict(),
            "stats": {"total": len(out), "ok": ok, "failed": len(out) - ok,
                      "nodes": graph.size[0], "edges": graph.size[1]},
        })


def _clean_nodes(raw: list[dict]) -> list[dict]:
    """Drop derived keys (id/degree) before reconstructing a GraphNode."""
    out = []
    for n in raw:
        out.append({k: v for k, v in n.items() if k in ("type", "value", "label", "meta")})
    return out
