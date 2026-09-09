from __future__ import annotations

from importlib import import_module
from typing import Any

__all__ = [
    "run_audit",
    "run_compile",
    "run_contract",
    "run_coverage",
    "run_dry",
    "run_format",
    "run_impact",
    "run_lint",
    "run_packages",
    "run_regex",
    "run_review",
    "run_security",
    "run_tests",
    "run_ui",
    "run_version",
]

_MODULES = {
    "run_audit": "quality_gates.gates.audit",
    "run_compile": "quality_gates.gates.compile",
    "run_contract": "quality_gates.gates.contract",
    "run_coverage": "quality_gates.gates.coverage",
    "run_dry": "quality_gates.gates.dry",
    "run_format": "quality_gates.gates.format",
    "run_impact": "quality_gates.gates.impact",
    "run_lint": "quality_gates.gates.lint",
    "run_packages": "quality_gates.gates.packages",
    "run_regex": "quality_gates.gates.regex",
    "run_review": "quality_gates.gates.review",
    "run_security": "quality_gates.gates.security",
    "run_tests": "quality_gates.gates.test",
    "run_ui": "quality_gates.gates.ui",
    "run_version": "quality_gates.gates.version",
}


def __getattr__(name: str) -> Any:
    module = _MODULES.get(name)
    if module is None:
        raise AttributeError(name)
    return getattr(import_module(module), name)


def __dir__() -> list[str]:
    return sorted(__all__)
