from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections.abc import Sequence
from pathlib import Path

from quality_gates import GATES, __version__
from quality_gates import gates as gate_runners
from quality_gates.change_manifest import discover_changes
from quality_gates.ci_plan import select_change_gates, select_gates, unknown_gates
from quality_gates.config import QualityConfig, is_pr_event, load_config
from quality_gates.decision import evaluate
from quality_gates.detect import detect_languages
from quality_gates.evidence import attach_evidence
from quality_gates.gates.version import apply_bump
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


def _invoked_as_sheriff(argv: Sequence[str] | None) -> bool:
    if argv is not None:
        return False
    name = Path(sys.argv[0]).name.lower().replace("_", "-")
    return name in {"codesheriff", "the-codesheriff"} or name.startswith("codesheriff")


def _add_onboard_args(
    parser: argparse.ArgumentParser,
    *,
    require_check: bool,
    hooks: bool = False,
    run: bool = False,
    agents: bool = False,
) -> None:
    parser.add_argument(
        "--org",
        default="",
        help="GitHub owner of a The Code Sheriff fork (default: pwoodman)",
    )
    parser.add_argument(
        "--source",
        default="",
        help="owner/repo that hosts the reusable workflow (default: pwoodman/the-code-sheriff)",
    )
    parser.add_argument(
        "--pin",
        default="auto",
        help="commit SHA or git ref to pin; auto resolves main",
    )
    parser.add_argument(
        "--policy",
        dest="init_policy",
        choices=["observe", "adopt", "enforce"],
        default="adopt",
        help="PR-blocking policy for the new repo (default adopt)",
    )
    parser.add_argument(
        "--vendor-cli",
        action="store_true",
        help="also write a pip-install workflow instead of only the reusable one",
    )
    parser.add_argument(
        "--require-check",
        action=argparse.BooleanOptionalAction,
        default=require_check,
        help="create a GitHub ruleset requiring The Code Sheriff",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="overwrite quality.toml and generated workflows",
    )
    parser.add_argument(
        "--hooks",
        action=argparse.BooleanOptionalAction,
        default=hooks,
        help="write .pre-commit-config.yaml and try pre-commit install",
    )
    parser.add_argument(
        "--run",
        action=argparse.BooleanOptionalAction,
        default=run,
        help="run gates once and write .quality-baseline.json",
    )
    parser.add_argument(
        "--agents",
        action=argparse.BooleanOptionalAction,
        default=agents,
        help="write Cursor/Claude MCP, rule, and skill so agents loop on quality oracle",
    )
    parser.add_argument(
        "--auto-merge",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="enable GitHub repo auto-merge so green Sheriff PRs can land",
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="codesheriff" if _invoked_as_sheriff(argv) else "quality",
        description="Multi-language format, lint, DRY, security, compile, impact, coverage, 120-point audit, UI, version, and AI review gates.",
    )
    parser.add_argument(
        "--version", action="version", version=f"The Code Sheriff {__version__}"
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

    regex_p = sub.add_parser("regex", help="regex checker over the change set")
    regex_p.add_argument("--base", default=None)
    packages_p = sub.add_parser(
        "packages",
        help="risky/undeclared packages from imports and new dependencies",
    )
    packages_p.add_argument("--base", default=None)

    sub.add_parser("dry", help="copy-paste / duplication scan")
    sub.add_parser(
        "security",
        help="secrets, SCA, SAST, IaC misconfig, SBOM (gitleaks/osv/semgrep/trivy/checkov)",
    )
    sbom_p = sub.add_parser(
        "sbom",
        help="write CycloneDX and SPDX SBOMs under .quality-reports",
    )
    sbom_p.add_argument(
        "--format",
        dest="sbom_format",
        choices=["all", "cyclonedx", "spdx"],
        default="all",
    )
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
        help=(
            "MCP stdio server: quality_oracle, quality_run, quality_review, "
            "quality_merge, quality_pr_comments, quality_finding_context, "
            "quality_apply_fix, quality_fix, quality_certify"
        ),
    )

    fix_p = sub.add_parser(
        "fix",
        help="safe auto-fixes: format --write, ruff --fix, finding patches",
    )
    fix_p.add_argument(
        "--no-patches",
        action="store_true",
        help="skip applying finding patches; only format/lint autofix",
    )

    sub.add_parser(
        "certify",
        help="print the merge certificate (auto-merge ready when green)",
    )

    apply_p = sub.add_parser(
        "apply",
        help="apply one finding patch by id from the last oracle report",
    )
    apply_p.add_argument("--id", dest="finding_id", default=None)

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

    merge_p = sub.add_parser(
        "merge",
        help=(
            "dry-merge vs the base branch: textual conflicts, optional "
            "sibling PRs, optional compile/impact verify"
        ),
    )
    merge_p.add_argument(
        "--base",
        default=None,
        help="git ref to merge into (default origin/main)",
    )
    merge_p.add_argument(
        "--verify",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="after a clean merge-tree, compile/impact the merged tree",
    )
    merge_p.add_argument(
        "--siblings",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="also merge-tree against other open PR heads",
    )

    comments_p = sub.add_parser(
        "comments",
        help=(
            "list unresolved GitHub review threads for the current PR "
            "(oracle remaining work)"
        ),
    )
    comments_p.add_argument(
        "--fail",
        action="store_true",
        help="exit 1 when unresolved threads remain (default: report only)",
    )

    sub.add_parser(
        "coverage",
        help="test coverage vs configurable floor (default 80%% lines)",
    )
    test_p = sub.add_parser(
        "test", help="run unit tests, require tests for source, track timing"
    )
    test_p.add_argument("--base", default=None)

    ignore_p = sub.add_parser(
        "ignore", help="override a finding (writes .quality/ignore.toml)"
    )
    ignore_p.add_argument("action", choices=["add"])
    ignore_p.add_argument("--rule", required=True)
    ignore_p.add_argument("--path", default=None)
    ignore_p.add_argument("--gate", default=None)
    ignore_p.add_argument("--reason", required=True)
    ignore_p.add_argument("--owner", default="")
    ignore_p.add_argument("--days", type=int, default=90)

    timing_p = sub.add_parser(
        "timing", help="accept a test duration baseline after a regression alert"
    )
    timing_p.add_argument("action", choices=["accept"])
    timing_p.add_argument("--test", action="append", dest="tests")
    timing_p.add_argument(
        "--all-regressed",
        action="store_true",
        help="accept every currently flagged timing regression",
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

    init = sub.add_parser(
        "init", help="write default quality.toml and a pinned The Code Sheriff workflow"
    )
    _add_onboard_args(init, require_check=False)
    setup = sub.add_parser(
        "setup",
        help="one command: defaults, workflow, hooks, required check, first baseline",
    )
    _add_onboard_args(setup, require_check=True, hooks=True, run=True, agents=True)
    setup.add_argument(
        "--app",
        action="store_true",
        help="also start GitHub App registration after writing files",
    )

    gh_app = sub.add_parser(
        "github-app",
        help="register The Code Sheriff GitHub App (runs on each repo's Actions minutes)",
    )
    gh_cmd = gh_app.add_subparsers(dest="app_command", required=True)
    manifest_p = gh_cmd.add_parser(
        "manifest", help="print the GitHub App manifest JSON"
    )
    manifest_p.add_argument("--name", default="The Code Sheriff")
    manifest_p.add_argument("--webhook-url", default="")
    manifest_p.add_argument("--redirect-url", default="")
    manifest_p.add_argument("--public", action="store_true")
    register = gh_cmd.add_parser(
        "register", help="create the App via GitHub's manifest flow"
    )
    register.add_argument("--host", default="127.0.0.1")
    register.add_argument("--port", type=int, default=8787)
    register.add_argument("--webhook-url", default="")
    register.add_argument("--org", default="", help="create under this GitHub org")
    register.add_argument("--name", default="The Code Sheriff")
    register.add_argument("--public", action="store_true")
    register.add_argument(
        "--no-open",
        action="store_true",
        help="do not open a browser for create/install",
    )
    register.add_argument(
        "--no-init",
        action="store_true",
        help="do not write quality.toml / workflow after the App is created",
    )
    serve = gh_cmd.add_parser(
        "serve", help="receive GitHub webhooks and dispatch Actions"
    )
    serve.add_argument("--host", default="0.0.0.0")
    serve.add_argument("--port", type=int, default=8787)
    handle = gh_cmd.add_parser(
        "handle", help="process one webhook payload from a file or stdin"
    )
    handle.add_argument("payload", nargs="?", default="-")
    handle.add_argument("--event", default="pull_request")
    handle.add_argument("--signature", default="")
    gh_cmd.add_parser(
        "prepare", help="verify a repository_dispatch payload in GitHub Actions"
    )
    check = gh_cmd.add_parser("check", help="create a check run on GITHUB_REPOSITORY")
    check.add_argument("--name", default="The Code Sheriff")
    check.add_argument(
        "--status",
        choices=["queued", "in_progress", "completed"],
        default="in_progress",
    )
    check.add_argument("--conclusion", default="")
    check.add_argument("--title", default="")
    check.add_argument("--summary", default="")
    token_p = gh_cmd.add_parser("token", help="mint an installation access token")
    token_p.add_argument("--installation-id", required=True)
    hook = gh_cmd.add_parser("webhook", help="set the GitHub App webhook URL")
    hook.add_argument("--url", required=True)

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
    report_p.add_argument(
        "--diff",
        dest="report_diff",
        nargs="?",
        const="history",
        default=None,
        help="show only findings new since the previous history entry or a git ref",
    )
    watch_p = sub.add_parser("watch", help="rerun cheap gates when files change")
    watch_p.add_argument(
        "--interval", type=float, default=1.5, help="poll interval in seconds"
    )

    args = parser.parse_args(argv)
    root = project_root(args.root)
    os.chdir(root)
    config = load_config(root)
    if args.policy:
        config.policy = args.policy

    if args.command == "github-app":
        from quality_gates.github_app import cli_github_app

        return cli_github_app(args)
    if args.command in {"init", "setup"}:
        return _onboard(root, args)
    if args.command == "mcp":
        from quality_gates.mcp_server import serve

        return serve()
    if args.command == "oracle":
        return _oracle(root, args)
    if args.command == "fix":
        return _fix(root, apply_patches=not args.no_patches, as_json=args.json)
    if args.command == "certify":
        return _certify(root, as_json=args.json)
    if args.command == "apply":
        return _apply_one(root, args.finding_id, as_json=args.json)
    if args.command == "eval":
        return _eval(root, args)
    if args.command == "baseline":
        return _baseline(root, config, ratchet=args.ratchet)
    if args.command == "report":
        return _print_report(
            root,
            fmt=args.report_format,
            as_json=args.json,
            diff=getattr(args, "report_diff", None),
        )
    if args.command == "watch":
        return _watch(root, config, interval=args.interval)
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

    if args.command == "ignore":
        from quality_gates.ignore import append_ignore

        path = append_ignore(
            root,
            rule=args.rule,
            path=args.path,
            gate=args.gate,
            reason=args.reason,
            owner=args.owner,
            days=args.days,
        )
        print(f"wrote {path.relative_to(root)}")
        return 0
    if args.command == "timing":
        from quality_gates.timing import accept_timings

        if not args.tests and not args.all_regressed:
            print("pass --test NODEID or --all-regressed", file=sys.stderr)
            return 2
        payload = accept_timings(
            root, nodeids=args.tests, all_regressed=args.all_regressed
        )
        if args.json:
            print(json.dumps(payload, indent=2))
        else:
            accepted = payload.get("accepted") or []
            print(f"accepted {len(accepted)} timing baseline(s)")
            for item in accepted:
                print(f"  {item}")
        return 0 if payload.get("accepted") else 1

    languages = _resolve_languages(root, config, getattr(args, "languages", None), None)
    if args.command == "format":
        result = gate_runners.run_format(root, config, languages, check=not args.write)
        return _emit([result], root, config, args.json, ["format"])
    if args.command == "lint":
        result = gate_runners.run_lint(root, config, languages)
        return _emit([result], root, config, args.json, ["lint"])
    if args.command == "regex":
        result = gate_runners.run_regex(root, config, base=args.base)
        return _emit([result], root, config, args.json, ["regex"])
    if args.command == "packages":
        result = gate_runners.run_packages(root, config, languages, base=args.base)
        return _emit([result], root, config, args.json, ["packages"])
    if args.command == "dry":
        result = gate_runners.run_dry(root, config, languages)
        return _emit([result], root, config, args.json, ["dry"])
    if args.command == "sbom":
        from quality_gates.sbom import write_sbom

        payload = write_sbom(root, fmt=args.sbom_format)
        if args.json:
            print(json.dumps(payload, indent=2))
        else:
            files = payload.get("files") or {}
            if files:
                print("wrote " + ", ".join(files.values()))
            for note in payload.get("notes") or []:
                print(note)
            print(f"components: {payload.get('components', 0)}")
        return 0
    if args.command == "security":
        result = gate_runners.run_security(root, config, languages)
        return _emit([result], root, config, args.json, ["security"])
    if args.command == "compile":
        security = None
        if not args.force and config.compile_require_security:
            security = gate_runners.run_security(root, config, languages)
            results = [security]
            compile_result = gate_runners.run_compile(
                root, config, languages, security=security
            )
            results.append(compile_result)
            return _emit(results, root, config, args.json, ["security", "compile"])
        from quality_gates.models import GateResult as GR

        fake = GR(
            name="security", status="pass", notes=["--force or require_security=false"]
        )
        result = gate_runners.run_compile(root, config, languages, security=fake)
        return _emit([result], root, config, args.json, ["compile"])
    if args.command == "version":
        result = gate_runners.run_version(root, config, base=args.base)
        return _emit([result], root, config, args.json, ["version"])
    if args.command == "review":
        result = gate_runners.run_review(
            root, config, languages, base=args.base, post=args.post
        )
        return _emit([result], root, config, args.json, ["review"])
    if args.command == "ui":
        result = gate_runners.run_ui(
            root,
            config,
            base=args.base,
            force_all=args.all,
            list_only=args.list,
        )
        return _emit([result], root, config, args.json, ["ui"])
    if args.command == "impact":
        result = gate_runners.run_impact(root, config, base=args.base)
        return _emit([result], root, config, args.json, ["impact"])
    if args.command == "merge":
        result = gate_runners.run_merge(
            root,
            config,
            base=args.base,
            verify=args.verify,
            siblings=args.siblings,
        )
        return _emit([result], root, config, args.json, ["merge"])
    if args.command == "comments":
        result = gate_runners.run_comments(
            root, config, fail=True if args.fail else None
        )
        required = ["comments"] if args.fail else []
        return _emit([result], root, config, args.json, required)
    if args.command == "coverage":
        result = gate_runners.run_coverage(root, config)
        return _emit([result], root, config, args.json, ["coverage"])
    if args.command == "test":
        result = gate_runners.run_tests(root, config)
        return _emit([result], root, config, args.json, ["test"])
    if args.command == "audit":
        result = gate_runners.run_audit(root, config)
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
                item = gate_runners.run_format(
                    root, config, languages, check=True, scope=changed
                )
            elif gate == "lint":
                item = gate_runners.run_lint(root, config, languages, scope=changed)
            elif gate == "regex":
                item = gate_runners.run_regex(
                    root,
                    config,
                    base=args.base,
                    diff=manifest.diff if manifest else None,
                )
            elif gate == "packages":
                item = gate_runners.run_packages(
                    root,
                    config,
                    languages,
                    base=args.base,
                    diff=manifest.diff if manifest else None,
                )
            elif gate == "dry":
                item = gate_runners.run_dry(root, config, languages)
            elif gate == "security":
                item = gate_runners.run_security(root, config, languages)
            elif gate == "compile":
                security = next((row for row in prior if row.name == "security"), None)
                if (
                    security is None
                    and config.compile_require_security
                    and "security" not in gates
                ):
                    security = gate_runners.run_security(root, config, languages)
                    security.duration_ms = max(
                        0, int((time.perf_counter() - started) * 1000)
                    )
                    results.append(security)
                    prior.append(security)
                    started = time.perf_counter()
                if not config.compile_require_security and security is None:
                    from quality_gates.models import GateResult as GR

                    security = GR(name="security", status="pass")
                item = gate_runners.run_compile(
                    root, config, languages, security=security
                )
            elif gate == "contract":
                item = gate_runners.run_contract(root, config, base=args.base)
            elif gate == "version":
                item = gate_runners.run_version(
                    root, config, base=args.base, manifest=manifest
                )
            elif gate == "impact":
                item = gate_runners.run_impact(root, config, base=args.base)
            elif gate == "merge":
                item = gate_runners.run_merge(root, config, base=args.base)
            elif gate == "test":
                item = gate_runners.run_tests(root, config)
            elif gate == "coverage":
                item = gate_runners.run_coverage(
                    root,
                    config,
                    manifest=manifest,
                    selection=manifest.paths if manifest else None,
                )
            elif gate == "audit":
                item = gate_runners.run_audit(root, config)
            elif gate == "ui":
                compile_prior = next(
                    (row for row in prior if row.name == "compile"), None
                )
                item = gate_runners.run_ui(
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
                item = gate_runners.run_review(
                    root,
                    config,
                    languages,
                    base=args.base,
                    post=post,
                    prior=prior,
                    manifest=manifest,
                )
            elif gate == "comments":
                item = gate_runners.run_comments(root, config)
            elif gate in {
                "migration",
                "authorization",
                "resilience",
                "mutation",
                "performance",
            }:
                item = gate_runners.run_advanced(
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


def _fix(root: Path, *, apply_patches: bool, as_json: bool) -> int:
    from quality_gates.autofix import run_autofix
    from quality_gates.oracle import remaining_from_reports, render_prompt

    payload = run_autofix(root, apply_patches=apply_patches)
    remaining = remaining_from_reports(root)
    remaining["autofix"] = payload
    if as_json:
        print(json.dumps(remaining, indent=2))
    else:
        for note in payload.get("applied") or []:
            print(note)
        print(render_prompt(remaining))
    return 0 if remaining.get("green") else 1


def _certify(root: Path, *, as_json: bool) -> int:
    from quality_gates.oracle import remaining_from_reports

    payload = remaining_from_reports(root)
    certificate = payload.get("certificate") or {}
    if as_json:
        print(json.dumps(certificate, indent=2))
    else:
        from quality_gates.certificate import render_certificate

        print(render_certificate(certificate))
    return 0 if certificate.get("ready") else 1


def _apply_one(root: Path, finding_id: str | None, *, as_json: bool) -> int:
    from quality_gates.models import Finding
    from quality_gates.oracle import finding_from_reports
    from quality_gates.review.apply import apply_and_verify

    packed = finding_from_reports(root, finding_id)
    row = packed.get("finding")
    if not isinstance(row, dict):
        if as_json:
            print(json.dumps(packed, indent=2))
        else:
            print(packed.get("error") or "no finding")
        return 1
    finding = Finding(
        gate=str(row.get("gate") or "review"),
        message=str(row.get("message") or ""),
        path=row.get("path"),
        line=row.get("line") if isinstance(row.get("line"), int) else None,
        rule=row.get("rule"),
        patch=row.get("patch"),
        suggestion=row.get("suggestion"),
        verify=row.get("verify"),
    )
    verified = apply_and_verify(root, finding)
    verified["id"] = row.get("id")
    if as_json:
        print(json.dumps(verified, indent=2))
    else:
        print(verified.get("status") or verified)
        if verified.get("next"):
            print(verified["next"])
    return 0 if verified.get("resolved") else 1


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
    dest = root / ".quality-reports" / "eval" / "SCORECARD.md"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(_eval_markdown(payload), encoding="utf-8")
    bench = payload.get("reviewbench")
    if isinstance(bench, dict) and bench.get("failed"):
        return 1
    if args.llm and not llm_eval_enabled():
        return 2
    return 0


def _eval_markdown(payload: dict[str, object]) -> str:
    lines = ["# Review eval scorecard", ""]
    bench = payload.get("reviewbench")
    if isinstance(bench, dict):
        lines += [
            "## ReviewBench (heuristic)",
            "",
            f"- cases: {bench.get('cases')}",
            f"- recall: {bench.get('recall')}",
            f"- hard-negative pass: {bench.get('hard_negative_pass')}",
            f"- failed: {', '.join(bench.get('failed') or []) or 'none'}",
            "",
        ]
    martian = payload.get("martian")
    if isinstance(martian, dict):
        lines += [
            "## Martian CRB",
            "",
            f"- {martian.get('citation') or martian.get('url') or ''}",
            f"- PRs: {martian.get('prs', martian.get('skipped', ''))}",
            "",
        ]
    macro = payload.get("macroscope")
    if isinstance(macro, dict):
        lines += ["## Macroscope reconstructed sample", "", f"- {macro.get('id')}", ""]
    lines.append("Source: `quality eval`. Settings are the heuristic suite defaults.")
    lines.append("")
    return "\n".join(lines)


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
    from quality_gates.findings_artifact import (
        reconcile_last_findings,
        rotate_and_persist,
    )
    from quality_gates.ignore import apply_ignores

    results, policy = apply_policy(results, root, config)
    leftover = reconcile_last_findings(root, results)
    if leftover:
        apply_ignores(results, root)
    rotate_and_persist(root, results)
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


def _watch(root: Path, config: QualityConfig, *, interval: float) -> int:
    from quality_gates.watch import watch_loop

    def _rerun() -> None:
        print("change detected — quality run --skip review", flush=True)
        main(["--root", str(root), "run", "--skip", "review"])

    print(f"watching {root} every {interval}s (Ctrl-C to stop)", flush=True)
    try:
        return watch_loop(root, config, _rerun, interval=interval)
    except KeyboardInterrupt:
        return 0


def _print_report(
    root: Path, *, fmt: str, as_json: bool, diff: str | None = None
) -> int:
    report_dir = root / ".quality-reports"
    results, policy = load_results(report_dir)
    if not results:
        print(
            "no .quality-reports/quality-report.json — run `quality run` first",
            file=sys.stderr,
        )
        return 2
    if diff:
        from quality_gates.report import filter_new_findings

        prior_results, _prior_policy = load_results(
            report_dir, "quality-report.prev.json"
        )
        previous = [finding for item in prior_results for finding in item.findings]
        current = [finding for item in results for finding in item.findings]
        if previous:
            kept = set(map(id, filter_new_findings(current, previous)))
            for item in results:
                item.findings = [
                    finding for finding in item.findings if id(finding) in kept
                ]
        else:
            print("no previous findings to diff against; showing full report")
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


def _onboard(root: Path, args: argparse.Namespace) -> int:
    from quality_gates.onboard import init_repo

    code = init_repo(
        root,
        policy=args.init_policy,
        org=args.org,
        source=args.source,
        pin=args.pin,
        vendor_cli=args.vendor_cli,
        require_check=bool(args.require_check),
        force=args.force,
        hooks=bool(getattr(args, "hooks", False)),
        agents=bool(getattr(args, "agents", False)),
        auto_merge=bool(getattr(args, "auto_merge", False)),
    )
    if getattr(args, "run", False):
        print("Running first gates and writing a baseline...")
        run_code = main(["--root", str(root), "run", "--skip", "review"])
        base_code = main(["--root", str(root), "baseline"])
        if run_code not in {0, 1}:
            code = run_code
        elif base_code != 0:
            code = base_code
    if args.command == "setup":
        print(
            "Commit quality.toml, .github/workflows/quality.yml, "
            "and .quality-baseline.json"
        )
        if getattr(args, "hooks", False):
            print("Include .pre-commit-config.yaml if it was just written.")
        if getattr(args, "agents", False):
            print(
                "Include .cursor/mcp.json, .mcp.json, "
                ".cursor/rules/the-code-sheriff.mdc, and the Code Sheriff skill."
            )
            print(
                "Put `quality` on PATH (`uv tool install git+https://github.com/pwoodman/the-code-sheriff.git`) so MCP can spawn."
            )
        if getattr(args, "auto_merge", False):
            print("GitHub auto-merge: land PRs when `quality certify` is ready.")
        print("GitHub App is optional: quality github-app register")
    else:
        print("Next: quality run --skip review && quality baseline")
    if args.command == "setup" and getattr(args, "app", False):
        from quality_gates.github_app import cli_github_app

        register = argparse.Namespace(
            app_command="register",
            host="127.0.0.1",
            port=8787,
            webhook_url="",
            org=args.org,
            name="The Code Sheriff",
            public=False,
            no_open=False,
            no_init=True,
        )
        app_code = cli_github_app(register)
        return app_code or code
    return code


def _baseline(root: Path, config: QualityConfig, *, ratchet: bool) -> int:
    report = root / ".quality-reports" / "quality-report.json"
    if not report.is_file():
        print(
            "no .quality-reports/quality-report.json — running coverage + audit first"
        )
        results = [
            gate_runners.run_coverage(root, config),
            gate_runners.run_audit(root, config),
        ]
        write_reports(results, root / ".quality-reports")
    path = write_baseline(root, config, ratchet=ratchet)
    print(f"wrote {path.relative_to(root)}" + (" (ratchet)" if ratchet else ""))
    print("Commit this file so PRs fail only on new issues, not the existing backlog.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
