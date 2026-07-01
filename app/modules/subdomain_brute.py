"""
modules/subdomain_brute.py
==========================
Active-DNS subdomain discovery: resolve a curated wordlist of common subdomain
labels against the target and keep the ones that exist. This complements the
passive `subdomains` module (which reads Certificate Transparency) by catching
hosts that never got a public cert — internal-ish names like vpn, dev, staging,
jenkins, grafana, etc.

It only performs DNS resolution (the same lookups your browser does); it does not
connect to or scan the discovered hosts.
"""

from __future__ import annotations

import asyncio

from app.core.base import (
    BaseModule, Category, Confidence, GraphEdge, GraphNode, InputType, RunContext,
)
from ._common import resolve_ip

WORDLIST = [
    "www", "mail", "smtp", "imap", "pop", "webmail", "ns1", "ns2", "dns",
    "vpn", "remote", "portal", "api", "api-dev", "dev", "staging", "stage",
    "test", "qa", "uat", "beta", "demo", "app", "apps", "admin", "dashboard",
    "cpanel", "whm", "webdisk", "autodiscover", "autoconfig", "mx", "mx1",
    "cdn", "static", "assets", "img", "images", "media", "files", "download",
    "docs", "wiki", "blog", "shop", "store", "pay", "payments", "billing",
    "git", "gitlab", "jenkins", "ci", "build", "deploy", "grafana", "kibana",
    "prometheus", "status", "monitor", "nagios", "jira", "confluence", "vpn2",
    "owa", "exchange", "lync", "sip", "voip", "gateway", "fw", "firewall",
    "proxy", "cache", "db", "database", "sql", "mysql", "postgres", "redis",
    "mongo", "elastic", "s3", "backup", "backups", "old", "new", "internal",
    "intranet", "extranet", "corp", "vpn1", "citrix", "rdp", "ssh", "sftp",
    "ftp", "cloud", "k8s", "kube", "docker", "registry", "harbor", "argocd",
    "auth", "sso", "login", "id", "accounts", "secure", "m", "mobile", "wap",
]


class SubdomainBruteModule(BaseModule):
    key = "subdomain_brute"
    name = "Subdomain brute (DNS)"
    category = Category.INFRASTRUCTURE
    subtitle = "Resolve common host labels"
    accepts = (InputType.DOMAIN,)
    needs_network = True
    description = (
        "Resolves a curated wordlist of common subdomain names to find live hosts "
        "that CT logs miss (vpn, dev, jenkins, grafana…). DNS resolution only."
    )

    async def run(self, value: str, ctx: RunContext):
        domain = value.lower().strip().lstrip("*.")
        if "." not in domain:
            return self.result(error="Provide a domain.")

        candidates = [f"{w}.{domain}" for w in WORDLIST]
        ips = await asyncio.gather(*(resolve_ip(c) for c in candidates))
        live = [(c, ip) for c, ip in zip(candidates, ips) if ip]

        nodes = [GraphNode("domain", domain)]
        edges: list[GraphEdge] = []
        for sub, ip in live:
            nodes.append(GraphNode("subdomain", sub, props={"ip": ip}))
            edges.append(GraphEdge(f"domain:{domain}", f"subdomain:{sub}", "has_subdomain"))
            nodes.append(GraphNode("ip", ip))
            edges.append(GraphEdge(f"subdomain:{sub}", f"ip:{ip}", "resolves_to"))

        findings = [{
            "label": "Live subdomains",
            "summary": f"{len(live)} of {len(candidates)} common names resolve",
            "values": [f"{s} → {ip}" for s, ip in live] or ["none resolved"],
            "confidence": "high" if live else "info",
        }]
        return self.result(
            findings=findings,
            confidence=Confidence.HIGH if live else Confidence.INFO,
            raw={"live": live, "tested": len(candidates)}, nodes=nodes, edges=edges,
        )
