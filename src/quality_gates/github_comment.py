"""Post GitHub PR issue comments, inline reviews, and check runs."""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from quality_gates.gitutil import git_head
from quality_gates.identity import PRODUCT
from quality_gates.models import Finding
from quality_gates.review.contract import suggestion_fence

API_VERSION = "2022-11-28"
MAX_INLINE = 24
MAX_ANNOTATIONS = 50
SUMMARY_START = "<!-- the-code-sheriff:summary -->"
SUMMARY_END = "<!-- /the-code-sheriff:summary -->"


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
    creds = _creds()
    if creds is None:
        return (
            "skipped GitHub comment (need GITHUB_TOKEN, GITHUB_REPOSITORY, "
            "pull request number)"
        )
    token, repo, pr = creds
    status, _payload = _request(
        "POST",
        f"https://api.github.com/repos/{repo}/issues/{pr}/comments",
        token,
        {"body": body},
    )
    if 200 <= status < 300:
        return f"posted comment on PR #{pr}"
    return f"GitHub comment returned HTTP {status}"


def post_review(
    body: str,
    findings: list[Finding],
    *,
    diff_lines: dict[str, set[int]] | None = None,
    inline: bool = True,
    check_run: bool = True,
    fail_on_review: bool = False,
) -> list[str]:
    notes: list[str] = []
    creds = _creds()
    sha = pr_head_sha()
    if inline and creds and sha:
        notes.append(_post_pull_review(creds, body, findings, sha, diff_lines or {}))
    elif inline:
        notes.append(post_pr_comment(body))
    if check_run:
        notes.append(
            _post_check_run(
                body,
                findings,
                sha=sha,
                fail_on_review=fail_on_review,
            )
        )
    return notes


def pr_head_sha() -> str | None:
    explicit = os.environ.get("QUALITY_HEAD_SHA") or os.environ.get("GITHUB_SHA")
    event_path = os.environ.get("GITHUB_EVENT_PATH")
    if event_path and Path(event_path).is_file():
        try:
            payload = json.loads(Path(event_path).read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            payload = {}
        head = ((payload.get("pull_request") or {}).get("head") or {}).get("sha")
        if head:
            return str(head)
    if explicit:
        return explicit
    root = Path(os.environ.get("GITHUB_WORKSPACE") or ".")
    return git_head(root)


def _inlineable(item: Finding) -> bool:
    if item.severity == "info" or not item.path or not item.line:
        return False
    posix = item.path.replace("\\", "/").lstrip("./")
    if posix.endswith(".md"):
        return False
    return "/fixtures/" not in f"/{posix}/"


def _post_pull_review(
    creds: tuple[str, str, str],
    body: str,
    findings: list[Finding],
    sha: str,
    diff_lines: dict[str, set[int]],
) -> str:
    token, repo, pr = creds
    comments = []
    for item in findings:
        if not _inlineable(item):
            continue
        path = str(item.path).replace("\\", "/")
        allowed = diff_lines.get(path) or diff_lines.get(path.lstrip("./"))
        if allowed is not None and item.line not in allowed:
            continue
        comments.append(
            {
                "path": path,
                "line": item.line,
                "side": "RIGHT",
                "body": _inline_body(item),
            }
        )
        if len(comments) >= MAX_INLINE:
            break
    payload: dict[str, Any] = {
        "commit_id": sha,
        "event": "COMMENT",
        "body": body,
    }
    if comments:
        payload["comments"] = comments
    status, data = _request(
        "POST",
        f"https://api.github.com/repos/{repo}/pulls/{pr}/reviews",
        token,
        payload,
    )
    if 200 <= status < 300:
        return f"posted PR review on #{pr} ({len(comments)} inline)"
    fallback = post_pr_comment(body)
    detail = ""
    if isinstance(data, dict) and data.get("message"):
        detail = f" ({data.get('message')})"
    return f"PR review HTTP {status}{detail}; {fallback}"


def _post_check_run(
    body: str,
    findings: list[Finding],
    *,
    sha: str | None,
    fail_on_review: bool,
) -> str:
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    repo = os.environ.get("GITHUB_REPOSITORY")
    if not token or not repo or not sha:
        return "skipped GitHub check run (need GITHUB_TOKEN, GITHUB_REPOSITORY, SHA)"
    errors = [item for item in findings if item.severity == "error"]
    if fail_on_review and errors:
        conclusion = "failure"
    elif findings:
        conclusion = "neutral"
    else:
        conclusion = "success"
    annotations = []
    for item in findings:
        if not item.path or not item.line:
            continue
        level = {
            "error": "failure",
            "warning": "warning",
            "info": "notice",
        }.get(item.severity, "warning")
        annotations.append(
            {
                "path": item.path.replace("\\", "/"),
                "start_line": item.line,
                "end_line": item.line,
                "annotation_level": level,
                "message": item.message[:65535],
                "title": item.rule or "review",
            }
        )
        if len(annotations) >= MAX_ANNOTATIONS:
            break
    title = (
        f"{len(errors)} blocking, {len(findings) - len(errors)} other"
        if findings
        else "No review findings"
    )
    payload = {
        "name": "quality-review",
        "head_sha": sha,
        "status": "completed",
        "conclusion": conclusion,
        "output": {
            "title": title,
            "summary": body[:65535],
            "annotations": annotations,
        },
    }
    status, data = _request(
        "POST",
        f"https://api.github.com/repos/{repo}/check-runs",
        token,
        payload,
    )
    if 200 <= status < 300:
        return f"posted check run quality-review ({conclusion})"
    message = ""
    if isinstance(data, dict) and data.get("message"):
        message = f" ({data.get('message')})"
    return f"GitHub check run HTTP {status}{message}"


def _inline_body(item: Finding) -> str:
    parts = [f"**{item.rule or 'review'}** ({item.severity})", "", item.message]
    if item.reason:
        parts.extend(["", f"Why: {item.reason}"])
    if item.owasp or item.cwe:
        labels = [value for value in (item.owasp, item.cwe) if value]
        parts.extend(["", " · ".join(labels)])
    if item.snippet:
        parts.extend(["", f"Where: `{item.snippet}`"])
    if item.suggestion:
        parts.extend(["", f"Suggested fix: {item.suggestion}"])
    if item.reproduce:
        parts.extend(["", "**Steps of reproduction**", "", item.reproduce])
    if item.verify:
        parts.extend(["", f"Verify: `{item.verify}`"])
    if item.documentation_url:
        parts.extend(["", f"Docs: {item.documentation_url}"])
    fence = suggestion_fence(item)
    if fence:
        parts.extend(["", fence])
    parts.extend(
        [
            "",
            "Fix with `quality oracle --prompt` or MCP `quality_finding_context`.",
        ]
    )
    return "\n".join(parts)


def merge_pr_body(existing: str, summary: str) -> str:
    """Insert or replace the Sheriff summary block in a pull request body."""
    block = f"{SUMMARY_START}\n## {PRODUCT}\n\n{summary.strip()}\n{SUMMARY_END}"
    text = existing or ""
    if SUMMARY_START in text and SUMMARY_END in text:
        start = text.find(SUMMARY_START)
        end = text.find(SUMMARY_END) + len(SUMMARY_END)
        return text[:start] + block + text[end:]
    if not text.strip():
        return block
    return text.rstrip() + "\n\n" + block + "\n"


def sync_pr_summary(summary: str) -> str:
    """Write the review summary onto the pull request description."""
    text = (summary or "").strip()
    if not text:
        return "skipped PR description (empty summary)"
    creds = _creds()
    if creds is None:
        return (
            "skipped PR description (need GITHUB_TOKEN, GITHUB_REPOSITORY, "
            "pull request number)"
        )
    token, repo, pr = creds
    status, payload = _request(
        "GET",
        f"https://api.github.com/repos/{repo}/pulls/{pr}",
        token,
    )
    if status < 200 or status >= 300:
        return f"PR description GET HTTP {status}"
    existing = ""
    if isinstance(payload, dict):
        existing = str(payload.get("body") or "")
    body = merge_pr_body(existing, text)
    status, _payload = _request(
        "PATCH",
        f"https://api.github.com/repos/{repo}/pulls/{pr}",
        token,
        {"body": body},
    )
    if 200 <= status < 300:
        return f"updated PR #{pr} description"
    return f"PR description PATCH HTTP {status}"


def _creds() -> tuple[str, str, str] | None:
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    repo = os.environ.get("GITHUB_REPOSITORY")
    pr = os.environ.get("QUALITY_PR_NUMBER") or pr_number()
    if not token or not repo or not pr:
        return None
    return token, repo, pr


def _request(
    method: str, url: str, token: str, payload: dict[str, Any] | None = None
) -> tuple[int, Any]:
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(
        url,
        data=body,
        method=method,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "Content-Type": "application/json",
            "X-GitHub-Api-Version": API_VERSION,
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            raw = response.read().decode("utf-8")
            data: Any
            try:
                data = json.loads(raw) if raw else {}
            except json.JSONDecodeError:
                data = {}
            return response.status, data
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            data = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            data = {"message": raw[:300]}
        return exc.code, data
    except urllib.error.URLError as exc:
        return 0, {"message": str(exc)}
