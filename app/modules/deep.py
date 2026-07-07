"""deep.py — deeper, still-legal capabilities.

  * cve_probe    — read a site's server/framework version banner and look up
                   matching public CVEs (NVD). Attack-surface depth, public data.
  * doc_metadata — pull author / software / timestamps out of a PUBLIC document
                   (PDF or DOCX) at a URL. Classic OSINT metadata extraction.

Public data only; nothing here identifies a private individual (a document's
"author" field is whatever metadata the publisher themselves embedded).
"""
from __future__ import annotations

import re

from ..core.base import (BaseModule, Category, Confidence, InputType, RunContext,
                         ModuleResult)
from ..core.net import get_client


def _host_of(target: str) -> str:
    t = re.sub(r"^https?://", "", target.strip(), flags=re.I)
    return t.split("/")[0].split(":")[0]


class CveProbe(BaseModule):
    id = "cve_probe"
    name = "CVE probe (version → CVEs)"
    description = "Reads a site's server/framework version and looks up matching public CVEs (NVD)."
    category = Category.INFRASTRUCTURE
    inputs = (InputType.DOMAIN, InputType.URL)
    tier = "elite"
    timeout = 20.0

    async def run(self, ctx: RunContext) -> ModuleResult:
        res = self.result()
        host = _host_of(ctx.target)
        url = ctx.target if ctx.target.startswith("http") else f"https://{host}"
        try:
            r = await get_client().get(url)
        except Exception:
            res.add("Probe", "host did not respond to HTTP", Confidence.INFO)
            res.summary = f"{host}: no HTTP banner to fingerprint"; return res
        res.node("domain", host, label=host)

        # Collect version tokens from telltale headers.
        banners = []
        for hk in ("server", "x-powered-by", "x-aspnet-version", "x-generator"):
            v = r.headers.get(hk)
            if v:
                res.add(hk, v, Confidence.CONFIRMED)
                banners.append(v)
        # Extract "product version" pairs like nginx/1.18.0, PHP/8.1.2.
        products = []
        for b in banners:
            for m in re.finditer(r"([A-Za-z][A-Za-z0-9\-\_\.]+?)[/ ]v?(\d+\.\d+(?:\.\d+)?)", b):
                products.append((m.group(1), m.group(2)))
        if not products:
            res.summary = f"{host}: no versioned software in banners"
            res.add("Note", "no version string to match CVEs against", Confidence.INFO)
            return res

        found = 0
        for prod, ver in products[:3]:
            try:
                q = f"{prod} {ver}"
                nr = await get_client().get(
                    "https://services.nvd.nist.gov/rest/json/cves/2.0",
                    params={"keywordSearch": q, "resultsPerPage": 5}, timeout=12)
                if nr.status_code != 200:
                    continue
                for item in nr.json().get("vulnerabilities", [])[:5]:
                    cve = item.get("cve", {})
                    cid = cve.get("id", "CVE")
                    sev = ""
                    metrics = cve.get("metrics", {})
                    for mk in ("cvssMetricV31", "cvssMetricV30", "cvssMetricV2"):
                        if metrics.get(mk):
                            sev = str(metrics[mk][0].get("cvssData", {}).get("baseScore", ""))
                            break
                    res.add(f"{prod} {ver}", f"{cid}{' · CVSS '+sev if sev else ''}",
                            Confidence.POSSIBLE, link=f"https://nvd.nist.gov/vuln/detail/{cid}")
                    found += 1
            except Exception:
                continue
        res.summary = (f"{host}: {found} candidate CVE(s) for "
                       f"{', '.join(p+' '+v for p,v in products[:3])}") if found else \
                      f"{host}: no CVEs matched the detected versions"
        return res


class DocMetadata(BaseModule):
    id = "doc_metadata"
    name = "Document metadata"
    description = "Extracts author, software and timestamps from a public PDF or DOCX URL."
    category = Category.INTEL
    inputs = (InputType.URL,)
    tier = "premium"
    timeout = 18.0

    async def run(self, ctx: RunContext) -> ModuleResult:
        res = self.result()
        url = ctx.target
        try:
            r = await get_client().get(url)
        except Exception as e:
            res.ok = False; res.error = str(e); return res
        data = r.content
        if not data:
            res.summary = "Empty document"; return res

        if data[:4] == b"%PDF":
            self._pdf(res, data)
        elif data[:2] == b"PK":  # zip → likely DOCX/XLSX/PPTX (OOXML)
            self._ooxml(res, data)
        else:
            res.summary = "Not a PDF/DOCX (or metadata stripped)"; return res
        if not res.findings:
            res.add("Metadata", "none embedded (stripped or minimal)", Confidence.INFO)
            res.summary = "No embedded document metadata"
        else:
            res.summary = f"{len(res.findings)} metadata fields extracted"
        return res

    @staticmethod
    def _pdf(res, data):
        text = data[:400000].decode("latin-1", "ignore")
        fields = {"Author": "Author", "Creator": "Software (Creator)",
                  "Producer": "Software (Producer)", "Title": "Title",
                  "CreationDate": "Created", "ModDate": "Modified"}
        for key, label in fields.items():
            m = re.search(rf"/{key}\s*\(([^)]{{1,200}})\)", text)
            if m:
                val = m.group(1).strip()
                if key.endswith("Date"):
                    dm = re.match(r"D:(\d{4})(\d{2})(\d{2})", val)
                    if dm: val = f"{dm.group(1)}-{dm.group(2)}-{dm.group(3)}"
                res.add(label, val, Confidence.LIKELY)

    @staticmethod
    def _ooxml(res, data):
        import io, zipfile
        try:
            z = zipfile.ZipFile(io.BytesIO(data))
            core = z.read("docProps/core.xml").decode("utf-8", "ignore")
            app = z.read("docProps/app.xml").decode("utf-8", "ignore") if "docProps/app.xml" in z.namelist() else ""
        except Exception:
            return
        for tag, label in [("dc:creator", "Author"), ("cp:lastModifiedBy", "Last modified by"),
                           ("dcterms:created", "Created"), ("dcterms:modified", "Modified"),
                           ("dc:title", "Title")]:
            m = re.search(rf"<{tag}[^>]*>([^<]{{1,200}})</{tag}>", core)
            if m: res.add(label, m.group(1).strip(), Confidence.LIKELY)
        am = re.search(r"<Application>([^<]+)</Application>", app)
        if am: res.add("Software", am.group(1).strip(), Confidence.LIKELY)
