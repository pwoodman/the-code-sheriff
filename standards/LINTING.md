# Lint standards

Lint is the language-aware cousin of format: unused bindings, hooks rules,
unchecked errors, injection-prone APIs. The lint gate fails on **error**
severity findings. Warnings are reported but do not fail CI unless a tool
treats them as errors (Rust clippy runs with `-D warnings`).

| Language | Linter | Config | What it catches |
| --- | --- | --- | --- |
| C# | `dotnet format analyzers` | SDK + `.editorconfig` | IDE000x / Roslyn analyzers when a `.csproj` exists |
| JavaScript | ESLint 9 (flat config) | `tooling/js/eslint.config.js` | eqeqeq, no-eval, unused vars |
| TypeScript | typescript-eslint | same | plus `no-explicit-any` as a warning |
| React | eslint-plugin-react, react-hooks, jsx-a11y | same | keys, hooks rules, alt text |
| Rust | clippy | `cargo clippy -- -D warnings` | requires `Cargo.toml` |
| Go | golangci-lint | `configs/golangci.yml` | errcheck, staticcheck, govet, revive; falls back to `go vet` |
| Python | ruff check | `configs/ruff.toml` / `pyproject.toml` | E/F/W/I/UP/B/SIM/RUF |
| Java | Checkstyle | `configs/checkstyle.xml` | Google Java Style (names, braces, whitespace) |
| SQL | SQLFluff | `configs/sqlfluff.ini` | layout, capitalisation, aliasing |

If a project already has ESLint/Ruff/golangci-lint on PATH (or in
`node_modules/.bin` / `.venv/bin`), those binaries are preferred. Missing tools
are **skipped with a note**, not a hard fail, so a Python-only repo is not
punished for lacking `rustc`.
