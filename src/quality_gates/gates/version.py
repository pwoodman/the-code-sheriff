from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from quality_gates.config import QualityConfig
from quality_gates.detect import iter_project_files
from quality_gates.gates.common import fail_or_pass, skip_result
from quality_gates.gitutil import (
    git_base_ref,
    git_changed_names,
    git_commit_subjects,
    git_file_at,
    git_is_repo,
)
from quality_gates.models import Finding, GateResult
from quality_gates.semver import SemVer, parse_semver, suggest_bump

INIT_VERSION = re.compile(r'^__version__\s*=\s*["\']([^"\']+)["\']', re.M)
PYPROJECT_VERSION = re.compile(r'^(version\s*=\s*)["\']([^"\']+)["\']', re.M)
CARGO_VERSION = re.compile(
    r'^(\[package\](?:.|\n)*?^version\s*=\s*)["\']([^"\']+)["\']', re.M
)
CSPROJ_VERSION = re.compile(
    r"(<Version>)([^<]+)(</Version>)",
)
POM_VERSION = re.compile(
    r"(<project\b[^>]*>.*?<version>)([^<]+)(</version>)",
    re.S,
)

SOURCE_SUFFIXES = {
    ".py",
    ".pyi",
    ".js",
    ".jsx",
    ".ts",
    ".tsx",
    ".go",
    ".rs",
    ".java",
    ".cs",
    ".sql",
    ".cjs",
    ".mjs",
}

VERSION_NAMES = {
    "pyproject.toml",
    "package.json",
    "cargo.toml",
    "version",
    "version.txt",
}

DOC_SUFFIXES = {".md", ".rst", ".txt"}


@dataclass
class VersionHit:
    path: Path
    relative: str
    value: str
    kind: str


def run_version(
    root: Path,
    config: QualityConfig,
    *,
    base: str | None = None,
) -> GateResult:
    hits = discover_versions(root, config)
    if not hits:
        return skip_result(
            "version",
            "no version files found (pyproject.toml, package.json, Cargo.toml, "
            "*.csproj <Version>, pom.xml, VERSION, or __version__)",
        )

    findings: list[Finding] = []
    notes: list[str] = []
    parsed = [(hit, parse_semver(hit.value)) for hit in hits]
    unparsed = [hit for hit, sem in parsed if sem is None]
    for hit in unparsed:
        findings.append(
            Finding(
                gate="version",
                path=hit.relative,
                rule="semver",
                message=f"{hit.value!r} is not semver (expected MAJOR.MINOR.PATCH)",
            )
        )

    valid = [(hit, sem) for hit, sem in parsed if sem is not None]
    unique_values = {str(sem) for _, sem in valid}
    if len(unique_values) > 1:
        listed = ", ".join(f"{hit.relative}={hit.value}" for hit, _ in valid)
        findings.append(
            Finding(
                gate="version",
                rule="consistent",
                message=f"version files disagree: {listed}",
            )
        )
    elif unique_values:
        notes.append("current version: " + next(iter(unique_values)))

    if git_is_repo(root):
        findings.extend(_bump_required(root, config, hits, valid, base, notes))
    else:
        notes.append("not a git checkout; skipped bump-vs-base check")

    return fail_or_pass("version", findings, notes)


def discover_versions(root: Path, config: QualityConfig) -> list[VersionHit]:
    hits: list[VersionHit] = []
    for path in iter_project_files(root, config):
        name = path.name.lower()
        relative = path.relative_to(root).as_posix()
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        if name == "pyproject.toml":
            match = PYPROJECT_VERSION.search(text)
            if match:
                hits.append(VersionHit(path, relative, match.group(2), "pyproject"))
        elif name == "package.json":
            try:
                data = json.loads(text)
            except json.JSONDecodeError:
                continue
            version = data.get("version")
            if version and not data.get("private"):
                hits.append(VersionHit(path, relative, str(version), "package.json"))
        elif name == "cargo.toml":
            match = CARGO_VERSION.search(text)
            if match:
                hits.append(VersionHit(path, relative, match.group(2), "cargo"))
        elif path.suffix.lower() == ".csproj":
            match = CSPROJ_VERSION.search(text)
            if match:
                hits.append(
                    VersionHit(path, relative, match.group(2).strip(), "csproj")
                )
        elif name == "pom.xml":
            match = POM_VERSION.search(text)
            if match:
                hits.append(VersionHit(path, relative, match.group(2).strip(), "pom"))
        elif name in {"version", "version.txt"}:
            value = text.strip().splitlines()[0].strip() if text.strip() else ""
            if value:
                hits.append(VersionHit(path, relative, value, "version-file"))
        elif path.suffix == ".py" and path.name == "__init__.py":
            match = INIT_VERSION.search(text)
            if match:
                hits.append(VersionHit(path, relative, match.group(1), "dunder"))
    return hits


def apply_bump(root: Path, config: QualityConfig, part: str) -> tuple[str, list[Path]]:
    hits = discover_versions(root, config)
    valid = [(hit, parse_semver(hit.value)) for hit in hits]
    semvers = [sem for _, sem in valid if sem is not None]
    if not semvers:
        raise ValueError("no semver versions to bump")
    current = max(semvers)
    if part == "auto":
        base = git_base_ref() or _default_base(root)
        subjects = git_commit_subjects(root, base)
        part = suggest_bump(subjects)
        if part == "none":
            part = "patch"
    new = current.bump(part)
    written: list[Path] = []
    for hit, sem in valid:
        if sem is None:
            continue
        _rewrite(hit, str(new))
        written.append(hit.path)
    changelog = root / "CHANGELOG.md"
    if changelog.is_file() or config.require_changelog == "always":
        _prepend_changelog(changelog, str(new), part)
        written.append(changelog)
    return str(new), written


def _rewrite(hit: VersionHit, new: str) -> None:
    text = hit.path.read_text(encoding="utf-8")
    if hit.kind == "pyproject":
        text = PYPROJECT_VERSION.sub(rf'\1"{new}"', text, count=1)
    elif hit.kind == "dunder":
        text = INIT_VERSION.sub(f'__version__ = "{new}"', text, count=1)
    elif hit.kind == "package.json":
        data = json.loads(text)
        data["version"] = new
        text = json.dumps(data, indent=2) + "\n"
    elif hit.kind == "cargo":
        text = CARGO_VERSION.sub(rf'\1"{new}"', text, count=1)
    elif hit.kind == "csproj":
        text = CSPROJ_VERSION.sub(rf"\g<1>{new}\3", text, count=1)
    elif hit.kind == "pom":
        text = POM_VERSION.sub(rf"\g<1>{new}\3", text, count=1)
    elif hit.kind == "version-file":
        lines = text.splitlines() or [""]
        lines[0] = new
        text = "\n".join(lines) + "\n"
    hit.path.write_text(text, encoding="utf-8")


def _prepend_changelog(path: Path, version: str, part: str) -> None:
    existing = path.read_text(encoding="utf-8") if path.is_file() else "# Changelog\n"
    heading = f"## {version}\n\n- {part} release.\n\n"
    if f"## {version}" in existing:
        return
    if existing.lstrip().startswith("# "):
        lines = existing.splitlines(keepends=True)
        # insert after title
        idx = 1
        while idx < len(lines) and not lines[idx].strip():
            idx += 1
        new = "".join(lines[:idx]) + "\n" + heading + "".join(lines[idx:])
    else:
        new = "# Changelog\n\n" + heading + existing
    path.write_text(new, encoding="utf-8")


def _default_base(root: Path) -> str | None:
    for candidate in ("origin/main", "origin/master", "main", "master"):
        if (
            git_file_at(root, candidate, "README.md") is not None
            or git_file_at(root, candidate, "pyproject.toml") is not None
        ):
            return candidate
    return None


def _bump_required(
    root: Path,
    config: QualityConfig,
    hits: list[VersionHit],
    valid: list[tuple[VersionHit, SemVer]],
    base: str | None,
    notes: list[str],
) -> list[Finding]:
    resolved = git_base_ref(base) or _default_base(root)
    changed = git_changed_names(root, resolved)
    if changed is None:
        notes.append("could not diff against a base ref; skipped bump check")
        return []
    if resolved:
        notes.append(f"compared to {resolved}")

    source_changed = any(
        Path(name).suffix.lower() in SOURCE_SUFFIXES for name in changed
    )
    version_changed = any(
        Path(name).name.lower() in VERSION_NAMES
        or name.endswith(".csproj")
        or name.endswith("pom.xml")
        or name.endswith("__init__.py")
        for name in changed
    )
    only_docs = bool(changed) and all(
        Path(name).suffix.lower() in DOC_SUFFIXES
        or name.startswith(".github/")
        or name.startswith("standards/")
        or name.startswith("examples/")
        for name in changed
    )
    if only_docs:
        notes.append("docs/meta-only change; version bump not required")
        return []

    findings: list[Finding] = []
    subjects = git_commit_subjects(root, resolved)
    suggested = suggest_bump(subjects) if subjects else "patch"
    if source_changed and not version_changed:
        findings.append(
            Finding(
                gate="version",
                rule="bump-required",
                message=(
                    "source changed without a version bump. "
                    f"Run `quality bump {suggested}` (conventional commits suggest {suggested})."
                ),
            )
        )
        return findings

    if version_changed and resolved and valid:
        current = max(sem for _, sem in valid)
        old_values: list[SemVer] = []
        for hit, _ in valid:
            previous = git_file_at(root, resolved, hit.relative)
            if previous is None:
                continue
            fake = VersionHit(hit.path, hit.relative, "", hit.kind)
            extracted = _extract_from_text(previous, fake)
            parsed = parse_semver(extracted) if extracted else None
            if parsed:
                old_values.append(parsed)
        if old_values:
            old = max(old_values)
            if current <= old:
                findings.append(
                    Finding(
                        gate="version",
                        rule="must-increase",
                        message=f"version {current} is not greater than {old} on {resolved}",
                    )
                )
            else:
                notes.append(f"bumped {old} → {current}")

        changelog = root / "CHANGELOG.md"
        policy = config.require_changelog
        if policy == "always" or (policy == "if-present" and changelog.is_file()):
            text = changelog.read_text(encoding="utf-8") if changelog.is_file() else ""
            if str(current) not in text:
                findings.append(
                    Finding(
                        gate="version",
                        path="CHANGELOG.md",
                        rule="changelog",
                        message=f"CHANGELOG.md does not mention {current}",
                    )
                )
    return findings


def _extract_from_text(text: str, hit: VersionHit) -> str | None:
    if hit.kind == "pyproject":
        match = PYPROJECT_VERSION.search(text)
        return match.group(2) if match else None
    if hit.kind == "dunder":
        match = INIT_VERSION.search(text)
        return match.group(1) if match else None
    if hit.kind == "package.json":
        try:
            return str(json.loads(text).get("version") or "") or None
        except json.JSONDecodeError:
            return None
    if hit.kind == "cargo":
        match = CARGO_VERSION.search(text)
        return match.group(2) if match else None
    if hit.kind == "csproj":
        match = CSPROJ_VERSION.search(text)
        return match.group(2).strip() if match else None
    if hit.kind == "pom":
        match = POM_VERSION.search(text)
        return match.group(2).strip() if match else None
    if hit.kind == "version-file":
        return text.strip().splitlines()[0].strip() if text.strip() else None
    return None
