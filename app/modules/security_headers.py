"""
modules/security_headers.py
===========================
Grade a site's HTTP security headers, securityheaders.com-style. Each important
header is worth points; we sum them into an A–F grade and explain what each one
does and why a missing one matters. Focused, graded, actionable — the companion
to http_probe's raw dump.
"""

from __future__ import annotations

from app.core.base import (
    BaseModule, Category, Confidence, GraphNode, InputType, RunContext,
)
from ._common import host_of

# header -> (points, why it matters)
HEADERS = {
    "strict-transport-security": (25, "Forces HTTPS; blocks SSL-strip downgrade."),
    "content-security-policy": (25, "Mitigates XSS / data injection."),
    "x-frame-options": (15, "Prevents clickjacking via framing."),
    "x-content-type-options": (10, "Stops MIME-type sniffing."),
    "referrer-policy": (10, "Controls how much referrer data leaks."),
    "permissions-policy": (10, "Restricts powerful browser features."),
    "cross-origin-opener-policy": (5, "Isolates browsing context (Spectre)."),
}


class SecurityHeadersModule(BaseModule):
    key = "security_headers"
    name = "Security headers"
    category = Category.INFRASTRUCTURE
    subtitle = "A–F hardening grade"
    accepts = (InputType.DOMAIN, InputType.URL)
    needs_network = True
    description = (
        "Grades HTTP security headers (HSTS, CSP, X-Frame-Options…) A–F with an "
        "explanation of each present/missing header."
    )

    async def run(self, value: str, ctx: RunContext):
        v = value.strip()
        url = v if v.startswith("http") else f"https://{v}"
        try:
            resp = await ctx.http.get(url, follow_redirects=True,
                                      headers={"User-Agent": "Mozilla/5.0"})
        except Exception as exc:  # noqa: BLE001
            return self.result(error=f"Fetch failed: {exc}", source_url=url)

        h = {k.lower(): v for k, v in resp.headers.items()}
        score, present, missing = 0, [], []
        for header, (pts, why) in HEADERS.items():
            if header in h:
                score += pts
                present.append(f"✓ {header}")
            else:
                missing.append(f"✗ {header} — {why}")
        # Penalise leaky headers.
        leaks = [x for x in ("server", "x-powered-by", "x-aspnet-version") if x in h]

        grade = ("A" if score >= 90 else "B" if score >= 70 else "C" if score >= 50
                 else "D" if score >= 30 else "F")
        findings = [
            {"label": "Grade", "summary": f"{grade}  ({score}/100)",
             "confidence": "high" if score >= 70 else "medium" if score >= 40 else "low"},
            {"label": f"Present ({len(present)})", "values": present or ["none"]},
            {"label": f"Missing ({len(missing)})", "values": missing or ["none — great!"],
             "confidence": "medium" if missing else "info"},
        ]
        if leaks:
            findings.append({"label": "Version leakage",
                             "values": [f"{x}: {h[x]}" for x in leaks],
                             "confidence": "low"})
        return self.result(
            findings=findings, confidence=Confidence.HIGH,
            source_url=f"https://securityheaders.com/?q={host_of(url)}",
            raw={"score": score, "grade": grade, "present": present, "missing": missing},
            nodes=[GraphNode("domain", host_of(url), props={"sec_grade": grade})],
        )
