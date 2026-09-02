# Formatting standards

These are the defaults this toolkit enforces. A consuming repo can override a
tool config (`.prettierrc`, `ruff.toml`, …); if none is present, the bundled
file in `configs/` is used.

Baseline for every file is [`.editorconfig`](../.editorconfig): UTF-8, LF
newlines, trailing whitespace stripped, a newline at end of file.

| Language | Formatter | Indent | Width | Quotes / extras |
| --- | --- | --- | --- | --- |
| C# | csharpier | 4 spaces | 120 | Allman braces, file-scoped namespaces preferred |
| JavaScript | Prettier | 2 spaces | 100 | Double quotes, semicolons, trailing commas |
| TypeScript | Prettier | 2 spaces | 100 | Same as JavaScript |
| React (JSX/TSX) | Prettier | 2 spaces | 100 | `jsxSingleQuote: false`, `bracketSameLine: false` |
| Rust | rustfmt | 4 spaces | 100 | Edition 2021, reorder imports |
| Go | gofmt | tabs | 120 | Official Go style; do not reflow to spaces |
| Python | ruff format | 4 spaces | 88 | Double quotes, LF, Black-compatible |
| Java | google-java-format | 2 spaces | 100 | Google Java Style |
| SQL | SQLFluff | 4 spaces | 120 | Uppercase keywords, explicit aliases |

## Why formatters, not style arguments in review

Format is mechanical. The format gate fails the build when a file differs from
the formatter. AI review is instructed to skip style nits the formatter already
owns, and spend tokens on correctness, security, and tests.

## Applying locally

```bash
quality format --write          # fix what can be fixed
quality format --check          # CI mode
```
