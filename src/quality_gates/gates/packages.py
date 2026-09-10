"""Cheap package-risk checks on imports and newly declared dependencies.

osv-scanner/Trivy already own CVE lockfile scans. This gate is the local,
no-network layer: if a language that imports packages just pulled in a known
risky name (typosquat, malware incident, abandoned crypto) or an undeclared
third-party import, fail before compile.
"""

from __future__ import annotations

import json
import re
import sys
import tomllib
from pathlib import Path
from typing import Any

from quality_gates.config import QualityConfig
from quality_gates.gates.common import fail_or_pass, skip_result
from quality_gates.models import Finding, GateResult
from quality_gates.review.diffscan import iter_added_lines, load_review_diff
from quality_gates.review.routing import path_skipped

PACKAGE_LANGS = {
    "python": "python",
    "javascript": "npm",
    "typescript": "npm",
    "react": "npm",
    "go": "go",
    "rust": "cargo",
    "java": "java",
    "kotlin": "java",
    "csharp": "nuget",
    "php": "composer",
    "ruby": "rubygems",
    "elixir": "hex",
    "dart": "pub",
}

PY_IMPORT = re.compile(
    r"^\s*(?:from\s+(\.*[\w.]*)\s+import\s+|import\s+([\w.]+))", re.M
)
JS_IMPORT = re.compile(
    r"""(?:from\s+|import\(\s*|require\(\s*|export\s+(?:.+\s+)?from\s+|import\s+)['"]([^'"]+)['"]"""
)
GO_IMPORT = re.compile(r"""["']([a-zA-Z0-9._/-]+)["']""")
RS_USE = re.compile(r"^\s*(?:pub\s+)?use\s+([a-zA-Z_][\w:]*)", re.M)
JAVA_IMPORT = re.compile(r"^\s*import\s+(?:static\s+)?([\w.]+)\s*;", re.M)
PHP_USE = re.compile(r"^\s*use\s+([A-Za-z_\\][\w\\]*)", re.M)
RB_REQUIRE = re.compile(r"""^\s*require(?:_relative)?\s+['"]([^'"]+)['"]""", re.M)
CS_USING = re.compile(r"^\s*using\s+([\w.]+)\s*;", re.M)
NPM_DEP_LINE = re.compile(r"""^\s*["'](@?[^"']+)["']\s*:""")
PEP508_LINE = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)")
GO_REQUIRE = re.compile(r"^\s*([a-zA-Z0-9._/-]+)\s+v")
CARGO_DEP = re.compile(r"^\s*([A-Za-z0-9_-]+)\s*=")
GEM_LINE = re.compile(r"""^\s*gem\s+['"]([^'"]+)['"]""")

NODE_BUILTINS = frozenset(
    {
        "assert",
        "async_hooks",
        "buffer",
        "child_process",
        "cluster",
        "console",
        "constants",
        "crypto",
        "dgram",
        "diagnostics_channel",
        "dns",
        "domain",
        "events",
        "fs",
        "http",
        "http2",
        "https",
        "inspector",
        "module",
        "net",
        "os",
        "path",
        "perf_hooks",
        "process",
        "punycode",
        "querystring",
        "readline",
        "repl",
        "stream",
        "string_decoder",
        "sys",
        "timers",
        "tls",
        "trace_events",
        "tty",
        "url",
        "util",
        "v8",
        "vm",
        "vscode",
        "wasi",
        "worker_threads",
        "zlib",
        "test",
    }
)
PY_STDLIB = frozenset(getattr(sys, "stdlib_module_names", ())) | {
    "__future__",
    "typing_extensions",
}
PY_IMPORT_TO_DIST = {
    "yaml": "pyyaml",
    "PIL": "pillow",
    "cv2": "opencv-python",
    "skimage": "scikit-image",
    "dateutil": "python-dateutil",
    "bs4": "beautifulsoup4",
    "dotenv": "python-dotenv",
    "attr": "attrs",
    "Cryptodome": "pycryptodome",
    "OpenSSL": "pyopenssl",
    "serial": "pyserial",
}

# High-confidence risks only. CVE lockfiles stay with osv-scanner.
DEFAULT_RISKS: list[dict[str, str]] = [
    {
        "name": "pycrypto",
        "ecosystem": "python",
        "kind": "abandoned",
        "severity": "error",
        "message": "PyCrypto is abandoned and has known memory-corruption bugs; use cryptography or pycryptodome",
    },
    {
        "name": "request",
        "ecosystem": "python",
        "kind": "typosquat",
        "severity": "error",
        "message": "PyPI 'request' is a typosquat of 'requests'",
    },
    {
        "name": "reqests",
        "ecosystem": "python",
        "kind": "typosquat",
        "severity": "error",
        "message": "PyPI 'reqests' is a typosquat of 'requests'",
    },
    {
        "name": "urlib3",
        "ecosystem": "python",
        "kind": "typosquat",
        "severity": "error",
        "message": "PyPI 'urlib3' is a typosquat of 'urllib3'",
    },
    {
        "name": "event-stream",
        "ecosystem": "npm",
        "kind": "malware",
        "severity": "error",
        "message": "npm event-stream was compromised (flatmap-stream); do not add it",
    },
    {
        "name": "flatmap-stream",
        "ecosystem": "npm",
        "kind": "malware",
        "severity": "error",
        "message": "npm flatmap-stream was malware shipped via event-stream",
    },
    {
        "name": "crossenv",
        "ecosystem": "npm",
        "kind": "typosquat",
        "severity": "error",
        "message": "npm crossenv is a malware typosquat of cross-env",
    },
    {
        "name": "uglifyjs",
        "ecosystem": "npm",
        "kind": "typosquat",
        "severity": "error",
        "message": "npm uglifyjs is a typosquat of uglify-js",
    },
    {
        "name": "node-ipc",
        "ecosystem": "npm",
        "kind": "protestware",
        "severity": "error",
        "message": "node-ipc shipped destructive protestware; pin an audited fork or drop it",
    },
    {
        "name": "electron-native-notify",
        "ecosystem": "npm",
        "kind": "malware",
        "severity": "error",
        "message": "electron-native-notify was used in a supply-chain attack",
    },
    {
        "name": "colors",
        "ecosystem": "npm",
        "kind": "protestware",
        "severity": "warning",
        "message": "npm colors shipped infinite-loop protestware; prefer an audited alternative",
    },
    {
        "name": "faker",
        "ecosystem": "npm",
        "kind": "protestware",
        "severity": "warning",
        "message": "npm faker shipped protestware; use @faker-js/faker",
    },
    {
        "name": "github.com/dgrijalva/jwt-go",
        "ecosystem": "go",
        "kind": "abandoned",
        "severity": "error",
        "message": "dgrijalva/jwt-go is unmaintained; switch to github.com/golang-jwt/jwt",
    },
    {
        "name": "org.apache.log4j",
        "ecosystem": "java",
        "kind": "insecure",
        "severity": "error",
        "message": "Log4j 1.x is EOL and has unfixed RCE classes; use log4j-core 2.17.1+ or reload4j with care",
    },
    {
        "name": "rustc-serialize",
        "ecosystem": "cargo",
        "kind": "abandoned",
        "severity": "warning",
        "message": "rustc-serialize is unmaintained; use serde",
    },
]


def run_packages(
    root: Path,
    config: QualityConfig,
    languages: list[str] | None = None,
    *,
    base: str | None = None,
    diff: str | None = None,
) -> GateResult:
    if not config.packages_enabled:
        return skip_result("packages", "packages gate disabled")
    text = load_review_diff(root, config, base=base, diff=diff)
    if text is None:
        return skip_result("packages", "no diff against the review base")
    if not _has_package_surface(languages or [], text):
        return skip_result("packages", "no package-import language in this change")
    skip_globs = config.review_skip_globs or []
    declared = load_declared_packages(root)
    local_py = _local_python_names(root)
    risks = _compiled_risks(config)
    findings = scan_diff(
        text,
        risks=risks,
        declared=declared,
        local_python=local_py,
        require_declared=config.packages_require_declared,
        allow=set(name.lower() for name in config.packages_allow),
        skip_globs=skip_globs,
    )
    notes = [
        f"{len(risks)} risk rule(s)",
        f"{len(findings)} hit(s)",
        "require_declared=" + ("on" if config.packages_require_declared else "off"),
    ]
    return fail_or_pass("packages", findings, notes)


def scan_diff(
    diff: str,
    *,
    risks: list[dict[str, str]],
    declared: dict[str, set[str]],
    local_python: set[str],
    require_declared: bool,
    allow: set[str],
    skip_globs: list[str],
) -> list[Finding]:
    findings: list[Finding] = []
    for current, new_line, line in iter_added_lines(diff):
        if path_skipped(current, skip_globs):
            continue
        ecosystem = _path_ecosystem(current)
        names = _names_from_line(current, line, ecosystem)
        for package, eco in names:
            key = package.lower()
            if key in allow or f"{eco}:{key}" in allow:
                continue
            risk = _match_risk(risks, package, eco)
            if risk:
                findings.append(
                    _finding(
                        current,
                        new_line,
                        rule="package-risk",
                        severity=risk.get("severity") or "error",
                        message=f"{package}: {risk['message']}",
                        suggestion=(
                            "remove the dependency, or "
                            f"`quality ignore add --rule package-risk --path {current}`"
                        ),
                    )
                )
            elif (
                require_declared
                and not _is_manifest(current)
                and _looks_third_party(package, eco, local_python)
                and not _is_declared(declared, package, eco)
            ):
                findings.append(
                    _finding(
                        current,
                        new_line,
                        rule="undeclared-import",
                        severity="error",
                        message=(
                            f"{package} is imported but not declared in the "
                            f"{eco} manifest"
                        ),
                        suggestion=(
                            f"add {package} to the {eco} manifest, or "
                            f"`quality ignore add --rule undeclared-import --path {current}`"
                        ),
                    )
                )
    return findings


def load_declared_packages(root: Path) -> dict[str, set[str]]:
    out: dict[str, set[str]] = {
        "python": set(),
        "npm": set(),
        "go": set(),
        "cargo": set(),
        "java": set(),
        "nuget": set(),
        "composer": set(),
        "rubygems": set(),
        "hex": set(),
        "pub": set(),
    }
    pyproject = root / "pyproject.toml"
    if pyproject.is_file():
        out["python"].update(_pyproject_names(pyproject))
    for req in root.glob("requirements*.txt"):
        out["python"].update(_requirements_names(req))
    package = root / "package.json"
    if package.is_file():
        out["npm"].update(_npm_names(package))
    go_mod = root / "go.mod"
    if go_mod.is_file():
        out["go"].update(_gomod_names(go_mod))
    cargo = root / "Cargo.toml"
    if cargo.is_file():
        out["cargo"].update(_cargo_names(cargo))
    composer = root / "composer.json"
    if composer.is_file():
        out["composer"].update(_npm_like_names(composer))
    gemfile = root / "Gemfile"
    if gemfile.is_file():
        out["rubygems"].update(_gemfile_names(gemfile))
    return out


def _compiled_risks(config: QualityConfig) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    if config.packages_include_defaults:
        rows.extend(DEFAULT_RISKS)
    for item in config.packages_deny:
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        rows.append(
            {
                "name": name,
                "ecosystem": str(item.get("ecosystem") or "").strip().lower(),
                "kind": str(item.get("kind") or "deny"),
                "severity": str(item.get("severity") or "error"),
                "message": str(
                    item.get("message") or f"{name} is denied by quality.packages"
                ),
            }
        )
    return rows


def _match_risk(
    risks: list[dict[str, str]], package: str, ecosystem: str
) -> dict[str, str] | None:
    needle = package.lower().rstrip("/")
    for item in risks:
        name = str(item.get("name") or "").lower().rstrip("/")
        eco = str(item.get("ecosystem") or "").lower()
        if not name:
            continue
        if eco and eco != ecosystem:
            continue
        if (
            needle == name
            or needle.startswith(name + ".")
            or needle.startswith(name + "/")
        ):
            return item
        aliases = str(item.get("aliases") or "")
        if aliases and needle in {part.strip().lower() for part in aliases.split(",")}:
            return item
    return None


def _names_from_line(path: str, line: str, ecosystem: str) -> list[tuple[str, str]]:
    name = Path(path.replace("\\", "/")).name.lower()
    if name in {"package.json", "package-lock.json"} or name.endswith("-lock.json"):
        match = NPM_DEP_LINE.search(line)
        return [(match.group(1), "npm")] if match else []
    if name in {"pyproject.toml", "pipfile"}:
        stripped = line.strip().rstrip(",")
        quoted = re.match(r"""^["']([A-Za-z0-9][A-Za-z0-9._-]*)""", stripped)
        if quoted:
            return [(quoted.group(1), "python")]
        return []
    if name.startswith("requirements"):
        match = PEP508_LINE.match(line.strip())
        return [(match.group(1), "python")] if match else []
    if name == "go.mod":
        match = GO_REQUIRE.match(line)
        return [(match.group(1), "go")] if match else []
    if name == "cargo.toml":
        match = CARGO_DEP.match(line)
        return [(match.group(1), "cargo")] if match else []
    if name == "composer.json":
        match = NPM_DEP_LINE.search(line)
        return [(match.group(1), "composer")] if match else []
    if name == "gemfile":
        match = GEM_LINE.match(line)
        return [(match.group(1), "rubygems")] if match else []
    if ecosystem == "python":
        return [(item, "python") for item in _python_imported(line)]
    if ecosystem == "npm":
        return [(item, "npm") for item in _js_imported(line)]
    if ecosystem == "go":
        return [
            (item, "go")
            for item in GO_IMPORT.findall(line)
            if "/" in item or "." in item
        ]
    if ecosystem == "cargo":
        found: list[tuple[str, str]] = []
        for match in RS_USE.finditer(line):
            crate = match.group(1).split("::", 1)[0]
            if crate not in {"crate", "self", "super", "std", "core", "alloc"}:
                found.append((crate.replace("_", "-"), "cargo"))
        return found
    if ecosystem == "java":
        return [(item, "java") for item in JAVA_IMPORT.findall(line)]
    if ecosystem == "composer":
        return [(item.replace("\\", "/"), "composer") for item in PHP_USE.findall(line)]
    if ecosystem == "rubygems":
        return [
            (item, "rubygems")
            for item in RB_REQUIRE.findall(line)
            if not item.startswith(".")
        ]
    if ecosystem == "nuget":
        return [(item, "nuget") for item in CS_USING.findall(line)]
    return []


def _python_imported(line: str) -> list[str]:
    found: list[str] = []
    for match in PY_IMPORT.finditer(line):
        module = (match.group(1) or match.group(2) or "").strip()
        if not module or module.startswith("."):
            continue
        top = module.split(".", 1)[0]
        found.append(PY_IMPORT_TO_DIST.get(top, top))
    return found


def _js_imported(line: str) -> list[str]:
    found: list[str] = []
    for match in JS_IMPORT.finditer(line):
        spec = match.group(1).strip()
        if not spec or spec.startswith((".", "/", "node:")):
            continue
        if spec.startswith("@"):
            parts = spec.split("/")
            found.append("/".join(parts[:2]) if len(parts) >= 2 else spec)
            continue
        found.append(spec.split("/", 1)[0])
    return found


def _looks_third_party(package: str, ecosystem: str, local_python: set[str]) -> bool:
    name = package.split(".", 1)[0]
    if ecosystem == "python":
        return name not in PY_STDLIB and name not in local_python
    if ecosystem == "npm":
        core = name[5:] if name.startswith("node:") else name
        return core not in NODE_BUILTINS
    if ecosystem == "go":
        first = package.split("/", 1)[0]
        return "." in first
    if ecosystem == "cargo":
        return name not in {"std", "core", "alloc"}
    if ecosystem == "java":
        return not package.startswith(("java.", "javax.", "jakarta."))
    if ecosystem == "nuget":
        return not package.startswith("System")
    return True


def _is_declared(declared: dict[str, set[str]], package: str, ecosystem: str) -> bool:
    known = declared.get(ecosystem) or set()
    lowered = {item.lower() for item in known}
    needle = package.lower()
    if needle in lowered:
        return True
    if ecosystem == "python":
        dist = PY_IMPORT_TO_DIST.get(package, package).lower()
        return dist in lowered or needle.replace("_", "-") in lowered
    if ecosystem == "npm" and "/" in needle:
        return needle.split("/", 1)[0] in lowered or needle in lowered
    if ecosystem == "go":
        return any(needle == item or needle.startswith(item + "/") for item in lowered)
    if ecosystem == "java":
        return any(needle == item or needle.startswith(item + ".") for item in lowered)
    return needle.replace("_", "-") in lowered


def _is_manifest(path: str) -> bool:
    name = Path(path.replace("\\", "/")).name.lower()
    return name in {
        "package.json",
        "package-lock.json",
        "pnpm-lock.yaml",
        "yarn.lock",
        "pyproject.toml",
        "pipfile",
        "go.mod",
        "go.sum",
        "cargo.toml",
        "cargo.lock",
        "composer.json",
        "composer.lock",
        "gemfile",
        "gemfile.lock",
        "pom.xml",
        "build.gradle",
        "build.gradle.kts",
    } or name.startswith("requirements")


def _has_package_surface(languages: list[str], diff: str) -> bool:
    if any(PACKAGE_LANGS.get(item) for item in languages):
        return True
    for raw in diff.splitlines():
        if raw.startswith("+++ b/") and _path_ecosystem(raw[6:].strip()):
            return True
    return False


def _path_ecosystem(path: str) -> str:
    posix = path.replace("\\", "/").lstrip("./")
    name = Path(posix).name.lower()
    suffix = Path(posix).suffix.lower()
    if name in {"package.json", "package-lock.json", "pnpm-lock.yaml", "yarn.lock"}:
        return "npm"
    if name in {"pyproject.toml", "pipfile"} or name.startswith("requirements"):
        return "python"
    if name in {"go.mod", "go.sum"}:
        return "go"
    if name in {"cargo.toml", "cargo.lock"}:
        return "cargo"
    if name in {"composer.json", "composer.lock"}:
        return "composer"
    if name in {"gemfile", "gemfile.lock"}:
        return "rubygems"
    if suffix in {".py", ".pyi"}:
        return "python"
    if suffix in {".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", ".vue", ".svelte"}:
        return "npm"
    if suffix == ".go":
        return "go"
    if suffix == ".rs":
        return "cargo"
    if suffix in {".java", ".kt", ".kts"}:
        return "java"
    if suffix == ".cs":
        return "nuget"
    if suffix == ".php":
        return "composer"
    if suffix == ".rb":
        return "rubygems"
    if suffix in {".ex", ".exs"}:
        return "hex"
    if suffix == ".dart":
        return "pub"
    return ""


def _local_python_names(root: Path) -> set[str]:
    names: set[str] = set()
    for base in (root, root / "src"):
        if not base.is_dir():
            continue
        for child in base.iterdir():
            if child.name.startswith("."):
                continue
            if child.suffix == ".py":
                names.add(child.stem)
            elif child.is_dir() and (
                (child / "__init__.py").is_file() or (child / "py.typed").is_file()
            ):
                names.add(child.name)
    return names


def _pyproject_names(path: Path) -> set[str]:
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return set()
    names: set[str] = set()
    project = data.get("project") if isinstance(data.get("project"), dict) else {}
    for item in project.get("dependencies") or []:
        names.update(_pep508(item))
    optional = project.get("optional-dependencies") or {}
    if isinstance(optional, dict):
        for rows in optional.values():
            if isinstance(rows, list):
                for item in rows:
                    names.update(_pep508(item))
    groups = data.get("dependency-groups") or {}
    if isinstance(groups, dict):
        for rows in groups.values():
            if isinstance(rows, list):
                for item in rows:
                    names.update(_pep508(item))
    uv = (
        data.get("tool", {}).get("uv", {}) if isinstance(data.get("tool"), dict) else {}
    )
    if isinstance(uv, dict):
        for item in uv.get("dev-dependencies") or []:
            names.update(_pep508(item))
    return names


def _requirements_names(path: Path) -> set[str]:
    names: set[str] = set()
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return names
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line or line.startswith("-"):
            continue
        names.update(_pep508(line))
    return names


def _pep508(value: Any) -> set[str]:
    text = str(value or "").strip()
    if not text:
        return set()
    match = re.match(r"([A-Za-z0-9][A-Za-z0-9._-]*)", text)
    return {match.group(1).lower().replace("_", "-")} if match else set()


def _npm_names(path: Path) -> set[str]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return set()
    names: set[str] = set()
    for key in (
        "dependencies",
        "devDependencies",
        "optionalDependencies",
        "peerDependencies",
    ):
        block = data.get(key)
        if isinstance(block, dict):
            names.update(str(item).lower() for item in block)
    return names


def _npm_like_names(path: Path) -> set[str]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return set()
    names: set[str] = set()
    for key in ("require", "require-dev"):
        block = data.get(key)
        if isinstance(block, dict):
            names.update(str(item).lower() for item in block)
    return names


def _gomod_names(path: Path) -> set[str]:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return set()
    names: set[str] = set()
    for match in re.finditer(r"^\s*([a-zA-Z0-9._/-]+)\s+v\d", text, re.M):
        names.add(match.group(1).lower())
    return names


def _cargo_names(path: Path) -> set[str]:
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return set()
    names: set[str] = set()
    for key in ("dependencies", "dev-dependencies", "build-dependencies"):
        block = data.get(key)
        if isinstance(block, dict):
            names.update(str(item).lower() for item in block)
    return names


def _gemfile_names(path: Path) -> set[str]:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return set()
    return {match.group(1).lower() for match in GEM_LINE.finditer(text)}


def _finding(
    path: str,
    line: int,
    *,
    rule: str,
    severity: str,
    message: str,
    suggestion: str,
) -> Finding:
    return Finding(
        gate="packages",
        rule=rule,
        path=path,
        line=line,
        severity=severity,
        message=message,
        suggestion=suggestion,
    )
