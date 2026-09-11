from __future__ import annotations

import os
import shutil
import subprocess
from collections.abc import Sequence
from pathlib import Path

from quality_gates.models import RunResult
from quality_gates.paths import bin_dir, tooling_js_dir


def which(
    name: str, project: Path | None = None, prefer_project: bool = True
) -> str | None:
    candidates: list[Path] = []
    if project is not None and prefer_project:
        candidates.extend(
            [
                project / "node_modules" / ".bin" / name,
                project / ".venv" / "bin" / name,
                project / "venv" / "bin" / name,
            ]
        )
    candidates.append(bin_dir() / name)
    js_bin = tooling_js_dir() / "node_modules" / ".bin" / name
    candidates.append(js_bin)
    for candidate in candidates:
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)
        windows = candidate.with_suffix(".cmd")
        if windows.is_file():
            return str(windows)
    found = shutil.which(name)
    return found


def prepend_path(*dirs: Path) -> dict[str, str]:
    env = os.environ.copy()
    extra = os.pathsep.join(str(path) for path in dirs if path.is_dir())
    if extra:
        env["PATH"] = extra + os.pathsep + env.get("PATH", "")
    return env


def isolated_env(base_env: dict[str, str] | None = None) -> dict[str, str]:
    """Sanitize environment variables by stripping cloud keys and API tokens."""
    env = (base_env or os.environ).copy()
    sensitive_markers = (
        "AWS_",
        "GITHUB_TOKEN",
        "ANTHROPIC_",
        "OPENAI_",
        "SSH_",
        "API_KEY",
        "SECRET",
        "PASSWORD",
        "PRIVATE_KEY",
    )
    for key in list(env.keys()):
        upper = key.upper()
        if any(marker in upper for marker in sensitive_markers):
            env.pop(key, None)
    return env


def run(
    argv: Sequence[str],
    *,
    cwd: Path,
    timeout: int = 600,
    env: dict[str, str] | None = None,
    isolated: bool = False,
) -> RunResult:
    argv_list = [str(part) for part in argv]
    run_env = isolated_env(env) if isolated else env
    if isolated:
        bwrap = which("bwrap")
        if not bwrap:
            return RunResult(
                argv=argv_list,
                skipped=True,
                skip_reason="isolated execution requires bubblewrap (bwrap)",
                tool=Path(argv_list[0]).name,
                exit_state="isolation-unavailable",
                tool_error="isolated execution requires bubblewrap (bwrap)",
                cwd=str(cwd),
            )
        argv_list = [
            bwrap,
            "--die-with-parent",
            "--unshare-net",
            "--ro-bind",
            "/",
            "/",
            "--dev",
            "/dev",
            "--tmpfs",
            "/tmp",
            "--chdir",
            str(cwd),
            "--",
            *argv_list,
        ]
    try:
        proc = subprocess.run(
            argv_list,
            cwd=cwd,
            capture_output=True,
            timeout=timeout,
            env=run_env,
            check=False,
        )
    except FileNotFoundError:
        return RunResult(
            argv=argv_list,
            skipped=True,
            skip_reason=f"{argv_list[0]} is not installed",
            tool=Path(argv_list[0]).name,
            exit_state="missing",
            tool_error=f"{argv_list[0]} is not installed",
            cwd=str(cwd),
        )
    except subprocess.TimeoutExpired as exc:
        return RunResult(
            argv=argv_list,
            returncode=124,
            stdout=_decode(exc.stdout),
            stderr=_decode(exc.stderr) or f"timed out after {timeout}s",
            tool=Path(argv_list[0]).name,
            exit_state="timeout",
            tool_error=f"timed out after {timeout}s",
            cwd=str(cwd),
        )
    return RunResult(
        argv=argv_list,
        returncode=proc.returncode,
        stdout=_decode(proc.stdout),
        stderr=_decode(proc.stderr),
        tool=Path(argv_list[0]).name,
        exit_state="success" if proc.returncode == 0 else "failed",
        cwd=str(cwd),
    )


def _decode(data: bytes | str | None) -> str:
    if data is None:
        return ""
    if isinstance(data, str):
        return data
    return data.decode("utf-8", errors="replace")


def tool_version(command: str, args: Sequence[str] = ("--version",)) -> str | None:
    path = which(command) or shutil.which(command)
    if not path:
        return None
    result = run([path, *args], cwd=Path.cwd(), timeout=30)
    if result.skipped or result.returncode not in {0, 1}:
        text = result.combined.strip()
        return text.splitlines()[0][:80] if text else "installed"
    text = result.combined.strip()
    return text.splitlines()[0][:120] if text else "installed"
