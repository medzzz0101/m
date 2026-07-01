"""
modules/doc_metadata.py
=======================
Pull metadata out of a PUBLIC document by URL — FOCA-style. Documents an
organisation publishes (PDFs, mainly) often carry leftover metadata: the author,
the software/version that produced them, and creation/modification timestamps.
That reveals internal usernames, toolchains and activity patterns.

We fetch the document and extract the PDF info dictionary from its bytes (no
heavy dependency). Reads a public URL you provide; metadata only.
"""

from __future__ import annotations

import re

from app.core.base import (
    BaseModule, Category, Confidence, GraphNode, InputType, RunContext,
)
from ._common import host_of

FIELDS = {
    "Author": rb"/Author\s*\(([^)]{1,200})\)",
    "Creator": rb"/Creator\s*\(([^)]{1,200})\)",
    "Producer": rb"/Producer\s*\(([^)]{1,200})\)",
    "Title": rb"/Title\s*\(([^)]{1,200})\)",
    "CreationDate": rb"/CreationDate\s*\(([^)]{1,60})\)",
    "ModDate": rb"/ModDate\s*\(([^)]{1,60})\)",
}


class DocMetadataModule(BaseModule):
    key = "doc_metadata"
    name = "Document metadata"
    category = Category.INFRASTRUCTURE
    subtitle = "FOCA-style PDF author/software"
    accepts = (InputType.URL,)
    needs_network = True
    description = (
        "Extracts leftover metadata (author, producing software, timestamps) from "
        "a public PDF by URL — can reveal internal usernames and toolchains."
    )

    async def run(self, value: str, ctx: RunContext):
        url = value.strip()
        if not url.startswith(("http://", "https://")):
            url = "https://" + url
        try:
            resp = await ctx.http.get(url, follow_redirects=True,
                                      headers={"User-Agent": "Mozilla/5.0"})
        except Exception as exc:  # noqa: BLE001
            return self.result(error=f"Fetch failed: {exc}", source_url=url)

        data = resp.content[:2_000_000]
        ctype = resp.headers.get("content-type", "")
        if not (b"%PDF" in data[:1024] or "pdf" in ctype.lower()):
            return self.result(
                findings=[{"label": "Document",
                           "summary": "Not a PDF (only PDF metadata is supported "
                                      "here). Content-Type: " + (ctype or "?")}],
                confidence=Confidence.INFO, source_url=url)

        found = {}
        for label, pat in FIELDS.items():
            m = re.search(pat, data)
            if m:
                try:
                    found[label] = m.group(1).decode("latin-1", "ignore").strip()
                except Exception:
                    pass

        findings = [{"label": "Type", "summary": "PDF"}]
        for label in FIELDS:
            if found.get(label):
                conf = "medium" if label in ("Author", "Creator", "Producer") else "info"
                findings.append({"label": label, "summary": found[label], "confidence": conf})
        if len(findings) == 1:
            findings.append({"label": "Metadata", "summary": "None recoverable "
                             "(stripped or encrypted)."})

        nodes = [GraphNode("domain", host_of(url))]
        if found.get("Author"):
            nodes.append(GraphNode("username", found["Author"],
                                   label=found["Author"], props={"source": "pdf-author"}))
        return self.result(
            findings=findings,
            confidence=Confidence.MEDIUM if len(findings) > 2 else Confidence.INFO,
            source_url=url, raw=found, nodes=nodes,
        )
