from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class Finding:
    gate: str
    message: str
    severity: str = "error"
    path: str | None = None
    line: int | None = None
    column: int | None = None
    rule: str | None = None
    language: str | None = None
    tool: str | None = None
    tool_version: str | None = None
    raw_artifact: str | None = None
    safety: str | None = None
    reason: str | None = None
    suggestion: str | None = None
    documentation_url: str | None = None
    snippet: str | None = None
    patch: str | None = None
    verify: str | None = None
    confidence: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {k: v for k, v in asdict(self).items() if v is not None}


@dataclass
class GateResult:
    name: str
    status: str
    findings: list[Finding] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    skipped_tools: list[str] = field(default_factory=list)
    duration_ms: int | None = None
    tool: str | None = None
    tool_version: str | None = None
    raw_artifacts: list[str] = field(default_factory=list)
    safety: str | None = None
    exit_state: str | None = None
    tool_errors: list[str] = field(default_factory=list)
    command: list[str] = field(default_factory=list)
    working_directory: str | None = None
    return_code: int | None = None
    output_excerpt: str | None = None
    # Evidence is deliberately structured rather than a free-form note.  It is
    # the provenance record that lets local and hosted callers make the same
    # conservative decision about whether a result can be reused.
    evidence: dict[str, Any] = field(default_factory=dict)

    def error_count(self) -> int:
        return sum(1 for item in self.findings if item.severity == "error")

    def warning_count(self) -> int:
        return sum(1 for item in self.findings if item.severity == "warning")

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "name": self.name,
            "status": self.status,
            "findings": [item.to_dict() for item in self.findings],
            "notes": self.notes,
            "skipped_tools": self.skipped_tools,
            "error_count": self.error_count(),
            "warning_count": self.warning_count(),
        }
        if self.duration_ms is not None:
            payload["duration_ms"] = self.duration_ms
        for key in (
            "tool",
            "tool_version",
            "safety",
            "exit_state",
            "working_directory",
            "return_code",
            "output_excerpt",
        ):
            value = getattr(self, key)
            if value is not None:
                payload[key] = value
        if self.command:
            payload["command"] = self.command
        if self.raw_artifacts:
            payload["raw_artifacts"] = self.raw_artifacts
        if self.tool_errors:
            payload["tool_errors"] = self.tool_errors
        if self.evidence:
            payload["evidence"] = self.evidence
        return payload


@dataclass
class RunResult:
    argv: list[str]
    returncode: int = 0
    stdout: str = ""
    stderr: str = ""
    skipped: bool = False
    skip_reason: str = ""
    tool: str | None = None
    tool_version: str | None = None
    raw_artifact: str | None = None
    safety: str | None = None
    exit_state: str | None = None
    tool_error: str | None = None
    cwd: str | None = None

    @property
    def combined(self) -> str:
        return "\n".join(part for part in (self.stdout, self.stderr) if part).strip()

    @property
    def timed_out(self) -> bool:
        return self.exit_state == "timeout"
