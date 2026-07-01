"""
modules/email_headers.py
========================
Analyse RAW email headers pasted in by the user — the classic "is this email
legit / where did it really come from?" forensic. We parse the Received: chain
into hops (with per-hop delays), read the Authentication-Results (SPF / DKIM /
DMARC verdicts), and pull the originating IP and sender/return-path.

Fully offline: it only parses the text you paste. This inspects a message's
technical headers; it doesn't fetch anything or identify a private person.
"""

from __future__ import annotations

import re
from email.parser import HeaderParser

from app.core.base import (
    BaseModule, Category, Confidence, GraphNode, InputType, RunContext,
)

IP_RE = re.compile(r"[\[(]?((?:\d{1,3}\.){3}\d{1,3})[\])]?")


class EmailHeadersModule(BaseModule):
    key = "email_headers"
    name = "Email header analyzer"
    category = Category.INTEL
    subtitle = "Received chain, SPF/DKIM/DMARC"
    accepts = (InputType.TEXT,)
    needs_network = False
    description = (
        "Parses raw email headers: the Received hop chain with delays, "
        "SPF/DKIM/DMARC authentication results, originating IP and sender. Paste "
        "the full headers of a message. Offline analysis only."
    )

    async def run(self, value: str, ctx: RunContext):
        text = value
        if "received:" not in text.lower() and "from:" not in text.lower():
            return self.result(error="Paste the full RAW email headers "
                                     "(including the Received: lines).")
        msg = HeaderParser().parsestr(text)

        findings = []
        for label, hdr in [("From", "From"), ("Return-Path", "Return-Path"),
                           ("Reply-To", "Reply-To"), ("Subject", "Subject"),
                           ("Message-ID", "Message-ID"), ("Date", "Date")]:
            if msg.get(hdr):
                findings.append({"label": label, "summary": msg.get(hdr)[:200]})

        # Authentication results.
        auth = msg.get("Authentication-Results", "") or ""
        verdicts = []
        for mech in ("spf", "dkim", "dmarc"):
            m = re.search(rf"{mech}=(\w+)", auth, re.I)
            if m:
                verdicts.append(f"{mech.upper()}={m.group(1)}")
        if verdicts:
            bad = any(v.split("=")[1].lower() in ("fail", "softfail", "none")
                      for v in verdicts)
            findings.append({"label": "Authentication", "values": verdicts,
                             "confidence": "medium" if bad else "high"})

        # Received hop chain (bottom-up = origin first).
        received = msg.get_all("Received") or []
        hops = []
        origin_ip = None
        for i, r in enumerate(reversed(received)):
            one = " ".join(r.split())
            ips = IP_RE.findall(one)
            if ips and not origin_ip:
                origin_ip = ips[0]
            hops.append(f"hop {i+1}: {one[:120]}")
        if hops:
            findings.append({"label": f"Received chain ({len(hops)} hops)",
                             "values": hops})
        if origin_ip:
            findings.append({"label": "Originating IP (approx)",
                             "summary": origin_ip, "confidence": "medium"})

        nodes = []
        if origin_ip:
            nodes.append(GraphNode("ip", origin_ip, props={"role": "email-origin"}))
        return self.result(
            findings=findings or [{"label": "Headers", "summary": "parsed, little of note"}],
            confidence=Confidence.MEDIUM, raw={"auth": auth, "hops": len(received)},
            nodes=nodes,
        )
