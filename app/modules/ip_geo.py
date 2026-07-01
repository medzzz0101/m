"""
modules/ip_geo.py
=================
INFRASTRUCTURE geolocation + network ownership for an IP (or a domain, which we
resolve first). Uses ip-api.com (free, no key) — it returns city-level geo plus
ISP / org / ASN / reverse-DNS in one call.

Note the wording: this geolocates *infrastructure* (where a server/network sits),
NOT a person. That's the legitimate, public-data side of geolocation.
"""

from __future__ import annotations

from app.core.base import (
    BaseModule, Category, Confidence, GraphEdge, GraphNode, InputType, RunContext,
)
from ._common import fetch_json, resolve_ip


class IpGeoModule(BaseModule):
    key = "ip_geo"
    name = "IP geolocation"
    category = Category.INFRASTRUCTURE
    subtitle = "City, ISP, org, ASN, rDNS"
    accepts = (InputType.IP, InputType.DOMAIN)
    needs_network = True
    description = (
        "Infrastructure geolocation for an IP (city/region/country) plus the "
        "ISP, organisation, ASN and reverse-DNS, via ip-api.com. Geolocates the "
        "network, not a person."
    )

    async def run(self, value: str, ctx: RunContext):
        ip = await resolve_ip(value.strip())
        if not ip:
            return self.result(error=f"Could not resolve '{value}' to an IP.")

        fields = "status,message,country,regionName,city,lat,lon,isp,org,as,asname,reverse,query"
        url = f"http://ip-api.com/json/{ip}?fields={fields}"
        try:
            data = await fetch_json(ctx, url, ttl=86400, namespace="ipapi")
        except Exception as exc:  # noqa: BLE001
            return self.result(error=f"ip-api lookup failed: {exc}", source_url=url)

        if data.get("status") != "success":
            return self.result(error=data.get("message", "lookup failed"),
                               source_url=url)

        place = ", ".join(filter(None, [data.get("city"), data.get("regionName"),
                                         data.get("country")]))
        lat, lon = data.get("lat"), data.get("lon")
        asn = data.get("as", "")

        findings = [
            {"label": "IP", "summary": ip},
            {"label": "Location", "summary": place or "—"},
            {"label": "ISP", "summary": data.get("isp", "—")},
            {"label": "Organisation", "summary": data.get("org", "—")},
            {"label": "ASN", "summary": asn or "—"},
            {"label": "Reverse DNS", "summary": data.get("reverse") or "—"},
        ]
        # Plot the infrastructure location on the map.
        if isinstance(lat, (int, float)) and isinstance(lon, (int, float)):
            findings.append({"label": "Map",
                             "map": {"lat": lat, "lon": lon,
                                     "label": f"{ip} · {place}"}})

        nodes = [GraphNode("ip", ip, props={"geo": place, "isp": data.get("isp")})]
        edges: list[GraphEdge] = []
        if asn:
            nodes.append(GraphNode("asn", asn.split()[0], label=asn))
            edges.append(GraphEdge(f"ip:{ip}", f"asn:{asn.split()[0]}", "hosted_on"))
        if place and lat is not None:
            geo_id = f"{lat},{lon}"
            nodes.append(GraphNode("geo", geo_id, label=place))
            edges.append(GraphEdge(f"ip:{ip}", f"geo:{geo_id}", "located_at"))

        return self.result(
            findings=findings, confidence=Confidence.HIGH,
            source_url=f"https://ip-api.com/#{ip}", raw=data,
            nodes=nodes, edges=edges,
        )
