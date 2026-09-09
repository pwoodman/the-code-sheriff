# Security

The security gate is layered so a repo with no lockfile still gets a secret
scan, a repo with lockfiles gets CVE results, and a tree with Terraform,
Kubernetes, Helm, or Dockerfiles gets IaC misconfig results. Findings carry
OWASP Top 10 / CWE ids and steps of reproduction.

| Layer | Tool | Looks for |
| --- | --- | --- |
| Secrets | gitleaks (default ruleset) + Trivy secret | keys, tokens, private keys in git history and worktree |
| Dependencies (SCA) | osv-scanner (recursive) + Trivy filesystem | known CVEs in npm, PyPI, crates, Go, Maven, NuGet lockfiles |
| Package risk | `quality packages` (local catalog) | newly imported or declared packages that are typosquats, malware incidents, abandoned/insecure libraries; undeclared third-party imports |
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

`quality packages` is a cheap local gate (also in `github_gates`). It does not
call a registry. It only runs when the change touches a language that imports
packages (Python, JS/TS, Go, Rust, Java, …). CVE versions still come from
osv-scanner/Trivy.

```toml
[quality.packages]
enabled = true
include_defaults = true          # typosquats, malware incidents, abandoned crypto
require_declared = true          # import must exist in pyproject/package.json/go.mod/…
allow = []                       # never flag these names
[[quality.packages.deny]]
name = "left-pad"
ecosystem = "npm"
message = "do not add left-pad"
severity = "error"
```
