"""Optional out-of-process plugin runner. Opt in with QUALITY_PLUGIN_SUBPROCESS=1."""

from __future__ import annotations

import json
import sys

from quality_gates.adapters import Adapter, AdapterContext, BaseAdapter
from quality_gates.models import Finding, GateResult
from quality_gates.tools import run


def _result_from_json(payload: dict[str, object]) -> GateResult:
    findings = [
        Finding(
            gate=str(item.get("gate") or payload.get("name") or "plugin"),
            message=str(item.get("message") or ""),
            severity=str(item.get("severity") or "error"),
            path=item.get("path") if isinstance(item.get("path"), str) else None,
            rule=item.get("rule") if isinstance(item.get("rule"), str) else None,
        )
        for item in payload.get("findings") or []
        if isinstance(item, dict)
    ]
    return GateResult(
        name=str(payload.get("name") or "plugin"),
        status=str(payload.get("status") or "fail"),
        findings=findings,
        notes=list(payload.get("notes") or []),
        exit_state=str(payload.get("exit_state") or payload.get("status") or "failed"),
    )


def run_in_subprocess(
    adapter: BaseAdapter | Adapter, context: AdapterContext
) -> GateResult:
    meta = getattr(adapter, "metadata", None)
    name = getattr(meta, "name", None) or "plugin"
    payload = {
        "adapter": name,
        "root": str(context.root),
        "language": context.language,
        "capability": context.capability,
        "files": [str(path) for path in context.files],
    }
    result = run(
        [
            sys.executable,
            "-c",
            (
                "import json,sys;"
                "from quality_gates.adapters import discover_adapters, AdapterContext;"
                "from quality_gates.config import load_config;"
                "from pathlib import Path;"
                "req=json.loads(sys.argv[1]);"
                "adapters=discover_adapters();"
                "cls=adapters.get(req['adapter']);"
                "cfg=load_config(Path(req['root']));"
                "ctx=AdapterContext(Path(req['root']),cfg,req['language'],req['capability'],"
                "tuple(Path(p) for p in req['files']));"
                "inst=cls() if isinstance(cls,type) else cls;"
                "print(json.dumps(inst.run(ctx).to_dict()))"
            ),
            json.dumps(payload),
        ],
        cwd=context.root,
        timeout=120,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr or result.stdout or "plugin worker failed")
    data = json.loads(result.stdout or "{}")
    if not isinstance(data, dict):
        raise RuntimeError("plugin worker returned non-object JSON")
    return _result_from_json(data)
