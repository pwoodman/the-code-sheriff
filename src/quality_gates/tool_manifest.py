from __future__ import annotations

import json
import os
import platform
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from quality_gates.paths import bundled_file


@dataclass(frozen=True)
class ToolArtifact:
    platform: str
    url: str
    sha256: str | None = None


@dataclass(frozen=True)
class ToolSpec:
    id: str
    version: str | None
    commands: tuple[str, ...]
    version_args: tuple[str, ...]
    license: str
    platforms: tuple[str, ...]
    capabilities: tuple[str, ...]
    languages: tuple[str, ...]
    file_kinds: tuple[str, ...]
    install_supported: bool
    installer: str | None
    install_reason: str | None
    cache_path: str | None
    artifacts: tuple[ToolArtifact, ...]

    def supports_current_platform(self) -> bool:
        return platform_id() in self.platforms


@dataclass(frozen=True)
class ToolManifest:
    version: int
    tools: tuple[ToolSpec, ...]

    def by_id(self) -> dict[str, ToolSpec]:
        return {tool.id: tool for tool in self.tools}


def artifact_for_install(
    tool: ToolSpec,
    *,
    system: str | None = None,
    machine: str | None = None,
) -> ToolArtifact:
    if not tool.install_supported:
        raise RuntimeError(
            f"{tool.id} auto-install is unsupported: "
            f"{tool.install_reason or 'no verified installer is available'}"
        )
    os_id = system or platform_id()
    arch = (machine or platform.machine()).lower().replace("amd64", "x86_64")
    selectors = (f"{os_id}-{arch}", os_id, "any")
    artifact = next(
        (
            item
            for selector in selectors
            for item in tool.artifacts
            if item.platform == selector
        ),
        None,
    )
    if artifact is None:
        raise RuntimeError(f"{tool.id} has no artifact for {os_id}-{arch}")
    if not artifact.sha256:
        raise RuntimeError(
            f"{tool.id} artifact for {artifact.platform} has no verified SHA-256"
        )
    return artifact


def platform_id() -> str:
    name = platform.system().lower()
    if name.startswith("msys") or name.startswith("mingw"):
        return "windows"
    return {"macos": "darwin"}.get(name, name)


def load_tool_manifest(path: Path | None = None) -> ToolManifest:
    source = path or bundled_file("tool-manifest.json")
    payload = json.loads(source.read_text(encoding="utf-8"))
    if payload.get("manifest_version") != 1 or not isinstance(
        payload.get("tools"), list
    ):
        raise ValueError(f"unsupported tool manifest: {source}")
    tools: list[ToolSpec] = []
    seen: set[str] = set()
    for raw in payload["tools"]:
        tool_id = str(raw["id"])
        if tool_id in seen:
            raise ValueError(f"duplicate tool id in manifest: {tool_id}")
        seen.add(tool_id)
        install = raw.get("auto_install") or {}
        artifacts = tuple(
            ToolArtifact(
                platform=str(item["platform"]),
                url=str(item["url"]),
                sha256=str(item["sha256"]) if item.get("sha256") else None,
            )
            for item in raw.get("artifacts", [])
        )
        tools.append(
            ToolSpec(
                id=tool_id,
                version=str(raw["version"]) if raw.get("version") else None,
                commands=tuple(str(item) for item in raw.get("commands", [])),
                version_args=tuple(
                    str(item) for item in raw.get("version_args", ["--version"])
                ),
                license=str(raw.get("license", "UNKNOWN")),
                platforms=tuple(str(item) for item in raw.get("platforms", [])),
                capabilities=tuple(str(item) for item in raw.get("capabilities", [])),
                languages=tuple(str(item) for item in raw.get("languages", [])),
                file_kinds=tuple(str(item) for item in raw.get("file_kinds", [])),
                install_supported=bool(install.get("supported", False)),
                installer=(
                    str(install["installer"]) if install.get("installer") else None
                ),
                install_reason=(
                    str(install["reason"]) if install.get("reason") else None
                ),
                cache_path=str(raw["cache_path"]) if raw.get("cache_path") else None,
                artifacts=artifacts,
            )
        )
    return ToolManifest(version=1, tools=tuple(tools))


@contextmanager
def cache_lock(path: Path) -> Iterator[None]:
    """Cross-process advisory lock for cache writers on supported platforms."""
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = path.open("a+b")
    try:
        if os.name == "nt":
            import msvcrt

            handle.seek(0, os.SEEK_END)
            if handle.tell() == 0:
                handle.write(b"\0")
                handle.flush()
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        yield
    finally:
        if os.name == "nt":
            import msvcrt

            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        handle.close()


def atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        Path(temporary).replace(path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise


def manifest_as_dict(manifest: ToolManifest) -> dict[str, Any]:
    return {
        "manifest_version": manifest.version,
        "tools": [tool.id for tool in manifest.tools],
    }
