"""Multi-language quality gates: format, lint, DRY, security, compile, coverage, audit, UI, and AI review."""

from __future__ import annotations

from quality_gates.registry import ALL_LANGUAGES as ALL_LANGUAGES

__version__ = "1.6.0"

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
