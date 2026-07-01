"""
modules/jwt_decoder.py
======================
Decode a JSON Web Token (JWT) — split it into header, payload and signature, and
surface the interesting security-relevant claims: algorithm, issuer, subject,
audience, issued-at / expiry (with a human "expired?" verdict), and any obvious
red flags (alg=none, weak alg). Decoding only — we do NOT verify the signature
(that needs the secret/key), and we never send the token anywhere.

Purely offline base64url decoding. A staple of any web/security analyst's kit.
"""

from __future__ import annotations

import base64
import json
import time

from app.core.base import (
    BaseModule, Category, Confidence, InputType, RunContext,
)


def _b64url(seg: str) -> bytes:
    seg += "=" * (-len(seg) % 4)
    return base64.urlsafe_b64decode(seg)


class JwtDecoderModule(BaseModule):
    key = "jwt_decoder"
    name = "JWT decoder"
    category = Category.INTEL
    subtitle = "Decode token header/claims"
    accepts = (InputType.TEXT,)
    needs_network = False
    description = (
        "Decodes a JWT into header + claims (alg, iss, sub, aud, iat/exp with an "
        "expiry verdict) and flags weak/none algorithms. Decode only — signature "
        "is not verified and the token never leaves the server."
    )

    async def run(self, value: str, ctx: RunContext):
        tok = value.strip()
        parts = tok.split(".")
        if len(parts) != 3:
            return self.result(error="Not a JWT (needs header.payload.signature).")
        try:
            header = json.loads(_b64url(parts[0]))
            payload = json.loads(_b64url(parts[1]))
        except Exception:
            return self.result(error="Could not decode the JWT segments.")

        alg = header.get("alg", "?")
        findings = [
            {"label": "Algorithm", "summary": str(alg),
             "confidence": "low" if str(alg).lower() in ("none", "hs256") else "info"},
            {"label": "Type", "summary": str(header.get("typ", "—"))},
        ]
        # Notable registered claims.
        for label, claim in [("Issuer (iss)", "iss"), ("Subject (sub)", "sub"),
                             ("Audience (aud)", "aud"), ("JWT ID (jti)", "jti")]:
            if claim in payload:
                findings.append({"label": label, "summary": str(payload[claim])[:200]})
        # Time claims with verdicts.
        now = int(time.time())
        for label, claim in [("Issued at (iat)", "iat"), ("Not before (nbf)", "nbf"),
                             ("Expires (exp)", "exp")]:
            if claim in payload:
                ts = payload[claim]
                try:
                    when = time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime(ts))
                except Exception:
                    when = str(ts)
                extra = ""
                if claim == "exp":
                    extra = "  — EXPIRED" if ts < now else "  — still valid"
                findings.append({"label": label, "summary": when + extra,
                                 "confidence": "low" if (claim == "exp" and ts < now)
                                 else "info"})

        flags = []
        if str(alg).lower() == "none":
            flags.append("alg=none — token is UNSIGNED (critical if trusted)")
        if "exp" not in payload:
            flags.append("no exp claim — token may never expire")
        if flags:
            findings.append({"label": "⚠ Flags", "values": flags, "confidence": "high"})

        # Show the full decoded payload for reference.
        findings.append({"label": "Full payload",
                         "values": [f"{k}: {json.dumps(v)}" for k, v in payload.items()]})

        return self.result(
            findings=findings,
            confidence=Confidence.MEDIUM if flags else Confidence.INFO,
            raw={"header": header, "payload": payload},
        )
