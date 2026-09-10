"""Rule-specific why / fix / docs for enrich_finding."""

from __future__ import annotations

# (tool_or_gate, rule) -> (why, fix, docs)
RULE_HELP: dict[tuple[str, str], tuple[str, str, str]] = {
    (
        "yamllint",
        "document-start",
    ): (
        "yamllint expects a YAML document start marker.",
        "Add `---` as the first line, or disable the rule for GitHub workflow files.",
        "https://yamllint.readthedocs.io/en/stable/rules.html#module-yamllint.rules.document_start",
    ),
    (
        "yamllint",
        "line-length",
    ): (
        "yamllint's default maximum line length is 80 characters.",
        "Wrap the line, move long values onto the next line, or add "
        "`# yamllint disable-line rule:line-length`.",
        "https://yamllint.readthedocs.io/en/stable/rules.html#module-yamllint.rules.line_length",
    ),
    (
        "yamllint",
        "truthy",
    ): (
        "YAML 1.1 treats on/off/yes/no as booleans, which breaks GitHub `on:` keys.",
        'Quote the key (`"on":`) or add `# yamllint disable-line rule:truthy`.',
        "https://yamllint.readthedocs.io/en/stable/rules.html#module-yamllint.rules.truthy",
    ),
    (
        "yamllint",
        "comments",
    ): (
        "yamllint wants two spaces before an inline comment.",
        "Insert a space so the comment is `  # note` rather than ` # note`.",
        "https://yamllint.readthedocs.io/en/stable/rules.html#module-yamllint.rules.comments",
    ),
    (
        "yamllint",
        "indentation",
    ): (
        "The YAML indentation does not match the configured indent width.",
        "Re-indent with two spaces, or match the indent used in the rest of the file.",
        "https://yamllint.readthedocs.io/en/stable/rules.html#module-yamllint.rules.indentation",
    ),
    (
        "version",
        "consistent",
    ): (
        "Multiple version files declare different numbers.",
        "Set every version file to the same semver, or run `quality bump auto`.",
        "",
    ),
    (
        "version",
        "semver",
    ): (
        "The declared version is not MAJOR.MINOR.PATCH.",
        "Change it to a numeric semver such as 1.2.3.",
        "",
    ),
    (
        "version",
        "must-increase",
    ): (
        "Source changed but the declared package version is not higher than the base branch.",
        "Run `quality bump auto` (or major/minor/patch) and mention the new version in CHANGELOG.md.",
        "",
    ),
    (
        "version",
        "bump-required",
    ): (
        "Source files changed without a matching version-file edit.",
        "Run `quality bump auto` so consumers can tell this release apart from the previous one.",
        "",
    ),
    (
        "version",
        "changelog",
    ): (
        "The changelog policy requires the new version to be mentioned in CHANGELOG.md.",
        "Add a `## x.y.z` section describing the change.",
        "",
    ),
    (
        "ruff",
        "F401",
    ): (
        "An import is never used in this module.",
        "Remove the import, or add `# noqa: F401` if it is imported for a side effect.",
        "https://docs.astral.sh/ruff/rules/unused-import/",
    ),
    (
        "ruff",
        "F841",
    ): (
        "A local variable is assigned but never used.",
        "Remove the assignment, use the value, or prefix the name with `_`.",
        "https://docs.astral.sh/ruff/rules/unused-variable/",
    ),
    (
        "ruff",
        "E722",
    ): (
        "A bare `except:` catches SystemExit and KeyboardInterrupt as well as bugs.",
        "Catch a specific exception type (`except OSError:`) or at least `Exception`.",
        "https://docs.astral.sh/ruff/rules/bare-except/",
    ),
    (
        "ruff",
        "S105",
    ): (
        "A hardcoded password-like string was assigned.",
        "Load the secret from the environment or a secret manager; never commit it.",
        "https://docs.astral.sh/ruff/rules/hardcoded-password-string/",
    ),
    (
        "ruff",
        "S106",
    ): (
        "A function argument looks like a hardcoded password.",
        "Pass the secret from configuration or the environment instead of a literal.",
        "https://docs.astral.sh/ruff/rules/hardcoded-password-func-arg/",
    ),
    (
        "ruff",
        "S107",
    ): (
        "A function default looks like a hardcoded password.",
        "Default to `None` and read the secret from the environment.",
        "https://docs.astral.sh/ruff/rules/hardcoded-password-default/",
    ),
    (
        "ruff",
        "S101",
    ): (
        "`assert` is stripped when Python runs with `-O`, so it is not a security check.",
        "Raise an explicit exception (or use a real validation library) instead of assert.",
        "https://docs.astral.sh/ruff/rules/assert/",
    ),
    (
        "eslint",
        "no-eval",
    ): (
        "`eval()` executes a string as code and is a classic injection sink.",
        "Parse JSON with `JSON.parse`, or use a dedicated parser — never eval user input.",
        "https://eslint.org/docs/latest/rules/no-eval",
    ),
    (
        "eslint",
        "no-undef",
    ): (
        "A name is used that is not defined in this scope.",
        "Import the symbol, declare it, or add it to ESLint globals if it is an env builtin.",
        "https://eslint.org/docs/latest/rules/no-undef",
    ),
    (
        "eslint",
        "eqeqeq",
    ): (
        "`==` coerces types and hides bugs; ESLint wants `===`.",
        "Replace `==` / `!=` with `===` / `!==`.",
        "https://eslint.org/docs/latest/rules/eqeqeq",
    ),
    (
        "eslint",
        "no-unused-vars",
    ): (
        "A variable, import, or function parameter is never used.",
        "Remove it, or prefix with `_` if it must stay for a signature.",
        "https://eslint.org/docs/latest/rules/no-unused-vars",
    ),
    (
        "clippy",
        "unwrap_used",
    ): (
        "`unwrap()` panics on `None`/`Err` and will crash the process.",
        "Use `?`, `map_err`, or `unwrap_or` / `expect` with a specific failure message.",
        "https://rust-lang.github.io/rust-clippy/master/index.html#unwrap_used",
    ),
    (
        "clippy",
        "expect_used",
    ): (
        "`expect()` still panics; it is only slightly better than unwrap.",
        "Propagate the error with `?` unless a crash is the documented contract.",
        "https://rust-lang.github.io/rust-clippy/master/index.html#expect_used",
    ),
    (
        "gitleaks",
        "generic-api-key",
    ): (
        "Gitleaks matched a high-entropy string that looks like an API key.",
        "Remove the secret, rotate it, and load it from the environment instead.",
        "https://github.com/gitleaks/gitleaks",
    ),
    (
        "gitleaks",
        "aws-access-token",
    ): (
        "An AWS access key id was committed.",
        "Remove it, rotate the key in IAM, and use a credentials provider or env vars.",
        "https://github.com/gitleaks/gitleaks",
    ),
    (
        "osv-scanner",
        "GHSA",
    ): (
        "osv-scanner found a known vulnerability in a locked dependency.",
        "Upgrade the package to a fixed version, or pin an override if you must delay.",
        "https://google.github.io/osv-scanner/",
    ),
    (
        "osv-scanner",
        "CVE",
    ): (
        "osv-scanner found a CVE in a locked dependency.",
        "Upgrade the package to a version that lists the CVE as fixed.",
        "https://google.github.io/osv-scanner/",
    ),
    (
        "review",
        "unsafe-api",
    ): (
        "This API executes, interpolates, or deserializes untrusted data.",
        "Use a safe parser, parameterized queries, or an allowlisted subprocess form.",
        "",
    ),
    (
        "review",
        "missing-tests",
    ): (
        "Production source changed without a matching test file in the diff.",
        "Add or update a test that fails if the new behavior regresses.",
        "",
    ),
    (
        "review",
        "todo",
    ): (
        "A TODO/FIXME was introduced in this change.",
        "Resolve it before merge, or file a tracked issue and reference it.",
        "",
    ),
    (
        "review",
        "large-file",
    ): (
        "One file gained hundreds of lines in a single change.",
        "Split the change, extract helpers, or confirm the generated blob is intentional.",
        "",
    ),
    (
        "review",
        "large-pr",
    ): (
        "The PR adds a large amount of production source, which hides bugs.",
        "Split into reviewable commits or pull requests.",
        "",
    ),
    (
        "review",
        "swallowed-exception",
    ): (
        "An empty except/catch hides failures so tests and operators cannot see them.",
        "Log, re-raise, or return an explicit error result. Never `except: pass`.",
        "",
    ),
    (
        "review",
        "bare-except",
    ): (
        "Bare `except:` also catches SystemExit and KeyboardInterrupt.",
        "Catch a specific exception type, or at least `Exception`.",
        "",
    ),
    (
        "review",
        "magic-number",
    ): (
        "The same unexplained literal appears more than once.",
        "Extract a named constant that says what the number means (timeout, rate, limit).",
        "",
    ),
    (
        "review",
        "long-function",
    ): (
        "The function does too many jobs to review or test in one sitting.",
        "Extract one named helper per job (validate, compute, format).",
        "",
    ),
    (
        "review",
        "deep-nesting",
    ): (
        "Control flow nested five or more levels hides the real decision.",
        "Extract the inner nest into a named predicate or helper.",
        "",
    ),
}


def docs_for_rule(tool: str, rule: str) -> str | None:
    if (
        tool in {"ruff", ""}
        and len(rule) >= 2
        and rule[0].isalpha()
        and rule[1:].isdigit()
    ):
        return f"https://docs.astral.sh/ruff/rules/{rule.lower()}/"
    if tool == "eslint" or "/" not in rule:
        if rule.startswith("http"):
            return rule
        if tool == "eslint":
            return f"https://eslint.org/docs/latest/rules/{rule}"
    if tool == "clippy":
        return (
            "https://rust-lang.github.io/rust-clippy/master/index.html#"
            + rule.replace("-", "_")
        )
    if tool == "gitleaks":
        return "https://github.com/gitleaks/gitleaks"
    if tool in {"osv-scanner", "osv"}:
        return "https://google.github.io/osv-scanner/"
    return None
