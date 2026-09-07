from __future__ import annotations

import hashlib
import hmac
import json
from pathlib import Path

from quality_gates.cli import main
from quality_gates.config import load_config
from quality_gates.github_app import (
    CHECK_NAME,
    AppSettings,
    canonical_json,
    default_manifest,
    dispatch_body,
    handle_webhook,
    job_from_webhook,
    load_manifest,
    sign_dispatch,
    verify_dispatch,
    verify_signature,
)

SECRET = "webhook-secret"


def _signed(body: bytes, secret: str = SECRET) -> str:
    digest = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def _settings(**kwargs: object) -> AppSettings:
    values = {
        "webhook_secret": SECRET,
        "dispatch_token": "dispatch-token",
        "home_repo": "pwoodman/poly-check",
        "skip_home": True,
    }
    values.update(kwargs)
    return AppSettings(**values)  # type: ignore[arg-type]


def test_verify_signature_rejects_missing_or_wrong() -> None:
    body = b'{"ok":true}'
    assert verify_signature(SECRET, _signed(body), body)
    assert not verify_signature(SECRET, None, body)
    assert not verify_signature(SECRET, _signed(body, "other"), body)


def test_pull_request_job_and_draft_skip() -> None:
    payload = {
        "action": "opened",
        "number": 9,
        "installation": {"id": 44},
        "repository": {"full_name": "acme/app"},
        "pull_request": {
            "number": 9,
            "draft": False,
            "head": {"sha": "abc", "repo": {"full_name": "acme/app"}},
            "base": {"ref": "main"},
        },
    }
    job = job_from_webhook("pull_request", payload)
    assert job == {
        "kind": "run",
        "repository": "acme/app",
        "sha": "abc",
        "pr": "9",
        "installation_id": "44",
        "base": "main",
        "fork": "false",
    }
    payload["pull_request"]["draft"] = True
    assert job_from_webhook("pull_request", payload) is None
    payload["action"] = "ready_for_review"
    assert job_from_webhook("pull_request", payload) is not None


def test_fork_flag_and_ignored_actions() -> None:
    payload = {
        "action": "synchronize",
        "installation": {"id": 1},
        "repository": {"full_name": "acme/app"},
        "pull_request": {
            "number": 3,
            "head": {"sha": "def", "repo": {"full_name": "other/app"}},
            "base": {"ref": "develop"},
        },
    }
    job = job_from_webhook("pull_request", payload)
    assert job is not None
    assert job["fork"] == "true"
    payload["action"] = "closed"
    assert job_from_webhook("pull_request", payload) is None


def test_check_run_rerequest_and_ping() -> None:
    assert job_from_webhook("ping", {}) == {"kind": "ping"}
    payload = {
        "action": "rerequested",
        "installation": {"id": 8},
        "repository": {"full_name": "acme/app"},
        "check_run": {
            "name": CHECK_NAME,
            "head_sha": "fff",
            "pull_requests": [{"number": 4, "base": {"ref": "main"}}],
        },
    }
    job = job_from_webhook("check_run", payload)
    assert job is not None
    assert job["sha"] == "fff"
    assert job["pr"] == "4"
    payload["check_run"]["name"] = "unrelated"
    assert job_from_webhook("check_run", payload) is None


def test_handle_webhook_dispatches_signed_job(monkeypatch) -> None:
    captured: list[dict] = []

    def fake_dispatch(
        settings: AppSettings,
        payload: dict[str, str],
        token: str | None = None,
    ) -> tuple[int, dict]:
        captured.append(payload)
        return 204, {}

    monkeypatch.setattr("quality_gates.github_app.dispatch_job", fake_dispatch)
    body_obj = {
        "action": "opened",
        "installation": {"id": 44},
        "repository": {"full_name": "acme/app"},
        "pull_request": {
            "number": 9,
            "head": {"sha": "abc", "repo": {"full_name": "acme/app"}},
            "base": {"ref": "main"},
        },
    }
    body = json.dumps(body_obj).encode()
    status, result = handle_webhook(
        {"X-Hub-Signature-256": _signed(body), "X-GitHub-Event": "pull_request"},
        body,
        _settings(),
    )
    assert status == 202
    assert result["dispatched"] == "acme/app"
    assert captured
    payload = captured[0]
    unsigned = {key: value for key, value in payload.items() if key != "sig"}
    assert verify_dispatch(SECRET, unsigned, payload["sig"])
    assert unsigned["pr"] == "9"


def test_handle_webhook_skips_home_repo(monkeypatch) -> None:
    def fail(*_args: object, **_kwargs: object) -> tuple[int, dict]:
        raise AssertionError("should not dispatch")

    monkeypatch.setattr("quality_gates.github_app.dispatch_job", fail)
    body_obj = {
        "action": "opened",
        "installation": {"id": 44},
        "repository": {"full_name": "pwoodman/poly-check"},
        "pull_request": {
            "number": 1,
            "head": {"sha": "abc", "repo": {"full_name": "pwoodman/poly-check"}},
            "base": {"ref": "main"},
        },
    }
    body = json.dumps(body_obj).encode()
    status, result = handle_webhook(
        {"X-Hub-Signature-256": _signed(body), "X-GitHub-Event": "pull_request"},
        body,
        _settings(),
    )
    assert status == 202
    assert "skipped" in result


def test_handle_webhook_rejects_bad_signature() -> None:
    body = b'{"action":"opened"}'
    status, result = handle_webhook(
        {"X-Hub-Signature-256": "sha256=00", "X-GitHub-Event": "pull_request"},
        body,
        _settings(),
    )
    assert status == 401
    assert result["error"] == "invalid signature"


def test_dispatch_canonical_form_is_stable() -> None:
    payload = {"pr": 9, "repository": "acme/app", "sig": "ignore"}
    body = dispatch_body(payload)
    assert body == {"pr": "9", "repository": "acme/app"}
    assert canonical_json(body) == '{"pr":"9","repository":"acme/app"}'
    signature = sign_dispatch(SECRET, payload)
    assert verify_dispatch(SECRET, body, signature)


def test_manifest_cli_and_file_agree(capsys) -> None:
    code = main(
        [
            "github-app",
            "manifest",
            "--webhook-url",
            "https://example.test/webhook",
            "--redirect-url",
            "http://127.0.0.1:8787/callback",
        ]
    )
    assert code == 0
    printed = json.loads(capsys.readouterr().out)
    loaded = load_manifest(
        webhook_url="https://example.test/webhook",
        redirect_url="http://127.0.0.1:8787/callback",
    )
    assert printed["name"] == CHECK_NAME
    assert printed["default_permissions"]["checks"] == "write"
    assert printed["default_permissions"]["contents"] == "read"
    assert printed["hook_attributes"]["url"] == "https://example.test/webhook"
    assert printed["hook_attributes"]["active"] is False
    assert printed["default_events"] == loaded["default_events"]
    fallback = default_manifest(
        webhook_url="https://example.test/webhook",
        redirect_url="http://127.0.0.1:8787/callback",
    )
    assert fallback["default_permissions"] == printed["default_permissions"]


def test_prepare_writes_github_output(tmp_path: Path, monkeypatch, capsys) -> None:
    payload = {
        "repository": "acme/app",
        "sha": "abc",
        "pr": "9",
        "installation_id": "44",
        "base": "main",
        "fork": "false",
    }
    payload["sig"] = sign_dispatch(SECRET, payload)
    event = tmp_path / "event.json"
    event.write_text(json.dumps({"client_payload": payload}), encoding="utf-8")
    output = tmp_path / "out.txt"
    monkeypatch.setenv("QUALITY_APP_WEBHOOK_SECRET", SECRET)
    monkeypatch.setenv("GITHUB_EVENT_NAME", "repository_dispatch")
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(event))
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    assert main(["github-app", "prepare"]) == 0
    text = output.read_text(encoding="utf-8")
    assert "repository=acme/app" in text
    assert "pr=9" in text
    assert "acme/app" in capsys.readouterr().out


def test_trust_env_overrides_toml(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / "quality.toml").write_text(
        '[quality]\ntrust = "trusted"\n', encoding="utf-8"
    )
    monkeypatch.setenv("QUALITY_TRUST", "untrusted")
    config = load_config(tmp_path)
    assert config.trust == "untrusted"


def test_check_cli_skips_without_github_env(capsys, monkeypatch) -> None:
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("GH_TOKEN", raising=False)
    monkeypatch.delenv("GITHUB_REPOSITORY", raising=False)
    assert main(["github-app", "check", "--status", "in_progress"]) == 0
    assert "skipped" in capsys.readouterr().out
