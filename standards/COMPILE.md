# Compile

The **compile** gate builds compiled languages. It does **not** execute the
program.

| Language | Command | Needs |
| --- | --- | --- |
| C# | `dotnet build` | `.sln` / `.csproj` |
| Rust | `cargo build --all-targets` | `Cargo.toml` |
| Go | `go build ./...` | `go.mod` |
| Java | `mvn compile` / `gradle compileJava` / `javac` | pom, gradle, or `.java` |
| TypeScript | `tsc --noEmit` | `tsconfig.json` |

JavaScript, Python, and SQL are not compiled here.

## Security gate first

Compile runs only when security **passed**:

- gitleaks / OSV / semgrep **errors** block the build
- security **skipped** (scanners not installed) also blocks compile — the tree
  is not deemed safe to build
- heuristic **warnings** do not block

Override only with `quality compile --force` or
`[quality.compile] require_security = false` (not recommended).
