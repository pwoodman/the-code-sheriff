from __future__ import annotations

import os

from quality_gates import GATES
from quality_gates.config import QualityConfig
from quality_gates.risk import triggered_capabilities

# Format and lint are cheap; they belong on GitHub even in local mode.
HEAVY_GATES = (
    "dry",
    "security",
    "compile",
    "coverage",
    "ui",
)
CHEAP_GITHUB_GATES = ("format", "lint", "impact", "audit", "version", "review")


def on_github_actions() -> bool:
    return os.environ.get("GITHUB_ACTIONS") == "true"


def force_full_suite() -> bool:
    return os.environ.get("QUALITY_CI_FULL", "").lower() in {"1", "true", "yes"}


def github_runs_full_suite(config: QualityConfig) -> bool:
    if force_full_suite():
        return True
    return config.ci_mode in {"github", "both"}


def ui_allowed_on_github(config: QualityConfig) -> bool:
    """Browser UI tests stay off Actions unless explicitly opted in.

    Installing Playwright/Cypress browsers on GitHub is the expensive part;
    local-first still applies even when ci.mode is github/both.
    """
    if os.environ.get("QUALITY_UI_ON_GITHUB", "").lower() in {"1", "true", "yes"}:
        return True
    return bool(config.ui_on_github)


def unknown_gates(names: list[str] | None) -> list[str]:
    if not names:
        return []
    known = set(GATES)
    return [name for name in names if name not in known]


def select_gates(
    config: QualityConfig,
    *,
    only: list[str] | None = None,
    skip: list[str] | None = None,
    full: bool = False,
) -> list[str]:
    bad = unknown_gates(only) + unknown_gates(skip)
    if bad:
        names = ", ".join(dict.fromkeys(bad))
        raise ValueError(f"unknown gate(s): {names}. Choose from: {', '.join(GATES)}")
    skip_set = set(skip or [])
    if only:
        chosen = [gate for gate in only if gate in GATES]
    elif on_github_actions() and not github_runs_full_suite(config) and not full:
        chosen = list(config.ci_github_gates)
    else:
        chosen = list(GATES)
    return [gate for gate in GATES if gate in chosen and gate not in skip_set]


def select_change_gates(gates: list[str], paths: list[str]) -> list[str]:
    """Only include costly risk gates when their changed surface warrants them."""
    selected = list(gates)
    for capability in sorted(triggered_capabilities(paths)):
        if capability not in selected:
            selected.append(capability)
    return [gate for gate in GATES if gate in selected]
