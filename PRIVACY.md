# Privacy

The Code Sheriff collects no telemetry and has no product analytics service. Local
gates read repository files and write reports and deterministic cache entries
locally.

The Code Sheriff GitHub App does not need a
hosted webhook. Gates run in each installed repository's GitHub Actions. If a
webhook is configured, it only verifies GitHub signatures and can dispatch a
workflow; diffs and source stay on GitHub.

AI review can send a git diff, related import-graph files, function-level
windows around changed lines, heuristic flags, and configured `.quality/rules`
to OpenAI or Anthropic only when that provider is selected and credentials
are present. Provider terms then apply.
Security and dependency scanners may make network requests; set
`quality.offline = true` to disable network-dependent behavior.
Offline mode does not promise that an independently invoked third-party plugin
is network-free, so only install trusted adapters.
