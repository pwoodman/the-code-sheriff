from __future__ import annotations

import configparser
import json
import re
import tomllib
import xml.etree.ElementTree as ET
from abc import ABC, abstractmethod
from collections.abc import Iterable
from dataclasses import dataclass, field
from importlib import metadata
from pathlib import Path
from typing import Any, ClassVar, Protocol, runtime_checkable

from quality_gates.config import QualityConfig
from quality_gates.diagnostics import enrich_findings
from quality_gates.gates.common import execution_details, findings_from_text
from quality_gates.models import Finding, GateResult
from quality_gates.registry import PROFILES, CapabilityProfile
from quality_gates.result_cache import cached_result
from quality_gates.tools import run, which

ADAPTER_ENTRY_POINT_GROUP = "quality_gates.adapters"
ADAPTER_API_VERSION = 1


@dataclass(frozen=True)
class AdapterMetadata:
    name: str
    languages: tuple[str, ...]
    capabilities: tuple[str, ...]
    tools: tuple[str, ...] = ()
    api_version: int = ADAPTER_API_VERSION
    safety_class: str = "static"
    scopes: tuple[str, ...] = ("file",)
    prerequisites: tuple[str, ...] = ()
    permissions: tuple[str, ...] = ("read-only",)
    output_schema: str = "quality-gates/gate-result/v1"
    cacheable: bool = False


@dataclass(frozen=True)
class AdapterContext:
    root: Path
    config: QualityConfig
    language: str
    capability: str
    files: tuple[Path, ...] = ()
    options: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class Adapter(Protocol):
    metadata: AdapterMetadata

    def run(self, context: AdapterContext) -> GateResult: ...


class BaseAdapter(ABC):
    """Stable phase-one base class for built-in and entry-point adapters."""

    metadata: ClassVar[AdapterMetadata]

    @abstractmethod
    def run(self, context: AdapterContext) -> GateResult:
        raise RuntimeError("adapter subclasses must implement run()")


def adapter_entry_points() -> Iterable[metadata.EntryPoint]:
    """Return installed adapters without importing them."""
    discovered = metadata.entry_points()
    if hasattr(discovered, "select"):
        return discovered.select(group=ADAPTER_ENTRY_POINT_GROUP)
    return discovered.get(ADAPTER_ENTRY_POINT_GROUP, ())  # type: ignore[union-attr]


def discover_adapters() -> dict[str, type[BaseAdapter] | Adapter]:
    """Load adapters registered under ``quality_gates.adapters``.

    Third-party adapters are optional. Invalid API versions fail explicitly when
    discovered so plugin incompatibility cannot silently alter a gate run.
    """
    loaded: dict[str, type[BaseAdapter] | Adapter] = {}
    for entry_point in adapter_entry_points():
        candidate = entry_point.load()
        metadata_value = getattr(candidate, "metadata", None)
        if not isinstance(metadata_value, AdapterMetadata):
            raise TypeError(f"adapter {entry_point.name!r} has no AdapterMetadata")
        if metadata_value.api_version != ADAPTER_API_VERSION:
            raise ValueError(
                f"adapter {entry_point.name!r} uses API {metadata_value.api_version}; "
                f"expected {ADAPTER_API_VERSION}"
            )
        if not metadata_value.scopes or not metadata_value.output_schema:
            raise ValueError(
                f"adapter {entry_point.name!r} must declare scope and output schema"
            )
        if not metadata_value.permissions:
            raise ValueError(
                f"adapter {entry_point.name!r} must declare execution permissions"
            )
        loaded[entry_point.name] = candidate
    return loaded


def run_adapter_safe(
    adapter: BaseAdapter | Adapter, context: AdapterContext
) -> GateResult:
    """Isolate plugin failures from crashing the orchestrator."""
    meta = getattr(adapter, "metadata", None)
    name = getattr(meta, "tools", ("plugin",))[0] if meta and meta.tools else "plugin"
    try:
        return adapter.run(context)
    except Exception as exc:
        return GateResult(
            name=name,
            status="fail",
            exit_state="errored",
            findings=[
                Finding(
                    gate=name,
                    rule="plugin-exception",
                    message=f"plugin execution failed: {exc}",
                    severity="error",
                )
            ],
            notes=[f"plugin exception: {type(exc).__name__}: {exc}"],
        )


@dataclass(frozen=True)
class CommandTemplate:
    """A non-shell command template for a built-in external adapter."""

    tool: str
    check: tuple[str, ...]
    write: tuple[str, ...] | None = None
    files_at_end: bool = True


FORMAT_COMMANDS: dict[str, CommandTemplate] = {
    "c": CommandTemplate("clang-format", ("--dry-run", "--Werror"), ("-i",)),
    "cpp": CommandTemplate("clang-format", ("--dry-run", "--Werror"), ("-i",)),
    "php": CommandTemplate("php-cs-fixer", ("fix", "--dry-run", "--diff"), ("fix",)),
    "ruby": CommandTemplate("rubocop", ("--format", "json"), ("--autocorrect",)),
    "swift": CommandTemplate("swift-format", ("lint",), ("format", "--in-place")),
    "kotlin": CommandTemplate("ktlint", (), ("-F",)),
    "dart": CommandTemplate(
        "dart",
        ("format", "--output=none", "--set-exit-if-changed"),
        ("format",),
    ),
    "scala": CommandTemplate("scalafmt", ("--test",), ()),
    "lua": CommandTemplate("stylua", ("--check",), ()),
    "r": CommandTemplate("air", ("format", "--check"), ("format",)),
    "matlab": CommandTemplate("mh_style", (), ("--fix",)),
    "shell": CommandTemplate("shfmt", ("-d",), ("-w",)),
    "fish": CommandTemplate("fish_indent", ("--check",), ("--write",)),
    "toml": CommandTemplate("tombi", ("format", "--check"), ("format",)),
    "yaml": CommandTemplate("prettier", ("--check",), ("--write",)),
    "markdown": CommandTemplate("prettier", ("--check",), ("--write",)),
    "json": CommandTemplate("prettier", ("--check",), ("--write",)),
    "jsonc": CommandTemplate("prettier", ("--check",), ("--write",)),
    "json5": CommandTemplate("prettier", ("--check",), ("--write",)),
    "html": CommandTemplate("prettier", ("--check",), ("--write",)),
    "css": CommandTemplate("prettier", ("--check",), ("--write",)),
    "scss": CommandTemplate("prettier", ("--check",), ("--write",)),
    "less": CommandTemplate("prettier", ("--check",), ("--write",)),
    "github_actions": CommandTemplate("prettier", ("--check",), ("--write",)),
}

LINT_COMMANDS: dict[str, CommandTemplate] = {
    "c": CommandTemplate("clang-tidy", ()),
    "cpp": CommandTemplate("clang-tidy", ()),
    "php": CommandTemplate("phpstan", ("analyse", "--error-format=json")),
    "ruby": CommandTemplate("rubocop", ("--format", "json")),
    "swift": CommandTemplate("swiftlint", ("lint", "--reporter", "json")),
    "kotlin": CommandTemplate("detekt", ("--input",), files_at_end=False),
    "dart": CommandTemplate("dart", ("analyze", "--format", "machine")),
    "scala": CommandTemplate("scalafix", ("--check",)),
    "lua": CommandTemplate("luacheck", ("--formatter", "plain")),
    "r": CommandTemplate(
        "R", ("--slave", "-e", "lintr::lint_dir('.')"), files_at_end=False
    ),
    "matlab": CommandTemplate("mh_lint", ()),
    "shell": CommandTemplate("shellcheck", ("--format", "gcc")),
    "zsh": CommandTemplate("zsh", ("-n",)),
    "fish": CommandTemplate("fish", ("-n",)),
    "yaml": CommandTemplate("yamllint", ("--format", "parsable")),
    "markdown": CommandTemplate("markdownlint-cli2", ()),
    "css": CommandTemplate("stylelint", ()),
    "scss": CommandTemplate("stylelint", ()),
    "less": CommandTemplate("stylelint", ()),
    "dockerfile": CommandTemplate("hadolint", ("--format", "json")),
    "makefile": CommandTemplate("checkmake", ()),
    "github_actions": CommandTemplate("actionlint", ("-format", "{{json .}}")),
    "dotenv": CommandTemplate("dotenv-linter", ("check",)),
    "xml": CommandTemplate("xmllint", ("--nonet", "--noout")),
    "toml": CommandTemplate("tombi", ("lint",)),
    "git": CommandTemplate(
        "git", ("config", "--no-includes", "--file"), files_at_end=False
    ),
}


def command_argv(
    template: CommandTemplate, executable: str, files: tuple[Path, ...], *, check: bool
) -> list[str] | None:
    """Build an argument array. ``None`` means writing is intentionally unsupported."""
    args = template.check if check else template.write
    if args is None:
        return None
    argv = [executable, *args]
    if template.files_at_end:
        argv.extend(str(path) for path in files)
    elif template.tool == "detekt":
        argv.append(",".join(str(path) for path in files))
    elif template.tool == "git" and files:
        argv.extend([str(files[0]), "--list"])
    return argv


def run_builtin_profile(
    root: Path,
    config: QualityConfig,
    profile_id: str,
    capability: str,
    files: tuple[Path, ...],
    *,
    check: bool = True,
) -> GateResult:
    """Dispatch a registry profile to a built-in validator or command adapter."""
    profile = PROFILES[profile_id]
    template = (
        LINT_COMMANDS.get(profile_id)
        if capability in {"lint", "validate"}
        else FORMAT_COMMANDS.get(profile_id)
    )
    validators = [item.name for item in profile.tools.get("validate", ())]
    builtin = next((name for name in validators if name.startswith("builtin-")), None)
    tool = template.tool if template else builtin
    if not check:
        return _run_builtin_profile(
            root, config, profile_id, capability, files, check=check
        )
    return cached_result(
        root,
        config,
        profile_id,
        capability,
        files,
        tool=tool,
        compute=lambda: _run_builtin_profile(
            root, config, profile_id, capability, files, check=check
        ),
    )


def _run_builtin_profile(
    root: Path,
    config: QualityConfig,
    profile_id: str,
    capability: str,
    files: tuple[Path, ...],
    *,
    check: bool = True,
) -> GateResult:
    profile = PROFILES[profile_id]
    if profile_id == "git":
        files = tuple(
            path for path in files if path.name.lower() in {".gitconfig", ".gitmodules"}
        )
        if not files:
            return _skip(capability, "no safely parseable git config files")
    if capability == "format" and profile.format_policy != "tool":
        return _skip(
            capability, f"{profile.display_name} formatting policy is preserve"
        )
    builtin_result: GateResult | None = None
    if capability in {"lint", "validate"}:
        builtin_result = _run_builtin_validator(profile, files, root)
        template = LINT_COMMANDS.get(profile_id)
    else:
        template = FORMAT_COMMANDS.get(profile_id)
    if template is None:
        if builtin_result is not None:
            return builtin_result
        return _skip(capability, f"no {capability} adapter for {profile.display_name}")
    executable = which(
        template.tool, project=root, prefer_project=config.prefer_project_tools
    )
    if not executable:
        if builtin_result is not None:
            builtin_result.notes.append(
                f"optional {template.tool} is not installed; built-in validation ran"
            )
            builtin_result.skipped_tools.append(template.tool)
            return builtin_result
        return _skip(
            capability,
            f"{template.tool} is not installed; {profile.display_name} {capability} skipped",
            template.tool,
        )
    argv = command_argv(template, executable, files, check=check)
    if argv is None:
        return _skip(
            capability,
            f"{profile.display_name} adapter is validation-only",
            template.tool,
        )
    result = run(argv, cwd=root)
    findings = list(builtin_result.findings) if builtin_result else []
    findings.extend(
        findings_from_text(
            capability,
            result,
            language=profile_id if profile.kind == "language" else None,
            default_message=f"{template.tool} exited {result.returncode}",
            root=root,
        )
    )
    findings = enrich_findings(findings, root, result)
    return GateResult(
        name=capability,
        status=(
            "fail" if any(item.severity == "error" for item in findings) else "pass"
        ),
        findings=findings,
        notes=[
            *(builtin_result.notes if builtin_result else []),
            f"{template.tool} checked {len(files)} file(s)",
        ],
        **execution_details(result),
    )


def _run_builtin_validator(
    profile: CapabilityProfile, files: tuple[Path, ...], root: Path | None = None
) -> GateResult | None:
    validators = [item.name for item in profile.tools.get("validate", ())]
    builtin = next((name for name in validators if name.startswith("builtin-")), None)
    if not builtin:
        return None
    findings: list[Finding] = []
    for path in files:
        findings.extend(_validate_file(profile.id, builtin, path))
    return GateResult(
        name="lint",
        status=(
            "fail" if any(item.severity == "error" for item in findings) else "pass"
        ),
        findings=enrich_findings(findings, root),
        notes=[f"{builtin} checked {len(files)} file(s)"],
        tool=builtin,
        safety="non-executing",
    )


def _validate_file(profile_id: str, validator: str, path: Path) -> list[Finding]:
    try:
        raw = path.read_bytes()
        text = raw.decode("utf-8-sig")
        if validator == "builtin-json":
            json.loads(text)
        elif validator == "builtin-toml":
            tomllib.loads(text)
        elif validator == "builtin-xml":
            if re.search(r"<!DOCTYPE|<!ENTITY", text, re.IGNORECASE):
                raise ValueError("DOCTYPE/entity declarations are not accepted")
            ET.fromstring(text)
        elif validator == "builtin-ini":
            parser = configparser.ConfigParser(
                interpolation=None, strict=True, empty_lines_in_values=False
            )
            parser.read_string(text)
        elif validator == "builtin-dotenv":
            return _validate_dotenv(path, text)
        elif validator == "builtin-properties":
            return _validate_properties(path, text)
        elif validator == "builtin-batch":
            return _validate_batch(path, text)
    except (
        OSError,
        UnicodeError,
        ValueError,
        json.JSONDecodeError,
        tomllib.TOMLDecodeError,
        ET.ParseError,
        configparser.Error,
    ) as exc:
        return [_validation_finding(profile_id, path, str(exc), validator)]
    return []


_ENV_KEY = re.compile(r"^[A-Za-z_][A-Za-z0-9_.-]*$")


def _validate_dotenv(path: Path, text: str) -> list[Finding]:
    findings: list[Finding] = []
    seen: dict[str, int] = {}
    for line_no, line in enumerate(text.splitlines(), 1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("export "):
            stripped = stripped[7:].lstrip()
        if "=" not in stripped:
            findings.append(
                _validation_finding("dotenv", path, "missing '='", "dotenv", line_no)
            )
            continue
        key = stripped.split("=", 1)[0].strip()
        if not _ENV_KEY.fullmatch(key):
            findings.append(
                _validation_finding(
                    "dotenv", path, f"invalid key {key!r}", "dotenv", line_no
                )
            )
        elif key in seen:
            findings.append(
                _validation_finding(
                    "dotenv",
                    path,
                    f"duplicate key {key!r} (first at line {seen[key]})",
                    "dotenv",
                    line_no,
                )
            )
        else:
            seen[key] = line_no
    return findings


def _validate_properties(path: Path, text: str) -> list[Finding]:
    findings: list[Finding] = []
    continuation = False
    for line_no, line in enumerate(text.splitlines(), 1):
        stripped = line.lstrip()
        if not continuation and stripped and not stripped.startswith(("#", "!")):
            for match in re.finditer(r"\\u([0-9A-Fa-f]{0,4})", stripped):
                if len(match.group(1)) != 4:
                    findings.append(
                        _validation_finding(
                            "properties",
                            path,
                            "malformed Unicode escape",
                            "properties",
                            line_no,
                        )
                    )
            if "\x00" in stripped:
                findings.append(
                    _validation_finding(
                        "properties",
                        path,
                        "NUL byte in property",
                        "properties",
                        line_no,
                    )
                )
        continuation = (len(line) - len(line.rstrip("\\"))) % 2 == 1
    if continuation:
        findings.append(
            _validation_finding(
                "properties", path, "unterminated continuation", "properties"
            )
        )
    return findings


def _validate_batch(path: Path, text: str) -> list[Finding]:
    findings: list[Finding] = []
    parens = 0
    labels: set[str] = set()
    gotos: list[tuple[int, str]] = []
    for line_no, line in enumerate(text.splitlines(), 1):
        stripped = line.strip()
        if not stripped or stripped.lower().startswith(("rem ", "::")):
            continue
        if "\x00" in line:
            findings.append(
                _validation_finding(
                    "batch",
                    path,
                    "NUL byte in command",
                    "batch",
                    line_no,
                    severity="warning",
                )
            )
        parens += line.count("(") - line.count(")")
        if stripped.startswith(":") and not stripped.startswith("::"):
            labels.add(stripped[1:].split()[0].lower())
        match = re.match(r"(?i)goto\s+:?([^\s&|<>]+)", stripped)
        if match:
            gotos.append((line_no, match.group(1).lower()))
    if parens:
        findings.append(
            _validation_finding(
                "batch",
                path,
                "unbalanced parentheses",
                "batch",
                severity="warning",
            )
        )
    for line_no, label in gotos:
        if label != "eof" and label not in labels:
            findings.append(
                _validation_finding(
                    "batch",
                    path,
                    f"goto target {label!r} is undefined",
                    "batch",
                    line_no,
                    severity="warning",
                )
            )
    return findings


def _validation_finding(
    profile_id: str,
    path: Path,
    message: str,
    rule: str,
    line: int | None = None,
    severity: str = "error",
) -> Finding:
    return Finding(
        gate="lint",
        language=profile_id if PROFILES[profile_id].kind == "language" else None,
        path=str(path),
        line=line,
        message=message,
        rule=rule,
        severity=severity,
    )


def _path_from_line(line: str, root: Path) -> str | None:
    candidate = line.split(":", 1)[0].strip()
    path = Path(candidate)
    if path.is_absolute() or (root / path).exists():
        return candidate
    return None


def _skip(name: str, reason: str, tool: str | None = None) -> GateResult:
    return GateResult(
        name=name,
        status="skip",
        notes=[reason],
        skipped_tools=[tool] if tool else [],
    )
