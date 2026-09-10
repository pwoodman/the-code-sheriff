"""GitHub API host, install URLs, and least-privilege permission rationale."""

from __future__ import annotations

import os
from typing import Any

from quality_gates.identity import DEFAULT_APP_NAME, HOMEPAGE, REPO_NAME

DEFAULT_API = "https://api.github.com"
DEFAULT_HTML = "https://github.com"
APP_SLUG = "the-code-sheriff"

PERMISSIONS: dict[str, tuple[str, str]] = {
    "checks": (
        "write",
        "Create and update the single The Code Sheriff check run.",
    ),
    "pull_requests": (
        "write",
        "Post inline review comments, suggested changes, and the PR summary.",
    ),
    "contents": (
        "read",
        "Read source, workflows, and CODEOWNERS for review and gates.",
    ),
    "metadata": (
        "read",
        "Identify the installation, repository, and private vs public visibility.",
    ),
    "security_events": (
        "write",
        "Attach security-gate alerts (secrets, SCA) to the repository.",
    ),
}

DEFAULT_EVENTS = (
    "pull_request",
    "check_run",
    "check_suite",
    "issue_comment",
)


def api_base() -> str:
    raw = os.environ.get("GITHUB_API_URL") or os.environ.get("GH_API") or DEFAULT_API
    return raw.rstrip("/")


def html_base() -> str:
    explicit = os.environ.get("GITHUB_SERVER_URL") or os.environ.get("GH_HOST")
    if explicit:
        return explicit.rstrip("/")
    api = api_base()
    if api == DEFAULT_API or api.endswith("://api.github.com"):
        return DEFAULT_HTML
    if api.endswith("/api/v3"):
        return api[: -len("/api/v3")]
    return api


def api_url(path: str) -> str:
    suffix = path if path.startswith("/") else f"/{path}"
    return f"{api_base()}{suffix}"


def graphql_url() -> str:
    api = api_base()
    if api.endswith("/api/v3"):
        return f"{api[: -len('/api/v3')]}/api/graphql"
    if api == DEFAULT_API:
        return f"{DEFAULT_API}/graphql"
    return f"{api}/graphql"


def is_github_enterprise() -> bool:
    return api_base() != DEFAULT_API


def install_url(*, slug: str = APP_SLUG) -> str:
    return f"{html_base()}/apps/{slug}/installations/new"


def marketplace_url(*, slug: str = APP_SLUG) -> str:
    if is_github_enterprise():
        return install_url(slug=slug)
    return f"{DEFAULT_HTML}/marketplace/{slug}"


def permission_table() -> list[dict[str, str]]:
    return [
        {"permission": name, "access": access, "why": why}
        for name, (access, why) in PERMISSIONS.items()
    ]


def app_identity() -> dict[str, Any]:
    return {
        "name": DEFAULT_APP_NAME,
        "slug": APP_SLUG,
        "homepage": HOMEPAGE,
        "repo": REPO_NAME,
        "install_url": install_url(),
        "marketplace_url": marketplace_url(),
        "events": list(DEFAULT_EVENTS),
        "permissions": permission_table(),
        "enterprise": is_github_enterprise(),
        "api_base": api_base(),
        "sso": "GitHub organization SAML/SSO",
        "scim": "GitHub Enterprise SCIM provisioning",
        "private_repos": True,
        "pricing": "MIT self-hosted; public and private repos use the repo's Actions minutes",
    }
