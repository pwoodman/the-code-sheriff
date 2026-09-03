# Security policy

Supported releases are the latest minor release and the preceding minor release.
Report vulnerabilities privately through GitHub Security Advisories at
https://github.com/pwoodman/poly-check/security/advisories/new. Do not open a
public issue for an unpatched vulnerability.

The CLI runs configured formatters, linters, builds, test runners, plugins, and
package scripts in `trusted` mode. Treat untrusted repositories accordingly and
use `quality.offline = true` plus `quality.trust = "untrusted"` for static-only
inspection. Automatic binary downloads are refused unless the bundled manifest
contains a matching platform artifact and verified SHA-256.
