"""The Code Sheriff GitHub App: manifest, optional webhook, Actions dispatch."""

from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from quality_gates.github_comment import API_VERSION, pr_head_sha
from quality_gates.identity import (
    CHECK_NAME,
    DEFAULT_APP_NAME,
    DEFAULT_HOME_REPO,
    DISPATCH_EVENT,
    HOMEPAGE,
    PRODUCT,
    USER_AGENT,
)
from quality_gates.paths import repo_root

PULL_ACTIONS = {"opened", "synchronize", "reopened", "ready_for_review"}
CREDENTIALS_DIRNAME = ".quality-app"


@dataclass(frozen=True)
class AppSettings:
    webhook_secret: str
    dispatch_token: str = ""
    home_repo: str = DEFAULT_HOME_REPO
    dispatch_ref: str = "main"
    skip_home: bool = True
    app_id: str = ""
    private_key: str = ""


def default_manifest(
    *,
    name: str = DEFAULT_APP_NAME,
    webhook_url: str,
    redirect_url: str,
    public: bool = False,
) -> dict[str, Any]:
    return {
        "name": name,
        "url": HOMEPAGE,
        "description": (
            f"{PRODUCT} runs change-aware quality gates: format, lint, security "
            "(SAST, secrets, SCA, IaC, SBOM), compile, impact, coverage, audit, and "
            "review as one required check."
        ),
        "public": public,
        "redirect_url": redirect_url,
        "hook_attributes": {"url": webhook_url, "active": False},
        "default_events": ["pull_request", "check_run"],
        "default_permissions": {
            "checks": "write",
            "contents": "read",
            "metadata": "read",
            "pull_requests": "write",
            "security_events": "write",
        },
    }


def load_manifest(**kwargs: Any) -> dict[str, Any]:
    root = repo_root()
    path = root / "github-app" / "manifest.json" if root else None
    if path and path.is_file():
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            data = dict(data)
            hooks = dict(data.get("hook_attributes") or {})
            if kwargs.get("webhook_url"):
                hooks["url"] = kwargs["webhook_url"]
                data["hook_attributes"] = hooks
            if kwargs.get("redirect_url"):
                data["redirect_url"] = kwargs["redirect_url"]
            if kwargs.get("name"):
                data["name"] = kwargs["name"]
            if "public" in kwargs and kwargs["public"] is not None:
                data["public"] = bool(kwargs["public"])
            return data
    return default_manifest(
        name=str(kwargs.get("name") or DEFAULT_APP_NAME),
        webhook_url=str(kwargs.get("webhook_url") or "https://example.invalid/webhook"),
        redirect_url=str(kwargs.get("redirect_url") or "http://127.0.0.1/callback"),
        public=bool(kwargs.get("public")),
    )


def settings_from_env() -> AppSettings:
    skip = os.environ.get("QUALITY_APP_HANDLE_HOME", "").lower() not in {
        "1",
        "true",
        "yes",
    }
    return AppSettings(
        webhook_secret=os.environ.get("QUALITY_APP_WEBHOOK_SECRET")
        or os.environ.get("WEBHOOK_SECRET")
        or "",
        dispatch_token=os.environ.get("QUALITY_APP_DISPATCH_TOKEN")
        or os.environ.get("DISPATCH_TOKEN")
        or "",
        home_repo=os.environ.get("QUALITY_APP_HOME_REPO") or DEFAULT_HOME_REPO,
        dispatch_ref=os.environ.get("QUALITY_APP_DISPATCH_REF") or "main",
        skip_home=skip,
        app_id=os.environ.get("QUALITY_APP_ID") or os.environ.get("APP_ID") or "",
        private_key=normalize_pem(
            os.environ.get("QUALITY_APP_PRIVATE_KEY")
            or os.environ.get("PRIVATE_KEY")
            or ""
        ),
    )


def normalize_pem(raw: str) -> str:
    text = raw.strip()
    if not text:
        return ""
    if "\\n" in text and "BEGIN" in text:
        text = text.replace("\\n", "\n")
    path = Path(text)
    if path.is_file():
        return path.read_text(encoding="utf-8")
    return text


def verify_signature(secret: str, signature_header: str | None, body: bytes) -> bool:
    if not secret or not signature_header:
        return False
    digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    expected = f"sha256={digest}"
    return hmac.compare_digest(expected, signature_header.strip())


def canonical_json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, separators=(",", ":"), sort_keys=True)


def dispatch_body(payload: dict[str, Any]) -> dict[str, str]:
    return {
        str(key): str(value)
        for key, value in payload.items()
        if key != "sig" and value is not None
    }


def sign_dispatch(secret: str, payload: dict[str, Any]) -> str:
    return hmac.new(
        secret.encode("utf-8"),
        canonical_json(dispatch_body(payload)).encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def verify_dispatch(secret: str, payload: dict[str, Any], signature: str) -> bool:
    if not secret or not signature:
        return False
    return hmac.compare_digest(sign_dispatch(secret, payload), signature)


def job_from_webhook(event: str, payload: dict[str, Any]) -> dict[str, str] | None:
    if event == "ping":
        return {"kind": "ping"}
    if event == "installation" and payload.get("action") == "created":
        account = ((payload.get("installation") or {}).get("account") or {}).get(
            "login"
        )
        return {"kind": "installed", "account": str(account or "")}
    if event == "pull_request":
        action = str(payload.get("action") or "")
        pull = payload.get("pull_request") or {}
        if action not in PULL_ACTIONS:
            return None
        if pull.get("draft") and action != "ready_for_review":
            return None
        return _run_job(
            repository=(payload.get("repository") or {}).get("full_name"),
            sha=(pull.get("head") or {}).get("sha"),
            pr=pull.get("number"),
            installation_id=(payload.get("installation") or {}).get("id"),
            base=(pull.get("base") or {}).get("ref"),
            fork=_is_fork(pull, (payload.get("repository") or {}).get("full_name")),
        )
    if event == "check_run" and payload.get("action") == "rerequested":
        check = payload.get("check_run") or {}
        if check.get("name") not in {CHECK_NAME, "quality-review"}:
            return None
        pull = (check.get("pull_requests") or [None])[0] or {}
        return _run_job(
            repository=(payload.get("repository") or {}).get("full_name"),
            sha=check.get("head_sha"),
            pr=pull.get("number"),
            installation_id=(payload.get("installation") or {}).get("id"),
            base=(pull.get("base") or {}).get("ref"),
            fork="false",
        )
    return None


def _is_fork(pull: dict[str, Any], repository: object) -> str:
    head_repo = ((pull.get("head") or {}).get("repo") or {}).get("full_name")
    return "true" if head_repo and head_repo != repository else "false"


def _run_job(
    *,
    repository: object,
    sha: object,
    pr: object,
    installation_id: object,
    base: object,
    fork: str,
) -> dict[str, str] | None:
    if not repository or not sha or not pr or not installation_id:
        return None
    return {
        "kind": "run",
        "repository": str(repository),
        "sha": str(sha),
        "pr": str(pr),
        "installation_id": str(installation_id),
        "base": str(base or "main"),
        "fork": fork,
    }


def handle_webhook(
    headers: dict[str, str], body: bytes, settings: AppSettings
) -> tuple[int, dict[str, Any]]:
    lowered = {key.lower(): value for key, value in headers.items()}
    signature = lowered.get("x-hub-signature-256")
    event = lowered.get("x-github-event") or ""
    if not verify_signature(settings.webhook_secret, signature, body):
        return 401, {"error": "invalid signature"}
    try:
        payload = json.loads(body.decode("utf-8") or "{}")
    except json.JSONDecodeError:
        return 400, {"error": "invalid json"}
    if not isinstance(payload, dict):
        return 400, {"error": "invalid json"}
    job = job_from_webhook(event, payload)
    if job is None:
        return 202, {"ok": True, "ignored": event or "unknown"}
    if job["kind"] == "ping":
        return 200, {"ok": True, "pong": True}
    if job["kind"] == "installed":
        return 200, {"ok": True, "installed": job.get("account")}
    if settings.skip_home and job["repository"] == settings.home_repo:
        return 202, {"ok": True, "skipped": "home repository uses its own workflow"}
    token = resolve_dispatch_token(settings)
    if not token:
        return 503, {
            "error": "set QUALITY_APP_DISPATCH_TOKEN or QUALITY_APP_ID + PRIVATE_KEY"
        }
    unsigned = dispatch_body(
        {key: value for key, value in job.items() if key != "kind"}
    )
    unsigned["sig"] = sign_dispatch(settings.webhook_secret, unsigned)
    status, data = dispatch_job(settings, unsigned, token)
    if status >= 300:
        return status, {"error": "dispatch failed", "github": data}
    return 202, {"ok": True, "dispatched": unsigned["repository"], "pr": unsigned["pr"]}


def resolve_dispatch_token(settings: AppSettings) -> str:
    if settings.dispatch_token:
        return settings.dispatch_token
    if not settings.app_id or not settings.private_key:
        return ""
    token_jwt = app_jwt(settings.app_id, settings.private_key)
    status, data = api_request(
        "GET",
        f"https://api.github.com/repos/{settings.home_repo}/installation",
        token_jwt,
    )
    installation_id = data.get("id") if isinstance(data, dict) else None
    if status >= 300 or not installation_id:
        return ""
    try:
        return installation_token(
            settings.app_id, settings.private_key, str(installation_id)
        )
    except RuntimeError:
        return ""


def dispatch_job(
    settings: AppSettings, payload: dict[str, str], token: str | None = None
) -> tuple[int, Any]:
    url = f"https://api.github.com/repos/{settings.home_repo}/dispatches"
    return api_request(
        "POST",
        url,
        token or settings.dispatch_token,
        {"event_type": DISPATCH_EVENT, "client_payload": payload},
    )


def api_request(
    method: str, url: str, token: str, payload: dict[str, Any] | None = None
) -> tuple[int, Any]:
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": API_VERSION,
        "User-Agent": USER_AGENT,
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    data = None
    if payload is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            raw = response.read().decode("utf-8")
            parsed: Any
            try:
                parsed = json.loads(raw) if raw else {}
            except json.JSONDecodeError:
                parsed = {}
            return response.status, parsed
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            parsed = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            parsed = {"message": raw[:300]}
        return exc.code, parsed
    except urllib.error.URLError as exc:
        return 0, {"message": str(exc)}


def app_jwt(app_id: str, pem: str, *, now: int | None = None) -> str:
    issued = int(now if now is not None else time.time())
    header = {"alg": "RS256", "typ": "JWT"}
    claims = {"iat": issued - 60, "exp": issued + 540, "iss": app_id}
    signing_input = (
        f"{_b64url(json.dumps(header, separators=(',', ':')).encode())}."
        f"{_b64url(json.dumps(claims, separators=(',', ':')).encode())}"
    )
    signature = _rsa_sign(pem, signing_input.encode("ascii"))
    return f"{signing_input}.{_b64url(signature)}"


def installation_token(app_id: str, pem: str, installation_id: str) -> str:
    token_jwt = app_jwt(app_id, pem)
    status, data = api_request(
        "POST",
        f"https://api.github.com/app/installations/{installation_id}/access_tokens",
        token_jwt,
        {},
    )
    if status >= 300 or not isinstance(data, dict) or not data.get("token"):
        raise RuntimeError(f"installation token failed HTTP {status}: {data}")
    return str(data["token"])


def post_check(
    *,
    name: str = CHECK_NAME,
    status: str = "in_progress",
    conclusion: str | None = None,
    title: str = "",
    summary: str = "",
) -> str:
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    repo = os.environ.get("GITHUB_REPOSITORY")
    sha = pr_head_sha()
    if not token or not repo or not sha:
        return "skipped check run (need GITHUB_TOKEN, GITHUB_REPOSITORY, SHA)"
    payload: dict[str, Any] = {
        "name": name,
        "head_sha": sha,
        "status": status,
    }
    if status == "completed":
        payload["conclusion"] = conclusion or "neutral"
    if title or summary:
        payload["output"] = {
            "title": (title or name)[:255],
            "summary": (summary or title or name)[:65535],
        }
    code, data = api_request(
        "POST", f"https://api.github.com/repos/{repo}/check-runs", token, payload
    )
    if 200 <= code < 300:
        return f"posted check run {name} ({status})"
    message = data.get("message") if isinstance(data, dict) else data
    return f"GitHub check run HTTP {code} ({message})"


def credentials_dir(root: Path) -> Path:
    path = root / CREDENTIALS_DIRNAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def save_credentials(root: Path, payload: dict[str, Any]) -> Path:
    directory = credentials_dir(root)
    pem = str(payload.get("pem") or "")
    if pem:
        pem_path = directory / "app.pem"
        pem_path.write_text(pem, encoding="utf-8")
        pem_path.chmod(0o600)
    body = {
        "id": payload.get("id"),
        "client_id": payload.get("client_id") or payload.get("slug"),
        "slug": payload.get("slug"),
        "name": payload.get("name"),
        "webhook_secret": payload.get("webhook_secret"),
        "html_url": payload.get("html_url"),
    }
    path = directory / "credentials.json"
    path.write_text(json.dumps(body, indent=2) + "\n", encoding="utf-8")
    path.chmod(0o600)
    env_path = directory / "credentials.env"
    env_path.write_text(
        "\n".join(
            [
                f"QUALITY_APP_ID={payload.get('id') or ''}",
                f"QUALITY_APP_WEBHOOK_SECRET={payload.get('webhook_secret') or ''}",
                f"QUALITY_APP_PRIVATE_KEY={directory / 'app.pem'}",
                f"QUALITY_APP_HOME_REPO={DEFAULT_HOME_REPO}",
                "",
            ]
        ),
        encoding="utf-8",
    )
    env_path.chmod(0o600)
    return path


def apply_saved_credentials(root: Path) -> None:
    directory = root / CREDENTIALS_DIRNAME
    creds = directory / "credentials.json"
    pem = directory / "app.pem"
    if creds.is_file() and not os.environ.get("QUALITY_APP_ID"):
        try:
            data = json.loads(creds.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            data = {}
        if isinstance(data, dict):
            if data.get("id"):
                os.environ["QUALITY_APP_ID"] = str(data["id"])
            if data.get("webhook_secret") and not os.environ.get(
                "QUALITY_APP_WEBHOOK_SECRET"
            ):
                os.environ["QUALITY_APP_WEBHOOK_SECRET"] = str(data["webhook_secret"])
    if pem.is_file() and not os.environ.get("QUALITY_APP_PRIVATE_KEY"):
        os.environ["QUALITY_APP_PRIVATE_KEY"] = str(pem)


def _set_webhook(url: str) -> int:
    settings = settings_from_env()
    if not settings.app_id or not settings.private_key:
        print("set QUALITY_APP_ID and QUALITY_APP_PRIVATE_KEY", file=sys.stderr)
        return 2
    token_jwt = app_jwt(settings.app_id, settings.private_key)
    status, data = api_request(
        "PATCH",
        "https://api.github.com/app/hook/config",
        token_jwt,
        {"url": url, "content_type": "json", "insecure_ssl": "0"},
    )
    if status >= 300:
        print(f"webhook update failed HTTP {status}: {data}", file=sys.stderr)
        return 1
    print(f"webhook -> {url}")
    return 0


def exchange_manifest_code(code: str) -> dict[str, Any]:
    status, data = api_request(
        "POST", f"https://api.github.com/app-manifests/{code}/conversions", "", {}
    )
    if status >= 300 or not isinstance(data, dict):
        raise RuntimeError(f"manifest conversion failed HTTP {status}: {data}")
    return data


def cli_github_app(args: argparse.Namespace) -> int:
    command = getattr(args, "app_command", None)
    root = Path.cwd()
    apply_saved_credentials(root)
    if command == "manifest":
        webhook = args.webhook_url or "https://example.invalid/webhook"
        redirect = args.redirect_url or "http://127.0.0.1:8787/callback"
        print(
            json.dumps(
                load_manifest(
                    name=args.name,
                    webhook_url=webhook,
                    redirect_url=redirect,
                    public=args.public,
                ),
                indent=2,
            )
        )
        return 0
    if command == "register":
        return _register(root, args)
    if command == "serve":
        settings = settings_from_env()
        if not settings.webhook_secret:
            print("set QUALITY_APP_WEBHOOK_SECRET", file=sys.stderr)
            return 2
        return serve(settings, host=args.host, port=args.port)
    if command == "handle":
        return _handle_cli(args)
    if command == "check":
        print(
            post_check(
                name=args.name,
                status=args.status,
                conclusion=args.conclusion or None,
                title=args.title,
                summary=args.summary,
            )
        )
        return 0
    if command == "prepare":
        return _prepare_dispatch()
    if command == "webhook":
        return _set_webhook(args.url)
    if command == "token":
        settings = settings_from_env()
        if not settings.app_id or not settings.private_key:
            print("set QUALITY_APP_ID and QUALITY_APP_PRIVATE_KEY", file=sys.stderr)
            return 2
        print(
            installation_token(
                settings.app_id, settings.private_key, args.installation_id
            )
        )
        return 0
    print(f"unknown github-app command: {command}", file=sys.stderr)
    return 2


def serve(settings: AppSettings, *, host: str, port: int) -> int:
    handler = _handler_for(settings, None)

    class Server(ThreadingHTTPServer):
        allow_reuse_address = True
        daemon_threads = True

    httpd = Server((host, port), handler)
    print(f"The Code Sheriff webhook on http://{host}:{port}/webhook", flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("stopped", flush=True)
        return 0
    return 0


def _prepare_dispatch() -> int:
    settings = settings_from_env()
    event_path = os.environ.get("GITHUB_EVENT_PATH")
    event_name = os.environ.get("GITHUB_EVENT_NAME")
    if event_name == "workflow_dispatch":
        payload = json.loads(os.environ.get("QUALITY_APP_PAYLOAD") or "{}")
    elif event_path and Path(event_path).is_file():
        event = json.loads(Path(event_path).read_text(encoding="utf-8"))
        payload = event.get("client_payload") if isinstance(event, dict) else {}
    else:
        print("no GitHub event payload", file=sys.stderr)
        return 2
    if not isinstance(payload, dict):
        print("invalid dispatch payload", file=sys.stderr)
        return 2
    signature = str(payload.get("sig") or "")
    body = dispatch_body(payload)
    if not verify_dispatch(settings.webhook_secret, body, signature):
        print("invalid dispatch signature", file=sys.stderr)
        return 1
    required = ("repository", "sha", "pr", "installation_id", "base")
    missing = [key for key in required if not body.get(key)]
    if missing:
        print(f"dispatch missing {', '.join(missing)}", file=sys.stderr)
        return 2
    output = os.environ.get("GITHUB_OUTPUT")
    if output:
        with Path(output).open("a", encoding="utf-8") as handle:
            for key, value in body.items():
                handle.write(f"{key}={value}\n")
    print(json.dumps(body, indent=2))
    return 0


def _handle_cli(args: argparse.Namespace) -> int:
    settings = settings_from_env()
    raw = (
        sys.stdin.buffer.read()
        if args.payload == "-"
        else Path(args.payload).read_bytes()
    )
    signature = args.signature or (
        f"sha256={hmac.new(settings.webhook_secret.encode(), raw, hashlib.sha256).hexdigest()}"
        if settings.webhook_secret
        else ""
    )
    headers = {
        "X-Hub-Signature-256": signature,
        "X-GitHub-Event": args.event,
        "Content-Type": "application/json",
    }
    status, payload = handle_webhook(headers, raw, settings)
    print(json.dumps(payload, indent=2))
    return 0 if status < 300 else 1


def _register(root: Path, args: argparse.Namespace) -> int:
    host = args.host
    port = args.port
    redirect = f"http://{host}:{port}/callback"
    webhook = args.webhook_url or "https://example.invalid/webhook"
    manifest = load_manifest(
        name=args.name,
        webhook_url=webhook,
        redirect_url=redirect,
        public=args.public,
    )
    target = (
        f"https://github.com/organizations/{args.org}/settings/apps/new"
        if args.org
        else "https://github.com/settings/apps/new"
    )
    state: dict[str, Any] = {"done": None, "error": None}
    handler = _handler_for(None, (manifest, target, root, state))

    class Server(ThreadingHTTPServer):
        allow_reuse_address = True

    httpd = Server((host, port), handler)
    page = redirect.replace("/callback", "/")
    print(f"Open {page} to create the GitHub App.", flush=True)
    print("Defaults are filled. Click Create GitHub App, then authorize.", flush=True)
    if not getattr(args, "no_open", False):
        webbrowser.open(page)
    httpd.timeout = 1
    try:
        while state["done"] is None and state["error"] is None:
            try:
                httpd.handle_request()
            except TimeoutError:
                continue
    except KeyboardInterrupt:
        print("cancelled", flush=True)
        return 1
    if state["error"]:
        print(state["error"], file=sys.stderr)
        return 1
    created = state["done"] or {}
    path = save_credentials(root, created)
    ident = created.get("id")
    slug = created.get("slug") or ""
    html = str(created.get("html_url") or "")
    if not html and slug:
        html = f"https://github.com/apps/{slug}"
    install = f"{html.rstrip('/')}/installations/new" if html else ""
    print(f"saved credentials to {path}")
    if not getattr(args, "no_init", False):
        from quality_gates.onboard import init_repo

        init_repo(root, org=str(args.org or ""), require_check=True)
    print()
    if install:
        print(f"Install The Code Sheriff: {install}")
        if not getattr(args, "no_open", False):
            webbrowser.open(install)
    else:
        print(
            "Install The Code Sheriff on the repos you own from the App's GitHub page."
        )
    print("Webhook stays inactive. No Worker or PAT is required.")
    if ident:
        print("Optional bot identity:")
        print(f"  gh secret set QUALITY_APP_ID --body {ident}")
        print("  gh secret set QUALITY_APP_PRIVATE_KEY < .quality-app/app.pem")
    return 0


def _handler_for(
    settings: AppSettings | None,
    register: tuple[dict[str, Any], str, Path, dict[str, Any]] | None,
):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            parsed = urllib.parse.urlparse(self.path)
            if parsed.path in {"/", "/health"}:
                if register:
                    self._html(_register_page(register[0], register[1]))
                    return
                self._json(200, {"ok": True, "app": "the-codesheriff"})
                return
            if parsed.path == "/callback" and register:
                query = urllib.parse.parse_qs(parsed.query)
                code = (query.get("code") or [""])[0]
                try:
                    payload = exchange_manifest_code(code)
                except (RuntimeError, OSError, ValueError) as exc:
                    register[3]["error"] = str(exc)
                    self._html(f"<pre>registration failed: {exc}</pre>", status=400)
                    return
                register[3]["done"] = payload
                save_credentials(register[2], payload)
                self._html(
                    "<p>App created. You can close this tab and return to the terminal.</p>"
                )
                return
            self._json(404, {"error": "not found"})

        def do_POST(self) -> None:
            parsed = urllib.parse.urlparse(self.path)
            if parsed.path not in {"/", "/webhook", "/event"}:
                self._json(404, {"error": "not found"})
                return
            if settings is None:
                self._json(
                    503, {"error": "webhook serving is not enabled on this process"}
                )
                return
            length = int(self.headers.get("Content-Length") or 0)
            body = self.rfile.read(length)
            headers = {key: value for key, value in self.headers.items()}
            status, payload = handle_webhook(headers, body, settings)
            self._json(status, payload)

        def log_message(self, fmt: str, *args: object) -> None:
            sys.stderr.write(f"{self.address_string()} - {fmt % args}\n")

        def _json(self, status: int, payload: dict[str, Any]) -> None:
            raw = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def _html(self, body: str, status: int = 200) -> None:
            raw = f"<!doctype html><html><body>{body}</body></html>".encode()
            self.send_response(status)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

    return Handler


def _register_page(manifest: dict[str, Any], action: str) -> str:
    encoded = json.dumps(manifest)
    return (
        "<h1>Create The Code Sheriff GitHub App</h1>"
        "<p>Defaults are already filled: webhook inactive, contents read-only, "
        "checks run on each installed repo's GitHub Actions minutes. "
        "No telemetry is sent. Click the button.</p>"
        f'<form action="{action}" method="post">'
        f'<input type="hidden" name="manifest" value="{_html_escape(encoded)}">'
        '<button type="submit">Create GitHub App</button>'
        "</form>"
    )


def _html_escape(value: str) -> str:
    return (
        value.replace("&", "&amp;")
        .replace('"', "&quot;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _rsa_sign(pem: str, data: bytes) -> bytes:
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False) as handle:
        handle.write(pem)
        path = handle.name
    try:
        result = subprocess.run(
            ["openssl", "dgst", "-sha256", "-sign", path],
            input=data,
            capture_output=True,
            check=False,
        )
        if result.returncode != 0:
            err = result.stderr.decode("utf-8", errors="replace")
            raise RuntimeError(f"openssl RS256 sign failed: {err}")
        return result.stdout
    finally:
        Path(path).unlink(missing_ok=True)
