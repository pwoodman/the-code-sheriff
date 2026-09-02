from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from pathlib import Path

from quality_gates.config import QualityConfig, is_pr_event
from quality_gates.gates.common import skip_result
from quality_gates.models import Finding, GateResult
from quality_gates.tools import run

DANGEROUS = [
    (re.compile(r"\beval\s*\("), "eval() on untrusted input is a code-injection risk"),
    (re.compile(r"new Function\s*\("), "new Function() is eval in disguise"),
    (re.compile(r"innerHTML\s*="), "innerHTML assignment is a common XSS sink"),
    (re.compile(r"document\.write\s*\("), "document.write is an XSS sink"),
    (re.compile(r"pickle\.loads\s*\("), "pickle.loads can execute arbitrary objects"),
    (re.compile(r"yaml\.load\s*\("), "yaml.load without SafeLoader can execute code"),
    (
        re.compile(r"shell\s*=\s*True"),
        "subprocess shell=True is command-injection-prone",
    ),
    (re.compile(r"verify\s*=\s*False"), "TLS verification disabled"),
    (re.compile(r"md5\s*\("), "MD5 is not suitable for security-sensitive hashing"),
    (
        re.compile(r"SELECT\s+.+\s*\+\s*", re.I),
        "string-concatenated SQL is an injection risk",
    ),
    (
        re.compile(r"Runtime\.getRuntime\(\)\.exec"),
        "Runtime.exec with user input is command injection",
    ),
    (
        re.compile(r"dangerouslySetInnerHTML"),
        "dangerouslySetInnerHTML bypasses React XSS protections",
    ),
]

TODO_RE = re.compile(r"\b(TODO|FIXME|HACK|XXX)\b")
TEST_HINT = re.compile(r"(test|spec|__tests__)", re.I)

STANDARDS_BRIEF = """
Formatting standards this repo enforces:
- C#: csharpier, 4 spaces, ~120 columns, Allman braces, file-scoped namespaces preferred
- JavaScript/TypeScript/React: Prettier 2 spaces, double quotes, trailing commas; ESLint recommended + react-hooks + jsx-a11y
- Rust: rustfmt defaults, clippy -D warnings
- Go: gofmt (tabs), golangci-lint (govet/staticcheck/errcheck)
- Python: ruff format/check, 88 columns, double quotes
- Java: Google Java Format + Checkstyle Google-style (2 spaces, 100 columns)
- SQL: SQLFluff, uppercase keywords, 4-space indent, explicit aliases
Review for correctness, DRY, error handling, tests, and security (injection, secrets, authz, unsafe APIs).
""".strip()


def run_review(
    root: Path,
    config: QualityConfig,
    languages: list[str],
    *,
    base: str | None,
    post: bool,
    prior: list[GateResult] | None = None,
) -> GateResult:
    if config.ai_review == "never":
        return skip_result("review", "ai_review = never")
    if config.ai_review == "pr-only" and not is_pr_event() and not base:
        return skip_result(
            "review",
            "AI review runs on pull requests (set ai_review = always to override)",
        )

    diff = _collect_diff(root, base, config.max_diff_bytes)
    if not diff.strip():
        return skip_result("review", "no diff against the review base")

    heuristic = _heuristic_review(diff, languages, prior or [])
    llm_text, provider = _maybe_llm(config, diff, heuristic, languages)

    body = _render_review(heuristic, llm_text, provider, languages)
    notes = [f"provider: {provider}"]
    report_dir = root / ".quality-reports"
    report_dir.mkdir(parents=True, exist_ok=True)
    (report_dir / "review.md").write_text(body, encoding="utf-8")
    notes.append("wrote .quality-reports/review.md")
    if post:
        notes.append(_post_github(body))

    findings = list(heuristic)
    # Review comments should not fail the job unless fail_on includes review.
    return GateResult(name="review", status="pass", findings=findings, notes=notes)


def _collect_diff(root: Path, base: str | None, limit: int) -> str:
    base_ref = base or os.environ.get("QUALITY_REVIEW_BASE") or _default_base()
    if not base_ref:
        result = run(["git", "diff", "HEAD~1"], cwd=root)
        text = result.stdout
    else:
        result = run(
            ["git", "diff", "--diff-filter=ACMRTUXB", f"{base_ref}...HEAD"], cwd=root
        )
        text = result.stdout
        if result.returncode != 0 or not text.strip():
            result = run(["git", "diff", base_ref], cwd=root)
            text = result.stdout
    if len(text) > limit:
        text = text[:limit] + "\n\n[diff truncated]\n"
    return text


def _default_base() -> str | None:
    base = os.environ.get("GITHUB_BASE_REF")
    if base:
        return f"origin/{base}"
    return None


def _heuristic_review(
    diff: str,
    languages: list[str],
    prior: list[GateResult],
) -> list[Finding]:
    findings: list[Finding] = []
    current_file = None
    added_by_file: dict[str, int] = {}
    added_lines_total = 0
    test_files_touched = False
    src_files_touched = False

    new_file_line = 0
    for raw in diff.splitlines():
        if raw.startswith("+++ b/"):
            current_file = raw[6:]
            if current_file == "/dev/null":
                current_file = None
            continue
        if raw.startswith("@@"):
            match = re.search(r"\+(\d+)", raw)
            new_file_line = int(match.group(1)) if match else 0
            continue
        if raw.startswith("+") and not raw.startswith("+++"):
            added_lines_total += 1
            if current_file:
                added_by_file[current_file] = added_by_file.get(current_file, 0) + 1
                name = current_file
                if TEST_HINT.search(name):
                    test_files_touched = True
                elif name.endswith(
                    (
                        ".py",
                        ".js",
                        ".ts",
                        ".tsx",
                        ".jsx",
                        ".go",
                        ".rs",
                        ".java",
                        ".cs",
                        ".sql",
                    )
                ):
                    src_files_touched = True
                text = raw[1:]
                if TODO_RE.search(text):
                    findings.append(
                        Finding(
                            gate="review",
                            severity="info",
                            path=current_file,
                            line=new_file_line,
                            rule="todo",
                            message="TODO/FIXME introduced in this change — track or resolve before merge",
                        )
                    )
                for pattern, message in DANGEROUS:
                    if pattern.search(text):
                        findings.append(
                            Finding(
                                gate="review",
                                severity="error",
                                path=current_file,
                                line=new_file_line,
                                rule="unsafe-api",
                                message=message,
                            )
                        )
            new_file_line += 1
        elif raw.startswith(" ") and not raw.startswith("+++"):
            new_file_line += 1

    for path, count in added_by_file.items():
        if count >= 400:
            findings.append(
                Finding(
                    gate="review",
                    severity="warning",
                    path=path,
                    rule="large-file",
                    message=f"{count} lines added in one file — consider splitting the change",
                )
            )

    if added_lines_total >= 800:
        findings.append(
            Finding(
                gate="review",
                severity="warning",
                rule="large-pr",
                message=f"diff adds {added_lines_total} lines — large PRs hide bugs; split if possible",
            )
        )

    if src_files_touched and not test_files_touched:
        findings.append(
            Finding(
                gate="review",
                severity="warning",
                rule="missing-tests",
                message="source changed without an accompanying test file — add coverage for the new behavior",
            )
        )

    for result in prior:
        if result.name == "dry" and result.findings:
            findings.append(
                Finding(
                    gate="review",
                    severity="warning",
                    rule="dry",
                    message=f"DRY gate found {len(result.findings)} cloned block(s) in this change set",
                )
            )
        if result.name == "security":
            errors = result.error_count()
            if errors:
                findings.append(
                    Finding(
                        gate="review",
                        severity="error",
                        rule="security-gate",
                        message=f"security gate reported {errors} error(s) — treat as blocking",
                    )
                )

    if languages:
        findings.append(
            Finding(
                gate="review",
                severity="info",
                rule="languages",
                message="languages in this change: " + ", ".join(languages),
            )
        )
    return findings


def _maybe_llm(
    config: QualityConfig,
    diff: str,
    heuristic: list[Finding],
    languages: list[str],
) -> tuple[str | None, str]:
    provider = (config.review_provider or "auto").lower()
    if provider == "off":
        return None, "heuristic"

    openai_key = os.environ.get("OPENAI_API_KEY")
    anthropic_key = os.environ.get("ANTHROPIC_API_KEY")
    github_token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")

    if provider == "auto":
        if anthropic_key:
            provider = "anthropic"
        elif openai_key:
            provider = "openai"
        elif github_token and os.environ.get("GITHUB_ACTIONS") == "true":
            provider = "github-models"
        else:
            return None, "heuristic"

    prompt = _prompt(diff, heuristic, languages)
    try:
        if provider == "anthropic" and anthropic_key:
            model = config.review_model or os.environ.get(
                "ANTHROPIC_MODEL", "claude-sonnet-4-20250514"
            )
            text = _chat_anthropic(anthropic_key, model, prompt)
            return text, "anthropic"
        if provider == "openai" and openai_key:
            model = config.review_model or os.environ.get("OPENAI_MODEL", "gpt-4.1")
            text = _chat_openai_compat(
                "https://api.openai.com/v1/chat/completions",
                openai_key,
                model,
                prompt,
            )
            return text, "openai"
        if provider == "github-models" and github_token:
            model = config.review_model or os.environ.get(
                "GITHUB_MODELS_MODEL", "openai/gpt-4.1-mini"
            )
            text = _chat_openai_compat(
                "https://models.github.ai/inference/chat/completions",
                github_token,
                model,
                prompt,
            )
            return text, "github-models"
    except (
        urllib.error.URLError,
        TimeoutError,
        RuntimeError,
        json.JSONDecodeError,
    ) as exc:
        return (
            f"LLM review failed ({exc}); heuristic findings still apply.",
            "heuristic",
        )
    return None, "heuristic"


def _prompt(diff: str, heuristic: list[Finding], languages: list[str]) -> str:
    bullets = "\n".join(
        f"- [{item.severity}] {item.path or ''}:{item.line or ''} {item.message}"
        for item in heuristic
        if item.rule != "languages"
    )
    return f"""You are a senior engineer performing a high-signal code review.
Languages in this change: {", ".join(languages) or "unknown"}.
{STANDARDS_BRIEF}

Heuristic flags already raised:
{bullets or "- none"}

Write a concise review:
1. Summary (2-4 sentences)
2. Blocking issues (must fix)
3. Non-blocking suggestions
4. Security notes
5. Test gaps
Do not restate the entire diff. Skip style nits already covered by formatters/linters unless they slipped through.

Diff:
```
{diff}
```
"""


def _chat_openai_compat(url: str, token: str, model: str, prompt: str) -> str:
    payload = json.dumps(
        {
            "model": model,
            "temperature": 0.2,
            "messages": [
                {
                    "role": "system",
                    "content": "You are a precise software reviewer. Prefer concrete, file-referenced comments.",
                },
                {"role": "user", "content": prompt},
            ],
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=payload,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=90) as response:
        body = json.loads(response.read().decode("utf-8"))
    return body["choices"][0]["message"]["content"]


def _chat_anthropic(token: str, model: str, prompt: str) -> str:
    payload = json.dumps(
        {
            "model": model,
            "max_tokens": 1600,
            "temperature": 0.2,
            "messages": [{"role": "user", "content": prompt}],
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=payload,
        headers={
            "x-api-key": token,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=90) as response:
        body = json.loads(response.read().decode("utf-8"))
    parts = body.get("content") or []
    return "".join(part.get("text", "") for part in parts if part.get("type") == "text")


def _render_review(
    heuristic: list[Finding],
    llm_text: str | None,
    provider: str,
    languages: list[str],
) -> str:
    lines = [
        "## AI code review",
        "",
        f"Provider: `{provider}` · languages: `{', '.join(languages) or 'none'}`",
        "",
    ]
    if llm_text:
        lines.extend([llm_text.strip(), ""])
    blockers = [item for item in heuristic if item.severity == "error"]
    warnings = [item for item in heuristic if item.severity == "warning"]
    infos = [item for item in heuristic if item.severity == "info"]
    if blockers:
        lines.append("### Blocking (heuristic)")
        lines.append("")
        for item in blockers:
            lines.append(f"- {item.path or 'repo'}: {item.message}")
        lines.append("")
    if warnings:
        lines.append("### Please consider")
        lines.append("")
        for item in warnings:
            lines.append(f"- {item.path or 'repo'}: {item.message}")
        lines.append("")
    if infos and not llm_text:
        lines.append("### Notes")
        lines.append("")
        for item in infos:
            lines.append(f"- {item.message}")
        lines.append("")
    if not llm_text:
        lines.append(
            "_No LLM key configured. Set `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, "
            "or use GitHub Models on Actions for a full narrative review. "
            "Heuristic flags still run._"
        )
    return "\n".join(lines).strip() + "\n"


def _post_github(body: str) -> str:
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    repo = os.environ.get("GITHUB_REPOSITORY")
    pr = os.environ.get("QUALITY_PR_NUMBER") or _pr_number()
    if not token or not repo or not pr:
        return "skipped GitHub review comment (need GITHUB_TOKEN, GITHUB_REPOSITORY, pull request number)"
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
                return f"posted review comment on PR #{pr}"
            return f"GitHub comment returned HTTP {response.status}"
    except urllib.error.HTTPError as exc:
        return f"GitHub comment failed: HTTP {exc.code}"


def _pr_number() -> str | None:
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
