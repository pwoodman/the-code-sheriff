"""Run all 120 checks. Findings require file/line evidence. No exploit attempts."""

from __future__ import annotations

import re
from pathlib import Path

from quality_gates.audit.catalog import CHECK_BY_ID, CHECKS, Check
from quality_gates.audit.code_quality import scan_code_quality
from quality_gates.audit.model import AuditFinding, CheckOutcome
from quality_gates.audit.patterns import Pathish, scan_patterns
from quality_gates.audit.walk import FileHit, RepoContext, load_context
from quality_gates.config import QualityConfig
from quality_gates.impact_graph import build_graph

GOD_LINES = 800
PUBLIC_PATHS = (
    "/health",
    "/ready",
    "/live",
    "/metrics",
    "/docs",
    "/redoc",
    "/openapi",
    "/favicon",
    "/static",
)
AUTH_HINTS = (
    "depends",
    "security",
    "httpbearer",
    "oauth2",
    "login_required",
    "permission",
    "current_user",
    "get_current",
    "require_auth",
    "requireauth",
    "isauthenticated",
    "authorize",
    "acl",
    "guard",
    "middleware",
    "authenticate",
    "request.user",
    "ctx.user",
)
OWNER_HINTS = (
    "owner",
    "user_id",
    "userid",
    "tenant",
    "current_user",
    "request.user",
    "organization",
    "account_id",
)
ADMIN_PATHS = (
    "/admin",
    "/approve",
    "/refund",
    "/impersonate",
    "/promote",
    "/configure",
    "/disable",
)
ROUTE_DECO = re.compile(
    r"""@(?:app|router|api|bp|blueprint)\.(get|post|put|patch|delete|route)\(\s*['\"]([^'\"]+)""",
    re.I,
)
EXPRESS_ROUTE = re.compile(
    r"""\b(?:app|router|r)\.(get|post|put|patch|delete)\(\s*['\"]([^'\"]+)['\"]\s*,""",
    re.I,
)
ACTION_USES = re.compile(
    r"""^\s+(?:-\s+)?uses:\s*['\"]?([^\s'\"@]+)@([^\s'\"]+)""",
    re.M,
)
WRITE_ALL = re.compile(r"(?im)^\s+permissions:\s*write-all\s*$")
SHA = re.compile(r"^[0-9a-f]{40}$")

STATIC_DETECTORS = {
    "pattern",
    "authz",
    "cycles",
    "lockfile",
    "actions",
    "ci_perms",
    "god_file",
    "dead_code",
    "observe",
}


def run_audit_engine(
    root: Path, config: QualityConfig
) -> tuple[list[CheckOutcome], RepoContext]:
    ctx = load_context(root, config)
    by_id = scan_patterns(ctx)
    _merge(by_id, scan_code_quality(ctx))
    _merge(by_id, _authz(ctx))
    _merge(by_id, _god_files(ctx))
    _merge(by_id, _lockfiles(ctx))
    _merge(by_id, _actions(ctx))
    _merge(by_id, _ci_perms(ctx))
    _merge(by_id, _cycles(root, config, ctx))
    _merge(by_id, _observe(ctx))

    skip = set(config.audit_skip_ids)
    outcomes: list[CheckOutcome] = []
    for check in CHECKS:
        if check.id in skip:
            outcomes.append(CheckOutcome(check.id, check.title, "skipped"))
            continue
        found = by_id.get(check.id) or []
        if found:
            outcomes.append(CheckOutcome(check.id, check.title, "finding", found))
            continue
        if check.surfaces and not any(
            surface in ctx.surfaces for surface in check.surfaces
        ):
            outcomes.append(CheckOutcome(check.id, check.title, "not_applicable"))
            continue
        if check.detector in STATIC_DETECTORS:
            outcomes.append(CheckOutcome(check.id, check.title, "pass"))
            continue
        outcomes.append(CheckOutcome(check.id, check.title, "not_statically_provable"))
    return outcomes, ctx


def _merge(
    into: dict[int, list[AuditFinding]], extra: dict[int, list[AuditFinding]]
) -> None:
    for check_id, items in extra.items():
        into.setdefault(check_id, []).extend(items)


def _authz(ctx: RepoContext) -> dict[int, list[AuditFinding]]:
    found: dict[int, list[AuditFinding]] = {}
    routes: list[tuple[FileHit, int, str, str, str]] = []
    for hit in ctx.files:
        if hit.is_test or not hit.is_source:
            continue
        for regex in (ROUTE_DECO, EXPRESS_ROUTE):
            for match in regex.finditer(hit.text):
                method = match.group(1).upper()
                if method == "ROUTE":
                    method = "ANY"
                path = match.group(2)
                line_no = hit.text.count("\n", 0, match.start()) + 1
                window = "\n".join(
                    hit.lines[line_no - 1 : min(len(hit.lines), line_no + 40)]
                )
                routes.append((hit, line_no, method, path, window))

    if not routes:
        return found

    for hit, line_no, method, path, window in routes:
        lower = window.lower()
        has_auth = any(hint in lower for hint in AUTH_HINTS)
        public = any(
            path.startswith(prefix) or path == prefix for prefix in PUBLIC_PATHS
        )
        mutating = method in {"POST", "PUT", "PATCH", "DELETE", "ANY"}
        admin = any(token in path.lower() for token in ADMIN_PATHS)
        id_param = bool(re.search(r"\{[^}]*id[^}]*\}|<[^>]*id[^>]*>|:id\b", path, re.I))
        has_owner = any(hint in lower for hint in OWNER_HINTS)

        if not has_auth and not public:
            if mutating or admin:
                _add(
                    found,
                    1,
                    hit,
                    line_no,
                    f"{method} {path} has no server-side auth hint in the handler window.",
                    "Call the endpoint directly without the UI; the operation proceeds.",
                    endpoint=path,
                    method=method,
                )
                _add(
                    found,
                    105,
                    hit,
                    line_no,
                    f"{method} {path} is registered without an auth dependency.",
                    "An unauthenticated client can hit a state-changing or privileged route.",
                    endpoint=path,
                    method=method,
                )
            if admin:
                _add(
                    found,
                    3,
                    hit,
                    line_no,
                    f"Admin-style path {path} has no backend authorization hint.",
                    "Hiding the admin screen does not stop a direct HTTP call.",
                    endpoint=path,
                    method=method,
                )
                _add(
                    found,
                    102,
                    hit,
                    line_no,
                    f"Privileged operation {method} {path} lacks an explicit permission check.",
                    "Any authenticated (or unauthenticated) caller can invoke it.",
                    endpoint=path,
                    method=method,
                )
            if mutating and method in {"PUT", "PATCH", "DELETE"}:
                # GET may be protected while write methods are not — we only
                # saw this handler; still evidence that THIS method is open.
                _add(
                    found,
                    104,
                    hit,
                    line_no,
                    f"Write method {method} {path} has no auth hint (GET-only protection is a common AI bug).",
                    "Changing the method bypasses the control that exists on GET.",
                    endpoint=path,
                    method=method,
                )

        if id_param and mutating and not has_owner:
            _add(
                found,
                2,
                hit,
                line_no,
                f"{method} {path} takes an object id with no ownership check in the handler window.",
                "Swap the id for another user's resource; the row is returned or mutated.",
                endpoint=path,
                method=method,
            )
            _add(
                found,
                101,
                hit,
                line_no,
                f"Possessing an id on {path} appears sufficient to authorize the operation.",
                "IDs are not secrets; another tenant's identifier must not grant access.",
                endpoint=path,
                method=method,
            )
    return found


def _god_files(ctx: RepoContext) -> dict[int, list[AuditFinding]]:
    found: dict[int, list[AuditFinding]] = {}
    check = _check(41)
    for hit in ctx.files:
        if not hit.is_source or hit.is_test:
            continue
        n = len(hit.lines)
        if n <= GOD_LINES:
            continue
        found.setdefault(41, []).append(
            _make(
                check,
                hit,
                1,
                f"{hit.relative} is {n} lines (god-file threshold {GOD_LINES}).",
                "Large mixed-concern files hide bugs and make safe change impossible.",
                "Split by responsibility; do not invent a new architecture.",
            )
        )
    return found


def _lockfiles(ctx: RepoContext) -> dict[int, list[AuditFinding]]:
    found: dict[int, list[AuditFinding]] = {}
    check = _check(37)
    problems: list[tuple[str, str]] = []
    if ctx.has_package_json and not ctx.has_lockfile:
        problems.append(
            (
                "package.json",
                "Node project has no package-lock.json / yarn.lock / pnpm-lock.yaml",
            )
        )
    if ctx.has_go_mod and not ctx.has_go_sum:
        problems.append(("go.mod", "Go module is missing go.sum"))
    if ctx.has_cargo and not ctx.has_cargo_lock:
        problems.append(("Cargo.toml", "Cargo project is missing Cargo.lock"))
    for path, message in problems:
        fake = _synthetic(ctx.root, path)
        found.setdefault(37, []).append(
            _make(
                check,
                fake,
                1,
                message,
                "Builds pull different transitive versions; supply-chain and 'works on my machine' follow.",
                "Commit the lockfile and install from it in CI.",
            )
        )
    return found


def _actions(ctx: RepoContext) -> dict[int, list[AuditFinding]]:
    found: dict[int, list[AuditFinding]] = {}
    check = _check(39)
    for hit in ctx.workflow_files:
        for match in ACTION_USES.finditer(hit.text):
            action, ref = match.group(1), match.group(2)
            if action.startswith("./") or action.startswith("docker://"):
                continue
            ref_clean = ref.split("#")[0].strip()
            if SHA.match(ref_clean.lower()):
                continue
            line_no = hit.text.count("\n", 0, match.start()) + 1
            found.setdefault(39, []).append(
                _make(
                    check,
                    hit,
                    line_no,
                    f"GitHub Action {action}@{ref_clean} is not pinned to a full commit SHA.",
                    "A moved tag can run different (including malicious) code in CI.",
                    "Pin uses: to a 40-character SHA and comment the version tag.",
                )
            )
    return found


def _ci_perms(ctx: RepoContext) -> dict[int, list[AuditFinding]]:
    found: dict[int, list[AuditFinding]] = {}
    check = _check(40)
    for hit in ctx.workflow_files:
        match = WRITE_ALL.search(hit.text)
        if match:
            line_no = hit.text.count("\n", 0, match.start()) + 1
            found.setdefault(40, []).append(
                _make(
                    check,
                    hit,
                    line_no,
                    "Workflow sets permissions: write-all.",
                    "A compromised build job can push, publish, and use every secret.",
                    "Set least-privilege permissions: at workflow and job level.",
                )
            )
    return found


def _cycles(
    root: Path, config: QualityConfig, ctx: RepoContext
) -> dict[int, list[AuditFinding]]:
    found: dict[int, list[AuditFinding]] = {}
    graph = build_graph(root, config)
    seen: set[frozenset[str]] = set()
    visiting: list[str] = []
    on_stack: set[str] = set()
    done: set[str] = set()

    def dfs(node: str) -> None:
        if node in done:
            return
        on_stack.add(node)
        visiting.append(node)
        for nxt in sorted(graph.imports.get(node, ())):
            if nxt not in graph.files:
                continue
            if nxt in on_stack:
                start = visiting.index(nxt)
                cycle = [*visiting[start:], nxt]
                key = frozenset(cycle)
                if key not in seen and len(cycle) > 2:
                    seen.add(key)
                    rel = cycle[0]
                    hit = next(
                        (item for item in ctx.files if item.relative == rel), None
                    )
                    if hit is None:
                        hit = _synthetic(root, rel)
                    check = _check(45)
                    found.setdefault(45, []).append(
                        _make(
                            check,
                            hit,
                            1,
                            "Import cycle: " + " → ".join(cycle[:8]),
                            "Cycles break layering and make initialization / testing order-dependent.",
                            "Extract a shared module or invert one import.",
                        )
                    )
            else:
                dfs(nxt)
        visiting.pop()
        on_stack.remove(node)
        done.add(node)

    for name in sorted(graph.files):
        dfs(name)
    return found


def _observe(ctx: RepoContext) -> dict[int, list[AuditFinding]]:
    if "http" not in ctx.surfaces:
        return {}
    blob = "\n".join(item.text for item in ctx.files if item.is_source).lower()
    markers = (
        "request_id",
        "request-id",
        "trace_id",
        "traceparent",
        "correlation_id",
        "x-request-id",
    )
    if any(marker in blob for marker in markers):
        return {}
    http_file = next(
        (item for item in ctx.files if item.is_source and "route" in item.text.lower()),
        None,
    )
    if http_file is None:
        http_file = next((item for item in ctx.files if item.is_source), None)
    if http_file is None:
        return {}
    check = _check(120)
    return {
        120: [
            _make(
                check,
                http_file,
                1,
                "HTTP handlers exist but no request/trace/correlation id appears in source.",
                "A failing request cannot be followed across services or logs.",
                "Generate a request_id at the edge, log it, and propagate it downstream. Never log secrets.",
            )
        ]
    }


def _add(
    found: dict[int, list[AuditFinding]],
    check_id: int,
    hit: FileHit,
    line_no: int,
    finding: str,
    scenario: str,
    *,
    endpoint: str | None = None,
    method: str | None = None,
) -> None:
    check = _check(check_id)
    found.setdefault(check_id, []).append(
        _make(
            check,
            hit,
            line_no,
            finding,
            scenario,
            check.fix,
            endpoint=endpoint,
            method=method,
        )
    )


def _make(
    check: Check,
    hit: FileHit,
    line_no: int,
    finding: str,
    scenario: str,
    fix: str,
    *,
    endpoint: str | None = None,
    method: str | None = None,
) -> AuditFinding:
    snippet = ""
    if 1 <= line_no <= len(hit.lines):
        snippet = hit.lines[line_no - 1].strip()[:180]
    return AuditFinding(
        check_id=check.id,
        title=check.title,
        severity=check.severity,
        priority=check.priority,
        category=check.category,
        confidence="HIGH",
        finding=finding,
        why=check.why,
        evidence=f"{hit.relative}:{line_no}: {snippet}".rstrip(),
        scenario=scenario,
        fix=fix,
        path=hit.relative,
        line=line_no,
        component=Pathish(hit.relative),
        endpoint=endpoint,
        method=method,
        suggested_test=f"Add a regression test around {hit.relative}:{line_no}.",
        references=f"audit check {check.id}",
        can_auto_fix="No",
        regression_test="Yes",
        effort="S",
    )


def _check(check_id: int) -> Check:
    return CHECK_BY_ID[check_id]


def _synthetic(root: Path, relative: str) -> FileHit:
    path = root / relative
    text = (
        path.read_text(encoding="utf-8", errors="replace")
        if path.is_file()
        else relative
    )
    return FileHit(
        path=path,
        relative=relative,
        text=text,
        lines=text.splitlines() or [relative],
        is_test=False,
        is_source=True,
    )
