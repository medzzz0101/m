"""
modules/exposed_files.py
========================
Check a web target for a curated set of commonly-exposed sensitive files and
endpoints — the low-hanging fruit every recon methodology looks at: leaked VCS
metadata (.git/.svn), environment/config files, backups, dumps, server status
pages and debug endpoints.

We only issue ordinary HTTP GETs to well-known paths (exactly what a browser
would fetch) and report the status + a hint of what was found. We do NOT download
full contents, brute-force, or exploit anything — it's a "what's carelessly left
public" surface check.
"""

from __future__ import annotations

import asyncio

from app.core.base import (
    BaseModule, Category, Confidence, GraphEdge, GraphNode, InputType, RunContext,
)
from ._common import host_of

# path -> (what it is, marker that confirms a TRUE positive in the body)
PATHS = {
    "/.git/config": ("Git repo metadata", "[core]"),
    "/.git/HEAD": ("Git repo metadata", "ref:"),
    "/.svn/entries": ("SVN metadata", ""),
    "/.env": ("Environment secrets", "="),
    "/.env.local": ("Environment secrets", "="),
    "/config.php.bak": ("PHP config backup", "<?php"),
    "/wp-config.php.bak": ("WordPress config backup", "DB_"),
    "/.DS_Store": ("macOS directory index", "Bud1"),
    "/backup.zip": ("Backup archive", "PK"),
    "/backup.sql": ("SQL dump", "INSERT"),
    "/database.sql": ("SQL dump", "INSERT"),
    "/server-status": ("Apache status page", "Apache Server Status"),
    "/phpinfo.php": ("phpinfo() debug", "PHP Version"),
    "/.htpasswd": ("HTTP auth file", ":"),
    "/.aws/credentials": ("AWS credentials", "aws_access_key"),
    "/id_rsa": ("Private SSH key", "PRIVATE KEY"),
    "/.well-known/security.txt": ("security.txt (good practice)", ""),
    "/actuator/env": ("Spring Boot actuator", "propertySources"),
    "/debug/vars": ("Go expvar debug", "cmdline"),
    "/.vscode/sftp.json": ("VS Code SFTP creds", "password"),
}


class ExposedFilesModule(BaseModule):
    key = "exposed_files"
    name = "Exposed files"
    category = Category.INFRASTRUCTURE
    subtitle = ".git / .env / backups / debug"
    accepts = (InputType.DOMAIN, InputType.URL)
    needs_network = True
    description = (
        "Checks common sensitive paths (.git, .env, backups, SQL dumps, "
        "server-status, phpinfo, actuator…) via ordinary GETs and reports what's "
        "publicly exposed. Recon only — no download or exploitation."
    )

    async def _check(self, base, path, meta, ctx):
        what, marker = meta
        url = base + path
        try:
            resp = await ctx.http.get(url, headers={"User-Agent": "Mozilla/5.0"},
                                      follow_redirects=False)
        except Exception:
            return None
        if resp.status_code != 200:
            return None
        body = resp.text[:600] if resp.text else ""
        # Reduce false positives: if a marker is defined, require it. Also skip
        # pages that are obviously the site's HTML 200 catch-all.
        looks_html = "<html" in body.lower() or "<!doctype html" in body.lower()
        confirmed = (marker in body) if marker else (not looks_html)
        if not confirmed and not marker:
            return None
        return {"path": path, "what": what, "url": url,
                "confirmed": bool(marker and marker in body),
                "status": resp.status_code}

    async def run(self, value: str, ctx: RunContext):
        v = value.strip()
        base = (v if v.startswith("http") else f"https://{v}").rstrip("/")
        host = host_of(base)

        results = [r for r in await asyncio.gather(
            *(self._check(base, p, m, ctx) for p, m in PATHS.items())) if r]

        hot = [r for r in results if r["confirmed"] and "good practice" not in r["what"]]
        findings = [{
            "label": "Checked", "summary": f"{len(PATHS)} sensitive paths",
            "confidence": "info",
        }, {
            "label": "Exposed",
            "summary": f"{len(results)} responded 200 · {len(hot)} confirmed sensitive",
            "values": [f"{'⚠ ' if r['confirmed'] else ''}{r['path']} — {r['what']}"
                       for r in results] or ["nothing obvious exposed"],
            "confidence": "high" if hot else ("medium" if results else "info"),
        }]
        if hot:
            findings.append({"label": "⚠ Action",
                             "summary": "Confirmed sensitive files are public. If "
                                        "this is yours, remove/lock them now.",
                             "confidence": "high"})

        nodes = [GraphNode("domain", host)]
        edges: list[GraphEdge] = []
        for r in results:
            nid = f"{host}{r['path']}"
            nodes.append(GraphNode("service", nid, label=r["path"],
                                   props={"what": r["what"], "url": r["url"]}))
            edges.append(GraphEdge(f"domain:{host}", f"service:{nid}", "exposes"))

        return self.result(
            confidence=Confidence.HIGH if hot else Confidence.INFO,
            findings=findings, raw={"results": results}, nodes=nodes, edges=edges,
        )
