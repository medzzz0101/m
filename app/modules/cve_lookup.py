"""
modules/cve_lookup.py
=====================
Look up known vulnerabilities (CVEs) for a piece of software by name/version via
the official NVD API (National Vulnerability Database, no key, rate-limited).

Give it a product term like "openssh 8.0", "nginx 1.18", "log4j" or "wordpress"
and it returns the most severe recent CVEs with CVSS scores and summaries. It
pairs naturally with tech_fingerprint / shodan_internetdb (which tell you WHAT is
running) to answer "and what's known-vulnerable about it?".

Public advisory data only — this reports what is publicly documented, it does not
test or exploit anything.
"""

from __future__ import annotations

from urllib.parse import quote

from app.core.base import (
    BaseModule, Category, Confidence, GraphNode, InputType, RunContext,
)
from ._common import fetch_json


def _severity(cve: dict) -> tuple[float, str]:
    """Extract the best-available CVSS base score + severity label."""
    metrics = cve.get("metrics", {})
    for key in ("cvssMetricV31", "cvssMetricV30", "cvssMetricV2"):
        arr = metrics.get(key)
        if arr:
            data = arr[0]["cvssData"]
            score = data.get("baseScore", 0.0)
            sev = data.get("baseSeverity") or arr[0].get("baseSeverity") or "?"
            return score, sev
    return 0.0, "?"


class CveLookupModule(BaseModule):
    key = "cve_lookup"
    name = "CVE lookup"
    category = Category.INTEL
    subtitle = "Known vulns for a product"
    accepts = (InputType.TEXT,)
    needs_network = True
    description = (
        "Searches the NVD for known CVEs affecting a product/version "
        "(e.g. 'openssh 8.0', 'nginx 1.18', 'log4j'). Returns CVSS scores and "
        "summaries. Public advisory data — no testing or exploitation."
    )

    async def run(self, value: str, ctx: RunContext):
        term = value.strip()
        if len(term) < 3:
            return self.result(error="Enter a product name (e.g. 'openssh 8.0').")
        url = ("https://services.nvd.nist.gov/rest/json/cves/2.0"
               f"?keywordSearch={quote(term)}&resultsPerPage=15")
        try:
            data = await fetch_json(ctx, url, ttl=43200, namespace="nvd")
        except Exception as exc:  # noqa: BLE001
            return self.result(error=f"NVD lookup failed: {exc}", source_url=url)

        vulns = data.get("vulnerabilities", []) or []
        rows = []
        for it in vulns:
            cve = it.get("cve", {})
            cid = cve.get("id", "?")
            score, sev = _severity(cve)
            desc = ""
            for d in cve.get("descriptions", []):
                if d.get("lang") == "en":
                    desc = d["value"]
                    break
            rows.append((score, cid, sev, desc))
        rows.sort(key=lambda r: -r[0])  # most severe first

        total = data.get("totalResults", len(rows))
        high = [r for r in rows if r[0] >= 7.0]
        findings = [{
            "label": "Matches",
            "summary": f"{total} CVE(s) mention “{term}” "
                       f"(showing top {len(rows)} by severity)",
            "confidence": "high" if high else "info",
        }]
        for score, cid, sev, desc in rows[:12]:
            findings.append({
                "label": f"{cid}  ·  CVSS {score} ({sev})",
                "summary": desc[:220],
                "values": [f"https://nvd.nist.gov/vuln/detail/{cid}"],
                "confidence": ("high" if score >= 9 else "medium" if score >= 7
                               else "info"),
            })

        nodes = [GraphNode("tech", term, label=term)]
        for _, cid, _, _ in rows[:12]:
            nodes.append(GraphNode("cve", cid, label=cid))
        return self.result(
            findings=findings,
            confidence=Confidence.HIGH if high else Confidence.INFO,
            source_url=f"https://nvd.nist.gov/vuln/search/results?query={quote(term)}",
            raw={"total": total, "cves": [{"id": r[1], "score": r[0]} for r in rows]},
            nodes=nodes,
        )
