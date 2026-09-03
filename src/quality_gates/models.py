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
        return payload


@dataclass
class RunResult:
    argv: list[str]
    returncode: int = 0
    stdout: str = ""
    stderr: str = ""
    skipped: bool = False
    skip_reason: str = ""

    @property
    def combined(self) -> str:
        return "\n".join(part for part in (self.stdout, self.stderr) if part).strip()
