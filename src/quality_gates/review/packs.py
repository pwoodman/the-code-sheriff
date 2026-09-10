"""Named review packs: frameworks, IaC, security standards, categories."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from quality_gates.config import QualityConfig

PACK_IDS = (
    "nextjs",
    "react",
    "express",
    "django",
    "fastapi",
    "dotnet",
    "spring",
    "go-service",
    "terraform",
    "docker",
    "kubernetes",
    "owasp-asvs",
    "cwe-top-25",
    "performance",
    "concurrency",
    "error-handling",
    "accessibility",
    "style",
    "security",
)

_MARKERS: dict[str, tuple[str, ...]] = {
    "nextjs": ("next.config", "next/"),
    "react": (".tsx", ".jsx", "react"),
    "express": ("express",),
    "django": ("django", "settings.py", "urls.py"),
    "fastapi": ("fastapi",),
    "dotnet": (".csproj", "aspnet"),
    "spring": ("springframework", "pom.xml"),
    "go-service": (".go", "go.mod"),
    "terraform": (".tf", "terraform"),
    "docker": ("dockerfile", "compose.yml", "compose.yaml"),
    "kubernetes": (".yaml", "helm", "kustomization"),
}

_BODIES: dict[str, str] = {
    "nextjs": "Review Next.js routing, server actions, and public env leaks.",
    "react": "Review React hooks, keys, and unsafe HTML sinks.",
    "express": "Review Express middleware order, cookie flags, and route auth.",
    "django": "Review Django CSRF, ORM injection, and DEBUG leftovers.",
    "fastapi": "Review FastAPI dependency auth and Pydantic trust boundaries.",
    "dotnet": "Review ASP.NET auth attributes and model binding.",
    "spring": "Review Spring Security filters and actuator exposure.",
    "go-service": "Review Go context cancelation, error wrapping, and SQL.",
    "terraform": "Review Terraform public resources, ignore_changes, and state.",
    "docker": "Review Dockerfile root user, secrets in layers, and latest tags.",
    "kubernetes": "Review privileged pods, hostPath, and default Service allow-all.",
    "owasp-asvs": "Map findings to OWASP ASVS authentication and injection controls.",
    "cwe-top-25": "Prioritize CWE Top 25 weakness classes when evidence is strong.",
    "performance": "Flag N+1 queries, hot-path serialization, and unbounded loops.",
    "concurrency": "Flag unawaited tasks, shared mutable state, and retry storms.",
    "error-handling": "Flag swallowed exceptions, missing timeouts, leaked internals.",
    "accessibility": "Flag missing labels, keyboard traps, and ARIA misuse.",
    "style": "Optional style nits. Off by default.",
    "security": "High-confidence injection, auth, and secret findings only.",
}


@dataclass(frozen=True)
class ReviewPack:
    name: str
    body: str
    category: str
    enabled: bool


def detect_packs(paths: list[str], languages: list[str]) -> list[str]:
    hay = " ".join(paths + languages).lower()
    found = ["security"]
    for name, markers in _MARKERS.items():
        if any(marker in hay for marker in markers):
            found.append(name)
    if (
        any(item in languages for item in ("javascript", "typescript", "react"))
        and "react" not in found
    ):
        found.append("react")
    return list(dict.fromkeys(found))


def load_packs(
    root: Path,
    config: QualityConfig,
    *,
    paths: list[str],
    languages: list[str],
) -> list[ReviewPack]:
    requested = list(getattr(config, "review_packs", None) or ["auto"])
    disabled = {
        item.lower() for item in getattr(config, "review_disabled_categories", [])
    }
    selected = (
        detect_packs(paths, languages) if "auto" in requested else list(requested)
    )
    selected = [name for name in selected if name in PACK_IDS and name not in disabled]
    if "style" not in requested:
        selected = [name for name in selected if name != "style"]
    packs = []
    for name in selected:
        body = _pack_body(root, name)
        category = (
            "security" if name in {"owasp-asvs", "cwe-top-25", "security"} else name
        )
        packs.append(ReviewPack(name=name, body=body, category=category, enabled=True))
    return packs


def _pack_roots() -> list[Path]:
    here = Path(__file__).resolve()
    return [
        here.parents[3] / "configs" / "packs",
        here.parents[1] / "bundled" / "packs",
        Path.cwd() / "configs" / "packs",
    ]


def _pack_body(root: Path, name: str) -> str:
    filename = f"{name}.md"
    for directory in [root / ".quality" / "packs", *_pack_roots()]:
        path = directory / filename
        if path.is_file():
            return path.read_text(encoding="utf-8").strip()
    return _BODIES.get(name, name)


def render_packs(packs: list[ReviewPack]) -> str:
    if not packs:
        return "- none"
    return "\n\n".join(f"### pack:{pack.name}\n{pack.body}" for pack in packs)
