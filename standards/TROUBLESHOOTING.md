# Troubleshooting

- Run `quality doctor --json` to inspect detected profiles, tool paths, versions,
  platform support, and actionable install reasons.
- Run `quality cache status` or `quality cache clean` if deterministic adapter
  results need inspection or invalidation.
- Set `QUALITY_GATES_CACHE_ENABLED=0` to bypass result caching and
  `QUALITY_GATES_JOBS=1` to diagnose concurrency-sensitive third-party tools.
- Set `quality.offline = true` for no-network operation. Network scanners and
  installation are then skipped or rejected.
- Auto-install refusal is intentional when no verified SHA-256 exists. Install
  the named tool with its official package manager and rerun doctor.
- Builds and test coverage can execute project build plugins and package scripts.
  Use `quality.trust = "untrusted"` for repositories you have not reviewed.
