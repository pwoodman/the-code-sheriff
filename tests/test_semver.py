from __future__ import annotations

from quality_gates.semver import parse_semver, suggest_bump


def test_parse_and_order() -> None:
    assert parse_semver("1.2.3") < parse_semver("1.3.0")
    assert parse_semver("not-a-version") is None
    assert str(parse_semver("2.0.0").bump("minor")) == "2.1.0"
    assert str(parse_semver("2.1.4").bump("major")) == "3.0.0"


def test_conventional_commit_suggestions() -> None:
    assert suggest_bump(["docs: readme"]) == "none"
    assert suggest_bump(["fix: nil pointer"]) == "patch"
    assert suggest_bump(["feat: compile gate"]) == "minor"
    assert suggest_bump(["feat!: drop python 3.10"]) == "major"
    assert suggest_bump(["feat: x", "BREAKING CHANGE: y"]) == "major"
