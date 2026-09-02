# DRY checks

Duplication is measured with [jscpd](https://github.com/kucherenko/jscpd), which
understands C#, JavaScript/TypeScript/JSX, Python, Java, Go, Rust, and SQL.

Defaults (override in `quality.toml`):

```toml
[quality.dry]
min_lines = 6
min_tokens = 50
threshold = 0    # any clone is a failure; raise to allow a % of duplicated tokens
```

`threshold = 0` is strict on purpose for new code. Existing codebases should
raise it (for example `5` or `10`) and then ratchet down.

jscpd ignores `node_modules`, `vendor`, `dist`, `build`, `target`, and
`tests/fixtures`. Generated files should be added to `quality.dry.ignore`.

The AI review job is also given DRY findings so it can suggest a shared helper
instead of only restating the clone locations.
