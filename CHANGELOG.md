# Changelog

## 1.1.0

- Version gate: semver consistency, required bumps on source changes, `quality bump`.
- Compile gate for C#, Rust, Go, Java, and TypeScript — only after a clean security scan.
- Local-first CI (`[quality.ci] mode = "local"`): heavy gates run on developer machines; GitHub Actions stays cheap unless you set `github` / `both` or dispatch `full_suite`.

## 1.0.0

- Initial format, lint, DRY, security, and AI review gates.
