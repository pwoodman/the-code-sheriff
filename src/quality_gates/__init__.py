"""Multi-language quality gates: format, lint, DRY, security, and AI review."""

from __future__ import annotations

__version__ = "1.0.0"

ALL_LANGUAGES = (
    "csharp",
    "javascript",
    "typescript",
    "react",
    "rust",
    "go",
    "python",
    "java",
    "sql",
)

GATES = ("format", "lint", "dry", "security", "review")
