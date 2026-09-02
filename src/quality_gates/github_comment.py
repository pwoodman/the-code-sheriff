"""Post a comment on the current GitHub pull request, if the job has credentials."""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from pathlib import Path


def pr_number() -> str | None:
    ref = os.environ.get("GITHUB_REF", "")
    match = re.match(r"refs/pull/(\d+)/", ref)
    if match:
        return match.group(1)
    event_path = os.environ.get("GITHUB_EVENT_PATH")
    if event_path and Path(event_path).is_file():
        try:
            payload = json.loads(Path(event_path).read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return None
        number = (payload.get("pull_request") or {}).get("number") or payload.get(
            "number"
        )
        return str(number) if number else None
    return None


def post_pr_comment(body: str) -> str:
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    repo = os.environ.get("GITHUB_REPOSITORY")
    pr = os.environ.get("QUALITY_PR_NUMBER") or pr_number()
    if not token or not repo or not pr:
        return (
            "skipped GitHub comment (need GITHUB_TOKEN, GITHUB_REPOSITORY, "
            "pull request number)"
        )
    url = f"https://api.github.com/repos/{repo}/issues/{pr}/comments"
    payload = json.dumps({"body": body}).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=payload,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "Content-Type": "application/json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            if 200 <= response.status < 300:
                return f"posted comment on PR #{pr}"
            return f"GitHub comment returned HTTP {response.status}"
    except urllib.error.HTTPError as exc:
        return f"GitHub comment failed: HTTP {exc.code}"
