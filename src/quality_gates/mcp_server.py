"""Minimal MCP stdio server so coding agents can loop until gates are green."""

from __future__ import annotations

import json
import sys
from collections.abc import Callable
from typing import Any

from quality_gates import __version__
from quality_gates.oracle import remaining_from_reports, render_prompt

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
                "serverInfo": {"name": "poly-check", "version": __version__},
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
    return f"unknown tool {name}"


def _default_runner(argv: list[str]) -> int:
    from quality_gates.cli import main

    return main(argv)


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
