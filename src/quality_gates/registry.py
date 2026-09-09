from __future__ import annotations

import fnmatch
import re
from contextlib import suppress
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Literal

ProfileKind = Literal["language", "file"]


@dataclass(frozen=True)
class CapabilityTool:
    name: str
    required: bool = False


@dataclass(frozen=True)
class CapabilityProfile:
    id: str
    display_name: str
    kind: ProfileKind
    aliases: tuple[str, ...] = ()
    suffixes: tuple[str, ...] = ()
    detect_suffixes: tuple[str, ...] = ()
    exact_names: tuple[str, ...] = ()
    path_patterns: tuple[str, ...] = ()
    shebangs: tuple[str, ...] = ()
    toolchain: str | None = None
    gate_language: str | None = None
    capabilities: tuple[str, ...] = ()
    tools: dict[str, tuple[CapabilityTool, ...]] = field(default_factory=dict)
    safety_class: str = "static"
    format_policy: str = "preserve"
    platforms: tuple[str, ...] = ("linux", "darwin", "windows")

    def __post_init__(self) -> None:
        object.__setattr__(self, "tools", MappingProxyType(dict(self.tools)))


def _language(
    id: str,
    display: str,
    suffixes: tuple[str, ...],
    *,
    aliases: tuple[str, ...] = (),
    detect_suffixes: tuple[str, ...] = (),
    names: tuple[str, ...] = (),
    shebangs: tuple[str, ...] = (),
    toolchain: str | None = None,
    gate: str | None = None,
    formatter: tuple[str, ...] = (),
    linter: tuple[str, ...] = (),
    compiler: tuple[str, ...] = (),
    validator: tuple[str, ...] = (),
    security: tuple[str, ...] = (),
    test: tuple[str, ...] = (),
    coverage: tuple[str, ...] = (),
    style: tuple[str, ...] = (),
    format_policy: str = "tool",
    platforms: tuple[str, ...] = ("linux", "darwin", "windows"),
) -> CapabilityProfile:
    tools: dict[str, tuple[CapabilityTool, ...]] = {}
    for capability, values in (
        ("format", formatter),
        ("lint", linter),
        ("compile", compiler),
        ("validate", validator),
        ("security", security),
        ("test", test),
        ("coverage", coverage),
        ("style", style),
    ):
        if values:
            tools[capability] = tuple(CapabilityTool(value) for value in values)
    capabilities = tuple(tools)
    return CapabilityProfile(
        id=id,
        display_name=display,
        kind="language",
        aliases=aliases,
        suffixes=suffixes,
        detect_suffixes=detect_suffixes or suffixes,
        exact_names=names,
        shebangs=shebangs,
        toolchain=toolchain or id,
        gate_language=gate or id,
        capabilities=capabilities,
        tools=tools,
        safety_class="build" if compiler else "static",
        format_policy=format_policy,
        platforms=platforms,
    )


def _file(
    id: str,
    display: str,
    suffixes: tuple[str, ...] = (),
    *,
    aliases: tuple[str, ...] = (),
    names: tuple[str, ...] = (),
    paths: tuple[str, ...] = (),
    shebangs: tuple[str, ...] = (),
    formatter: tuple[str, ...] = (),
    validator: tuple[str, ...] = (),
    linter: tuple[str, ...] = (),
    security: tuple[str, ...] = (),
    policy: str = "preserve",
    platforms: tuple[str, ...] = ("linux", "darwin", "windows"),
) -> CapabilityProfile:
    tools = {
        capability: tuple(CapabilityTool(value) for value in values)
        for capability, values in (
            ("format", formatter),
            ("validate", validator),
            ("lint", linter),
            ("security", security),
        )
        if values
    }
    return CapabilityProfile(
        id=id,
        display_name=display,
        kind="file",
        aliases=aliases,
        suffixes=suffixes,
        detect_suffixes=suffixes,
        exact_names=names,
        path_patterns=paths,
        shebangs=shebangs,
        capabilities=tuple(tools),
        tools=tools,
        format_policy=policy,
        platforms=platforms,
    )


# Order is public: the first nine entries preserve the pre-registry CLI order.
REGISTRY: tuple[CapabilityProfile, ...] = (
    _language(
        "csharp",
        "C#",
        (".cs",),
        aliases=("c#", "cs"),
        detect_suffixes=(".cs", ".csproj", ".sln"),
        toolchain="csharp",
        formatter=("csharpier",),
        linter=("dotnet",),
        compiler=("dotnet",),
        security=("semgrep",),
        test=("dotnet",),
        coverage=("opencover", "cobertura"),
    ),
    _language(
        "javascript",
        "JavaScript",
        (".js", ".mjs", ".cjs"),
        aliases=("js", "nodejs"),
        detect_suffixes=(".js", ".mjs", ".cjs", ".jsx", ".tsx"),
        names=("package.json",),
        toolchain="node",
        formatter=("prettier",),
        linter=("eslint",),
        security=("semgrep",),
        test=("jest", "vitest"),
        coverage=("istanbul", "lcov"),
    ),
    _language(
        "typescript",
        "TypeScript",
        (".ts", ".cts", ".mts"),
        aliases=("ts",),
        detect_suffixes=(".ts", ".cts", ".mts", ".tsx"),
        names=("tsconfig.json",),
        toolchain="node",
        gate="javascript",
        formatter=("prettier",),
        linter=("eslint",),
        compiler=("tsc",),
        security=("semgrep",),
        test=("jest", "vitest"),
        coverage=("istanbul", "lcov"),
    ),
    _language(
        "react",
        "React",
        (".jsx", ".tsx"),
        aliases=("jsx", "tsx"),
        toolchain="node",
        gate="javascript",
        formatter=("prettier",),
        linter=("eslint",),
        security=("semgrep",),
        test=("jest", "vitest"),
        coverage=("istanbul", "lcov"),
    ),
    _language(
        "rust",
        "Rust",
        (".rs",),
        names=("cargo.toml",),
        formatter=("rustfmt",),
        linter=("cargo-clippy",),
        compiler=("cargo",),
        security=("semgrep",),
        test=("cargo",),
        coverage=("lcov",),
    ),
    _language(
        "go",
        "Go",
        (".go",),
        names=("go.mod",),
        formatter=("gofmt",),
        linter=("golangci-lint", "go"),
        compiler=("go",),
        security=("semgrep",),
        test=("go",),
        coverage=("go-cover",),
    ),
    _language(
        "python",
        "Python",
        (".py", ".pyi"),
        aliases=("py",),
        names=("pyproject.toml", "requirements.txt"),
        shebangs=(r"\bpython(?:3(?:\.\d+)?)?\b",),
        formatter=("ruff",),
        linter=("ruff",),
        validator=("python3",),
        security=("semgrep",),
        test=("pytest",),
        coverage=("cobertura",),
    ),
    _language(
        "java",
        "Java",
        (".java",),
        names=("pom.xml", "build.gradle", "build.gradle.kts"),
        formatter=("google-java-format",),
        compiler=("javac",),
        style=("checkstyle",),
        security=("semgrep",),
        test=("maven", "gradle"),
        coverage=("jacoco",),
    ),
    _language(
        "sql",
        "SQL",
        (".sql",),
        formatter=("sqlfluff",),
        linter=("sqlfluff",),
    ),
    _language(
        "c",
        "C",
        (".c", ".h"),
        formatter=("clang-format",),
        linter=("clang-tidy",),
        compiler=("cc",),
        security=("semgrep",),
        test=("ctest",),
        coverage=("lcov",),
    ),
    _language(
        "cpp",
        "C++",
        (".cc", ".cpp", ".cxx", ".hh", ".hpp", ".hxx"),
        aliases=("c++", "cplusplus"),
        detect_suffixes=(".cc", ".cpp", ".cxx", ".h", ".hh", ".hpp", ".hxx"),
        formatter=("clang-format",),
        linter=("clang-tidy",),
        compiler=("c++",),
        security=("semgrep",),
        test=("ctest",),
        coverage=("lcov",),
    ),
    _language(
        "php",
        "PHP",
        (".php", ".phtml"),
        shebangs=(r"\bphp\b",),
        formatter=("php-cs-fixer",),
        linter=("phpstan",),
        validator=("php",),
        security=("semgrep",),
        test=("phpunit",),
        coverage=("cobertura",),
    ),
    _language(
        "ruby",
        "Ruby",
        (".rb", ".rake", ".gemspec"),
        aliases=("rb",),
        names=("gemfile", "rakefile"),
        shebangs=(r"\bruby\b",),
        formatter=("rubocop",),
        linter=("rubocop",),
        validator=("ruby",),
        security=("semgrep",),
        test=("rspec",),
        coverage=("cobertura",),
    ),
    _language(
        "swift",
        "Swift",
        (".swift",),
        formatter=("swift-format",),
        linter=("swiftlint",),
        compiler=("swiftc",),
        security=("semgrep",),
        test=("swift",),
        coverage=("lcov",),
        platforms=("linux", "darwin"),
    ),
    _language(
        "kotlin",
        "Kotlin",
        (".kt", ".kts"),
        aliases=("kt",),
        formatter=("ktlint",),
        linter=("detekt",),
        compiler=("kotlinc",),
        security=("semgrep",),
        test=("gradle",),
        coverage=("jacoco",),
    ),
    _language(
        "dart",
        "Dart",
        (".dart",),
        formatter=("dart",),
        linter=("dart",),
        validator=("dart",),
        security=("semgrep",),
        test=("dart",),
        coverage=("lcov",),
    ),
    _language(
        "scala",
        "Scala",
        (".scala", ".sc"),
        formatter=("scalafmt",),
        linter=("scalafix",),
        compiler=("scalac",),
        security=("semgrep",),
        test=("sbt",),
        coverage=("cobertura",),
    ),
    _language(
        "lua",
        "Lua",
        (".lua",),
        shebangs=(r"\blua(?:jit)?\b",),
        formatter=("stylua",),
        linter=("luacheck",),
        validator=("luac",),
        security=("semgrep",),
        test=("busted",),
        coverage=("lcov",),
    ),
    _language(
        "r",
        "R",
        (".r", ".rmd"),
        aliases=("r-lang",),
        shebangs=(r"\bRscript\b",),
        formatter=("air",),
        linter=("R",),
        validator=("Rscript",),
        security=("semgrep",),
        test=("R",),
        coverage=("cobertura",),
    ),
    _language(
        "elixir",
        "Elixir",
        (".ex", ".exs"),
        aliases=("ex",),
        names=("mix.exs",),
        formatter=("mix",),
        linter=("credo",),
        compiler=("mix",),
        test=("mix",),
        coverage=("cobertura",),
    ),
    _language(
        "shell",
        "Shell",
        (".sh", ".bash"),
        aliases=("bash", "sh"),
        names=(".bashrc", ".profile"),
        shebangs=(r"\b(?:ba|da|k)?sh\b",),
        formatter=("shfmt",),
        linter=("shellcheck",),
        validator=("sh",),
        security=("semgrep",),
        test=("bats",),
        coverage=("lcov",),
        platforms=("linux", "darwin"),
    ),
    _language(
        "powershell",
        "PowerShell",
        (".ps1", ".psm1", ".psd1"),
        aliases=("pwsh", "ps"),
        shebangs=(r"\bpwsh\b", r"\bpowershell\b"),
        formatter=("pwsh",),
        linter=("pwsh",),
        validator=("pwsh",),
        test=("pester",),
        coverage=("cobertura",),
    ),
    _file(
        "zsh",
        "Z shell",
        names=(".zshrc", ".zprofile", ".zshenv"),
        shebangs=(r"\bzsh\b",),
        validator=("zsh",),
        policy="preserve",
        platforms=("linux", "darwin"),
    ),
    _file(
        "fish",
        "fish shell",
        (".fish",),
        names=("config.fish",),
        shebangs=(r"\bfish\b",),
        formatter=("fish_indent",),
        validator=("fish",),
        platforms=("linux", "darwin"),
    ),
    _file("batch", "Windows batch", (".bat", ".cmd"), validator=("builtin-batch",)),
    _file(
        "toml",
        "TOML",
        (".toml",),
        formatter=("tombi",),
        validator=("builtin-toml",),
    ),
    _file(
        "yaml",
        "YAML",
        (".yaml", ".yml"),
        aliases=("yml",),
        formatter=("prettier",),
        linter=("yamllint",),
    ),
    _file(
        "markdown",
        "Markdown",
        (".md", ".markdown"),
        aliases=("md",),
        formatter=("prettier",),
        linter=("markdownlint-cli2",),
    ),
    _file("xml", "XML", (".xml",), validator=("builtin-xml", "xmllint")),
    _file(
        "json",
        "JSON",
        (".json",),
        formatter=("prettier",),
        validator=("builtin-json",),
    ),
    _file("jsonc", "JSON with comments", (".jsonc",), formatter=("prettier",)),
    _file("json5", "JSON5", (".json5",), formatter=("prettier",)),
    _file("html", "HTML", (".html", ".htm"), formatter=("prettier",)),
    _file("css", "CSS", (".css",), formatter=("prettier",)),
    _file("scss", "SCSS", (".scss",), formatter=("prettier",)),
    _file("less", "Less", (".less",), formatter=("prettier",)),
    _file("ini", "INI", (".ini", ".cfg"), validator=("builtin-ini",)),
    _file(
        "properties",
        "Java properties",
        (".properties",),
        validator=("builtin-properties",),
    ),
    _file(
        "dotenv",
        "dotenv",
        (".env",),
        names=(".env", ".env.example", ".env.local"),
        validator=("builtin-dotenv", "dotenv-linter"),
        policy="preserve-sensitive",
    ),
    _file(
        "dockerfile",
        "Dockerfile",
        names=("dockerfile",),
        paths=("dockerfile.*", "**/dockerfile.*"),
        linter=("hadolint",),
        security=("semgrep",),
    ),
    _file(
        "makefile",
        "Makefile",
        names=("makefile", "gnumakefile"),
        paths=("*.mk", "**/*.mk"),
        validator=("checkmake",),
        policy="tabs",
    ),
    _file(
        "github_actions",
        "GitHub Actions",
        names=("action.yml", "action.yaml"),
        paths=(
            ".github/workflows/*.yml",
            ".github/workflows/*.yaml",
            "**/action.yml",
            "**/action.yaml",
        ),
        formatter=("prettier",),
        validator=("actionlint",),
        security=("zizmor",),
    ),
    _file(
        "git",
        "Git configuration",
        names=(".gitignore", ".gitattributes", ".gitmodules", ".gitconfig"),
        paths=("**/.gitignore", "**/.gitattributes"),
        validator=("git",),
    ),
    _file(
        "terraform",
        "Terraform",
        (".tf", ".tfvars"),
        aliases=("tf", "opentofu"),
        names=("terraform.tfvars",),
        validator=("builtin-terraform", "terraform"),
        linter=("tflint",),
    ),
    _file(
        "kubernetes",
        "Kubernetes",
        paths=(
            "**/k8s/**/*.yaml",
            "**/k8s/**/*.yml",
            "**/kubernetes/**/*.yaml",
            "**/kubernetes/**/*.yml",
            "**/manifests/**/*.yaml",
            "**/manifests/**/*.yml",
        ),
        validator=("kubeconform",),
    ),
    _file(
        "helm",
        "Helm",
        names=("chart.yaml", "chart.yml"),
        paths=("**/templates/*.yaml", "**/templates/*.yml"),
        validator=("helm",),
    ),
    _file(
        "protobuf",
        "Protocol Buffers",
        (".proto",),
        aliases=("proto",),
        validator=("builtin-protobuf",),
    ),
    _file(
        "graphql",
        "GraphQL",
        (".graphql", ".gql"),
        aliases=("gql",),
        validator=("builtin-graphql",),
    ),
)

PROFILES = MappingProxyType({profile.id: profile for profile in REGISTRY})
LANGUAGE_PROFILES = tuple(profile for profile in REGISTRY if profile.kind == "language")
FILE_PROFILES = tuple(profile for profile in REGISTRY if profile.kind == "file")
ALL_LANGUAGES = tuple(profile.id for profile in LANGUAGE_PROFILES)
ALL_FILE_KINDS = tuple(profile.id for profile in FILE_PROFILES)

_ALIASES = {
    alias.lower(): profile.id
    for profile in REGISTRY
    for alias in (profile.id, profile.display_name, *profile.aliases)
}
ALIASES = MappingProxyType(_ALIASES)


def canonical_name(value: str) -> str | None:
    return ALIASES.get(value.strip().lower())


def profiles_for_path(
    path: Path, root: Path | None = None
) -> tuple[CapabilityProfile, ...]:
    name = path.name.lower()
    relative = path.as_posix().lower()
    if root is not None:
        with suppress(ValueError):
            relative = path.relative_to(root).as_posix().lower()

    # Explicit path rules are most specific, followed by special names.
    path_matches = tuple(
        profile
        for profile in REGISTRY
        if any(
            fnmatch.fnmatch(relative, pattern.lower())
            for pattern in profile.path_patterns
        )
    )
    if path_matches:
        return path_matches
    name_matches = tuple(
        profile
        for profile in REGISTRY
        if name in {item.lower() for item in profile.exact_names}
    )
    if name_matches:
        return name_matches

    suffix = path.suffix.lower()
    return tuple(
        profile for profile in REGISTRY if suffix and suffix in profile.detect_suffixes
    )


def profiles_for_shebang(line: str) -> tuple[CapabilityProfile, ...]:
    if not line.startswith("#!"):
        return ()
    return tuple(
        profile
        for profile in REGISTRY
        if any(re.search(pattern, line, re.IGNORECASE) for pattern in profile.shebangs)
    )


def source_suffixes(language: str) -> frozenset[str]:
    profile = PROFILES.get(language)
    return frozenset(profile.suffixes if profile and profile.kind == "language" else ())


def gate_language(language: str) -> str:
    profile = PROFILES.get(language)
    return profile.gate_language if profile and profile.gate_language else language
