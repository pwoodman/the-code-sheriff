# Versioning

The **version** gate keeps published numbers honest.

1. Every discovered version file must be **semver** (`MAJOR.MINOR.PATCH`).
2. Files that version the same product must **agree**.
3. If source changes (`*.py`, `*.ts`, `*.go`, `*.rs`, `*.java`, `*.cs`, `*.sql`, …)
   and no version file changed, the gate fails and tells you which bump to make.
4. A bump must be **greater** than the version on the base branch.
5. If `CHANGELOG.md` exists (or `require_changelog = "always"`), it must mention
   the new version.

Version files we read: `pyproject.toml`, `__version__` in `__init__.py`,
`package.json` (non-private), `Cargo.toml`, `*.csproj` `<Version>`, `pom.xml`,
`VERSION` / `version.txt`.

Docs-only and `.github/` changes do not require a bump.

```bash
quality version --base origin/main
quality bump auto     # conventional commits: feat → minor, fix → patch, breaking → major
quality bump patch
```
