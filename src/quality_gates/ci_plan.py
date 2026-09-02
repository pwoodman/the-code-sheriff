from __future__ import annotations

import os

from quality_gates import GATES
from quality_gates.config import QualityConfig

HEAVY_GATES = ("format", "lint", "dry", "security", "compile")
CHEAP_GITHUB_GATES = ("version", "review")


def on_github_actions() -> bool:
    return os.environ.get("GITHUB_ACTIONS") == "true"


def force_full_suite() -> bool:
    return os.environ.get("QUALITY_CI_FULL", "").lower() in {"1", "true", "yes"}


def github_runs_full_suite(config: QualityConfig) -> bool:
    if force_full_suite():
        return True
    return config.ci_mode in {"github", "both"}


def select_gates(
    config: QualityConfig,
    *,
    only: list[str] | None = None,
    skip: list[str] | None = None,
    full: bool = False,
) -> list[str]:
    skip_set = set(skip or [])
    if only:
        chosen = [gate for gate in only if gate in GATES or gate in only]
    elif on_github_actions() and not github_runs_full_suite(config) and not full:
        chosen = list(config.ci_github_gates)
    else:
        chosen = list(GATES)
    ordered = [gate for gate in GATES if gate in chosen and gate not in skip_set]
    extras = [gate for gate in chosen if gate not in GATES and gate not in skip_set]
    return ordered + extras
