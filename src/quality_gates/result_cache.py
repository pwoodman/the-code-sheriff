from __future__ import annotations

import hashlib
import json
import shutil
from collections.abc import Callable
from contextlib import suppress
from pathlib import Path
from typing import Any

from quality_gates.config import QualityConfig
from quality_gates.models import Finding, GateResult
from quality_gates.paths import cache_dir
from quality_gates.tool_manifest import atomic_write, cache_lock
from quality_gates.tools import tool_version, which

CACHE_VERSION = 1


def result_cache_dir() -> Path:
    return cache_dir() / "results-v1"


def cache_key(
    root: Path,
    config: QualityConfig,
    profile: str,
    capability: str,
    files: tuple[Path, ...],
    *,
    tool: str | None,
) -> str:
    digest = hashlib.sha256()
    metadata = {
        "cache_version": CACHE_VERSION,
        "profile": profile,
        "capability": capability,
        "config": config.raw,
        "tool": tool,
        "tool_version": _version(root, config, tool),
    }
    digest.update(json.dumps(metadata, sort_keys=True, separators=(",", ":")).encode())
    for path in sorted(files, key=lambda item: item.as_posix()):
        try:
            relative = path.resolve().relative_to(root.resolve()).as_posix()
            content = path.read_bytes()
        except (OSError, ValueError):
            relative = path.as_posix()
            content = b"<unreadable>"
        digest.update(relative.encode("utf-8", errors="surrogateescape"))
        digest.update(b"\0")
        digest.update(hashlib.sha256(content).digest())
    return digest.hexdigest()


def cached_result(
    root: Path,
    config: QualityConfig,
    profile: str,
    capability: str,
    files: tuple[Path, ...],
    *,
    tool: str | None,
    compute: Callable[[], GateResult],
) -> GateResult:
    if not config.cache_enabled:
        return compute()
    key = cache_key(root, config, profile, capability, files, tool=tool)
    path = result_cache_dir() / key[:2] / f"{key}.json"
    lock = path.with_suffix(".lock")
    entered = False
    try:
        with cache_lock(lock):
            entered = True
            return _read_or_compute(path, compute)
    except OSError:
        if entered:
            raise
        # Read-only homes and sandboxed CI must not make a deterministic check fail.
        return compute()


def cache_status() -> dict[str, int | str]:
    directory = result_cache_dir()
    files = list(directory.glob("*/*.json")) if directory.is_dir() else []
    size = sum(path.stat().st_size for path in files if path.is_file())
    return {"path": str(directory), "entries": len(files), "bytes": size}


def clean_cache() -> dict[str, int | str]:
    status = cache_status()
    shutil.rmtree(result_cache_dir(), ignore_errors=True)
    return status


def _read_or_compute(path: Path, compute: Callable[[], GateResult]) -> GateResult:
    if path.is_file():
        try:
            result = _decode(json.loads(path.read_text(encoding="utf-8")))
            result.notes.append("deterministic cache hit")
            return result
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            path.unlink(missing_ok=True)
    result = compute()
    with suppress(OSError):
        atomic_write(
            path,
            (json.dumps(result.to_dict(), sort_keys=True) + "\n").encode("utf-8"),
        )
    return result


def _version(root: Path, config: QualityConfig, tool: str | None) -> str | None:
    if not tool or tool.startswith("builtin-"):
        return str(CACHE_VERSION) if tool else None
    executable = which(tool, project=root, prefer_project=config.prefer_project_tools)
    return tool_version(executable or tool) if executable else None


def _decode(payload: dict[str, Any]) -> GateResult:
    findings = [Finding(**item) for item in payload.get("findings", [])]
    return GateResult(
        name=str(payload["name"]),
        status=str(payload["status"]),
        findings=findings,
        notes=list(payload.get("notes", [])),
        skipped_tools=list(payload.get("skipped_tools", [])),
        duration_ms=payload.get("duration_ms"),
        tool=payload.get("tool"),
        tool_version=payload.get("tool_version"),
        raw_artifacts=list(payload.get("raw_artifacts", [])),
        safety=payload.get("safety"),
        exit_state=payload.get("exit_state"),
        tool_errors=list(payload.get("tool_errors", [])),
        command=list(payload.get("command", [])),
        working_directory=payload.get("working_directory"),
        return_code=payload.get("return_code"),
        output_excerpt=payload.get("output_excerpt"),
    )
