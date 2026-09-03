"""Multi-language quality gates: format, lint, DRY, security, compile, coverage, audit, UI, and AI review."""

from __future__ import annotations

__version__ = "1.5.1"

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

GATES = (
    "format",
    "lint",
    "dry",
    "security",
    "compile",
    "impact",
    "coverage",
    "audit",
    "ui",
    "version",
    "review",
)
