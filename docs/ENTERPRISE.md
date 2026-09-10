# Enterprise, identity, and private networks

The Code Sheriff does not operate a second identity provider.

- **SSO / SAML** — use GitHub organization SAML SSO (GitHub Enterprise Cloud
  or Server). Installing the App inherits those members.
- **SCIM** — use GitHub Enterprise user provisioning. Sheriff roles map from
  GitHub permissions (`admin`, `maintain`, `write`, `read`) via
  `quality_gates.platform.map_github_role`.
- **GitHub Enterprise Server** — set `GITHUB_API_URL` (and `GITHUB_SERVER_URL`)
  so API calls do not hardcode `api.github.com`.
- **Private repositories** — supported when the App or Actions token can read
  the repo. Code stays on the customer runner.
- **VPC / air-gapped** — run `quality` on self-hosted runners. Optional webhook
  worker: `github-app/compose.yaml`.
