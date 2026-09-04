"""Turn raw tool findings into what / where / why / fix pointers."""

from __future__ import annotations

import shlex
from pathlib import Path

from quality_gates.models import Finding, RunResult

_RULE_HELP: dict[tuple[str, str], tuple[str, str, str]] = {
    (
        "yamllint",
        "document-start",
    ): (
        "yamllint expects a YAML document start marker.",
        "Add `---` as the first line, or disable the rule for GitHub workflow files.",
        "https://yamllint.readthedocs.io/en/stable/rules.html#module-yamllint.rules.document_start",
    ),
    (
        "yamllint",
        "line-length",
    ): (
        "yamllint's default maximum line length is 80 characters.",
        "Wrap the line, move long values onto the next line, or add "
        "`# yamllint disable-line rule:line-length`.",
        "https://yamllint.readthedocs.io/en/stable/rules.html#module-yamllint.rules.line_length",
    ),
    (
        "yamllint",
        "truthy",
    ): (
        "YAML 1.1 treats on/off/yes/no as booleans, which breaks GitHub `on:` keys.",
        'Quote the key (`"on":`) or add `# yamllint disable-line rule:truthy`.',
        "https://yamllint.readthedocs.io/en/stable/rules.html#module-yamllint.rules.truthy",
    ),
    (
        "yamllint",
        "comments",
    ): (
        "yamllint wants two spaces before an inline comment.",
        "Insert a space so the comment is `  # note` rather than ` # note`.",
        "https://yamllint.readthedocs.io/en/stable/rules.html#module-yamllint.rules.comments",
    ),
    (
        "yamllint",
        "indentation",
    ): (
        "The YAML indentation does not match the configured indent width.",
        "Re-indent with two spaces, or match the indent used in the rest of the file.",
        "https://yamllint.readthedocs.io/en/stable/rules.html#module-yamllint.rules.indentation",
    ),
    (
        "version",
        "consistent",
    ): (
        "Multiple version files declare different numbers.",
        "Set every version file to the same semver, or run `quality bump auto`.",
        "",
    ),
    (
        "version",
        "semver",
    ): (
        "The declared version is not MAJOR.MINOR.PATCH.",
        "Change it to a numeric semver such as 1.2.3.",
        "",
    ),
    (
        "version",
        "must-increase",
    ): (
        "Source changed but the declared package version is not higher than the base branch.",
        "Run `quality bump auto` (or major/minor/patch) and mention the new version in CHANGELOG.md.",
        "",
    ),
    (
        "version",
        "bump-required",
    ): (
        "Source files changed without a matching version-file edit.",
        "Run `quality bump auto` so consumers can tell this release apart from the previous one.",
        "",
    ),
    (
        "version",
        "changelog",
    ): (
        "The changelog policy requires the new version to be mentioned in CHANGELOG.md.",
        "Add a `## x.y.z` section describing the change.",
        "",
    ),
    (
        "ruff",
        "F401",
    ): (
        "An import is never used in this module.",
        "Remove the import, or add `# noqa: F401` if it is imported for a side effect.",
        "https://docs.astral.sh/ruff/rules/unused-import/",
    ),
}


def enrich_finding(
    finding: Finding,
    root: Path | None = None,
    result: RunResult | None = None,
) -> Finding:
    """Fill relative path, snippet, reason, suggestion, and docs when missing."""
    finding.path = _relative_path(finding.path, root)
    finding.snippet = finding.snippet or _snippet(finding.path, finding.line, root)
    why, fix, docs = _rule_help(finding)
    if not finding.reason:
        finding.reason = why or _generic_reason(finding, result)
    if not finding.suggestion:
        finding.suggestion = fix or _generic_suggestion(finding, result)
    if not finding.documentation_url:
        finding.documentation_url = docs or _docs_url(finding)
    if not finding.tool and result is not None:
        finding.tool = result.tool
    return finding


def enrich_findings(
    findings: list[Finding],
    root: Path | None = None,
    result: RunResult | None = None,
) -> list[Finding]:
    return [enrich_finding(item, root, result) for item in findings]


def pointer(finding: Finding) -> str:
    """Compact `path:line:column` pointer, or the rule/gate when no file is known."""
    loc = finding.path or finding.rule or finding.gate
    if finding.path and finding.line:
        loc = f"{finding.path}:{finding.line}"
        if finding.column:
            loc = f"{loc}:{finding.column}"
    return loc


def _relative_path(path: str | None, root: Path | None) -> str | None:
    if not path:
        return path
    candidate = Path(path)
    if root is not None:
        try:
            return candidate.resolve().relative_to(root.resolve()).as_posix()
        except (OSError, ValueError):
            pass
    return candidate.as_posix()


def _snippet(path: str | None, line: int | None, root: Path | None) -> str | None:
    if not path or not line or line < 1:
        return None
    candidate = Path(path)
    if not candidate.is_file() and root is not None:
        candidate = root / path
    if not candidate.is_file():
        return None
    try:
        text = candidate.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return None
    lines = text.splitlines()
    if line > len(lines):
        return None
    body = lines[line - 1].rstrip()
    if len(body) > 160:
        body = body[:157] + "..."
    return f"{line} | {body}"


def _rule_help(finding: Finding) -> tuple[str | None, str | None, str | None]:
    rule = (finding.rule or "").strip()
    if not rule:
        return None, None, None
    tool = (finding.tool or "").strip().lower()
    gate = (finding.gate or "").strip().lower()
    for key in ((tool, rule), (gate, rule), ("", rule)):
        if key in _RULE_HELP:
            why, fix, docs = _RULE_HELP[key]
            return why, fix, docs or None
    return None, None, None


def _docs_url(finding: Finding) -> str | None:
    rule = finding.rule
    if not rule:
        return None
    tool = (finding.tool or "").lower()
    if (
        tool in {"ruff", ""}
        and len(rule) >= 2
        and rule[0].isalpha()
        and rule[1:].isdigit()
    ):
        return f"https://docs.astral.sh/ruff/rules/{rule.lower()}/"
    if tool == "eslint" or (finding.language == "javascript" and "/" not in rule):
        if rule.startswith("http"):
            return rule
        return f"https://eslint.org/docs/latest/rules/{rule}"
    return None


def _generic_reason(finding: Finding, result: RunResult | None) -> str | None:
    if finding.rule:
        return f"{finding.tool or finding.gate} reported `{finding.rule}`"
    if result is not None and result.returncode not in {0, None}:
        name = result.tool or finding.tool or "command"
        return f"{name} exited with code {result.returncode}"
    return None


def _generic_suggestion(finding: Finding, result: RunResult | None) -> str | None:
    loc = pointer(finding)
    if finding.path:
        return f"Open `{loc}` and apply the {finding.tool or finding.gate} finding, then re-run `quality {finding.gate}`."
    if result is not None and result.argv:
        return f"Re-run `{shlex.join(result.argv)}` from `{result.cwd or '.'}`."
    return f"Re-run `quality {finding.gate}` after fixing the reported issue."


def detail_lines(finding: Finding) -> list[str]:
    """Console-oriented why / where / fix lines for a finding."""
    lines: list[str] = []
    if finding.snippet:
        lines.append(f"where: {finding.snippet}")
    if finding.reason:
        lines.append(f"why: {finding.reason}")
    if finding.suggestion:
        lines.append(f"fix: {finding.suggestion}")
    if finding.documentation_url:
        lines.append(f"docs: {finding.documentation_url}")
    return lines
