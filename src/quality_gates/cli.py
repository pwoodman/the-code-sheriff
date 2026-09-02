from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Sequence
from pathlib import Path

from quality_gates import __version__
from quality_gates.ci_plan import select_gates
from quality_gates.config import QualityConfig, is_pr_event, load_config
from quality_gates.detect import detect_languages, git_changed_files
from quality_gates.gates.audit import run_audit
from quality_gates.gates.compile import run_compile
from quality_gates.gates.coverage import run_coverage
from quality_gates.gates.dry import run_dry
from quality_gates.gates.format import run_format
from quality_gates.gates.impact import run_impact
from quality_gates.gates.lint import run_lint
from quality_gates.gates.review import run_review
from quality_gates.gates.security import run_security
from quality_gates.gates.ui import run_ui
from quality_gates.gates.version import apply_bump, run_version
from quality_gates.installers import (
    ensure_checkstyle,
    ensure_gitleaks,
    ensure_golangci_lint,
    ensure_google_java_format,
    ensure_node_tooling,
    ensure_osv_scanner,
    ensure_python_tools,
    ensure_sqlfluff,
    write_github_path,
)
from quality_gates.models import GateResult
from quality_gates.paths import project_root
from quality_gates.policy import apply_policy, maybe_comment_pr, write_baseline
from quality_gates.report import emit_annotations, render_console, write_reports
from quality_gates.tools import tool_version, which

INIT_WORKFLOW = """name: Quality gates

on:
  pull_request:
  push:
    branches: [main, master]
  workflow_dispatch:

permissions:
  contents: read
  pull-requests: write
  security-events: write

jobs:
  quality:
    uses: REPLACE_ORG/quality-gates/.github/workflows/quality.yml@v1
    secrets: inherit
"""

INIT_LOCAL = """name: Quality gates (vendored CLI)

on:
  pull_request:
  push:
    branches: [main, master]
  workflow_dispatch:

permissions:
  contents: read
  pull-requests: write

jobs:
  quality:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - name: Install quality-gates
        run: pip install "git+https://github.com/REPLACE_ORG/quality-gates.git@v1"
      - name: Run gates
        env:
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
        run: quality run
"""


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="quality",
        description="Multi-language format, lint, DRY, security, compile, impact, coverage, 120-point audit, UI, version, and AI review gates.",
    )
    parser.add_argument(
        "--version", action="version", version=f"quality-gates {__version__}"
    )
    parser.add_argument(
        "--root", type=Path, default=None, help="project root (default: cwd / git root)"
    )
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    parser.add_argument(
        "--policy",
        choices=["observe", "adopt", "enforce"],
        default=None,
        help="observe = report only; adopt = ratchet vs baseline; enforce = fail_on (default: quality.toml)",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("detect", help="list languages and toolchains in the project")
    doctor = sub.add_parser("doctor", help="show which tools are available")
    doctor.add_argument(
        "--install", action="store_true", help="download pinned CI binaries"
    )

    fmt = sub.add_parser("format", help="run formatters")
    fmt.add_argument("--check", action="store_true", default=True)
    fmt.add_argument(
        "--write", action="store_true", help="apply formatting instead of checking"
    )
    fmt.add_argument("--language", action="append", dest="languages")

    lint = sub.add_parser("lint", help="run linters")
    lint.add_argument("--language", action="append", dest="languages")

    sub.add_parser("dry", help="copy-paste / duplication scan")
    sub.add_parser("security", help="secrets, dependency CVEs, SAST")
    compile_p = sub.add_parser(
        "compile",
        help="build compiled languages (only after a clean security gate)",
    )
    compile_p.add_argument("--language", action="append", dest="languages")
    compile_p.add_argument(
        "--force",
        action="store_true",
        help="compile even if security has not passed (not recommended)",
    )
    version_p = sub.add_parser("version", help="semver consistency and required bumps")
    version_p.add_argument("--base", default=None)

    bump = sub.add_parser("bump", help="write a semver bump into version files")
    bump.add_argument(
        "part",
        choices=["auto", "major", "minor", "patch"],
        help="auto uses conventional commits since the base ref",
    )

    review = sub.add_parser("review", help="AI / heuristic code review")
    review.add_argument("--base", default=None, help="git ref to diff against")
    review.add_argument(
        "--post", action="store_true", help="post the review on the GitHub PR"
    )

    ui_p = sub.add_parser(
        "ui",
        help="selective Playwright/Cypress tests for files changed vs --base",
    )
    ui_p.add_argument(
        "--list",
        action="store_true",
        help="print which specs would run, without launching a browser",
    )
    ui_p.add_argument(
        "--all",
        action="store_true",
        help="run every spec instead of selecting from the diff",
    )
    ui_p.add_argument("--base", default=None, help="git ref to diff against")

    impact_p = sub.add_parser(
        "impact",
        help="upstream/downstream impact: who uses this change, and is it validated",
    )
    impact_p.add_argument("--base", default=None, help="git ref to diff against")

    sub.add_parser(
        "coverage",
        help="test coverage vs configurable floor (default 80% lines)",
    )
    sub.add_parser(
        "audit",
        help="120-point evidence-backed repo inspection (security, API, architecture)",
    )

    run_p = sub.add_parser("run", help="run selected gates in order")
    run_p.add_argument("--only", default=None, help="comma-separated gates")
    run_p.add_argument("--skip", default=None, help="comma-separated gates")
    run_p.add_argument("--base", default=None)
    run_p.add_argument("--post-review", action="store_true")
    run_p.add_argument(
        "--changed", action="store_true", help="only files changed vs --base"
    )
    run_p.add_argument("--language", action="append", dest="languages")
    run_p.add_argument(
        "--full",
        action="store_true",
        help="on GitHub Actions, run the heavy suite even when ci.mode=local",
    )

    init = sub.add_parser("init", help="write quality.toml and a starter workflow")
    init.add_argument(
        "--org", default="REPLACE_ORG", help="GitHub org/user that hosts quality-gates"
    )
    init.add_argument(
        "--policy",
        dest="init_policy",
        choices=["observe", "adopt", "enforce"],
        default="adopt",
        help="PR-blocking policy for the new repo (default adopt)",
    )

    baseline_p = sub.add_parser(
        "baseline",
        help="write .quality-baseline.json from the last run (grandfather current findings)",
    )
    baseline_p.add_argument(
        "--ratchet",
        action="store_true",
        help="merge with the existing baseline; raise coverage floor if it improved",
    )

    args = parser.parse_args(argv)
    root = project_root(args.root)
    os.chdir(root)
    config = load_config(root)
    if args.policy:
        config.policy = args.policy

    if args.command == "init":
        return _init(root, args.org, policy=args.init_policy)
    if args.command == "baseline":
        return _baseline(root, config, ratchet=args.ratchet)
    if args.command == "doctor":
        return _doctor(root, config, install=args.install, as_json=args.json)
    if args.command == "detect":
        info = detect_languages(root, config)
        return _print_detect(info, args.json)

    if args.command == "bump":
        try:
            new, written = apply_bump(root, config, args.part)
        except ValueError as exc:
            print(f"bump failed: {exc}", file=sys.stderr)
            return 1
        print(f"bumped to {new}")
        for path in written:
            print(f"  {path.relative_to(root)}")
        return 0

    languages = _resolve_languages(root, config, getattr(args, "languages", None), None)
    if args.command == "format":
        result = run_format(root, config, languages, check=not args.write)
        return _emit([result], root, config, args.json, ["format"])
    if args.command == "lint":
        result = run_lint(root, config, languages)
        return _emit([result], root, config, args.json, ["lint"])
    if args.command == "dry":
        result = run_dry(root, config, languages)
        return _emit([result], root, config, args.json, ["dry"])
    if args.command == "security":
        result = run_security(root, config, languages)
        return _emit([result], root, config, args.json, ["security"])
    if args.command == "compile":
        security = None
        if not args.force and config.compile_require_security:
            security = run_security(root, config, languages)
            results = [security]
            compile_result = run_compile(root, config, languages, security=security)
            results.append(compile_result)
            return _emit(results, root, config, args.json, ["security", "compile"])
        from quality_gates.models import GateResult as GR

        fake = GR(
            name="security", status="pass", notes=["--force or require_security=false"]
        )
        result = run_compile(root, config, languages, security=fake)
        return _emit([result], root, config, args.json, ["compile"])
    if args.command == "version":
        result = run_version(root, config, base=args.base)
        return _emit([result], root, config, args.json, ["version"])
    if args.command == "review":
        result = run_review(root, config, languages, base=args.base, post=args.post)
        return _emit([result], root, config, args.json, ["review"])
    if args.command == "ui":
        result = run_ui(
            root,
            config,
            base=args.base,
            force_all=args.all,
            list_only=args.list,
        )
        return _emit([result], root, config, args.json, ["ui"])
    if args.command == "impact":
        result = run_impact(root, config, base=args.base)
        return _emit([result], root, config, args.json, ["impact"])
    if args.command == "coverage":
        result = run_coverage(root, config)
        return _emit([result], root, config, args.json, ["coverage"])
    if args.command == "audit":
        result = run_audit(root, config)
        return _emit([result], root, config, args.json, ["audit"])
    if args.command == "run":
        gates = select_gates(
            config,
            only=_csv(args.only) or None,
            skip=_csv(args.skip),
            full=args.full,
        )
        if not args.only and not args.full:
            print(f"ci.mode={config.ci_mode} · gates: {', '.join(gates)}")
        changed = git_changed_files(root, args.base) if args.changed else None
        languages = _resolve_languages(root, config, args.languages, changed)
        results = []
        prior = []
        for gate in gates:
            if gate == "format":
                item = run_format(root, config, languages, check=True)
            elif gate == "lint":
                item = run_lint(root, config, languages)
            elif gate == "dry":
                item = run_dry(root, config, languages)
            elif gate == "security":
                item = run_security(root, config, languages)
            elif gate == "compile":
                security = next((row for row in prior if row.name == "security"), None)
                if (
                    security is None
                    and config.compile_require_security
                    and "security" not in gates
                ):
                    security = run_security(root, config, languages)
                    results.append(security)
                    prior.append(security)
                if not config.compile_require_security and security is None:
                    from quality_gates.models import GateResult as GR

                    security = GR(name="security", status="pass")
                item = run_compile(root, config, languages, security=security)
            elif gate == "version":
                item = run_version(root, config, base=args.base)
            elif gate == "impact":
                item = run_impact(root, config, base=args.base)
            elif gate == "coverage":
                item = run_coverage(root, config)
            elif gate == "audit":
                item = run_audit(root, config)
            elif gate == "ui":
                compile_prior = next(
                    (row for row in prior if row.name == "compile"), None
                )
                item = run_ui(
                    root,
                    config,
                    base=args.base,
                    compile_result=compile_prior,
                )
            elif gate == "review":
                post = args.post_review or (
                    is_pr_event() and config.ai_review != "never"
                )
                item = run_review(
                    root,
                    config,
                    languages,
                    base=args.base,
                    post=post,
                    prior=prior,
                )
            else:
                continue
            results.append(item)
            prior.append(item)
        return _emit(results, root, config, args.json, config.fail_on)
    parser.error("unknown command")
    return 2


def _csv(value: str | None) -> list[str]:
    if not value:
        return []
    return [part.strip() for part in value.split(",") if part.strip()]


def _resolve_languages(
    root: Path,
    config: QualityConfig,
    explicit: list[str] | None,
    files: list[Path] | None,
) -> list[str]:
    if explicit:
        return explicit
    return detect_languages(root, config, files)["languages"]


def _print_detect(info: dict[str, list[str]], as_json: bool) -> int:
    if as_json:
        print(json.dumps(info))
    else:
        langs = ", ".join(info["languages"]) or "(none)"
        tools = ", ".join(info["toolchains"]) or "(none)"
        print(f"languages:  {langs}")
        print(f"toolchains: {tools}")
    return 0


def _emit(
    results: list[GateResult],
    root: Path,
    config: QualityConfig,
    as_json: bool,
    fail_on: list[str],
) -> int:
    results, policy = apply_policy(results, root, config)
    maybe_comment_pr(results, root, config, policy)
    emit_annotations(results)
    write_reports(results, root / ".quality-reports")
    payload = {
        "policy": policy,
        "results": [item.to_dict() for item in results],
    }
    if as_json:
        print(json.dumps(payload, indent=2))
    else:
        print(f"Quality gates · policy={policy}")
        print(render_console(results))
        print("\nWrote .quality-reports/quality-report.md")
    failed = [
        item
        for item in results
        if item.status == "fail"
        and (item.name in fail_on or (item.name == "review" and "review" in fail_on))
    ]
    # skip does not fail
    return 1 if failed else 0


def _doctor(root: Path, config: QualityConfig, *, install: bool, as_json: bool) -> int:
    if install or config.should_auto_install():
        _install_all()
        write_github_path()
    rows = []
    checks = [
        ("python", "python3", ("--version",)),
        ("ruff", "ruff", ("--version",)),
        ("node", "node", ("--version",)),
        ("npm", "npm", ("--version",)),
        ("prettier", "prettier", ("--version",)),
        ("eslint", "eslint", ("--version",)),
        ("jscpd", "jscpd", ("--version",)),
        ("go", "go", ("version",)),
        ("gofmt", "gofmt", ()),
        ("golangci-lint", "golangci-lint", ("version",)),
        ("rustc", "rustc", ("--version",)),
        ("cargo", "cargo", ("--version",)),
        ("rustfmt", "rustfmt", ("--version",)),
        ("java", "java", ("-version",)),
        ("dotnet", "dotnet", ("--version",)),
        ("csharpier", "csharpier", ("--version",)),
        ("sqlfluff", "sqlfluff", ("--version",)),
        ("gitleaks", "gitleaks", ("version",)),
        ("osv-scanner", "osv-scanner", ("--version",)),
        ("semgrep", "semgrep", ("--version",)),
        ("playwright", "playwright", ("--version",)),
        ("cypress", "cypress", ("--version",)),
        ("coverage", "coverage", ("--version",)),
    ]
    for label, command, argv in checks:
        path = which(command, project=root, prefer_project=True)
        version = tool_version(command, argv or ("--version",)) if path else None
        rows.append(
            {
                "tool": label,
                "path": path,
                "version": version,
                "ok": bool(path),
            }
        )
    if as_json:
        print(json.dumps(rows, indent=2))
    else:
        print(f"project: {root}")
        width = max(len(row["tool"]) for row in rows)
        for row in rows:
            mark = "ok" if row["ok"] else "missing"
            extra = row["version"] or row["path"] or "not on PATH"
            print(f"  {row['tool']:<{width}}  {mark:<8}  {extra}")
        print(
            "\nTip: quality doctor --install downloads gitleaks, osv-scanner, golangci-lint, and Java jars."
        )
    return 0


def _install_all() -> None:
    ensure_python_tools()
    ensure_sqlfluff()
    ensure_node_tooling()
    for loader in (
        ensure_gitleaks,
        ensure_osv_scanner,
        ensure_golangci_lint,
        ensure_google_java_format,
        ensure_checkstyle,
    ):
        try:
            loader()
        except OSError as exc:
            print(f"warning: {loader.__name__} failed: {exc}", file=sys.stderr)


def _init(root: Path, org: str, *, policy: str = "adopt") -> int:
    config_path = root / "quality.toml"
    if not config_path.exists():
        config_path.write_text(_consumer_toml(policy), encoding="utf-8")
        print(f"wrote {config_path} (policy={policy})")
    else:
        print(f"kept existing {config_path}")
    workflow_dir = root / ".github" / "workflows"
    workflow_dir.mkdir(parents=True, exist_ok=True)
    reusable = workflow_dir / "quality.yml"
    if not reusable.exists():
        reusable.write_text(INIT_WORKFLOW.replace("REPLACE_ORG", org), encoding="utf-8")
        print(f"wrote {reusable}")
    local = workflow_dir / "quality-cli.yml"
    if not local.exists():
        local.write_text(INIT_LOCAL.replace("REPLACE_ORG", org), encoding="utf-8")
        print(f"wrote {local} (CLI fallback)")
    print("Edit REPLACE_ORG if you used the default, then commit.")
    print(
        "Next: quality run --skip review && quality baseline && git add .quality-baseline.json"
    )
    return 0


def _baseline(root: Path, config: QualityConfig, *, ratchet: bool) -> int:
    report = root / ".quality-reports" / "quality-report.json"
    if not report.is_file():
        print(
            "no .quality-reports/quality-report.json — running coverage + audit first"
        )
        results = [run_coverage(root, config), run_audit(root, config)]
        write_reports(results, root / ".quality-reports")
    path = write_baseline(root, config, ratchet=ratchet)
    print(f"wrote {path.relative_to(root)}" + (" (ratchet)" if ratchet else ""))
    print("Commit this file so PRs fail only on new issues, not the existing backlog.")
    return 0


def _consumer_toml(policy: str) -> str:
    return f"""[quality]
languages = ["auto"]
# observe  = never block PRs (still comments + warnings)
# adopt    = fail only on NEW issues vs .quality-baseline.json (recommended for old repos)
# enforce  = fail_on list blocks the job
policy = "{policy}"
baseline = ".quality-baseline.json"
comment_on_pr = true
fail_on = ["format", "lint", "dry", "security", "compile", "impact", "coverage", "audit", "ui", "version"]
ai_review = "pr-only"

[quality.ci]
mode = "local"
github_gates = ["impact", "audit", "version", "review"]

[quality.compile]
require_security = true

[quality.coverage]
line = 80
branch = 0
tool = "auto"

[quality.audit]
fail_on_priority = ["P0"]
min_confidence = "HIGH"

[quality.ui]
select = "changed"
on_github = false

[quality.impact]
depth = 4
require_downstream = true

[quality.version]
require_changelog = "if-present"
"""


def _default_toml() -> str:
    return _consumer_toml("adopt")


if __name__ == "__main__":
    raise SystemExit(main())
