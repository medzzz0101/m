"""
modules/github_user.py
======================
Deep public profile for a GitHub handle via GitHub's public API (no auth needed
for public data). It surfaces the professional footprint the user PUBLISHED:
display name, company, location, blog, linked Twitter, account age, follower
count, and their most-recently-pushed public repositories with primary languages.

Scope: public self-published profile + public repositories — the same data on the
person's public GitHub page. It does NOT harvest commit author emails or attempt
to unmask anyone; it reads what the account chose to make public.
"""

from __future__ import annotations

from app.core.base import (
    BaseModule, Category, Confidence, GraphEdge, GraphNode, InputType, RunContext,
)
from ._common import fetch_json


class GithubUserModule(BaseModule):
    key = "github_user"
    name = "GitHub profile"
    category = Category.IDENTITY
    subtitle = "Public profile + repos"
    accepts = (InputType.USERNAME,)
    needs_network = True
    description = (
        "Deep public GitHub profile for a handle: name/company/location/blog the "
        "user published, account age, followers, and top public repos with "
        "languages. Public self-published data — no email harvesting."
    )

    async def run(self, value: str, ctx: RunContext):
        user = value.strip().lstrip("@")
        api = f"https://api.github.com/users/{user}"
        hdrs = {"User-Agent": "osint-engine", "Accept": "application/vnd.github+json"}
        try:
            u = await fetch_json(ctx, api, ttl=3600, namespace="github", headers=hdrs)
        except Exception as exc:  # noqa: BLE001
            if "404" in str(exc):
                return self.result(
                    findings=[{"label": "GitHub", "summary": f"No public user '{user}'."}],
                    confidence=Confidence.INFO, source_url=f"https://github.com/{user}")
            return self.result(error=f"GitHub lookup failed: {exc}", source_url=api)

        # Recent repos (public), most-recently pushed first.
        repos = []
        try:
            repos = await fetch_json(
                ctx, f"{api}/repos?sort=pushed&per_page=10", ttl=3600,
                namespace="github", headers=hdrs)
        except Exception:
            pass

        langs: dict[str, int] = {}
        top = []
        for r in repos or []:
            if r.get("fork"):
                continue
            lang = r.get("language")
            if lang:
                langs[lang] = langs.get(lang, 0) + 1
            top.append(f"{r.get('name')} ★{r.get('stargazers_count',0)}"
                       f" · {lang or '—'}")

        findings = [
            {"label": "Name", "summary": u.get("name") or "—",
             "confidence": "high"},
            {"label": "Handle", "summary": "@" + u.get("login", user)},
        ]
        for label, key in [("Company", "company"), ("Location", "location"),
                           ("Blog / site", "blog"), ("Bio", "bio"),
                           ("Twitter/X", "twitter_username")]:
            if u.get(key):
                val = u[key]
                if key == "twitter_username":
                    val = "@" + val
                findings.append({"label": label, "summary": str(val)[:200]})
        findings.append({"label": "Public repos / gists",
                         "summary": f"{u.get('public_repos',0)} repos · "
                                    f"{u.get('public_gists',0)} gists"})
        findings.append({"label": "Followers / following",
                         "summary": f"{u.get('followers',0):,} / {u.get('following',0):,}"})
        findings.append({"label": "Joined", "summary": (u.get("created_at") or "")[:10]})
        if langs:
            findings.append({"label": "Top languages",
                             "summary": ", ".join(sorted(langs, key=lambda k: -langs[k]))})
        if top:
            findings.append({"label": "Recent repos", "values": top})
        findings.append({"label": "Note",
                         "summary": "Public self-published profile — not identity "
                                    "attribution.", "confidence": "info"})

        nodes = [GraphNode("username", user, label="@" + user,
                           props={"github_name": u.get("name"),
                                  "github_followers": u.get("followers")})]
        edges: list[GraphEdge] = []
        if u.get("blog"):
            findings_url = u["blog"]
            nodes.append(GraphNode("domain", findings_url, label=findings_url))
            edges.append(GraphEdge(f"username:{user}", f"domain:{findings_url}", "related_to"))
        if u.get("twitter_username"):
            tw = u["twitter_username"]
            nodes.append(GraphNode("username", tw, label="@" + tw))
            edges.append(GraphEdge(f"username:{user}", f"username:{tw}", "same_owner",
                                   props={"via": "github->twitter (self-declared)"}))

        return self.result(
            findings=findings, confidence=Confidence.HIGH,
            source_url=f"https://github.com/{user}",
            raw={"user": u, "repos": top}, nodes=nodes, edges=edges,
        )
