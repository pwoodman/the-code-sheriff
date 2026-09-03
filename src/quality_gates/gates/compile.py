from __future__ import annotations

import tempfile
from pathlib import Path

from quality_gates.config import QualityConfig
from quality_gates.detect import iter_project_files
from quality_gates.gates.common import fail_or_pass, findings_from_text, skip_result
from quality_gates.models import Finding, GateResult
from quality_gates.registry import LANGUAGE_PROFILES
from quality_gates.tools import run, which

COMPILED_LANGUAGES = tuple(
    profile.id
    for profile in LANGUAGE_PROFILES
    if {"compile", "validate"} & set(profile.capabilities) and profile.id != "python"
)
BUILD_LANGUAGES = {"csharp", "rust", "go", "java", "typescript"}


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
            "no compiled or syntax-checkable languages detected. "
            "JavaScript/Python/SQL are not treated as compiled languages.",
        )

    parts: list[GateResult] = []
    for language in compiled:
        if language in {"c", "cpp"}:
            parts.append(_c_family(root, config, language))
        elif language in {"php", "ruby", "dart", "lua", "powershell", "shell", "r"}:
            parts.append(_syntax_check(root, config, language))
        elif language == "swift":
            parts.append(_swift(root, config))
        elif language == "kotlin":
            parts.append(_kotlin(root, config))
        elif language == "scala":
            parts.append(_scala(root, config))

    builds = [language for language in compiled if language in BUILD_LANGUAGES]
    allowed, reason = security_cleared(security)
    if builds and (config.trust != "trusted" or not allowed):
        blocked = (
            "project builds require quality.trust = 'trusted'"
            if config.trust != "trusted"
            else reason
        )
        parts.append(
            GateResult(
                name="compile",
                status="fail" if not allowed else "skip",
                findings=(
                    [
                        Finding(
                            gate="compile",
                            rule="security-gate",
                            message=blocked,
                            severity="error",
                        )
                    ]
                    if not allowed
                    else []
                ),
                notes=[blocked],
            )
        )
    elif builds:
        if "go" in builds:
            parts.append(_go(root, config))
        if "rust" in builds:
            parts.append(_rust(root))
        if "csharp" in builds:
            parts.append(_csharp(root))
        if "java" in builds:
            parts.append(_java(root, config))
        if "typescript" in builds:
            parts.append(_typescript(root))

    findings: list[Finding] = []
    notes = [reason] if builds else ["non-executing syntax checks"]
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


def _c_family(root: Path, config: QualityConfig, language: str) -> GateResult:
    command = "cc" if language == "c" else "c++"
    compiler = which(command, project=root, prefer_project=config.prefer_project_tools)
    if not compiler:
        return skip_result("compile", f"{command} is not installed", tool=command)
    suffixes = (
        {".c", ".h"}
        if language == "c"
        else {".cc", ".cpp", ".cxx", ".hh", ".hpp", ".hxx"}
    )
    files = [
        path
        for path in iter_project_files(root, config)
        if path.suffix.lower() in suffixes
    ]
    if not files:
        return skip_result(
            "compile", f"no unambiguous {language} files for syntax checking"
        )
    result = run([compiler, "-fsyntax-only", *map(str, files)], cwd=root, timeout=300)
    return fail_or_pass(
        "compile",
        findings_from_text("compile", result, language=language),
        [f"{command} -fsyntax-only ({len(files)} file(s))"],
    )


def _syntax_check(root: Path, config: QualityConfig, language: str) -> GateResult:
    settings = {
        "php": ("php", ["-l"], {".php", ".phtml"}),
        "ruby": ("ruby", ["-c"], {".rb", ".rake", ".gemspec"}),
        "dart": ("dart", ["analyze"], {".dart"}),
        "lua": ("luac", ["-p"], {".lua"}),
        "powershell": (
            "pwsh",
            [
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                "$e=$null;[System.Management.Automation.Language.Parser]::"
                "ParseFile($args[0],[ref]$null,[ref]$e)>$null;"
                "if($e){$e|% ToString;exit 1}",
            ],
            {".ps1", ".psm1", ".psd1"},
        ),
        "r": (
            "Rscript",
            [
                "--vanilla",
                "-e",
                "parse(file=commandArgs(trailingOnly=TRUE)[1], keep.source=TRUE)",
                "--args",
            ],
            {".r"},
        ),
    }
    if language == "shell":
        return _shell_syntax(root, config)
    tool, args, suffixes = settings[language]
    files = [
        path
        for path in iter_project_files(root, config)
        if path.suffix.lower() in suffixes
    ]
    if not files:
        reason = (
            "R Markdown parsing is unsupported without extracting code chunks"
            if language == "r"
            else f"no {language} files for syntax checking"
        )
        return skip_result("compile", reason)
    executable = which(tool, project=root, prefer_project=config.prefer_project_tools)
    if not executable and language == "powershell":
        executable = which("powershell", project=root)
    if not executable:
        return skip_result("compile", f"{tool} is not installed", tool=tool)
    findings: list[Finding] = []
    if language == "dart":
        result = run([executable, *args, *map(str, files)], cwd=root, timeout=300)
        findings.extend(findings_from_text("compile", result, language=language))
    else:
        for path in files:
            result = run([executable, *args, str(path)], cwd=root, timeout=120)
            if result.returncode != 0:
                findings.extend(
                    findings_from_text("compile", result, language=language)
                )
    return fail_or_pass(
        "compile", findings, [f"{tool} syntax check ({len(files)} file(s))"]
    )


def _shell_syntax(root: Path, config: QualityConfig) -> GateResult:
    files = [
        path
        for path in iter_project_files(root, config)
        if path.suffix.lower() in {".sh", ".bash"}
    ]
    if not files:
        return skip_result("compile", "no shell files for syntax checking")
    findings: list[Finding] = []
    skipped: set[str] = set()
    checked = 0
    for path in files:
        tool = "bash" if path.suffix.lower() == ".bash" else "sh"
        executable = which(
            tool, project=root, prefer_project=config.prefer_project_tools
        )
        if not executable:
            skipped.add(tool)
            continue
        checked += 1
        result = run([executable, "-n", str(path)], cwd=root, timeout=120)
        if result.returncode != 0:
            findings.extend(findings_from_text("compile", result, language="shell"))
    if not checked:
        return skip_result(
            "compile", "sh/bash is not installed", tool="/".join(sorted(skipped))
        )
    result = fail_or_pass(
        "compile", findings, [f"shell -n syntax check ({checked} file(s))"]
    )
    result.skipped_tools = sorted(skipped)
    return result


def _swift(root: Path, config: QualityConfig) -> GateResult:
    compiler = which("swiftc", project=root, prefer_project=config.prefer_project_tools)
    if not compiler:
        return skip_result("compile", "swiftc is not installed", tool="swiftc")
    files = [
        path
        for path in iter_project_files(root, config)
        if path.suffix.lower() == ".swift"
    ]
    if not files:
        return skip_result("compile", "no Swift files for syntax checking")
    mode = "-typecheck" if config.trust == "trusted" else "-parse"
    result = run([compiler, mode, *map(str, files)], cwd=root, timeout=300)
    return fail_or_pass(
        "compile",
        findings_from_text("compile", result, language="swift"),
        [f"swiftc {mode} ({len(files)} file(s))"],
    )


def _kotlin(root: Path, config: QualityConfig) -> GateResult:
    if config.trust != "trusted":
        return skip_result(
            "compile",
            "kotlinc direct compilation requires trusted mode; use ktlint/detekt otherwise",
            tool="kotlinc",
        )
    compiler = which(
        "kotlinc", project=root, prefer_project=config.prefer_project_tools
    )
    if not compiler:
        return skip_result("compile", "kotlinc is not installed", tool="kotlinc")
    files = [
        path
        for path in iter_project_files(root, config)
        if path.suffix.lower() in {".kt", ".kts"}
    ]
    if not files:
        return skip_result("compile", "no Kotlin files for syntax checking")
    with tempfile.TemporaryDirectory(prefix="quality-kotlin-") as output:
        result = run(
            [compiler, *map(str, files), "-d", str(Path(output) / "classes.jar")],
            cwd=root,
            timeout=300,
        )
    return fail_or_pass(
        "compile",
        findings_from_text("compile", result, language="kotlin"),
        [f"kotlinc temporary output ({len(files)} file(s))"],
    )


def _scala(root: Path, config: QualityConfig) -> GateResult:
    compiler = which("scalac", project=root, prefer_project=config.prefer_project_tools)
    if not compiler:
        return skip_result("compile", "scalac is not installed", tool="scalac")
    files = [
        path
        for path in iter_project_files(root, config)
        if path.suffix.lower() in {".scala", ".sc"}
    ]
    if not files:
        return skip_result("compile", "no Scala files for syntax checking")
    if config.trust != "trusted":
        argv = [compiler, "-Ystop-after:parser", *map(str, files)]
        note = f"scalac parser check ({len(files)} file(s))"
        result = run(argv, cwd=root, timeout=300)
    else:
        with tempfile.TemporaryDirectory(prefix="quality-scala-") as output:
            result = run(
                [compiler, "-d", output, *map(str, files)],
                cwd=root,
                timeout=300,
            )
        note = f"scalac temporary output ({len(files)} file(s))"
    return fail_or_pass(
        "compile",
        findings_from_text("compile", result, language="scala"),
        [note],
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
