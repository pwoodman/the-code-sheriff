"""High-confidence static patterns for the 120-point audit.

Every match is evidence (file + line + snippet). Patterns are written so they
do not match their own source. Tests and fixtures are skipped for security
heuristics unless skip_tests is False.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from quality_gates.audit.catalog import CHECK_BY_ID, Check
from quality_gates.audit.model import AuditFinding
from quality_gates.audit.walk import FileHit, RepoContext

_SECRET = re.compile(
    r"""(?ix)
    (?:api[_-]?key|apikey|secret_key|private_key|password|passwd|token|jwt_secret|
       aws_secret_access_key|database_url|mongodb_uri)
    \s*[=:]\s*['\"][^'\"]{12,}['\"]
    """
)
_AWS = re.compile(r"\bAKIA[0-9A-Z]{16}\b")
_PEM = re.compile(r"-----BEGIN (?:RSA |OPENSSH |EC )?PRIVATE KEY-----")
_PUBLIC_SECRET = re.compile(
    r"""(?ix)
    (?:NEXT_PUBLIC_|VITE_|REACT_APP_)
    (?:[A-Z0-9_]*?(?:SECRET|TOKEN|PASSWORD|PRIVATE|KEY))
    \s*[=:]\s*['\"][^'\"]{8,}['\"]
    """
)
_SQL_CONCAT = re.compile(
    r"""(?ix)
    (?:execute|executemany|raw|query|cursor\.execute)\s*\(\s*(?:f['\"].*(?:SELECT|INSERT|UPDATE|DELETE|WHERE)
      |['\"](?:SELECT|INSERT|UPDATE|DELETE).*(?:%s|\{|\+|`))
    |
    (?:SELECT|INSERT|UPDATE|DELETE)\s+[^;]{0,80}['\"]\s*\+
    |
    f['\"][^'\"]*(?:SELECT|INSERT|UPDATE|DELETE|WHERE)\s+[^'\"]*\{
    """
)
_MONGO_INJECT = re.compile(
    r"""(?ix)(?:find|update|delete)\s*\(\s*(?:request\.|req\.|body|json(?!\.)|params)"""
)
_SHELL = re.compile(
    r"""(?ix)
    (?:os\.system|os\.popen|commands\.getoutput)\s*\(
    |subprocess\.(?:call|run|Popen|check_output|check_call)\s*\([^)]{0,200}shell\s*=\s*True
    |child_process\.(?:exec|execSync|spawnSync)\s*\(
    |Runtime\.getRuntime\(\)\.exec\s*\(
    """
)
_XSS = re.compile(
    r"""(?ix)
    dangerouslySetInnerHTML\s*=
    |\.innerHTML\s*=
    |document\.write\s*\(
    |v-html\s*=
    |\|safe\}
    |markdown\.(?:html|convert)\s*\([^)]*(?:request|user|body|input)
    """
)
_TRAVERSAL = re.compile(
    r"""(?ix)
    (?:send_file|sendfile|FileResponse|open)\s*\(\s*(?:os\.path\.join\([^)]*(?:request|filename|user)
      |(?:request|req|params|body)\.[A-Za-z_]+)
    |path\.join\s*\([^)]*(?:req\.|request)
    """
)
_SSRF = re.compile(
    r"""(?ix)
    (?:requests\.(?:get|post|put|head|request)|httpx\.(?:get|post|request)|urllib\.request\.urlopen|
       aiohttp\.ClientSession\(\)[^;]{0,80}\.get|fetch)\s*\(\s*(?:request\.|req\.|url\s*=\s*(?:request|body|params))
    """
)
_WEAK_HASH = re.compile(
    r"""(?ix)
    (?:md5|sha1)\s*\(\s*(?:password|passwd|user_password)
    |hashlib\.(?:md5|sha1)\s*\(\s*(?:password|passwd)
    |DigestUtils\.(?:md5|sha1)
    """
)
_CUSTOM_AUTH = re.compile(
    r"""(?ix)
    (?:hmac\.new|hashlib\.sha256\s*\(\s*(?:password|passwd)|base64\.b64encode\s*\(\s*password)
    """
)
_JWT_NONE = re.compile(
    r"""(?ix)
    jwt\.(?:decode|verify)\s*\([^)]{0,200}(?:verify\s*=\s*False|algorithms\s*=\s*\[\s*['\"]none['\"])
    """
)
_LOCAL_TOKEN = re.compile(
    r"""(?ix)
    (?:localStorage|sessionStorage)\.setItem\s*\(\s*['\"][^'\"]*(?:token|jwt|session|auth)
    |document\.cookie\s*=\s*[^;]*(?:token|jwt)
    """
)
_COOKIE = re.compile(
    r"""(?ix)
    (?:set_cookie|Set-Cookie|cookies\.set)\s*\([^)]{0,200}(?:httponly\s*=\s*False|secure\s*=\s*False)
    """
)
_MASS = re.compile(
    r"(?ix)"
    r"\.update\s*\(\s*request\.(?:json|form|POST|data)"
    r"|(?:User|Account|Member)\s*\(\s*\*\*(?:request|data|payload|body)"
    r"|model_validate\s*\(\s*request\.(?:json|body)"
    r"|setattr\s*\(\s*\w+\s*,\s*(?:key|field)\s*,\s*(?:request|body)"
)
_PRIV_FIELD = re.compile(
    r"""(?ix)
    (?:request\.(?:json|data|form|POST)|body|payload)\s*(?:\[['\"]|\.get\(\s*['\"])
    (?:role|is_admin|is_superuser|permissions|account_status|balance|credit|owner_id|approved|verified)
    """
)
_SENSITIVE_RETURN = re.compile(
    r"""(?ix)
    (?:return|jsonify|JSONResponse)\s*\([^)]{0,200}(?:password_hash|passwordHash|hashed_password|secret_answer|api_key)
    """
)
_UPLOAD = re.compile(
    r"""(?ix)
    (?:save\s*\(\s*(?:os\.path\.join\()?[^)]*(?:filename|file\.filename)
      |\.save\(\s*request\.files
    )
    """
)
_ARCHIVE = re.compile(
    r"""(?ix)
    (?:ZipFile|tarfile\.open)\([^)]*\)\.(?:extractall|extract)\s*\(
    |shutil\.unpack_archive\s*\(
    """
)
_PICKLE = re.compile(
    r"""(?ix)
    pickle\.(?:loads|load)\s*\(
    |yaml\.load\s*\((?!.*Loader\s*=)
    |Marshal\.load
    |unserialize\s*\(
    """
)
_EVAL = re.compile(
    r"""(?ix)
    \beval\s*\(
    |\bexec\s*\(
    |new\s+Function\s*\(
    |setTimeout\s*\(\s*['\"]
    |__import__\s*\(\s*(?:request|user|input)
    """
)
_CORS = re.compile(
    r"""(?ix)
    Access-Control-Allow-Origin['\"]?\s*[:=]\s*['\"]\*['\"]
    |cors\(\s*(?:origins\s*=\s*\[\s*['\"]\*['\"]|origin\s*=\s*True)
    |app\.use\(\s*cors\(\s*\)
    |CORS_ORIGIN_ALLOW_ALL\s*=\s*True
    |AllowAnyOrigin\(\)
    """
)
_DEBUG = re.compile(
    r"""(?ix)
    DEBUG\s*=\s*True
    |app\.run\s*\([^)]*debug\s*=\s*True
    |SPRING_PROFILES_ACTIVE\s*=\s*['\"]dev['\"]
    |NODE_ENV\s*=\s*['\"]development['\"]
    """
)
_DEFAULT_CREDS = re.compile(
    r"""(?ix)
    (?:username|user|login)\s*=\s*['\"]admin['\"][^\n]{0,80}(?:password|passwd)\s*=\s*['\"](?:admin|password|changeme|secret)['\"]
    |password\s*=\s*['\"](?:admin|password|changeme|secret|123456)['\"]
    """
)
_PLACEHOLDER = re.compile(
    r"""(?ix)
    (?:\#|//|/\*|\*)\s*(?:TODO|FIXME|XXX|HACK)\b
    |raise\s+NotImplementedError
    """
)
_SWALLOW = re.compile(
    r"""(?m)^\s*except(?:\s+\w+(?:\s+as\s+\w+)?)?\s*:\s*(?:pass|\.\.\.)\s*$"""
)
_SWALLOW_JS = re.compile(r"catch\s*\(\s*\w*\s*\)\s*\{\s*\}")
_FAKE_OK = re.compile(
    r"""(?ix)
    except[\s\S]{0,80}return\s+(?:jsonify\([^)]*\)|\{[^}]*['\"]success['\"]\s*:\s*True)(?:[^,]*,\s*200)?
    """
)
_SELECT_STAR = re.compile(
    r"""(?ix)
    SELECT\s+\*\s+FROM
    |\.objects\.all\(\)
    |\.query\([^)]*\)\.all\(\)
    |find\(\s*\{\s*\}\s*\)
    |findMany\(\s*\)
    """
)
_NPLUS1 = re.compile(
    r"""(?ms)
    for\s+\w+\s+in\s+\w+[^\n]*:\n(?:[^\n]*\n){0,6}[^\n]*(?:
      \.objects\.(?:get|filter)|session\.(?:query|get|execute)|cursor\.execute|
      fetchone|find_one|findUnique
    )
    """
)
_CONNECT_LOOP = re.compile(
    r"""(?ix)
    (?:psycopg2\.connect|create_engine|MongoClient|redis\.Redis|httpx\.Client|requests\.Session)\s*\(
    """
)
_BLOCKING_ASYNC = re.compile(
    r"""(?ix)
    async\s+def\s+\w+[\s\S]{0,400}\b(?:time\.sleep|requests\.(?:get|post)|subprocess\.run|open\s*\()
    """
)
_NO_TIMEOUT = re.compile(
    r"""(?ix)
    requests\.(?:get|post|put|delete|request)\s*\([^)]{8,200}\)
    """
)
_RETRY_FOREVER = re.compile(
    r"""(?ix)
    while\s+True\s*:[\s\S]{0,200}(?:requests\.|httpx\.|retry)
    |Retry\s*\([^)]*infinite
    """
)
_UNBOUNDED = re.compile(
    r"""(?ix)
    while\s+True\s*:[\s\S]{0,160}(?:\.append\(|cache\[)
    """
)
_SOC = re.compile(
    r"""(?ix)
    (?:psycopg2\.connect|create_engine|sqlite3\.connect|MongoClient)\s*\(
    """
)
_DELETE_NO_CONFIRM = re.compile(
    r"""(?ix)
    (?:onClick|onPress|onSubmit)\s*=\s*\{[^}]{0,80}(?:delete|destroy|reset|revoke)
    """
)
_PAGE_BYPASS = re.compile(
    r"""(?ix)
    (?:limit|page_size|pageSize|per_page)\s*=\s*(?:int\()?[^\n]*(?:request|query|params|searchParams)
    """
)
_FILTER_DOS = re.compile(
    r"""(?ix)
    \.filter\s*\(\s*(?:request|query|params)
    |order_by\s*\(\s*(?:request|query|params)
    |\$where
    |raw\s*=\s*True
    """
)
_SYNC_LONG = re.compile(
    r"""(?ix)
    \b(?:openai|anthropic|replicate|ffmpeg)\s*\([^)]{0,200}\)
    """
)
_SERIALIZE = re.compile(
    r"""(?ix)
    (?:return\s+\w+\.dict\(\)|model_dump\(\)|JsonResponse\s*\(\s*\w+\.__dict__)
    """
)
_JWT_DECODE_LOOSE = re.compile(r"jwt\.decode\s*\(")
_REQUESTS_CALL = re.compile(r"requests\.(?:get|post|put|delete|request)\s*\(")


@dataclass(frozen=True)
class Pattern:
    check_id: int
    rule: str
    regex: re.Pattern[str]
    finding: str
    scenario: str
    skip_tests: bool = True
    skip_md: bool = True
    source_only: bool = False
    frontend_only: bool = False
    extra_filter: str | None = None  # timeout-missing uses this


PATTERNS: tuple[Pattern, ...] = (
    Pattern(
        4,
        "hardcoded-secret",
        _SECRET,
        "Hardcoded credential or secret assigned in source.",
        "Anyone with repo access can use this credential; it will leak in git history.",
    ),
    Pattern(
        4,
        "aws-access-key",
        _AWS,
        "AWS access key id embedded in the tree.",
        "The key can be used against the cloud account.",
    ),
    Pattern(
        4,
        "private-key-pem",
        _PEM,
        "PEM private key material in the repository.",
        "The private key can authenticate as the associated identity.",
    ),
    Pattern(
        5,
        "frontend-secret-env",
        _PUBLIC_SECRET,
        "Secret-like value exposed via a public frontend env prefix.",
        "The value ships in the browser bundle and is recoverable from DevTools.",
    ),
    Pattern(
        6,
        "sql-string-concat",
        _SQL_CONCAT,
        "SQL built from concatenated or interpolated strings.",
        "An attacker can change the query by supplying SQL metacharacters.",
    ),
    Pattern(
        6,
        "mongo-query-inject",
        _MONGO_INJECT,
        "Mongo query built directly from request data.",
        "Operator injection can return or modify another user's documents.",
    ),
    Pattern(
        7,
        "shell-exec",
        _SHELL,
        "Process spawned through a shell or OS exec API.",
        "User-controlled input in the command line can run arbitrary programs.",
    ),
    Pattern(
        8,
        "unsafe-html",
        _XSS,
        "HTML rendered without escaping.",
        "Script in user content runs in the victim's session.",
    ),
    Pattern(
        9,
        "path-join-request",
        _TRAVERSAL,
        "Filesystem path derived from request input.",
        "Paths containing ../ can read or write files outside the intended directory.",
    ),
    Pattern(
        10,
        "url-from-request",
        _SSRF,
        "Server-side HTTP client called with a request-controlled URL.",
        "The server can be pointed at localhost, metadata, or internal services.",
    ),
    Pattern(
        11,
        "homegrown-password",
        _CUSTOM_AUTH,
        "Homegrown password handling instead of a vetted library.",
        "Custom crypto is a common source of authentication bypass.",
    ),
    Pattern(
        12,
        "weak-password-hash",
        _WEAK_HASH,
        "Password hashed with MD5 or SHA-1.",
        "Offline cracking of leaked hashes is practical.",
    ),
    Pattern(
        14,
        "jwt-verify-false",
        _JWT_NONE,
        "JWT accepted without a proper signature/algorithm check.",
        "A forged token can impersonate any user.",
    ),
    Pattern(
        15,
        "token-in-web-storage",
        _LOCAL_TOKEN,
        "Auth token written to JavaScript-accessible storage.",
        "XSS can steal the session.",
    ),
    Pattern(
        16,
        "insecure-cookie-flags",
        _COOKIE,
        "Auth cookie set without Secure/HttpOnly.",
        "The cookie can be stolen over HTTP or by script.",
    ),
    Pattern(
        23,
        "mass-assignment",
        _MASS,
        "Request payload spread onto a model.",
        "Clients can set role, owner, or other privileged fields.",
    ),
    Pattern(
        24,
        "sensitive-in-response",
        _SENSITIVE_RETURN,
        "Response appears to include a secret field.",
        "Hashes, tokens, or keys leak to the client.",
    ),
    Pattern(
        25,
        "unsanitized-upload-name",
        _UPLOAD,
        "Uploaded file saved using a client-supplied name.",
        "A crafted filename can overwrite files or escape the upload directory.",
    ),
    Pattern(
        27,
        "extractall",
        _ARCHIVE,
        "Archive extracted without path checks.",
        "ZIP Slip / tar traversal can write outside the destination.",
    ),
    Pattern(
        28,
        "unsafe-deserialize",
        _PICKLE,
        "Untrusted data deserialized with a dangerous loader.",
        "Crafted payloads can execute code during load.",
    ),
    Pattern(
        29,
        "dynamic-exec",
        _EVAL,
        "Dynamic code execution.",
        "User-influenced strings become runnable code.",
    ),
    Pattern(
        31,
        "cors-star",
        _CORS,
        "CORS allows any origin.",
        "A malicious site can read authenticated responses if credentials are involved.",
    ),
    Pattern(
        32,
        "debug-true",
        _DEBUG,
        "Debug / development mode hardcoded on.",
        "Stack traces and debug consoles leak in production.",
    ),
    Pattern(
        33,
        "default-password",
        _DEFAULT_CREDS,
        "Default or example credential in source.",
        "Unchanged sample passwords are the first thing attackers try.",
    ),
    Pattern(
        46,
        "ui-db-connect",
        _SOC,
        "Database client constructed in a UI-layer file.",
        "UI components should not open infrastructure connections.",
        source_only=True,
        frontend_only=True,
    ),
    Pattern(
        50,
        "ui-db-direction",
        _SOC,
        "UI file depends directly on a database driver.",
        "Domain/UI layers should not import infrastructure.",
        source_only=True,
        frontend_only=True,
    ),
    Pattern(
        51,
        "placeholder",
        _PLACEHOLDER,
        "Placeholder marker (TODO/FIXME/NotImplemented) in production source.",
        "The feature is documented as present but the implementation is unfinished.",
        source_only=True,
        skip_md=True,
    ),
    Pattern(
        58,
        "fake-success",
        _FAKE_OK,
        "Exception path still returns success.",
        "Callers treat a failure as completed work.",
    ),
    Pattern(
        59,
        "swallowed-exception",
        _SWALLOW,
        "Exception handler discards the error with pass.",
        "Failures disappear; operators cannot detect them.",
    ),
    Pattern(
        59,
        "empty-catch",
        _SWALLOW_JS,
        "Empty catch block.",
        "The failure is swallowed with no log or recovery.",
    ),
    Pattern(
        61,
        "n-plus-one",
        _NPLUS1,
        "Database call inside a loop.",
        "Each extra row becomes another round-trip (N+1).",
    ),
    Pattern(
        63,
        "select-star",
        _SELECT_STAR,
        "Unbounded table read (SELECT * / .all() / findMany()).",
        "As the table grows this becomes a latency and memory incident.",
    ),
    Pattern(
        71,
        "blocking-in-async",
        _BLOCKING_ASYNC,
        "Synchronous I/O or sleep inside an async function.",
        "The event loop stalls for every concurrent request.",
    ),
    Pattern(
        73,
        "retry-forever",
        _RETRY_FOREVER,
        "Retry loop with no visible limit.",
        "A downstream outage can amplify into a retry storm.",
    ),
    Pattern(
        79,
        "unbounded-append",
        _UNBOUNDED,
        "Unbounded append/cache growth in a while-True loop.",
        "Memory grows until the process is killed.",
    ),
    Pattern(
        93,
        "delete-no-guard",
        _DELETE_NO_CONFIRM,
        "Destructive UI handler with no confirm/dialog in the same expression.",
        "A misclick permanently deletes data.",
    ),
    Pattern(
        103,
        "privileged-field-from-client",
        _PRIV_FIELD,
        "Privileged field taken from the client body.",
        "A caller can escalate role, balance, or ownership.",
    ),
    Pattern(
        108,
        "dump-model",
        _SERIALIZE,
        "Domain/ORM object dumped directly into a response.",
        "Newly added columns (hashes, flags) leak automatically.",
    ),
    Pattern(
        113,
        "client-controlled-limit",
        _PAGE_BYPASS,
        "Page size/limit taken from the client without an obvious cap nearby.",
        "limit=999999999 bypasses pagination and dumps the table.",
    ),
    Pattern(
        114,
        "dynamic-filter",
        _FILTER_DOS,
        "ORM filter/order_by/raw driven by request input.",
        "Unindexed or expression filters become a database DoS.",
    ),
    Pattern(
        118,
        "sync-inference",
        _SYNC_LONG,
        "Potentially long-running work invoked inline.",
        "The HTTP request blocks until inference/ffmpeg finishes.",
    ),
)


def scan_patterns(ctx: RepoContext) -> dict[int, list[AuditFinding]]:
    grouped: dict[int, list[AuditFinding]] = {}
    for hit in ctx.files:
        rel = hit.relative.replace("\\", "/")
        if rel.endswith("audit/patterns.py") or "/audit/patterns.py" in rel:
            continue
        for spec in PATTERNS:
            if spec.skip_tests and hit.is_test:
                continue
            if spec.skip_md and hit.path.suffix.lower() in {".md", ".rst"}:
                continue
            if spec.source_only and not hit.is_source:
                continue
            if spec.frontend_only and hit.path.suffix.lower() not in {
                ".tsx",
                ".jsx",
                ".vue",
                ".svelte",
                ".html",
            }:
                continue
            check = CHECK_BY_ID[spec.check_id]
            for match in spec.regex.finditer(hit.text):
                line_no = hit.text.count("\n", 0, match.start()) + 1
                snippet = _snippet(hit.lines, line_no)
                if _skip_meta(snippet):
                    continue
                finding = _finding(check, spec, hit, line_no, snippet)
                grouped.setdefault(check.id, []).append(finding)
        _timeout_hits(hit, grouped, CHECK_BY_ID[72])
        _jwt_loose(hit, grouped, CHECK_BY_ID[14])
        _connect_per_request(hit, grouped, CHECK_BY_ID[75])
        _select_columns(hit, grouped, CHECK_BY_ID[66])
    _dedupe(grouped)
    return grouped


def _timeout_hits(
    hit: FileHit, grouped: dict[int, list[AuditFinding]], check: Check
) -> None:
    if hit.is_test:
        return
    for match in _REQUESTS_CALL.finditer(hit.text):
        window = hit.text[match.start() : match.end() + 180]
        if "timeout" in window:
            continue
        line_no = hit.text.count("\n", 0, match.start()) + 1
        if _skip_meta(_snippet(hit.lines, line_no)):
            continue
        spec = Pattern(
            72,
            "missing-timeout",
            _REQUESTS_CALL,
            "Outbound HTTP call has no timeout argument in the call window.",
            "A hung peer holds a worker forever.",
        )
        grouped.setdefault(72, []).append(
            _finding(check, spec, hit, line_no, _snippet(hit.lines, line_no))
        )


def _jwt_loose(
    hit: FileHit, grouped: dict[int, list[AuditFinding]], check: Check
) -> None:
    if hit.is_test:
        return
    for match in _JWT_DECODE_LOOSE.finditer(hit.text):
        window = hit.text[match.start() : match.end() + 220]
        compact = window.replace(" ", "")
        if "algorithms" in window and "verify=False" not in compact:
            continue
        line_no = hit.text.count("\n", 0, match.start()) + 1
        spec = Pattern(
            14,
            "jwt-decode-loose",
            _JWT_DECODE_LOOSE,
            "jwt.decode used without an explicit algorithms allowlist in the call window.",
            "An unexpected algorithm (including none) may be accepted.",
        )
        grouped.setdefault(14, []).append(
            _finding(check, spec, hit, line_no, _snippet(hit.lines, line_no))
        )


def _connect_per_request(
    hit: FileHit, grouped: dict[int, list[AuditFinding]], check: Check
) -> None:
    if hit.is_test or not hit.is_source:
        return
    if "def " not in hit.text and "func " not in hit.text:
        return
    for match in _CONNECT_LOOP.finditer(hit.text):
        # Flag when connect/engine is constructed inside a handler-looking function.
        line_no = hit.text.count("\n", 0, match.start()) + 1
        prefix = "\n".join(hit.lines[max(0, line_no - 12) : line_no])
        if not re.search(r"(def\s+\w+|async\s+def\s+\w+|func\s+\w+)\s*\(", prefix):
            continue
        if re.search(
            r"(get|post|put|patch|delete|handler|endpoint|view)", prefix, re.I
        ):
            spec = Pattern(
                75,
                "connect-in-handler",
                _CONNECT_LOOP,
                "New database/HTTP client constructed inside a request handler.",
                "Each request opens a connection instead of using a pool.",
            )
            grouped.setdefault(75, []).append(
                _finding(check, spec, hit, line_no, _snippet(hit.lines, line_no))
            )


def _select_columns(
    hit: FileHit, grouped: dict[int, list[AuditFinding]], check: Check
) -> None:
    if hit.is_test:
        return
    for match in re.finditer(r"(?i)SELECT\s+\*\s+FROM", hit.text):
        line_no = hit.text.count("\n", 0, match.start()) + 1
        spec = Pattern(
            66,
            "select-star-columns",
            _SELECT_STAR,
            "Query loads every column including blobs/json that the caller may not need.",
            "Payload and I/O grow with unused columns.",
        )
        grouped.setdefault(66, []).append(
            _finding(check, spec, hit, line_no, _snippet(hit.lines, line_no))
        )


def _finding(
    check: Check, spec: Pattern, hit: FileHit, line_no: int, snippet: str
) -> AuditFinding:
    return AuditFinding(
        check_id=check.id,
        title=check.title,
        severity=check.severity,
        priority=check.priority,
        category=check.category,
        confidence="HIGH",
        finding=spec.finding,
        why=check.why,
        evidence=f"{hit.relative}:{line_no}: {snippet}",
        scenario=spec.scenario,
        fix=check.fix,
        path=hit.relative,
        line=line_no,
        component=Pathish(hit.relative),
        suggested_test=f"Regression: the pattern {spec.rule} must not reappear at {hit.relative}.",
        references=f"audit check {check.id} / {spec.rule}",
        can_auto_fix="No",
        regression_test="Yes",
        effort="S",
    )


def Pathish(relative: str) -> str:
    parts = relative.replace("\\", "/").split("/")
    if len(parts) >= 2:
        return "/".join(parts[:2])
    return parts[0]


def _skip_meta(line: str) -> bool:
    """Regex catalogs, detector messages, and help strings are not defects."""
    stripped = line.strip().rstrip(",")
    if "re.compile" in stripped:
        return True
    if stripped.startswith(('r"', "r'", 'r"""', "r'''")):
        return True
    if "TODO/FIXME" in stripped:
        return True
    return bool(re.match(r"""^['\"][^'\"]+['\"]$""", stripped))


def _snippet(lines: list[str], line_no: int, width: int = 180) -> str:
    if line_no < 1 or line_no > len(lines):
        return ""
    text = lines[line_no - 1].strip()
    if len(text) > width:
        return text[: width - 3] + "..."
    return text


def _dedupe(grouped: dict[int, list[AuditFinding]]) -> None:
    for check_id, items in list(grouped.items()):
        seen: dict[tuple[str | None, int | None, str], AuditFinding] = {}
        for item in items:
            key = (item.path, item.line, item.finding)
            if key in seen:
                seen[key].occurrences += 1
            else:
                seen[key] = item
        grouped[check_id] = list(seen.values())
