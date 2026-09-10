"""Local HTTP API, outcome webhooks, SARIF ingest, evidence export, RBAC."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from quality_gates.config import load_config
from quality_gates.host import app_identity
from quality_gates.models import Finding
from quality_gates.review.parse import fingerprint

ROLE_MAP = {
    "admin": "org admin",
    "maintain": "repo maintainer",
    "write": "repo maintainer",
    "triage": "read-only analyst",
    "read": "read-only analyst",
}


def map_github_role(permission: str) -> str:
    return ROLE_MAP.get((permission or "").lower(), "read-only analyst")


def ingest_sarif(root: Path, payload: dict[str, Any] | str | Path) -> list[Finding]:
    data: Any
    if isinstance(payload, Path):
        data = json.loads(payload.read_text(encoding="utf-8"))
    elif isinstance(payload, str):
        path = Path(payload)
        data = json.loads(
            path.read_text(encoding="utf-8") if path.is_file() else payload
        )
    else:
        data = payload
    findings: list[Finding] = []
    for run in data.get("runs") or []:
        tool = ((run.get("tool") or {}).get("driver") or {}).get("name") or "sarif"
        for result in run.get("results") or []:
            loc = (result.get("locations") or [{}])[0].get("physicalLocation") or {}
            artifact = (loc.get("artifactLocation") or {}).get("uri")
            region = loc.get("region") or {}
            level = str(result.get("level") or "warning")
            severity = {"error": "error", "warning": "warning"}.get(level, "info")
            findings.append(
                Finding(
                    gate="review",
                    rule=str(result.get("ruleId") or tool),
                    severity=severity,
                    path=artifact,
                    line=region.get("startLine"),
                    message=str((result.get("message") or {}).get("text") or tool),
                    tool=str(tool),
                    confidence="HIGH",
                )
            )
    reports = root / ".quality-reports"
    reports.mkdir(parents=True, exist_ok=True)
    (reports / "ingested-sarif.json").write_text(
        json.dumps([item.to_dict() for item in findings], indent=2) + "\n",
        encoding="utf-8",
    )
    return findings


def dedupe_findings(groups: list[list[Finding]]) -> list[Finding]:
    seen: set[str] = set()
    out: list[Finding] = []
    for group in groups:
        for item in group:
            key = fingerprint(item, bucket=1)
            if key in seen:
                continue
            seen.add(key)
            out.append(item)
    return out


def export_evidence(
    root: Path,
    *,
    framework: str = "soc2",
) -> Path:
    reports = root / ".quality-reports"
    reports.mkdir(parents=True, exist_ok=True)
    findings = _read_json(reports / "review.json")
    baseline = _read_json(root / ".quality-baseline.json")
    audit_lines = []
    audit_path = reports / "audit.jsonl"
    if audit_path.is_file():
        audit_lines = [
            line for line in audit_path.read_text(encoding="utf-8").splitlines() if line
        ]
    bundle = {
        "framework": framework,
        "product": "The Code Sheriff",
        "findings": findings,
        "suppressions": baseline,
        "audit": audit_lines[:500],
        "identity": app_identity(),
    }
    dest = reports / f"evidence-{framework}.json"
    dest.write_text(json.dumps(bundle, indent=2) + "\n", encoding="utf-8")
    return dest


def emit_outcome(url: str, event: str, payload: dict[str, Any]) -> int:
    body = json.dumps({"event": event, "payload": payload}).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={"Content-Type": "application/json", "User-Agent": "the-codesheriff"},
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            return response.status
    except urllib.error.HTTPError as exc:
        return exc.code
    except urllib.error.URLError:
        return 0


def notify_chat(url: str, text: str) -> int:
    return emit_outcome(url, "review.completed", {"text": text})


def api_state(root: Path) -> dict[str, Any]:
    reports = root / ".quality-reports"
    return {
        "findings": _read_json(reports / "review.json"),
        "runs": _read_json(reports / "history.json"),
        "metrics": _read_json(reports / "cost.json"),
        "rules": sorted(p.name for p in (root / ".quality" / "rules").glob("*.md"))
        if (root / ".quality" / "rules").is_dir()
        else [],
        "config": load_config(root).ai_review,
        "events": [
            line for line in _read_text(reports / "audit.jsonl").splitlines() if line
        ][-50:],
        "identity": app_identity(),
    }


def serve_api(root: Path, *, host: str = "127.0.0.1", port: int = 8788) -> int:
    state = lambda: api_state(root)  # noqa: E731

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            parsed = urlparse(self.path)
            data = state()
            routes = {
                "/health": {"ok": True, "app": "the-codesheriff"},
                "/findings": data.get("findings"),
                "/runs": data.get("runs"),
                "/metrics": data.get("metrics"),
                "/rules": data.get("rules"),
                "/config": {"ai_review": data.get("config")},
                "/events": data.get("events"),
                "/identity": data.get("identity"),
            }
            payload = routes.get(parsed.path)
            if payload is None:
                self._json(404, {"error": "not found"})
                return
            self._json(200, payload)

        def log_message(self, fmt: str, *args: object) -> None:
            return

        def _json(self, status: int, payload: Any) -> None:
            raw = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

    httpd = ThreadingHTTPServer((host, port), Handler)
    print(f"The Code Sheriff API on http://{host}:{port}", flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        return 0
    return 0


def terraform_schema() -> dict[str, Any]:
    return {
        "provider": "codesheriff",
        "resources": [
            "codesheriff_repo",
            "codesheriff_policy",
            "codesheriff_model_provider",
            "codesheriff_budget",
            "codesheriff_team",
        ],
        "module": "terraform/codesheriff",
    }


def simulate_rule(paths: list[str], pattern: str) -> dict[str, Any]:
    from fnmatch import fnmatch

    matched = [
        path
        for path in paths
        if fnmatch(path, pattern) or fnmatch(path.split("/")[-1], pattern)
    ]
    return {
        "pattern": pattern,
        "matched_files": len(matched),
        "estimated_comments": min(24, len(matched)),
        "paths": matched[:20],
    }


def rule_stats(findings: list[Finding]) -> list[dict[str, Any]]:
    buckets: dict[str, dict[str, Any]] = {}
    for item in findings:
        key = item.rule or item.gate
        bucket = buckets.setdefault(
            key,
            {"rule": key, "count": 0, "severities": {}, "languages": {}},
        )
        bucket["count"] += 1
        bucket["severities"][item.severity] = (
            bucket["severities"].get(item.severity, 0) + 1
        )
        lang = item.language or "unknown"
        bucket["languages"][lang] = bucket["languages"].get(lang, 0) + 1
    return sorted(buckets.values(), key=lambda item: item["count"], reverse=True)


def _read_json(path: Path) -> Any:
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _read_text(path: Path) -> str:
    if not path.is_file():
        return ""
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""
