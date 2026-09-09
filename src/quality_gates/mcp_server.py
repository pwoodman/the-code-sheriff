"""Minimal MCP stdio server so coding agents can loop until gates are green."""

from __future__ import annotations

import json
import sys
from collections.abc import Callable
from typing import Any

from quality_gates import __version__
from quality_gates.oracle import (
    finding_from_reports,
    remaining_from_reports,
    render_prompt,
)

TOOLS = [
    {
        "name": "quality_oracle",
        "description": (
            "Read the last quality-gates run and return remaining blocking "
            "findings. Iterate until green is true."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "prompt": {
                    "type": "boolean",
                    "description": "If true, return a fix-it prompt instead of JSON.",
                }
            },
        },
    },
    {
        "name": "quality_run",
        "description": (
            "Run quality gates (same as `quality run`). Optional only/skip lists. "
            "Returns remaining blockers after the run."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "only": {"type": "string"},
                "skip": {"type": "string"},
                "full": {"type": "boolean"},
            },
        },
    },
    {
        "name": "quality_review",
        "description": "Run the AI/heuristic review gate against the review base.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "base": {"type": "string"},
                "post": {"type": "boolean"},
            },
        },
    },
    {
        "name": "quality_finding_context",
        "description": (
            "Pack one finding (what/where/why/fix/patch/verify) for a coding agent. "
            "Pass id to select; otherwise the first blocker."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {"id": {"type": "string"}},
        },
    },
    {
        "name": "quality_apply_fix",
        "description": (
            "Apply a finding's patch to the working tree. Pass finding id from "
            "quality_finding_context. Re-run quality_oracle after."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {"id": {"type": "string"}},
        },
    },
    {
        "name": "quality_merge",
        "description": (
            "Dry-merge HEAD into the base branch with git merge-tree. Reports "
            "textual conflicts and optionally compile/impact on the merged tree. "
            "Set siblings to also check other open PR heads."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "base": {"type": "string"},
                "verify": {"type": "boolean"},
                "siblings": {"type": "boolean"},
            },
        },
    },
    {
        "name": "quality_pr_comments",
        "description": (
            "List unresolved GitHub review threads on the current pull request "
            "(Greptile, BugBot, humans, Sheriff). Apply suggestion patches with "
            "quality_apply_fix, then re-run quality_oracle."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "fail": {
                    "type": "boolean",
                    "description": "If true, treat unresolved threads as blocking.",
                }
            },
        },
    },
]


def serve(
    stdin=None,
    stdout=None,
    *,
    runner: Callable[[list[str]], int] | None = None,
) -> int:
    stdin = stdin or sys.stdin
    stdout = stdout or sys.stdout
    run = runner or _default_runner
    while True:
        message = _read(stdin)
        if message is None:
            return 0
        response = handle(message, runner=run)
        if response is not None:
            _write(stdout, response)
        if message.get("method") == "exit":
            return 0


def handle(
    message: dict[str, Any], *, runner: Callable[[list[str]], int]
) -> dict[str, Any] | None:
    method = message.get("method")
    msg_id = message.get("id")
    if method == "initialize":
        return _ok(
            msg_id,
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "the-codesheriff", "version": __version__},
            },
        )
    if method == "notifications/initialized" or method == "exit":
        return None
    if method == "ping":
        return _ok(msg_id, {})
    if method == "tools/list":
        return _ok(msg_id, {"tools": TOOLS})
    if method == "tools/call":
        params = message.get("params") or {}
        name = params.get("name")
        args = params.get("arguments") or {}
        if not isinstance(args, dict):
            args = {}
        try:
            text = _call_tool(str(name), args, runner)
        except Exception as exc:
            return _ok(
                msg_id,
                {
                    "content": [{"type": "text", "text": f"tool error: {exc}"}],
                    "isError": True,
                },
            )
        return _ok(msg_id, {"content": [{"type": "text", "text": text}]})
    if msg_id is None:
        return None
    return {
        "jsonrpc": "2.0",
        "id": msg_id,
        "error": {"code": -32601, "message": f"Unknown method {method}"},
    }


def _call_tool(
    name: str, args: dict[str, Any], runner: Callable[[list[str]], int]
) -> str:
    if name == "quality_oracle":
        payload = remaining_from_reports(_root())
        if args.get("prompt"):
            return render_prompt(payload)
        return json.dumps(payload, indent=2)
    if name == "quality_run":
        argv = ["run"]
        if args.get("only"):
            argv.extend(["--only", str(args["only"])])
        if args.get("skip"):
            argv.extend(["--skip", str(args["skip"])])
        if args.get("full"):
            argv.append("--full")
        code = runner(argv)
        payload = remaining_from_reports(_root())
        payload["exit_code"] = code
        return json.dumps(payload, indent=2)
    if name == "quality_review":
        argv = ["review"]
        if args.get("base"):
            argv.extend(["--base", str(args["base"])])
        if args.get("post"):
            argv.append("--post")
        code = runner(argv)
        payload = remaining_from_reports(_root())
        payload["exit_code"] = code
        return json.dumps(payload, indent=2)
    if name == "quality_finding_context":
        finding_id = str(args["id"]) if args.get("id") else None
        return json.dumps(finding_from_reports(_root(), finding_id), indent=2)
    if name == "quality_apply_fix":
        from quality_gates.models import Finding
        from quality_gates.review.apply import apply_and_verify

        packed = finding_from_reports(_root(), str(args.get("id") or "") or None)
        row = packed.get("finding")
        if not isinstance(row, dict):
            return json.dumps(packed, indent=2)
        finding = Finding(
            gate=str(row.get("gate") or "review"),
            message=str(row.get("message") or ""),
            path=row.get("path"),
            line=row.get("line") if isinstance(row.get("line"), int) else None,
            rule=row.get("rule"),
            patch=row.get("patch"),
            suggestion=row.get("suggestion"),
            verify=row.get("verify"),
        )
        verified = apply_and_verify(_root(), finding)
        verified["id"] = row.get("id")
        return json.dumps(verified, indent=2)
    if name == "quality_merge":
        argv = ["merge"]
        if args.get("base"):
            argv.extend(["--base", str(args["base"])])
        if args.get("verify") is True:
            argv.append("--verify")
        if args.get("verify") is False:
            argv.append("--no-verify")
        if args.get("siblings") is True:
            argv.append("--siblings")
        if args.get("siblings") is False:
            argv.append("--no-siblings")
        code = runner(argv)
        payload = remaining_from_reports(_root())
        payload["exit_code"] = code
        return json.dumps(payload, indent=2)
    if name == "quality_pr_comments":
        argv = ["comments"]
        if args.get("fail"):
            argv.append("--fail")
        code = runner(argv)
        payload = remaining_from_reports(_root())
        payload["exit_code"] = code
        return json.dumps(payload, indent=2)
    return f"unknown tool {name}"


def _default_runner(argv: list[str]) -> int:
    import subprocess

    return subprocess.call([sys.executable, "-m", "quality_gates", *argv])


def _root():
    from quality_gates.paths import project_root

    return project_root()


def _ok(msg_id: object, result: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": msg_id, "result": result}


def _read(stdin) -> dict[str, Any] | None:
    headers: dict[str, str] = {}
    while True:
        line = stdin.readline()
        if line == "":
            return None
        stripped = line.strip()
        if not stripped:
            break
        if ":" in stripped:
            key, value = stripped.split(":", 1)
            headers[key.strip().lower()] = value.strip()
    length = int(headers.get("content-length") or "0")
    if length <= 0:
        return None
    raw = stdin.read(length)
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def _write(stdout, message: dict[str, Any]) -> None:
    raw = json.dumps(message, ensure_ascii=False)
    stdout.write(f"Content-Length: {len(raw.encode('utf-8'))}\r\n\r\n{raw}")
    stdout.flush()
