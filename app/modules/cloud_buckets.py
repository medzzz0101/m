"""
modules/cloud_buckets.py
========================
Hunt for an organisation's PUBLICLY-exposed cloud storage. Given a name (a domain
or org keyword) we generate likely bucket names from common patterns and check
whether each exists and is publicly listable on AWS S3, Google Cloud Storage and
Azure Blob.

This only ever performs an unauthenticated HTTP GET/HEAD against PUBLIC storage
endpoints — the same request a browser makes. It reports what's already exposed
to the world; it never tries to bypass access controls.
"""

from __future__ import annotations

import asyncio

from app.core.base import (
    BaseModule, Category, Confidence, GraphEdge, GraphNode, InputType, RunContext,
)

# Suffix/prefix patterns organisations commonly use.
PATTERNS = [
    "{b}", "{b}-prod", "{b}-dev", "{b}-staging", "{b}-backup", "{b}-backups",
    "{b}-assets", "{b}-static", "{b}-media", "{b}-uploads", "{b}-data",
    "{b}-public", "{b}-private", "{b}-files", "{b}-logs", "{b}-cdn",
    "{b}-images", "{b}-web", "{b}-test", "backup-{b}", "assets-{b}",
]


def _base_names(value: str) -> list[str]:
    """Derive candidate base tokens from a domain or keyword."""
    v = value.strip().lower()
    tokens = set()
    if "." in v:
        parts = v.split(".")
        tokens.add(parts[0])                 # example.com -> example
        tokens.add("".join(parts[:-1]))      # example.co -> exampleco
        tokens.add(v.replace(".", "-"))
    else:
        tokens.add(v)
    return [t for t in tokens if t and 2 < len(t) < 40]


class CloudBucketsModule(BaseModule):
    key = "cloud_buckets"
    name = "Cloud buckets"
    category = Category.INFRASTRUCTURE
    subtitle = "Exposed S3 / GCS / Azure"
    accepts = (InputType.DOMAIN, InputType.TEXT)
    needs_network = True
    description = (
        "Checks common naming patterns for an org's PUBLICLY-exposed S3, Google "
        "Cloud Storage and Azure Blob buckets. Only reads public endpoints — never "
        "bypasses access controls."
    )

    def _endpoints(self, name: str) -> list[tuple[str, str, str]]:
        """(provider, bucket, url) — path-style to avoid dotted-name TLS issues."""
        return [
            ("S3", name, f"https://s3.amazonaws.com/{name}/"),
            ("GCS", name, f"https://storage.googleapis.com/{name}/"),
            ("Azure", name, f"https://{name}.blob.core.windows.net/?comp=list"),
        ]

    async def _check(self, provider, bucket, url, ctx):
        try:
            resp = await ctx.http.get(url, headers={"User-Agent": "Mozilla/5.0"})
        except Exception:
            return None
        code = resp.status_code
        body = resp.text[:400].lower()
        # Interpret provider-specific responses.
        if provider in ("S3", "GCS"):
            if code == 200:
                listable = "<listbucketresult" in body or "<?xml" in body
                return {"provider": provider, "bucket": bucket, "url": url,
                        "status": "PUBLIC — listable" if listable else "exists (200)"}
            if code == 403:
                return {"provider": provider, "bucket": bucket, "url": url,
                        "status": "exists but private (403)"}
        elif provider == "Azure":
            if code == 200 and "enumerationresults" in body:
                return {"provider": provider, "bucket": bucket, "url": url,
                        "status": "PUBLIC — listable"}
            if code in (403, 409):
                return {"provider": provider, "bucket": bucket, "url": url,
                        "status": f"exists ({code})"}
        return None

    async def run(self, value: str, ctx: RunContext):
        bases = _base_names(value)
        if not bases:
            return self.result(error="Provide a domain or org keyword.")

        # Build the candidate list (bounded).
        candidates: list[str] = []
        for base in bases:
            for pat in PATTERNS:
                candidates.append(pat.format(b=base))
        candidates = list(dict.fromkeys(candidates))[:40]  # dedupe + cap

        tasks = []
        for name in candidates:
            for provider, bucket, url in self._endpoints(name):
                tasks.append(self._check(provider, bucket, url, ctx))
        results = [r for r in await asyncio.gather(*tasks) if r]

        public = [r for r in results if "PUBLIC" in r["status"]]
        findings = [{
            "label": "Checked",
            "summary": f"{len(candidates)} candidate names across S3/GCS/Azure",
            "confidence": "info",
        }, {
            "label": "Found",
            "summary": f"{len(results)} existing bucket(s), {len(public)} PUBLICLY listable",
            "values": [f"[{r['provider']}] {r['bucket']} — {r['status']}"
                       for r in results] or ["none found with these patterns"],
            "confidence": "high" if public else ("medium" if results else "info"),
        }]
        if public:
            findings.append({"label": "⚠ Exposure",
                             "summary": "Publicly listable buckets can leak data. "
                                        "Verify and lock down if these are yours.",
                             "confidence": "high"})

        nodes: list[GraphNode] = []
        edges: list[GraphEdge] = []
        for r in results:
            bid = f"{r['provider']}:{r['bucket']}"
            nodes.append(GraphNode("cloud_bucket", bid,
                                   label=f"{r['bucket']} ({r['provider']})",
                                   props={"status": r["status"], "url": r["url"]}))
        return self.result(
            findings=findings,
            confidence=Confidence.HIGH if public else Confidence.INFO,
            raw={"results": results}, nodes=nodes, edges=edges,
        )
