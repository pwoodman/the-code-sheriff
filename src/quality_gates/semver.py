from __future__ import annotations

import re
from dataclasses import dataclass

SEMVER_RE = re.compile(
    r"^(?P<major>0|[1-9]\d*)\.(?P<minor>0|[1-9]\d*)\.(?P<patch>0|[1-9]\d*)"
    r"(?P<pre>-[0-9A-Za-z.-]+)?(?P<build>\+[0-9A-Za-z.-]+)?$"
)


@dataclass(frozen=True, order=True)
class SemVer:
    major: int
    minor: int
    patch: int
    pre: str = ""
    build: str = ""

    def __str__(self) -> str:
        text = f"{self.major}.{self.minor}.{self.patch}"
        if self.pre:
            text += self.pre if self.pre.startswith("-") else f"-{self.pre}"
        if self.build:
            text += self.build if self.build.startswith("+") else f"+{self.build}"
        return text

    def bump(self, part: str) -> SemVer:
        if part == "major":
            return SemVer(self.major + 1, 0, 0)
        if part == "minor":
            return SemVer(self.major, self.minor + 1, 0)
        if part == "patch":
            return SemVer(self.major, self.minor, self.patch + 1)
        raise ValueError(f"unknown bump part: {part}")


def parse_semver(value: str) -> SemVer | None:
    match = SEMVER_RE.match(value.strip())
    if not match:
        return None
    return SemVer(
        int(match.group("major")),
        int(match.group("minor")),
        int(match.group("patch")),
        match.group("pre") or "",
        match.group("build") or "",
    )


def suggest_bump(commit_subjects: list[str]) -> str:
    """Return major, minor, patch, or none from conventional commit subjects."""
    bump = "none"
    for subject in commit_subjects:
        lower = subject.lower()
        if (
            lower.startswith("breaking")
            or "breaking change" in lower
            or re.match(r"^\w+(\([^)]+\))?!:", subject)
        ):
            return "major"
        if lower.startswith("feat:") or lower.startswith("feat("):
            bump = "minor"
            continue
        if bump == "minor":
            continue
        if lower.startswith("fix:") or lower.startswith("fix("):
            bump = "patch"
            continue
        if bump == "none" and re.match(r"^(perf|refactor)(\(|:)", lower):
            bump = "patch"
    return bump
