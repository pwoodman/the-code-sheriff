"""CycloneDX and SPDX SBOMs for the working tree."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from quality_gates.identity import HOMEPAGE, PRODUCT
from quality_gates.tools import run, which

REPORT_DIR = ".quality-reports"
SKIP_DIRS = (
    ".git",
    ".quality-reports",
    "node_modules",
    ".venv",
    "vendor",
    "dist",
    "build",
)


def write_sbom(root: Path, *, fmt: str = "all") -> dict[str, Any]:
    """Write SBOM files under `.quality-reports`. Prefer Trivy; else lockfile inventory."""
    out = root / REPORT_DIR
    out.mkdir(parents=True, exist_ok=True)
    wanted = {"cyclonedx", "spdx"} if fmt == "all" else {fmt}
    notes: list[str] = []
    files: dict[str, str] = {}
    if which("trivy"):
        files, notes = _trivy_sbom(root, out, wanted)
    if set(wanted) - set(files):
        components = inventory_components(root)
        generated = _from_inventory(root, components)
        if "cyclonedx" in wanted and "cyclonedx" not in files:
            path = out / "sbom.cdx.json"
            path.write_text(
                json.dumps(generated["cyclonedx"], indent=2) + "\n", encoding="utf-8"
            )
            files["cyclonedx"] = path.as_posix()
            notes.append("cyclonedx from lockfile inventory (trivy missing or failed)")
        if "spdx" in wanted and "spdx" not in files:
            path = out / "sbom.spdx.json"
            path.write_text(
                json.dumps(generated["spdx"], indent=2) + "\n", encoding="utf-8"
            )
            files["spdx"] = path.as_posix()
            notes.append("spdx from lockfile inventory (trivy missing or failed)")
    return {
        "files": files,
        "notes": notes,
        "components": _component_count(root, files),
    }


def inventory_components(root: Path) -> list[dict[str, str]]:
    """Best-effort package list from common lockfiles and manifests."""
    found: list[dict[str, str]] = []
    package = root / "package.json"
    if package.is_file():
        found.extend(_npm_components(package))
    pyproject = root / "pyproject.toml"
    if pyproject.is_file():
        found.extend(_pyproject_components(pyproject))
    go_mod = root / "go.mod"
    if go_mod.is_file():
        found.extend(_gomod_components(go_mod))
    cargo = root / "Cargo.toml"
    if cargo.is_file():
        found.extend(_toml_name(cargo, "cargo", "crates.io"))
    return _dedupe(found)


def _trivy_sbom(
    root: Path, out: Path, wanted: set[str]
) -> tuple[dict[str, str], list[str]]:
    binary = which("trivy")
    files: dict[str, str] = {}
    notes: list[str] = []
    mapping = {
        "cyclonedx": ("cyclonedx", out / "sbom.cdx.json"),
        "spdx": ("spdx-json", out / "sbom.spdx.json"),
    }
    skip = ",".join(SKIP_DIRS)
    for key in ("cyclonedx", "spdx"):
        if key not in wanted:
            continue
        fmt, path = mapping[key]
        result = run(
            [
                binary,
                "fs",
                "--format",
                fmt,
                "--output",
                str(path),
                "--skip-dirs",
                skip,
                "--quiet",
                str(root),
            ],
            cwd=root,
            timeout=300,
        )
        if path.is_file() and path.stat().st_size > 2:
            files[key] = path.as_posix()
            notes.append(f"{key} via trivy")
        elif result.skipped:
            notes.append("trivy skipped SBOM generation")
        else:
            notes.append(f"trivy {key} SBOM failed")
    return files, notes


def _from_inventory(
    root: Path, components: list[dict[str, str]]
) -> dict[str, Any]:
    now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    name = root.name or PRODUCT
    cdx_components = [
        {
            "type": "library",
            "name": item["name"],
            "version": item.get("version") or "unknown",
            "purl": item.get("purl") or "",
        }
        for item in components
    ]
    spdx_packages = [
        {
            "SPDXID": f"SPDXRef-Package-{index}",
            "name": item["name"],
            "versionInfo": item.get("version") or "NOASSERTION",
            "downloadLocation": "NOASSERTION",
            "licenseConcluded": "NOASSERTION",
        }
        for index, item in enumerate(components, start=1)
    ]
    return {
        "cyclonedx": {
            "bomFormat": "CycloneDX",
            "specVersion": "1.5",
            "version": 1,
            "metadata": {
                "timestamp": now,
                "tools": [{"name": PRODUCT, "externalReferences": [{"url": HOMEPAGE}]}],
                "component": {"type": "application", "name": name},
            },
            "components": cdx_components,
        },
        "spdx": {
            "spdxVersion": "SPDX-2.3",
            "dataLicense": "CC0-1.0",
            "SPDXID": "SPDXRef-DOCUMENT",
            "name": f"{name}-sbom",
            "documentNamespace": f"{HOMEPAGE}/sbom/{name}",
            "creationInfo": {
                "created": now,
                "creators": [f"Tool: {PRODUCT}"],
            },
            "packages": [
                {
                    "SPDXID": "SPDXRef-Package-root",
                    "name": name,
                    "downloadLocation": "NOASSERTION",
                    "licenseConcluded": "NOASSERTION",
                },
                *spdx_packages,
            ],
        },
    }


def _npm_components(path: Path) -> list[dict[str, str]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    rows: list[dict[str, str]] = []
    for section in ("dependencies", "devDependencies", "optionalDependencies"):
        block = payload.get(section) or {}
        if not isinstance(block, dict):
            continue
        for name, version in block.items():
            ver = str(version).lstrip("^~>=<")
            rows.append(
                {
                    "name": str(name),
                    "version": ver,
                    "purl": f"pkg:npm/{name}@{ver}",
                }
            )
    return rows


def _pyproject_components(path: Path) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return []
    in_deps = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("dependencies") and "=" in stripped and "[" in stripped:
            after = stripped.split("=", 1)[1].strip()
            if after.startswith("["):
                chunk = after[1:]
                closed = "]" in chunk
                if closed:
                    chunk = chunk.split("]", 1)[0]
                rows.extend(_pypi_names(chunk.split(",")))
                in_deps = not closed
                continue
        if stripped.startswith("[") and "dependencies" in stripped.lower():
            in_deps = "project.optional" not in stripped and "tool." not in stripped
            continue
        if stripped.startswith("[") or stripped.startswith("]"):
            in_deps = False
            continue
        if not in_deps:
            continue
        rows.extend(_pypi_names([stripped]))
    return rows


def _pypi_names(items: list[str]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for raw in items:
        item = raw.strip(" ,\"'")
        if not item or item.startswith("#"):
            continue
        name = item.split("[")[0].split(">")[0].split("<")[0].split("=")[0].split("~")[0]
        name = name.strip()
        if name:
            rows.append({"name": name, "version": "unknown", "purl": f"pkg:pypi/{name}"})
    return rows


def _gomod_components(path: Path) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("module "):
            name = stripped.split()[1]
            rows.append({"name": name, "version": "unknown", "purl": f"pkg:golang/{name}"})
        elif stripped.startswith("require "):
            parts = stripped.split()
            if len(parts) >= 3:
                rows.append(
                    {
                        "name": parts[1],
                        "version": parts[2],
                        "purl": f"pkg:golang/{parts[1]}@{parts[2]}",
                    }
                )
    return rows


def _toml_name(path: Path, ecosystem: str, registry: str) -> list[dict[str, str]]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return []
    for line in text.splitlines():
        if line.startswith("name"):
            name = line.split("=", 1)[-1].strip().strip("\"'")
            return [
                {
                    "name": name,
                    "version": "unknown",
                    "purl": f"pkg:{ecosystem}/{name}",
                    "registry": registry,
                }
            ]
    return []


def _dedupe(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    seen: set[str] = set()
    unique: list[dict[str, str]] = []
    for item in rows:
        key = f"{item.get('name')}@{item.get('version')}"
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)
    return unique


def _component_count(root: Path, files: dict[str, str]) -> int:
    for key in ("cyclonedx", "spdx"):
        rel = files.get(key)
        if not rel:
            continue
        path = Path(rel)
        if not path.is_file():
            path = root / rel
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if key == "cyclonedx":
            return len(payload.get("components") or [])
        return max(0, len(payload.get("packages") or []) - 1)
    return 0
