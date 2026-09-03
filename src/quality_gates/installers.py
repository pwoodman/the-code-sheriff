from __future__ import annotations

import hashlib
import os
import stat
import tarfile
import zipfile
from pathlib import Path
from urllib.request import Request, urlopen

from quality_gates.paths import bin_dir, cache_dir, tooling_js_dir
from quality_gates.tool_manifest import (
    artifact_for_install,
    atomic_write,
    cache_lock,
    load_tool_manifest,
)
from quality_gates.tools import run, which

USER_AGENT = "quality-gates/1.6.0 (+https://github.com/pwoodman/poly-check)"

GITLEAKS_VERSION = "8.24.3"
OSV_VERSION = "2.0.2"
GOLANGCI_VERSION = "1.64.8"
GOOGLE_JAVA_FORMAT = "1.25.2"
CHECKSTYLE_VERSION = "10.21.4"


def _manifest_artifact(tool_id: str):
    spec = load_tool_manifest().by_id()[tool_id]
    return artifact_for_install(spec)


def _download(url: str, destination: Path, *, sha256: str | None = None) -> None:
    if not sha256:
        raise RuntimeError(
            f"refusing unverified download from {url}; the tool manifest must "
            "provide a SHA-256 for this platform"
        )
    destination.parent.mkdir(parents=True, exist_ok=True)
    with cache_lock(destination.with_suffix(destination.suffix + ".lock")):
        if destination.is_file():
            return
        request = Request(url, headers={"User-Agent": USER_AGENT})
        with urlopen(request, timeout=120) as response:
            data = response.read()
        digest = hashlib.sha256(data).hexdigest()
        if digest != sha256:
            raise RuntimeError(f"checksum mismatch for {url}: {digest} != {sha256}")
        atomic_write(destination, data)


def _make_executable(path: Path) -> None:
    mode = path.stat().st_mode
    path.chmod(mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def _extract_named(archive: Path, member_name: str, destination: Path) -> None:
    if (
        archive.suffixes[-2:] == [".tar", ".gz"]
        or archive.suffix == ".tgz"
        or archive.name.endswith(".tar.gz")
    ):
        with tarfile.open(archive, "r:gz") as tar:
            for member in tar.getmembers():
                if Path(member.name).name == member_name and member.isfile():
                    extracted = tar.extractfile(member)
                    if extracted is None:
                        continue
                    destination.write_bytes(extracted.read())
                    _make_executable(destination)
                    return
        raise RuntimeError(f"{member_name} not found in {archive}")
    if archive.suffix == ".zip":
        with zipfile.ZipFile(archive) as zipped:
            for info in zipped.infolist():
                if Path(info.filename).name == member_name:
                    destination.write_bytes(zipped.read(info.filename))
                    _make_executable(destination)
                    return
        raise RuntimeError(f"{member_name} not found in {archive}")
    raise RuntimeError(f"unsupported archive: {archive}")


def ensure_gitleaks() -> Path | None:
    existing = which("gitleaks")
    if existing:
        return Path(existing)
    target = bin_dir() / "gitleaks"
    if target.is_file():
        return target
    artifact = _manifest_artifact("gitleaks")
    url = artifact.url
    archive = cache_dir() / "downloads" / f"gitleaks_{GITLEAKS_VERSION}.tar.gz"
    _download(url, archive, sha256=artifact.sha256)
    _extract_named(archive, "gitleaks", target)
    return target


def ensure_osv_scanner() -> Path | None:
    existing = which("osv-scanner")
    if existing:
        return Path(existing)
    target = bin_dir() / "osv-scanner"
    if target.is_file():
        return target
    artifact = _manifest_artifact("osv-scanner")
    _download(artifact.url, target, sha256=artifact.sha256)
    _make_executable(target)
    return target


def ensure_golangci_lint() -> Path | None:
    existing = which("golangci-lint")
    if existing:
        return Path(existing)
    target = bin_dir() / "golangci-lint"
    if target.is_file():
        return target
    artifact = _manifest_artifact("golangci-lint")
    url = artifact.url
    archive = cache_dir() / "downloads" / f"golangci-lint-{GOLANGCI_VERSION}.tar.gz"
    _download(url, archive, sha256=artifact.sha256)
    _extract_named(archive, "golangci-lint", target)
    return target


def ensure_jar(name: str, tool_id: str) -> Path:
    jars = cache_dir() / "jars"
    jars.mkdir(parents=True, exist_ok=True)
    target = jars / name
    if not target.is_file():
        artifact = _manifest_artifact(tool_id)
        _download(artifact.url, target, sha256=artifact.sha256)
    return target


def ensure_google_java_format() -> Path:
    name = f"google-java-format-{GOOGLE_JAVA_FORMAT}-all-deps.jar"
    return ensure_jar(name, "google-java-format")


def ensure_checkstyle() -> Path:
    name = f"checkstyle-{CHECKSTYLE_VERSION}-all.jar"
    return ensure_jar(name, "checkstyle")


def ensure_node_tooling() -> None:
    js_dir = tooling_js_dir()
    package = js_dir / "package.json"
    if not package.is_file():
        return
    modules = js_dir / "node_modules"
    if modules.is_dir():
        return
    npm = which("npm")
    if not npm:
        return
    lockfile = js_dir / "package-lock.json"
    if not lockfile.is_file():
        raise RuntimeError("refusing npm install without tooling/js/package-lock.json")
    run([npm, "ci", "--no-fund", "--no-audit"], cwd=js_dir, timeout=300)


def ensure_python_tools() -> None:
    try:
        import ruff  # noqa: F401
    except ImportError:
        python = which("python3") or which("python")
        if python:
            run(
                [python, "-m", "pip", "install", "--quiet", "ruff>=0.8"], cwd=Path.cwd()
            )


def ensure_sqlfluff() -> None:
    if which("sqlfluff"):
        return
    python = which("python3") or which("python")
    if python:
        run(
            [python, "-m", "pip", "install", "--quiet", "sqlfluff>=3.2"],
            cwd=Path.cwd(),
        )


def write_github_path() -> None:
    github_path = os.environ.get("GITHUB_PATH")
    if not github_path:
        return
    path = Path(github_path)
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    line = str(bin_dir())
    if line not in existing.splitlines():
        with path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
