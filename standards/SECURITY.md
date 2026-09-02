# Security

The security gate is layered so a repo with no lockfile still gets a secret
scan, and a repo with lockfiles gets CVE results without a second tool per
ecosystem.

| Layer | Tool | Looks for |
| --- | --- | --- |
| Secrets | gitleaks (default ruleset) | keys, tokens, private keys in git history and worktree |
| Dependencies | osv-scanner (recursive) | known CVEs in npm, PyPI, crates, Go, Maven, NuGet lockfiles |
| SAST | semgrep + `configs/semgrep.yml` | `eval`, `innerHTML`, `pickle.loads`, `shell=True`, `Runtime.exec`, hardcoded credentials |
| Heuristic | quality-gates itself | assignment-shaped secrets in source if gitleaks is missing |

Semgrep is optional (`pip install semgrep` or `pip install 'quality-gates[security]'`).
gitleaks and osv-scanner are downloaded to `~/.cache/quality-gates/bin` on CI
(`quality doctor --install`, or automatically when `GITHUB_ACTIONS=true`).

The security gate **fails the build** on gitleaks hits and OSV vulnerabilities.
Heuristic secret matches are warnings so a documentation example does not page
anyone. Tune allowlists in `configs/gitleaks.toml`.
