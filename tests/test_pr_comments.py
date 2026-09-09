from __future__ import annotations

from pathlib import Path

from quality_gates.models import Finding
from quality_gates.oracle import remaining_from_reports, render_prompt
from quality_gates.pr_comments import (
    ReviewThread,
    _from_graphql,
    drop_dismissed,
    save_comments_report,
    unresolved_findings,
)
from quality_gates.review.parse import fingerprint


def _thread(**kwargs) -> ReviewThread:
    defaults = {
        "resolved": False,
        "outdated": False,
        "path": "src/app.py",
        "line": 4,
        "body": "Please fix this.\n\n```suggestion\nvalue = 2\n```",
        "url": "https://example.test/1",
        "author": "greptile-apps",
        "suggestion": "value = 2",
        "rule": None,
    }
    defaults.update(kwargs)
    return ReviewThread(**defaults)


def test_graphql_parse_extracts_suggestion_and_false_positive() -> None:
    data = {
        "data": {
            "repository": {
                "pullRequest": {
                    "reviewThreads": {
                        "nodes": [
                            {
                                "isResolved": False,
                                "isOutdated": False,
                                "comments": {
                                    "nodes": [
                                        {
                                            "body": (
                                                "**logic** (error)\n\n"
                                                "Use the other helper.\n\n"
                                                "```suggestion\nreturn other()\n```"
                                            ),
                                            "path": "src/app.py",
                                            "line": 12,
                                            "url": "https://example.test/t",
                                            "author": {"login": "greptile-apps"},
                                        }
                                    ]
                                },
                            },
                            {
                                "isResolved": False,
                                "isOutdated": False,
                                "comments": {
                                    "nodes": [
                                        {
                                            "body": "Looks unused.",
                                            "path": "src/old.py",
                                            "originalLine": 3,
                                            "url": "https://example.test/u",
                                            "author": {"login": "bot"},
                                        },
                                        {"body": "false positive — keep it"},
                                    ]
                                },
                            },
                        ]
                    }
                }
            }
        }
    }
    threads = _from_graphql(data)
    assert len(threads) == 2
    assert threads[0].suggestion == "return other()"
    assert threads[0].rule == "logic"
    assert threads[0].line == 12
    assert threads[1].resolved is True


def test_unresolved_findings_skip_resolved_and_outdated() -> None:
    findings = unresolved_findings(
        [
            _thread(),
            _thread(resolved=True, body="done", suggestion=None),
            _thread(outdated=True, body="stale", suggestion=None),
        ]
    )
    assert len(findings) == 1
    assert findings[0].gate == "comments"
    assert findings[0].patch is not None
    assert "suggestion" in findings[0].patch


def test_drop_dismissed_matches_review_fingerprints() -> None:
    finding = Finding(
        gate="review",
        rule="logic",
        path="src/app.py",
        line=4,
        message="bad",
    )
    marks = [fingerprint(finding, bucket=1)]
    kept = drop_dismissed(
        [finding, Finding(gate="review", rule="other", path="src/b.py", message="x")],
        marks,
    )
    assert [item.rule for item in kept] == ["other"]


def test_oracle_loads_cached_comments(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("GITHUB_REPOSITORY", raising=False)
    finding = Finding(
        gate="comments",
        rule="unresolved-review",
        path="src/app.py",
        line=4,
        message="Please fix this.",
        suggestion="value = 2",
        patch="```suggestion\nvalue = 2\n```",
        verify="quality comments",
    )
    save_comments_report(tmp_path, [finding])
    payload = remaining_from_reports(tmp_path)
    assert payload["green"] is False
    assert payload["comments"]
    assert payload["comments"][0]["id"]
    prompt = render_prompt(payload)
    assert "Unresolved PR review comments" in prompt
    assert "Please fix this." in prompt
