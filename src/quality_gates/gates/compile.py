from __future__ import annotations

from pathlib import Path

from quality_gates.config import QualityConfig
from quality_gates.detect import iter_project_files
from quality_gates.gates.common import fail_or_pass, findings_from_text, skip_result
from quality_gates.models import Finding, GateResult
from quality_gates.tools import run, which

COMPILED_LANGUAGES = ("csharp", "rust", "go", "java", "typescript")


def security_cleared(result: GateResult | None) -> tuple[bool, str]:
    if result is None:
        return False, "compile requires the security gate to run first"
    if result.status == "fail" or result.error_count() > 0:
        return (
            False,
            "compile blocked: security findings or known vulnerabilities must be cleared first",
        )
    if result.status == "skip":
        return (
            False,
            "compile blocked: security scanners did not run, so this tree is not deemed safe to build",
        )
    if result.status not in {"pass"}:
        return False, f"compile blocked: security status is {result.status}"
    return True, "security cleared"


def run_compile(
    root: Path,
    config: QualityConfig,
    languages: list[str],
    *,
    security: GateResult | None,
) -> GateResult:
    compiled = [lang for lang in languages if lang in COMPILED_LANGUAGES]
    has_tsx = any(
        path.suffix.lower() == ".tsx" for path in iter_project_files(root, config)
    )
    if "react" in languages and "typescript" not in compiled and has_tsx:
        compiled.append("typescript")
    if not compiled:
        return skip_result(
            "compile",
            "no compiled languages detected (C#, Rust, Go, Java, TypeScript). "
            "JavaScript/Python/SQL are not compiled.",
        )

    allowed, reason = security_cleared(security)
    if not allowed:
        status = "fail" if compiled else "skip"
        return GateResult(
            name="compile",
            status=status,
            findings=[
                Finding(
                    gate="compile",
                    rule="security-gate",
                    message=reason,
                    severity="error" if status == "fail" else "info",
                )
            ],
            notes=[reason],
        )

    parts: list[GateResult] = []
    if "go" in compiled:
        parts.append(_go(root, config))
    if "rust" in compiled:
        parts.append(_rust(root))
    if "csharp" in compiled:
        parts.append(_csharp(root))
    if "java" in compiled:
        parts.append(_java(root, config))
    if "typescript" in compiled:
        parts.append(_typescript(root))

    findings: list[Finding] = []
    notes = [reason]
    skipped: list[str] = []
    failed = False
    any_pass = False
    for part in parts:
        findings.extend(part.findings)
        notes.extend(part.notes)
        skipped.extend(part.skipped_tools)
        if part.status == "fail":
            failed = True
        elif part.status == "pass":
            any_pass = True
    if failed:
        status = "fail"
    elif any_pass:
        status = "pass"
    else:
        status = "skip"
    return GateResult(
        name="compile",
        status=status,
        findings=findings,
        notes=notes,
        skipped_tools=skipped,
    )


def _go(root: Path, config: QualityConfig) -> GateResult:
    go = which("go", project=root)
    if not go:
        return skip_result("compile", "go is not installed", tool="go")
    modules = [
        path for path in iter_project_files(root, config) if path.name == "go.mod"
    ]
    if not modules:
        return skip_result("compile", "Go files present but no go.mod")
    findings: list[Finding] = []
    for mod in modules:
        result = run([go, "build", "./..."], cwd=mod.parent, timeout=300)
        if result.returncode != 0:
            findings.extend(
                findings_from_text(
                    "compile",
                    result,
                    language="go",
                    default_message=f"go build failed in {mod.parent}",
                )
            )
    return fail_or_pass("compile", findings, [f"go build {len(modules)} module(s)"])


def _rust(root: Path) -> GateResult:
    cargo = which("cargo", project=root)
    if not cargo:
        return skip_result("compile", "cargo is not installed", tool="cargo")
    manifest = root / "Cargo.toml"
    if not manifest.is_file():
        nested = list(root.glob("**/Cargo.toml"))
        nested = [path for path in nested if "target" not in path.parts]
        if not nested:
            return skip_result("compile", "Rust files present but no Cargo.toml")
        manifest = nested[0]
    result = run(
        [cargo, "build", "--manifest-path", str(manifest), "--all-targets"],
        cwd=root,
        timeout=600,
    )
    return fail_or_pass(
        "compile",
        findings_from_text(
            "compile",
            result,
            language="rust",
            default_message="cargo build failed",
        ),
        ["cargo build"],
    )


def _csharp(root: Path) -> GateResult:
    dotnet = which("dotnet", project=root)
    if not dotnet:
        return skip_result("compile", "dotnet SDK is not installed", tool="dotnet")
    projects = list(root.glob("*.sln")) + list(root.glob("**/*.csproj"))
    projects = [
        path
        for path in projects
        if "tests/fixtures" not in path.as_posix() and "obj" not in path.parts
    ]
    if not projects:
        return skip_result("compile", "C# files present but no .sln/.csproj")
    findings: list[Finding] = []
    for project in projects[:8]:
        result = run(
            [dotnet, "build", str(project), "--nologo", "-v", "q"],
            cwd=root,
            timeout=480,
        )
        if result.returncode != 0:
            findings.extend(
                findings_from_text(
                    "compile",
                    result,
                    language="csharp",
                    default_message=f"dotnet build failed: {project.name}",
                )
            )
    return fail_or_pass(
        "compile", findings, [f"dotnet build {len(projects)} project(s)"]
    )


def _java(root: Path, config: QualityConfig) -> GateResult:
    if (root / "pom.xml").is_file():
        mvn = which("mvn", project=root)
        if not mvn:
            return skip_result(
                "compile", "Maven project but mvn is not installed", tool="mvn"
            )
        result = run(
            [mvn, "-q", "-DskipTests", "compile"],
            cwd=root,
            timeout=600,
        )
        return fail_or_pass(
            "compile",
            findings_from_text(
                "compile", result, language="java", default_message="mvn compile failed"
            ),
        )
    gradle = root / "build.gradle"
    gradle_kts = root / "build.gradle.kts"
    if gradle.is_file() or gradle_kts.is_file():
        wrapper = root / "gradlew"
        cmd = str(wrapper) if wrapper.is_file() else which("gradle", project=root)
        if not cmd:
            return skip_result(
                "compile", "Gradle project but gradle is not installed", tool="gradle"
            )
        result = run([cmd, "-q", "compileJava"], cwd=root, timeout=600)
        return fail_or_pass(
            "compile",
            findings_from_text(
                "compile",
                result,
                language="java",
                default_message="gradle compileJava failed",
            ),
        )
    java = which("javac", project=root)
    if not java:
        return skip_result("compile", "javac is not installed", tool="javac")
    sources = [
        path for path in iter_project_files(root, config) if path.suffix == ".java"
    ]
    if not sources:
        return skip_result("compile", "no .java files")
    out = root / ".quality-reports" / "javac-out"
    out.mkdir(parents=True, exist_ok=True)
    result = run(
        [java, "-d", str(out), *[str(path) for path in sources]],
        cwd=root,
        timeout=300,
    )
    return fail_or_pass(
        "compile",
        findings_from_text(
            "compile", result, language="java", default_message="javac failed"
        ),
    )


def _typescript(root: Path) -> GateResult:
    tsconfig = root / "tsconfig.json"
    if not tsconfig.is_file():
        return skip_result(
            "compile",
            "TypeScript/TSX files present but no tsconfig.json (tsc --noEmit skipped)",
        )
    tsc = which("tsc", project=root, prefer_project=True)
    if not tsc:
        npx = which("npx", project=root)
        if not npx:
            return skip_result("compile", "tsc/npx is not installed", tool="tsc")
        argv = [npx, "--yes", "tsc", "--noEmit", "-p", str(tsconfig)]
    else:
        argv = [tsc, "--noEmit", "-p", str(tsconfig)]
    result = run(argv, cwd=root, timeout=300)
    return fail_or_pass(
        "compile",
        findings_from_text(
            "compile",
            result,
            language="typescript",
            default_message="tsc --noEmit failed",
        ),
        ["tsc --noEmit"],
    )
