"""Compatibility checks for changed JSON-schema style public contracts."""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

from quality_gates.change_manifest import discover_changes
from quality_gates.config import QualityConfig
from quality_gates.gates.common import fail_or_pass, skip_result
from quality_gates.models import Finding, GateResult


def run_contract(root: Path, config: QualityConfig, *, base: str | None) -> GateResult:
    manifest = discover_changes(root, base)
    if manifest.state == "unknown":
        return GateResult(
            name="contract",
            status="blocked",
            notes=[manifest.reason or "contract base unavailable"],
            exit_state="blocked",
        )
    findings: list[Finding] = []
    for change in manifest.changes:
        if (
            change.kind == "deleted"
            or not _is_contract(change.path)
            or not manifest.base
        ):
            continue
        if _is_schema_text(change.path):
            current_text = _text(root / change.path)
            previous_text = _base_text(
                root, manifest.base, change.old_path or change.path
            )
            if current_text is None or previous_text is None:
                continue
            pairs = _schema_text_breaking(previous_text, current_text, change.path)
        else:
            current = _json(root / change.path)
            previous = _base_json(root, manifest.base, change.old_path or change.path)
            if current is None or previous is None:
                continue
            pairs = _contract_breaking_changes(previous, current)
        for rule, msg in pairs:
            findings.append(
                Finding(
                    gate="contract",
                    rule=rule,
                    path=change.path,
                    message=msg,
                    severity="error",
                )
            )
    if not any(_is_contract(item.path) for item in manifest.changes):
        return skip_result(
            "contract", "no changed JSON schema, OpenAPI, protobuf, or GraphQL contract"
        )
    return fail_or_pass(
        "contract", findings, ["compared changed contracts with base snapshot"]
    )


def _is_contract(path: str) -> bool:
    lower = path.lower()
    return (
        lower.endswith(".schema.json")
        or lower.endswith(".proto")
        or lower.endswith((".graphql", ".gql"))
        or "openapi" in lower
        or "swagger" in lower
    )


def _is_schema_text(path: str) -> bool:
    lower = path.lower()
    return lower.endswith((".proto", ".graphql", ".gql"))


def _text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return None


def _base_text(root: Path, base: str, path: str) -> str | None:
    result = subprocess.run(
        ["git", "show", f"{base}:{path}"],
        cwd=root,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode:
        return None
    return result.stdout


def _schema_text_breaking(
    previous: str, current: str, path: str
) -> list[tuple[str, str]]:
    if path.lower().endswith(".proto"):
        old = set(re.findall(r"^\s*(?:message|rpc|enum)\s+(\w+)", previous, re.M))
        new = set(re.findall(r"^\s*(?:message|rpc|enum)\s+(\w+)", current, re.M))
        old_fields = set(re.findall(r"^\s+\w+\s+(\w+)\s*=\s*\d+", previous, re.M))
        new_fields = set(re.findall(r"^\s+\w+\s+(\w+)\s*=\s*\d+", current, re.M))
    else:
        old = set(re.findall(r"^\s*(?:type|enum|interface)\s+(\w+)", previous, re.M))
        new = set(re.findall(r"^\s*(?:type|enum|interface)\s+(\w+)", current, re.M))
        old_fields = set(re.findall(r"^\s+(\w+)\s*[:\(]", previous, re.M))
        new_fields = set(re.findall(r"^\s+(\w+)\s*[:\(]", current, re.M))
    issues: list[tuple[str, str]] = []
    for name in sorted(old - new):
        issues.append(("type-removed", f"contract type or rpc removed: {name}"))
    for name in sorted(old_fields - new_fields):
        issues.append(("field-removed", f"contract field removed: {name}"))
    return issues


def _json(path: Path) -> dict | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except (OSError, json.JSONDecodeError):
        return None


def _base_json(root: Path, base: str, path: str) -> dict | None:
    result = subprocess.run(
        ["git", "show", f"{base}:{path}"],
        cwd=root,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode:
        return None
    try:
        data = json.loads(result.stdout)
        return data if isinstance(data, dict) else None
    except json.JSONDecodeError:
        return None


def _contract_breaking_changes(
    previous: dict, current: dict, prefix: str = ""
) -> list[tuple[str, str]]:
    issues: list[tuple[str, str]] = []
    old_required = set(previous.get("required") or [])
    new_required = set(current.get("required") or [])
    for field in sorted(old_required - new_required):
        issues.append(
            (
                "required-field-removed",
                f"required contract field removed: {prefix}{field}",
            )
        )
    old_properties = previous.get("properties") or {}
    new_properties = current.get("properties") or {}
    for key in sorted(set(old_properties.keys()) - set(new_properties.keys())):
        issues.append(("field-removed", f"contract property removed: {prefix}{key}"))
    for key, old in old_properties.items():
        if (
            key in new_properties
            and isinstance(old, dict)
            and isinstance(new_properties[key], dict)
        ):
            old_type = old.get("type")
            new_type = new_properties[key].get("type")
            if old_type and new_type and old_type != new_type:
                issues.append(
                    (
                        "type-changed",
                        f"property type changed from {old_type!r} to {new_type!r} at {prefix}{key}",
                    )
                )
            issues.extend(
                _contract_breaking_changes(old, new_properties[key], prefix + key + ".")
            )
    return issues
