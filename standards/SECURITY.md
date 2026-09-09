# Security

The security gate is layered so a repo with no lockfile still gets a secret
scan, a repo with lockfiles gets CVE results, and a tree with Terraform,
Kubernetes, Helm, or Dockerfiles gets IaC misconfig results. Findings carry
OWASP Top 10 / CWE ids and steps of reproduction.

| Layer | Tool | Looks for |
| --- | --- | --- |
| Secrets | gitleaks (default ruleset) + Trivy secret | keys, tokens, private keys in git history and worktree |
| Dependencies (SCA) | osv-scanner (recursive) + Trivy filesystem | known CVEs in npm, PyPI, crates, Go, Maven, NuGet lockfiles |
| SAST | semgrep + `configs/semgrep.yml` | `eval`, `innerHTML`, `pickle.loads`, `shell=True`, `Runtime.exec`, hardcoded credentials |
| IaC | Trivy misconfig + Checkov (if installed) | Terraform, CloudFormation, Kubernetes, Helm, Dockerfile, and similar |
| SBOM | Trivy CycloneDX/SPDX, or lockfile inventory | `.quality-reports/sbom.cdx.json` and `sbom.spdx.json` (`quality sbom`) |
| Heuristic | The Code Sheriff itself | assignment-shaped secrets in source if gitleaks is missing |

Semgrep is optional (`pip install semgrep` or `pip install 'quality-gates[security]'`).
Checkov is optional and used when present. gitleaks and osv-scanner are
downloaded to `~/.cache/quality-gates/bin` on CI (`quality doctor --install`,
or automatically when `GITHUB_ACTIONS=true`). Trivy is used when installed for
CVE, IaC, secrets, and SBOM.

The security gate **fails the build** on gitleaks hits and OSV vulnerabilities.
Heuristic secret matches are warnings so a documentation example does not page
anyone. Tune allowlists in `configs/gitleaks.toml`.
