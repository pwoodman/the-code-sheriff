"""Write The Code Sheriff defaults: quality.toml, pinned workflow, required check."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import urllib.error
import urllib.request
from pathlib import Path

from quality_gates.github_app import CHECK_NAME, DEFAULT_HOME_REPO

DEFAULT_SOURCE = DEFAULT_HOME_REPO
DEFAULT_REF = "main"
PLACEHOLDER_PIN = "REPLACE_FULL_COMMIT_SHA"
_SHA = re.compile(r"^[0-9a-f]{40}$")
_GITHUB_REPO = re.compile(
    r"github\.com[:/](?P<owner>[^/]+)/(?P<repo>[^/.]+?)(?:\.git)?$"
)


def consumer_toml(policy: str = "adopt") -> str:
    return f"""# The Code Sheriff defaults. Every key is optional.
# policy=adopt grandfathers existing issues after `quality baseline`.

[quality]
languages = ["auto"]
policy = "{policy}"
baseline = ".quality-baseline.json"
comment_on_pr = true
fail_on = ["format", "lint", "dry", "security", "compile", "contract", "impact", "test", "coverage", "audit", "ui", "version"]
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

[quality.format]
prefer_project_tools = true

[quality.lint]
prefer_project_tools = true

[quality.review]
provider = "auto"
inline_comments = true
check_run = true
"""


def workflow_yaml(source: str, pin: str) -> str:
    comment = (
        f"# Pinned {source}@{pin[:12]}"
        if _SHA.fullmatch(pin)
        else f"# Ref {source}@{pin} — re-run quality setup to pin a SHA"
    )
    return f"""name: {CHECK_NAME}

on:
  pull_request:
  push:
    branches: [main, master]
  workflow_dispatch:

permissions:
  contents: read
  pull-requests: write
  checks: write
  security-events: write

jobs:
  sheriff:
    name: {CHECK_NAME}
    {comment}
    uses: {source}/.github/workflows/quality.yml@{pin}
    secrets: inherit
"""


def vendor_cli_yaml(source: str, pin: str) -> str:
    return f"""name: {CHECK_NAME} (vendored CLI)

on:
  pull_request:
  push:
    branches: [main, master]
  workflow_dispatch:

permissions:
  contents: read
  pull-requests: write
  checks: write

jobs:
  quality:
    name: {CHECK_NAME}
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@11d5960a326750d5838078e36cf38b85af677262
        with:
          fetch-depth: 0
      - uses: actions/setup-python@a26af69be951a213d495a4c3e4e4022e16d87065
        with:
          python-version: "3.12"
      - name: Install quality-gates
        run: pip install "git+https://github.com/{source}.git@{pin}"
      - name: Run gates
        env:
          GITHUB_TOKEN: ${{{{ secrets.GITHUB_TOKEN }}}}
        run: quality run
"""


def resolve_source(org: str = "", source: str = "") -> str:
    if source.strip():
        return source.strip().removesuffix(".git")
    owner = org.strip()
    if owner and owner not in {"REPLACE_ORG", "YOUR_ORG"}:
        return f"{owner}/poly-check"
    return DEFAULT_SOURCE


def resolve_pin(source: str, pin: str = "auto", *, ref: str = DEFAULT_REF) -> str:
    requested = (pin or "auto").strip()
    if requested not in {"", "auto", "latest"}:
        if _SHA.fullmatch(requested):
            return requested
        return _lookup_sha(source, requested) or requested
    return _lookup_sha(source, ref) or ref


def _lookup_sha(source: str, ref: str) -> str | None:
    url = f"https://github.com/{source}.git"
    try:
        proc = subprocess.run(
            ["git", "ls-remote", url, f"refs/heads/{ref}", f"refs/tags/{ref}", ref],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        proc = None
    if proc and proc.returncode == 0:
        for line in proc.stdout.splitlines():
            sha = line.split()[0] if line.split() else ""
            if _SHA.fullmatch(sha):
                return sha
    try:
        req = urllib.request.Request(
            f"https://api.github.com/repos/{source}/commits/{ref}",
            headers={
                "Accept": "application/vnd.github+json",
                "User-Agent": "the-codesheriff",
            },
        )
        with urllib.request.urlopen(req, timeout=15) as response:
            data = json.loads(response.read().decode("utf-8"))
    except (
        OSError,
        urllib.error.URLError,
        json.JSONDecodeError,
        TimeoutError,
        ValueError,
    ):
        return None
    sha = str(data.get("sha") or "") if isinstance(data, dict) else ""
    return sha if _SHA.fullmatch(sha) else None


def github_repo_from_remote(root: Path) -> tuple[str, str] | None:
    try:
        proc = subprocess.run(
            ["git", "-C", str(root), "remote", "get-url", "origin"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0:
        return None
    match = _GITHUB_REPO.search(proc.stdout.strip())
    if not match:
        return None
    return match.group("owner"), match.group("repo")


def consumer_precommit(source: str, pin: str) -> str:
    return f"""# The Code Sheriff. Install with:
#   pre-commit install --hook-type pre-commit --hook-type pre-push
repos:
  - repo: https://github.com/{source}
    rev: {pin}
    hooks:
      - id: quality-format
      - id: quality-lint
      - id: quality-version
      - id: quality-push
"""


def enable_required_check(
    root: Path, check_name: str = CHECK_NAME, *, branch: str = ""
) -> str:
    if shutil.which("gh") is None:
        return (
            f"skipped required check (install GitHub CLI, then: "
            f"Settings → Rules → require {check_name})"
        )
    repo = github_repo_from_remote(root)
    owner_repo = f"{repo[0]}/{repo[1]}" if repo is not None else _gh_repo_slug(root)
    if not owner_repo:
        return f"skipped required check (no GitHub remote). Require {check_name} in branch rules."
    default_branch = branch or _gh_default_branch(root, owner_repo) or "main"
    existing = _gh_json(["api", f"repos/{owner_repo}/rulesets"], root)
    if isinstance(existing, list):
        for item in existing:
            if isinstance(item, dict) and item.get("name") == check_name:
                return f"required check already present: {check_name}"
    includes = list(
        dict.fromkeys(
            [
                f"refs/heads/{default_branch}",
                "refs/heads/main",
                "refs/heads/master",
            ]
        )
    )
    payload = {
        "name": check_name,
        "target": "branch",
        "enforcement": "active",
        "conditions": {
            "ref_name": {
                "include": includes,
                "exclude": [],
            }
        },
        "rules": [
            {
                "type": "required_status_checks",
                "parameters": {
                    "strict_required_status_checks_policy": False,
                    "required_status_checks": [{"context": check_name}],
                },
            }
        ],
    }
    code, body = _gh_write(
        ["api", "--method", "POST", f"repos/{owner_repo}/rulesets", "--input", "-"],
        json.dumps(payload),
        root,
    )
    if 200 <= code < 300:
        return f"required {check_name} on {owner_repo} ({default_branch})"
    message = body.get("message") if isinstance(body, dict) else body
    return f"could not require {check_name} (HTTP {code}: {message})"


def _gh_repo_slug(root: Path) -> str:
    data = _gh_json(["repo", "view", "--json", "nameWithOwner"], root)
    if isinstance(data, dict):
        return str(data.get("nameWithOwner") or "")
    return ""


def _gh_default_branch(root: Path, owner_repo: str) -> str:
    data = _gh_json(
        ["api", f"repos/{owner_repo}", "--jq", ".default_branch"],
        root,
        raw=True,
    )
    if isinstance(data, str) and data.strip():
        return data.strip().strip('"')
    return ""


def _gh_json(args: list[str], root: Path, *, raw: bool = False) -> object:
    try:
        proc = subprocess.run(
            ["gh", *args],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
            cwd=root,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0:
        return None
    text = proc.stdout.strip()
    if raw:
        return text
    try:
        return json.loads(text) if text else None
    except json.JSONDecodeError:
        return text


def _gh_write(args: list[str], payload: str, root: Path) -> tuple[int, object]:
    try:
        proc = subprocess.run(
            ["gh", *args],
            input=payload,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
            cwd=root,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 400, str(exc)
    try:
        body: object = json.loads(proc.stdout) if proc.stdout.strip() else {}
    except json.JSONDecodeError:
        body = proc.stdout.strip() or proc.stderr.strip()
    if proc.returncode == 0:
        return 200, body
    return 400, body or proc.stderr.strip() or "gh failed"


def install_git_hooks(root: Path) -> str:
    if shutil.which("pre-commit") is None:
        return (
            "skipped hook install (pip install pre-commit, then: "
            "pre-commit install --hook-type pre-commit --hook-type pre-push)"
        )
    try:
        proc = subprocess.run(
            [
                "pre-commit",
                "install",
                "--hook-type",
                "pre-commit",
                "--hook-type",
                "pre-push",
            ],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return f"skipped hook install ({exc})"
    if proc.returncode == 0:
        return (proc.stdout or "pre-commit installed").strip()
    return f"skipped hook install ({(proc.stderr or proc.stdout).strip()})"


def _should_write_workflow(path: Path, *, force: bool) -> bool:
    if force or not path.is_file():
        return True
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return False
    return PLACEHOLDER_PIN in text or "REPLACE_ORG" in text


def init_repo(
    root: Path,
    *,
    policy: str = "adopt",
    org: str = "",
    source: str = "",
    pin: str = "auto",
    vendor_cli: bool = False,
    require_check: bool = False,
    force: bool = False,
    hooks: bool = False,
) -> int:
    source_repo = resolve_source(org, source)
    resolved = resolve_pin(source_repo, pin)
    notes: list[str] = []

    config_path = root / "quality.toml"
    if force or not config_path.exists():
        config_path.write_text(consumer_toml(policy), encoding="utf-8")
        notes.append(f"wrote {config_path} (policy={policy})")
    else:
        notes.append(f"kept existing {config_path}")

    workflow_dir = root / ".github" / "workflows"
    workflow_dir.mkdir(parents=True, exist_ok=True)
    reusable = workflow_dir / "quality.yml"
    if _should_write_workflow(reusable, force=force):
        reusable.write_text(workflow_yaml(source_repo, resolved), encoding="utf-8")
        notes.append(f"wrote {reusable} → {source_repo}@{resolved}")
    else:
        notes.append(f"kept existing {reusable}")

    if vendor_cli:
        local = workflow_dir / "quality-cli.yml"
        if _should_write_workflow(local, force=force):
            local.write_text(vendor_cli_yaml(source_repo, resolved), encoding="utf-8")
            notes.append(f"wrote {local}")
        else:
            notes.append(f"kept existing {local}")

    if hooks:
        hook_path = root / ".pre-commit-config.yaml"
        if force or not hook_path.exists():
            hook_path.write_text(
                consumer_precommit(source_repo, resolved), encoding="utf-8"
            )
            notes.append(f"wrote {hook_path}")
        else:
            notes.append(f"kept existing {hook_path}")

    for line in notes:
        print(line)
    if not _SHA.fullmatch(resolved):
        print(
            f"could not resolve a SHA for {source_repo}; workflow uses @{resolved}. "
            "Re-run quality setup when online to pin."
        )
    if require_check:
        print(enable_required_check(root))
    if hooks:
        print(install_git_hooks(root))
    return 0
