"""Fresh, attributable execution evidence shared by local and hosted runs."""

from __future__ import annotations

import hashlib
import json
import os
import platform
from pathlib import Path
from typing import Any

from quality_gates.change_manifest import ChangeManifest
from quality_gates.config import QualityConfig
from quality_gates.models import GateResult

EVIDENCE_VERSION = 1


def snapshot_digest(root: Path, manifest: ChangeManifest | None = None) -> str:
    """Return a stable identity for the exact tree being assessed.

    A manifest already contains the committed target plus unstaged/untracked
    digest.  For full runs, include every quality-relevant file so a stale local
    report cannot be accepted after an edit.
    """
    if manifest is not None:
        value = "|".join(
            [
                manifest.target or "",
                manifest.target_tree or "",
                manifest.working_tree_digest,
            ]
        )
        return hashlib.sha256(value.encode()).hexdigest()
    digest = hashlib.sha256()
    try:
        from quality_gates.detect import discover_workspaces

        for workspace in discover_workspaces(root):
            digest.update(workspace.path.encode())
            digest.update(workspace.manifest.encode())
    except OSError:
        pass
    for path in sorted(root.rglob("*")):
        if (
            not path.is_file()
            or ".git" in path.parts
            or ".quality-reports" in path.parts
        ):
            continue
        try:
            digest.update(path.relative_to(root).as_posix().encode())
            digest.update(hashlib.sha256(path.read_bytes()).digest())
        except OSError:
            continue
    return digest.hexdigest()


def config_digest(config: QualityConfig) -> str:
    return hashlib.sha256(
        json.dumps(config.raw, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def runner_identity() -> str | None:
    """Hosted results need a stable, authenticated runner identity.

    GitHub supplies run and repository identities.  A plain local run has no
    attestation and is intentionally not treated as remotely reusable.
    """
    if os.environ.get("GITHUB_ACTIONS") == "true":
        return ":".join(
            part
            for part in (
                "github",
                os.environ.get("GITHUB_REPOSITORY"),
                os.environ.get("GITHUB_RUN_ID"),
                os.environ.get("GITHUB_RUN_ATTEMPT"),
            )
            if part
        )
    return None


def attach_evidence(
    result: GateResult,
    root: Path,
    config: QualityConfig,
    *,
    manifest: ChangeManifest | None = None,
    selection: list[str] | None = None,
) -> GateResult:
    result.evidence = {
        "version": EVIDENCE_VERSION,
        "snapshot": snapshot_digest(root, manifest),
        "configuration": config_digest(config),
        "selection": sorted(selection or []),
        "tool": result.tool,
        "tool_version": result.tool_version,
        "environment": {
            "platform": platform.platform(),
            "python": platform.python_version(),
        },
        "runner": runner_identity(),
    }
    return result


def evidence_is_fresh(
    evidence: dict[str, Any],
    root: Path,
    config: QualityConfig,
    *,
    manifest: ChangeManifest | None = None,
) -> bool:
    return bool(
        evidence
        and evidence.get("version") == EVIDENCE_VERSION
        and evidence.get("snapshot") == snapshot_digest(root, manifest)
        and evidence.get("configuration") == config_digest(config)
    )


def evidence_is_hosted(evidence: dict[str, Any]) -> bool:
    return bool(
        isinstance(evidence.get("runner"), str)
        and evidence["runner"].startswith("github:")
    )
