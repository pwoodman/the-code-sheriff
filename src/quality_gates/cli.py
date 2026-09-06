from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections.abc import Sequence
from pathlib import Path

from quality_gates import GATES, __version__
from quality_gates.change_manifest import discover_changes
from quality_gates.ci_plan import select_change_gates, select_gates, unknown_gates
from quality_gates.config import QualityConfig, is_pr_event, load_config
from quality_gates.decision import evaluate
from quality_gates.detect import detect_languages
from quality_gates.evidence import attach_evidence
from quality_gates.gates.advanced import run_advanced
from quality_gates.gates.audit import run_audit
from quality_gates.gates.compile import run_compile
from quality_gates.gates.contract import run_contract
from quality_gates.gates.coverage import run_coverage
from quality_gates.gates.dry import run_dry
from quality_gates.gates.format import run_format
from quality_gates.gates.impact import run_impact
from quality_gates.gates.lint import run_lint
from quality_gates.gates.review import run_review
from quality_gates.gates.security import run_security
from quality_gates.gates.test import run_tests
from quality_gates.gates.ui import run_ui
from quality_gates.gates.version import apply_bump, run_version
from quality_gates.installers import (
    ensure_checkstyle,
    ensure_gitleaks,
    ensure_golangci_lint,
    ensure_google_java_format,
    ensure_node_tooling,
    ensure_osv_scanner,
    write_github_path,
)
from quality_gates.models import GateResult
from quality_gates.paths import cache_dir, project_root
from quality_gates.planner import build_plan, render_plan, write_plan
from quality_gates.policy import apply_policy, maybe_comment_pr, write_baseline
from quality_gates.registry import canonical_name
from quality_gates.report import (
    build_digest,
    emit_annotations,
    load_results,
    render_console,
    render_html,
    render_junit,
    render_markdown,
    render_sarif,
    write_reports,
)
from quality_gates.result_cache import cache_status, clean_cache
from quality_gates.tool_manifest import load_tool_manifest, platform_id
from quality_gates.tools import tool_version, which

INIT_WORKFLOW = """name: Quality gates

on:
  pull_request:
  push:
    branches: [main]
  workflow_dispatch:

permissions:
  contents: read
  pull-requests: write
  checks: write
  security-events: write

jobs:
  quality:
    # Replace with a reviewed 40-character commit SHA from pwoodman/poly-check.
    uses: pwoodman/poly-check/.github/workflows/quality.yml@REPLACE_FULL_COMMIT_SHA
    secrets: inherit
"""

INIT_LOCAL = """name: Quality gates (vendored CLI)

on:
  pull_request:
  push:
    branches: [main]
  workflow_dispatch:

permissions:
  contents: read
  pull-requests: write
  checks: write

jobs:
  quality:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@11d5960a326750d5838078e36cf38b85af677262
        with:
          fetch-depth: 0
      - uses: actions/setup-python@a26af69be951a213d495a4c3e4e4022e16d87065
        with:
          python-version: "3.12"
      - name: Install quality-gates
        run: pip install "git+https://github.com/pwoodman/poly-check.git@v1"
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
    cache_p = sub.add_parser("cache", help="inspect or clean deterministic results")
    cache_p.add_argument(
        "action", choices=["status", "clean"], nargs="?", default="status"
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
        "--post",
        action="store_true",
        help="post inline review comments and a check run",
    )

    eval_p = sub.add_parser(
        "eval",
        help="ReviewBench scorecard; optional Martian / Macroscope comparison",
    )
    eval_p.add_argument(
        "--suite",
        dest="eval_suite",
        choices=["reviewbench", "martian", "macroscope", "all"],
        default="reviewbench",
    )
    eval_p.add_argument(
        "--download",
        action="store_true",
        help="fetch Martian golden comments (MIT) into .quality-reports/eval",
    )
    eval_p.add_argument(
        "--llm",
        action="store_true",
        help="require a live LLM (QUALITY_REVIEW_EVAL / provider key)",
    )

    oracle_p = sub.add_parser(
        "oracle",
        help="remaining blockers for coding agents (loop until green)",
    )
    oracle_p.add_argument(
        "--run",
        action="store_true",
        help="run gates first, then report what is still blocking",
    )
    oracle_p.add_argument(
        "--prompt",
        action="store_true",
        help="print a fix-it prompt instead of JSON",
    )
    oracle_p.add_argument("--only", default=None, help="comma-separated gates")
    oracle_p.add_argument("--skip", default=None, help="comma-separated gates")
    oracle_p.add_argument("--full", action="store_true")
    oracle_p.add_argument("--base", default=None)

    sub.add_parser(
        "mcp",
        help="MCP stdio server: quality_oracle, quality_run, quality_review, quality_finding_context, quality_apply_fix",
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
        help="test coverage vs configurable floor (default 80%% lines)",
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
    run_p.add_argument(
        "--plan", action="store_true", help="show selected execution without running it"
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

    report_p = sub.add_parser(
        "report",
        help="reprint the last run: scorecard, performance, issues, recommendations",
    )
    report_p.add_argument(
        "--format",
        dest="report_format",
        choices=["console", "markdown", "html", "json", "sarif", "junit"],
        default="console",
        help="console (default), markdown, html, or json",
    )

    args = parser.parse_args(argv)
    root = project_root(args.root)
    os.chdir(root)
    config = load_config(root)
    if args.policy:
        config.policy = args.policy

    if args.command == "init":
        return _init(root, args.org, policy=args.init_policy)
    if args.command == "mcp":
        from quality_gates.mcp_server import serve

        return serve()
    if args.command == "oracle":
        return _oracle(root, args)
    if args.command == "eval":
        return _eval(root, args)
    if args.command == "baseline":
        return _baseline(root, config, ratchet=args.ratchet)
    if args.command == "report":
        return _print_report(root, fmt=args.report_format, as_json=args.json)
    if args.command == "doctor":
        return _doctor(root, config, install=args.install, as_json=args.json)
    if args.command == "cache":
        payload = clean_cache() if args.action == "clean" else cache_status()
        if args.json:
            print(json.dumps(payload, indent=2))
        else:
            verb = "removed" if args.action == "clean" else "contains"
            print(
                f"cache {payload['path']} {verb} {payload['entries']} entries "
                f"({payload['bytes']} bytes)"
            )
        return 0
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
        only = _csv(args.only) or None
        skip = _csv(args.skip)
        bad = unknown_gates(only) + unknown_gates(skip)
        if bad:
            print(
                "unknown gate(s): "
                + ", ".join(dict.fromkeys(bad))
                + ". Choose from: "
                + ", ".join(GATES),
                file=sys.stderr,
            )
            return 2
        gates = select_gates(
            config,
            only=only,
            skip=skip,
            full=args.full,
        )
        if not args.only and not args.full:
            print(f"ci.mode={config.ci_mode} · gates: {', '.join(gates)}")
        manifest = discover_changes(root, args.base) if args.changed else None
        if manifest is not None and manifest.state == "unknown":
            print(f"change discovery failed: {manifest.reason}", file=sys.stderr)
            return 2
        if manifest is not None:
            manifest.write(root)
            gates = select_change_gates(gates, manifest.paths)
        changed = (
            [
                (root / path).resolve()
                for path in manifest.paths
                if (root / path).is_file()
            ]
            if manifest is not None
            else None
        )
        plan = build_plan(gates, config, manifest)
        write_plan(root, plan)
        if args.plan:
            if args.json:
                print(json.dumps({"plan": [item.to_dict() for item in plan]}, indent=2))
            else:
                print(render_plan(plan))
            return 0
        languages = _resolve_languages(root, config, args.languages, changed)
        results = []
        prior = []
        for gate in gates:
            started = time.perf_counter()
            if gate == "format":
                item = run_format(root, config, languages, check=True, scope=changed)
            elif gate == "lint":
                item = run_lint(root, config, languages, scope=changed)
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
                    security.duration_ms = max(
                        0, int((time.perf_counter() - started) * 1000)
                    )
                    results.append(security)
                    prior.append(security)
                    started = time.perf_counter()
                if not config.compile_require_security and security is None:
                    from quality_gates.models import GateResult as GR

                    security = GR(name="security", status="pass")
                item = run_compile(root, config, languages, security=security)
            elif gate == "contract":
                item = run_contract(root, config, base=args.base)
            elif gate == "version":
                item = run_version(root, config, base=args.base, manifest=manifest)
            elif gate == "impact":
                item = run_impact(root, config, base=args.base)
            elif gate == "test":
                item = run_tests(root, config)
            elif gate == "coverage":
                item = run_coverage(
                    root,
                    config,
                    manifest=manifest,
                    selection=manifest.paths if manifest else None,
                )
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
                    manifest=manifest,
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
                    manifest=manifest,
                )
            elif gate in {
                "migration",
                "authorization",
                "resilience",
                "mutation",
                "performance",
            }:
                item = run_advanced(
                    root, config, gate, manifest.paths if manifest else []
                )
            else:
                continue
            item.duration_ms = max(0, int((time.perf_counter() - started) * 1000))
            plan_item = next((entry for entry in plan if entry.name == gate), None)
            selection = list(plan_item.inputs) if plan_item else []
            attach_evidence(item, root, config, manifest=manifest, selection=selection)
            results.append(item)
            prior.append(item)
        return _emit(
            results,
            root,
            config,
            args.json,
            [item.name for item in plan if item.required],
        )
    parser.error("unknown command")
    return 2


def _oracle(root: Path, args: argparse.Namespace) -> int:
    from quality_gates.oracle import remaining_from_reports, render_prompt

    if args.run:
        argv = ["--root", str(root), "run"]
        if args.only:
            argv.extend(["--only", args.only])
        if args.skip:
            argv.extend(["--skip", args.skip])
        if args.full:
            argv.append("--full")
        if getattr(args, "base", None):
            argv.extend(["--base", args.base])
        main(argv)
    payload = remaining_from_reports(root)
    if args.prompt:
        print(render_prompt(payload))
    else:
        print(json.dumps(payload, indent=2))
    return 0 if payload.get("green") else 1


def _eval(root: Path, args: argparse.Namespace) -> int:
    from quality_gates.review.bench import run_heuristic_suite
    from quality_gates.review.external_eval import (
        download_martian,
        llm_eval_enabled,
        macroscope_reconstructed,
    )

    suite = args.eval_suite
    payload: dict[str, object] = {}
    if suite in {"reviewbench", "all"}:
        payload["reviewbench"] = run_heuristic_suite()
    if suite in {"martian", "all"}:
        if args.download or suite == "martian":
            payload["martian"] = download_martian(root, force=args.download)
        else:
            payload["martian"] = {
                "skipped": "pass --download to fetch MIT golden comments",
                "url": "https://github.com/withmartian/code-review-benchmark",
            }
    if suite in {"macroscope", "all"}:
        payload["macroscope"] = macroscope_reconstructed()
    if args.llm and not llm_eval_enabled():
        payload["llm"] = {
            "skipped": True,
            "reason": "set QUALITY_REVIEW_EVAL=1 and ANTHROPIC_API_KEY or OPENAI_API_KEY",
        }
    print(json.dumps(payload, indent=2))
    bench = payload.get("reviewbench")
    if isinstance(bench, dict) and bench.get("failed"):
        return 1
    if args.llm and not llm_eval_enabled():
        return 2
    return 0


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
        return [canonical_name(item) or item for item in explicit]
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
    for result in results:
        if not result.evidence:
            attach_evidence(result, root, config)
    maybe_comment_pr(results, root, config, policy)
    emit_annotations(results)
    digest = build_digest(
        results, policy=policy, report_dir=root / ".quality-reports", root=root
    )
    write_reports(digest, root / ".quality-reports", policy=policy)
    if as_json:
        print(json.dumps(digest.to_dict(), indent=2))
    else:
        print(render_console(digest))
    # ``fail_on`` is the selected run's required contract for one-command and
    # CI execution. The evaluator also rejects failed scanners without findings.
    required = [item.name for item in results if item.name in fail_on]
    return 0 if evaluate(results, required).approved else 1


def _print_report(root: Path, *, fmt: str, as_json: bool) -> int:
    report_dir = root / ".quality-reports"
    results, policy = load_results(report_dir)
    if not results:
        print(
            "no .quality-reports/quality-report.json — run `quality run` first",
            file=sys.stderr,
        )
        return 2
    digest = build_digest(results, policy=policy, report_dir=report_dir)
    write_reports(digest, report_dir, policy=policy)
    if as_json or fmt == "json":
        print(json.dumps(digest.to_dict(), indent=2))
        return 0 if digest.verdict == "pass" else 1
    if fmt == "markdown":
        print(render_markdown(digest), end="")
    elif fmt == "html":
        print(render_html(digest), end="")
    elif fmt == "sarif":
        print(json.dumps(render_sarif(digest), indent=2))
    elif fmt == "junit":
        print(render_junit(digest), end="")
    else:
        print(render_console(digest))
    return 0 if digest.verdict == "pass" else 1


def _doctor(root: Path, config: QualityConfig, *, install: bool, as_json: bool) -> int:
    if install and config.offline:
        print(
            "doctor --install is unavailable while quality.offline=true",
            file=sys.stderr,
        )
        return 2
    if install:
        _install_all()
        write_github_path()
    detected = detect_languages(root, config)
    manifest = load_tool_manifest()
    language_set = set(detected["languages"])
    kind_set = set(detected["file_kinds"])
    required = set(config.required_tools)
    selected = [
        tool
        for tool in manifest.tools
        if language_set.intersection(tool.languages)
        or kind_set.intersection(tool.file_kinds)
        or required.intersection({tool.id})
        or set(tool.capabilities).intersection({"security", "dry"})
    ]
    rows: list[dict[str, object]] = []
    for tool in selected:
        path = next(
            (
                found
                for command in tool.commands
                if (
                    found := which(
                        command,
                        project=root,
                        prefer_project=config.prefer_project_tools,
                    )
                )
            ),
            None,
        )
        if path is None and tool.cache_path:
            cached = cache_dir() / tool.cache_path
            path = str(cached) if cached.is_file() else None
        command = tool.commands[0] if tool.commands else tool.id
        version = (
            tool_version(command, tool.version_args)
            if path and tool.commands
            else tool.version
            if path
            else None
        )
        rows.append(
            {
                "tool": tool.id,
                "path": path,
                "version": version,
                "ok": bool(path),
                "required": tool.id in required,
                "capabilities": list(tool.capabilities),
                "platform_supported": tool.supports_current_platform(),
                "auto_install_supported": tool.install_supported,
                "auto_install_reason": tool.install_reason,
            }
        )
    known = {tool.id for tool in selected}
    for tool_id in sorted(required - known):
        rows.append(
            {
                "tool": tool_id,
                "path": None,
                "version": None,
                "ok": False,
                "required": True,
                "capabilities": [],
                "platform_supported": False,
                "auto_install_supported": False,
                "auto_install_reason": "not present in the tool manifest",
            }
        )
    missing_required = [
        str(row["tool"]) for row in rows if row["required"] and not row["ok"]
    ]
    missing_optional = [
        str(row["tool"]) for row in rows if not row["required"] and not row["ok"]
    ]
    payload = {
        "platform": platform_id(),
        "cache": str(cache_dir()),
        "trust": config.trust,
        "offline": config.offline,
        "detected": detected,
        "tools": rows,
        "missing_required": missing_required,
        "missing_optional": missing_optional,
    }
    if as_json:
        print(json.dumps(payload, indent=2))
    else:
        print(f"project: {root}")
        print(
            f"platform: {payload['platform']} · trust: {config.trust} · "
            f"offline: {str(config.offline).lower()}"
        )
        print(f"cache: {payload['cache']}")
        width = max(len(row["tool"]) for row in rows)
        for row in rows:
            mark = "ok" if row["ok"] else "missing"
            requirement = "required" if row["required"] else "optional"
            extra = row["version"] or row["path"] or "not on PATH"
            print(f"  {row['tool']:<{width}}  {mark:<8}  {requirement:<8}  {extra}")
        print(
            "\nTip: quality doctor --install downloads gitleaks, osv-scanner, golangci-lint, and Java jars."
        )
    return 1 if missing_required else 0


def _install_all() -> None:
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
        except (OSError, RuntimeError) as exc:
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
github_gates = ["format", "lint", "impact", "audit", "version", "review"]

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


if __name__ == "__main__":
    raise SystemExit(main())
