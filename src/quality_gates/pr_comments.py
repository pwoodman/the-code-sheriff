"""Unresolved GitHub review threads for the agent oracle."""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from quality_gates.github_comment import _creds, _request, pr_number
from quality_gates.models import Finding
from quality_gates.review.parse import fingerprint

DISMISSED_FILE = "dismissed.json"
COMMENTS_FILE = "comments.json"
_SUGGESTION = re.compile(
    r"```suggestion[^\n]*\n(.*?)```", re.S | re.I
)
_SHERIFF_RULE = re.compile(
    r"\*\*(?P<rule>[^*]+)\*\*\s*\((?P<severity>error|warning|info)\)",
    re.I,
)
_FALSE_POSITIVE = re.compile(
    r"\b(false positive|won'?t fix|not an issue|dismiss(ed)?|ignore this)\b",
    re.I,
)

_GRAPHQL = """
query($owner: String!, $name: String!, $number: Int!) {
  repository(owner: $owner, name: $name) {
    pullRequest(number: $number) {
      reviewThreads(first: 100) {
        nodes {
          isResolved
          isOutdated
          comments(first: 20) {
            nodes {
              databaseId
              body
              path
              originalLine
              line
              url
              author { login }
            }
          }
        }
      }
    }
  }
}
"""


@dataclass
class ReviewThread:
    resolved: bool
    outdated: bool
    path: str | None
    line: int | None
    body: str
    url: str
    author: str
    suggestion: str | None
    rule: str | None


def list_threads(
    *,
    token: str | None = None,
    repo: str | None = None,
    pr: str | None = None,
) -> list[ReviewThread]:
    creds = (token, repo, pr) if token and repo and pr else _creds()
    if creds is None:
        return []
    token, repo, pr = creds
    owner, _, name = repo.partition("/")
    if not owner or not name:
        return []
    try:
        number = int(pr)
    except ValueError:
        return []
    status, data = _request(
        "POST",
        "https://api.github.com/graphql",
        token,
        {
            "query": _GRAPHQL,
            "variables": {"owner": owner, "name": name, "number": number},
        },
    )
    if 200 <= status < 300:
        threads = _from_graphql(data)
        if threads or _graphql_ok(data):
            return threads
    return _from_rest(token, repo, pr)


def list_open_pr_heads(
    *, ours_sha: str = "", branch: str = ""
) -> list[tuple[str, str]]:
    creds = _creds()
    if creds is None:
        return []
    token, repo, current_pr = creds
    status, data = _request(
        "GET",
        f"https://api.github.com/repos/{repo}/pulls?state=open&per_page=30",
        token,
    )
    if not (200 <= status < 300) or not isinstance(data, list):
        return []
    out: list[tuple[str, str]] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        number = str(item.get("number") or "")
        if number and current_pr and number == str(current_pr):
            continue
        head = item.get("head") if isinstance(item.get("head"), dict) else {}
        sha = str(head.get("sha") or "").strip()
        ref = str(head.get("ref") or "").strip()
        if ref and branch and ref == branch:
            continue
        if not sha or sha == ours_sha:
            continue
        title = str(item.get("title") or f"#{number}")
        out.append((sha, f"#{number} {title}".strip()))
    return out[:20]


def unresolved_findings(threads: list[ReviewThread] | None = None) -> list[Finding]:
    findings: list[Finding] = []
    for thread in threads if threads is not None else list_threads():
        if thread.resolved or thread.outdated:
            continue
        suggestion = thread.suggestion
        findings.append(
            Finding(
                gate="comments",
                rule=thread.rule or "unresolved-review",
                severity="error",
                path=thread.path,
                line=thread.line,
                message=_summary(thread.body),
                suggestion=suggestion,
                patch=_suggestion_patch(thread.path, suggestion) if suggestion else None,
                verify="quality comments",
                reason=f"unresolved review by {thread.author or 'reviewer'}",
                documentation_url=thread.url or None,
            )
        )
    return findings


def dismissed_fingerprints(threads: list[ReviewThread] | None = None) -> list[str]:
    out: list[str] = []
    for thread in threads if threads is not None else list_threads():
        if not thread.resolved:
            continue
        finding = Finding(
            gate="review",
            rule=thread.rule or "logic",
            path=thread.path,
            line=thread.line,
            message=_summary(thread.body),
        )
        out.append(fingerprint(finding, bucket=1))
        out.append(fingerprint(finding, bucket=5))
    return list(dict.fromkeys(out))


def drop_dismissed(findings: list[Finding], fingerprints: list[str]) -> list[Finding]:
    known = set(fingerprints)
    if not known:
        return findings
    kept: list[Finding] = []
    for item in findings:
        if fingerprint(item, bucket=1) in known or fingerprint(item, bucket=5) in known:
            continue
        kept.append(item)
    return kept


def load_dismissed(root: Path) -> list[str]:
    path = root / ".quality-reports" / DISMISSED_FILE
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    rows = data.get("fingerprints") if isinstance(data, dict) else data
    if not isinstance(rows, list):
        return []
    return [str(item) for item in rows if str(item).strip()]


def save_dismissed(root: Path, fingerprints: list[str]) -> None:
    dest = root / ".quality-reports"
    dest.mkdir(parents=True, exist_ok=True)
    existing = load_dismissed(root)
    merged = list(dict.fromkeys([*existing, *fingerprints]))
    (dest / DISMISSED_FILE).write_text(
        json.dumps({"schema_version": "1.0.0", "fingerprints": merged}, indent=2)
        + "\n",
        encoding="utf-8",
    )


def save_comments_report(root: Path, findings: list[Finding]) -> None:
    from quality_gates.review.contract import finding_payload

    dest = root / ".quality-reports"
    dest.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": "1.0.0",
        "pr": os.environ.get("QUALITY_PR_NUMBER") or pr_number(),
        "unresolved": [finding_payload(item) for item in findings],
    }
    (dest / COMMENTS_FILE).write_text(
        json.dumps(payload, indent=2) + "\n", encoding="utf-8"
    )


def load_comment_findings(root: Path) -> list[dict[str, Any]]:
    path = root / ".quality-reports" / COMMENTS_FILE
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    rows = data.get("unresolved") if isinstance(data, dict) else None
    if not isinstance(rows, list):
        return []
    return [item for item in rows if isinstance(item, dict)]


def sync_dismissed(root: Path) -> list[str]:
    threads = list_threads()
    marks = dismissed_fingerprints(threads)
    if marks:
        save_dismissed(root, marks)
    return marks


def _from_graphql(data: Any) -> list[ReviewThread]:
    nodes = (
        ((data or {}).get("data") or {})
        .get("repository", {})
        .get("pullRequest", {})
        .get("reviewThreads", {})
        .get("nodes")
        or []
    )
    threads: list[ReviewThread] = []
    if not isinstance(nodes, list):
        return []
    for node in nodes:
        if not isinstance(node, dict):
            continue
        comments = ((node.get("comments") or {}).get("nodes")) or []
        if not isinstance(comments, list) or not comments:
            continue
        first = comments[0] if isinstance(comments[0], dict) else {}
        bodies = [
            str(item.get("body") or "")
            for item in comments
            if isinstance(item, dict)
        ]
        body = "\n\n".join(part for part in bodies if part.strip())
        path = str(first.get("path") or "").strip() or None
        line = first.get("line") or first.get("originalLine")
        try:
            line_no = int(line) if line is not None else None
        except (TypeError, ValueError):
            line_no = None
        author = ""
        raw_author = first.get("author")
        if isinstance(raw_author, dict):
            author = str(raw_author.get("login") or "")
        suggestion = _extract_suggestion(body)
        rule = _extract_rule(body)
        if any(_FALSE_POSITIVE.search(part or "") for part in bodies[1:]):
            node["isResolved"] = True
        threads.append(
            ReviewThread(
                resolved=bool(node.get("isResolved")),
                outdated=bool(node.get("isOutdated")),
                path=path,
                line=line_no,
                body=body,
                url=str(first.get("url") or ""),
                author=author,
                suggestion=suggestion,
                rule=rule,
            )
        )
    return threads


def _graphql_ok(data: Any) -> bool:
    return isinstance(data, dict) and "data" in data and not data.get("errors")


def _from_rest(token: str, repo: str, pr: str) -> list[ReviewThread]:
    status, data = _request(
        "GET",
        f"https://api.github.com/repos/{repo}/pulls/{pr}/comments",
        token,
    )
    if not (200 <= status < 300) or not isinstance(data, list):
        return []
    threads: list[ReviewThread] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        body = str(item.get("body") or "")
        path = str(item.get("path") or "").strip() or None
        line = item.get("line") or item.get("original_line")
        try:
            line_no = int(line) if line is not None else None
        except (TypeError, ValueError):
            line_no = None
        user = item.get("user") if isinstance(item.get("user"), dict) else {}
        threads.append(
            ReviewThread(
                resolved=False,
                outdated=str(item.get("position") or "") in {"", "None"}
                and item.get("line") is None,
                path=path,
                line=line_no,
                body=body,
                url=str(item.get("html_url") or ""),
                author=str(user.get("login") or ""),
                suggestion=_extract_suggestion(body),
                rule=_extract_rule(body),
            )
        )
    return [item for item in threads if item.body.strip()]


def _extract_suggestion(body: str) -> str | None:
    match = _SUGGESTION.search(body or "")
    if not match:
        return None
    text = match.group(1).strip("\n")
    return text or None


def _extract_rule(body: str) -> str | None:
    match = _SHERIFF_RULE.search(body or "")
    if not match:
        return None
    return match.group("rule").strip() or None


def _suggestion_patch(path: str | None, suggestion: str | None) -> str | None:
    if not suggestion:
        return None
    return f"```suggestion\n{suggestion}\n```"


def _summary(body: str) -> str:
    text = _SUGGESTION.sub("", body or "").strip()
    first = text.splitlines()[0].strip() if text else "unresolved review comment"
    return first[:400]
