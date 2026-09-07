# Support and compatibility

Python 3.11–3.14 is tested. Linux, macOS, and Windows run unit CI; scheduled
fixtures exercise representative Python, Node.js, Go, Rust, .NET, Java, PHP, and Ruby toolchains.
The current and previous minor poly-check releases receive bug and security
fixes.

The built-in Python, JavaScript/TypeScript, Go, Rust, Java, C#, and SQL handlers
are the mature tier. Registry profiles outside that tier are experimental and
best-effort: availability and output can vary with the installed tool version.
`quality doctor --json` is the authoritative manifest-driven capability and
platform negotiation output for a machine. A skip, not-applicable, or
unsupported result is coverage information, not evidence that a check passed.

[`SUPPORT_MATRIX.md`](SUPPORT_MATRIX.md) is generated from
`configs/tool-manifest.json` by `python scripts/gen_support_matrix.py`. The
versioned manifest is the canonical machine-readable matrix and feeds doctor
output, SBOM license inventory, and packaging.
