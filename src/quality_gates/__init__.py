"""Multi-language quality gates: format, lint, DRY, security, compile, UI, and AI review."""

from __future__ import annotations

__version__ = "1.2.1"

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

GATES = ("format", "lint", "dry", "security", "compile", "ui", "version", "review")
