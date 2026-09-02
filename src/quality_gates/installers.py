from __future__ import annotations

import hashlib
import os
import stat
import tarfile
import zipfile
from pathlib import Path
from urllib.request import Request, urlopen

from quality_gates.paths import bin_dir, cache_dir, tooling_js_dir
from quality_gates.tools import run, which

USER_AGENT = "quality-gates/1.0 (+https://github.com)"

GITLEAKS_VERSION = "8.24.3"
OSV_VERSION = "2.0.2"
GOLANGCI_VERSION = "1.64.8"
GOOGLE_JAVA_FORMAT = "1.25.2"
CHECKSTYLE_VERSION = "10.21.4"


def _download(url: str, destination: Path, *, sha256: str | None = None) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    request = Request(url, headers={"User-Agent": USER_AGENT})
    with urlopen(request, timeout=120) as response:
        data = response.read()
    if sha256:
        digest = hashlib.sha256(data).hexdigest()
        if digest != sha256:
            raise RuntimeError(f"checksum mismatch for {url}: {digest} != {sha256}")
    tmp = destination.with_suffix(destination.suffix + ".tmp")
    tmp.write_bytes(data)
    tmp.replace(destination)


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
    url = (
        "https://github.com/gitleaks/gitleaks/releases/download/"
        f"v{GITLEAKS_VERSION}/gitleaks_{GITLEAKS_VERSION}_linux_x64.tar.gz"
    )
    archive = cache_dir() / "downloads" / f"gitleaks_{GITLEAKS_VERSION}.tar.gz"
    _download(url, archive)
    _extract_named(archive, "gitleaks", target)
    return target


def ensure_osv_scanner() -> Path | None:
    existing = which("osv-scanner")
    if existing:
        return Path(existing)
    target = bin_dir() / "osv-scanner"
    if target.is_file():
        return target
    url = (
        "https://github.com/google/osv-scanner/releases/download/"
        f"v{OSV_VERSION}/osv-scanner_linux_amd64"
    )
    _download(url, target)
    _make_executable(target)
    return target


def ensure_golangci_lint() -> Path | None:
    existing = which("golangci-lint")
    if existing:
        return Path(existing)
    target = bin_dir() / "golangci-lint"
    if target.is_file():
        return target
    url = (
        "https://github.com/golangci/golangci-lint/releases/download/"
        f"v{GOLANGCI_VERSION}/golangci-lint-{GOLANGCI_VERSION}-linux-amd64.tar.gz"
    )
    archive = cache_dir() / "downloads" / f"golangci-lint-{GOLANGCI_VERSION}.tar.gz"
    _download(url, archive)
    _extract_named(archive, "golangci-lint", target)
    return target


def ensure_jar(name: str, url: str) -> Path:
    jars = cache_dir() / "jars"
    jars.mkdir(parents=True, exist_ok=True)
    target = jars / name
    if not target.is_file():
        _download(url, target)
    return target


def ensure_google_java_format() -> Path:
    name = f"google-java-format-{GOOGLE_JAVA_FORMAT}-all-deps.jar"
    url = (
        "https://github.com/google/google-java-format/releases/download/"
        f"v{GOOGLE_JAVA_FORMAT}/{name}"
    )
    return ensure_jar(name, url)


def ensure_checkstyle() -> Path:
    name = f"checkstyle-{CHECKSTYLE_VERSION}-all.jar"
    url = (
        "https://github.com/checkstyle/checkstyle/releases/download/"
        f"checkstyle-{CHECKSTYLE_VERSION}/{name}"
    )
    return ensure_jar(name, url)


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
    run([npm, "install", "--no-fund", "--no-audit"], cwd=js_dir, timeout=300)


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
