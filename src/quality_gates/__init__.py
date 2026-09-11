"""Multi-language quality gates: format, lint, dead code, DRY, security, compile, coverage, audit, UI, and AI review."""

from __future__ import annotations

from quality_gates.registry import ALL_LANGUAGES as ALL_LANGUAGES

__version__ = "1.15.2"

GATES = (
    "format",
    "lint",
    "regex",
    "packages",
    "dry",
    "dead",
    "security",
    "compile",
    "contract",
    "impact",
    "test",
    "coverage",
    "audit",
    "ui",
    "version",
    "merge",
    "review",
    "comments",
    "migration",
    "authorization",
    "resilience",
    "mutation",
    "performance",
)
