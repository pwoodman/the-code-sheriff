"""Parse /sheriff reviewer commands from pull-request comments."""

from __future__ import annotations

import re
from dataclasses import dataclass

PREFIX = "/sheriff"
COMMANDS = (
    "review",
    "summary",
    "explain",
    "check",
    "fix",
    "ignore",
    "help",
)
CHECK_FOCUSES = ("security", "tests", "migration", "architecture")
HELP = """The Code Sheriff commands (prefix `/sheriff` so they do not collide with other bots):

- `/sheriff review` — full review
- `/sheriff summary` — PR summary only
- `/sheriff explain [question]` — explain the diff
- `/sheriff check security` — security-focused review
- `/sheriff check tests` — test-gap review
- `/sheriff fix` — generate fix suggestions / a separate fix PR
- `/sheriff ignore <rule> [reason]` — suppress a finding with rationale
- `/sheriff help` — this list
"""

_LINE = re.compile(
    r"^/sheriff(?:\s+(?P<cmd>[a-z-]+))?(?:\s+(?P<rest>.+))?$",
    re.I | re.M,
)


@dataclass(frozen=True)
class SheriffCommand:
    name: str
    focus: str = ""
    argument: str = ""
    raw: str = ""

    @property
    def forces_review(self) -> bool:
        return self.name in {"review", "check", "explain", "fix", "summary"}


def parse_sheriff_command(body: str | None) -> SheriffCommand | None:
    text = (body or "").strip()
    if not text:
        return None
    match = _LINE.search(text)
    if not match:
        return None
    name = (match.group("cmd") or "help").lower()
    rest = (match.group("rest") or "").strip()
    if name not in COMMANDS:
        return SheriffCommand(name="help", argument=name, raw=text)
    if name == "check":
        focus = rest.split()[0].lower() if rest else "security"
        if focus not in CHECK_FOCUSES:
            focus = "security"
        leftover = (
            rest[len(focus) :].strip() if rest.lower().startswith(focus) else rest
        )
        return SheriffCommand(name="check", focus=focus, argument=leftover, raw=text)
    return SheriffCommand(name=name, argument=rest, raw=text)


def help_text() -> str:
    return HELP.strip() + "\n"
