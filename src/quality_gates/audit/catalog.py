"""Canonical 120-point AI-generated-code audit checklist.

Titles and severities match the published inspection. Detectors and required
surfaces live here so markdown docs do not duplicate the catalog (jscpd).
"""

from __future__ import annotations

from dataclasses import dataclass

CAT_SECURITY = "Security & Access Control"
CAT_AUTH = "Authentication, Sessions & API Security"
CAT_INPUT = "Input, Data & File Handling"
CAT_SUPPLY = "Security Configuration & Supply Chain"
CAT_ARCH = "Architecture & AI-Generated Code Quality"
CAT_AI = "AI Hallucinations & Incomplete Implementations"
CAT_DB = "Database & Persistence"
CAT_BE = "Backend/API Performance & Reliability"
CAT_FE = "Frontend Performance"
CAT_UX = "UX, Accessibility & Workflow"
CAT_API = "Additional API-Specific Checks"


@dataclass(frozen=True)
class Check:
    id: int
    title: str
    severity: str
    priority: str
    category: str
    detector: str
    surfaces: tuple[str, ...]
    why: str
    fix: str


def _c(
    check_id: int,
    title: str,
    severity: str,
    category: str,
    detector: str,
    surfaces: str = "",
    why: str = "",
    fix: str = "",
) -> Check:
    priority = {"CRITICAL": "P0", "HIGH": "P1", "MEDIUM": "P2"}[severity]
    return Check(
        id=check_id,
        title=title,
        severity=severity,
        priority=priority,
        category=category,
        detector=detector,
        surfaces=tuple(part for part in surfaces.split(",") if part),
        why=why
        or "This class of defect shows up often in AI-generated code and causes real failures.",
        fix=fix
        or "Fix the smallest evidence-backed issue; do not rewrite the architecture.",
    )


# detector:
#   pattern / authz / cycles / lockfile / actions / ci_perms / god_file
#   dead_code / craft / observe / runtime — runtime is never a confirmed
#   defect without evidence. craft is AST/lexical clean-code evidence.
CHECKS: tuple[Check, ...] = (
    _c(
        1,
        "Missing Server-Side Authorization",
        "CRITICAL",
        CAT_SECURITY,
        "authz",
        "http",
    ),
    _c(
        2,
        "Broken Object-Level Authorization / IDOR",
        "CRITICAL",
        CAT_SECURITY,
        "authz",
        "http",
    ),
    _c(
        3,
        "Admin Functionality Protected Only by UI",
        "CRITICAL",
        CAT_SECURITY,
        "authz",
        "http,frontend",
    ),
    _c(4, "Hardcoded Secrets", "CRITICAL", CAT_SECURITY, "pattern"),
    _c(
        5,
        "Secrets Exposed to Frontend Bundles",
        "CRITICAL",
        CAT_SECURITY,
        "pattern",
        "frontend",
    ),
    _c(6, "SQL / NoSQL Injection", "CRITICAL", CAT_SECURITY, "pattern", "http,sql"),
    _c(7, "Command / Shell Injection", "CRITICAL", CAT_SECURITY, "pattern"),
    _c(
        8,
        "Cross-Site Scripting / Unsafe HTML",
        "CRITICAL",
        CAT_SECURITY,
        "pattern",
        "frontend,http",
    ),
    _c(9, "Path Traversal", "CRITICAL", CAT_SECURITY, "pattern", "http"),
    _c(10, "Server-Side Request Forgery", "CRITICAL", CAT_SECURITY, "pattern", "http"),
    _c(11, "Weak Custom Authentication", "CRITICAL", CAT_AUTH, "pattern", "auth"),
    _c(12, "Passwords Stored Incorrectly", "CRITICAL", CAT_AUTH, "pattern", "auth"),
    _c(13, "Missing Brute-Force Protection", "HIGH", CAT_AUTH, "runtime", "auth"),
    _c(14, "Weak JWT Validation", "HIGH", CAT_AUTH, "pattern", "auth"),
    _c(
        15,
        "Authentication Tokens Stored Insecurely",
        "HIGH",
        CAT_AUTH,
        "pattern",
        "frontend",
    ),
    _c(16, "Insecure Cookies", "HIGH", CAT_AUTH, "pattern", "http"),
    _c(17, "Missing CSRF Protection", "HIGH", CAT_AUTH, "runtime", "http"),
    _c(18, "Weak Password Recovery", "HIGH", CAT_AUTH, "runtime", "auth"),
    _c(19, "Missing Session Invalidation", "HIGH", CAT_AUTH, "runtime", "auth"),
    _c(20, "Unlimited API Resource Consumption", "HIGH", CAT_AUTH, "runtime", "http"),
    _c(
        21,
        "Trusting Frontend Validation",
        "HIGH",
        CAT_INPUT,
        "runtime",
        "http,frontend",
    ),
    _c(22, "Missing Schema Validation", "HIGH", CAT_INPUT, "runtime", "http"),
    _c(23, "Mass Assignment / Over-Posting", "HIGH", CAT_INPUT, "pattern", "http"),
    _c(
        24,
        "Sensitive Fields Returned Unnecessarily",
        "HIGH",
        CAT_INPUT,
        "pattern",
        "http",
    ),
    _c(25, "Unsafe File Uploads", "HIGH", CAT_INPUT, "pattern", "upload"),
    _c(
        26,
        "Executable Uploads Served From Trusted Origin",
        "HIGH",
        CAT_INPUT,
        "runtime",
        "upload",
    ),
    _c(27, "Unsafe Archive Extraction", "HIGH", CAT_INPUT, "pattern", "upload"),
    _c(28, "Unsafe Deserialization", "HIGH", CAT_INPUT, "pattern"),
    _c(29, "Unsafe Dynamic Code Execution", "HIGH", CAT_INPUT, "pattern"),
    _c(
        30,
        "Third-Party Responses Trusted Blindly",
        "HIGH",
        CAT_INPUT,
        "runtime",
        "http",
    ),
    _c(31, "Permissive CORS", "CRITICAL", CAT_SUPPLY, "pattern", "http"),
    _c(32, "Development Mode Available in Production", "HIGH", CAT_SUPPLY, "pattern"),
    _c(33, "Default Credentials", "HIGH", CAT_SUPPLY, "pattern"),
    _c(34, "Missing Security Headers", "HIGH", CAT_SUPPLY, "runtime", "http"),
    _c(35, "Vulnerable Dependencies", "HIGH", CAT_SUPPLY, "runtime", "deps"),
    _c(
        36,
        "Hallucinated or Unnecessary Dependencies",
        "HIGH",
        CAT_SUPPLY,
        "runtime",
        "deps",
    ),
    _c(37, "Non-Reproducible Dependencies", "HIGH", CAT_SUPPLY, "lockfile", "deps"),
    _c(
        38,
        "Dependency Confusion / Typosquatting",
        "HIGH",
        CAT_SUPPLY,
        "runtime",
        "deps",
    ),
    _c(39, "Unsafe CI/CD Dependencies", "HIGH", CAT_SUPPLY, "actions", "ci"),
    _c(40, "Excessive CI/CD Permissions", "HIGH", CAT_SUPPLY, "ci_perms", "ci"),
    _c(41, "God Classes / God Components", "HIGH", CAT_ARCH, "god_file"),
    _c(42, "Business Logic Duplicated Across Layers", "HIGH", CAT_ARCH, "runtime"),
    _c(43, "Copy/Paste Duplicate Functions", "HIGH", CAT_ARCH, "runtime"),
    _c(44, "Multiple Implementations of the Same Concept", "HIGH", CAT_ARCH, "runtime"),
    _c(45, "Circular Dependencies", "HIGH", CAT_ARCH, "cycles"),
    _c(46, "Incorrect Separation of Concerns", "HIGH", CAT_ARCH, "pattern", "frontend"),
    _c(47, "Excessive Abstraction", "HIGH", CAT_ARCH, "runtime"),
    _c(
        48,
        "Missing Abstraction Where Needed",
        "HIGH",
        CAT_ARCH,
        "craft",
        why=(
            "Deeply nested conditionals hide the real decision. AI-generated "
            "code often inlines discount/auth/validation trees instead of a named helper."
        ),
        fix=(
            "Extract the inner nest into a function whose name is the why "
            "(get_discount_rate, is_eligible). Keep the caller flat."
        ),
    ),
    _c(49, "Architecture Inconsistent With Repository", "HIGH", CAT_ARCH, "runtime"),
    _c(50, "Dependency Direction Violations", "HIGH", CAT_ARCH, "pattern", "frontend"),
    _c(51, "Placeholder Implementations Marked Complete", "HIGH", CAT_AI, "pattern"),
    _c(52, "Buttons With No Working Behavior", "HIGH", CAT_AI, "runtime", "frontend"),
    _c(53, "UI Links to Nonexistent Routes", "HIGH", CAT_AI, "runtime", "frontend"),
    _c(
        54,
        "Calls to Nonexistent API Endpoints",
        "HIGH",
        CAT_AI,
        "runtime",
        "frontend,http",
    ),
    _c(55, "References to Nonexistent Functions or Classes", "HIGH", CAT_AI, "runtime"),
    _c(56, "Comments Do Not Match Implementation", "HIGH", CAT_AI, "runtime"),
    _c(57, "Dead Code After AI Refactors", "HIGH", CAT_AI, "dead_code"),
    _c(58, "Fake Success Paths", "HIGH", CAT_AI, "pattern", "http"),
    _c(59, "Exceptions Silently Swallowed", "HIGH", CAT_AI, "pattern"),
    _c(60, "Tests Mock Away the Actual Feature", "HIGH", CAT_AI, "runtime"),
    _c(61, "N+1 Queries", "HIGH", CAT_DB, "pattern", "db"),
    _c(62, "Missing Database Indexes", "HIGH", CAT_DB, "runtime", "db"),
    _c(63, "Fetching Entire Tables", "HIGH", CAT_DB, "pattern", "db"),
    _c(64, "Missing Pagination", "HIGH", CAT_DB, "runtime", "http,db"),
    _c(65, "Inefficient Offset Pagination", "HIGH", CAT_DB, "runtime", "http,db"),
    _c(66, "Loading Unnecessary Columns", "HIGH", CAT_DB, "pattern", "db"),
    _c(67, "Missing Transactions", "HIGH", CAT_DB, "runtime", "db"),
    _c(
        68,
        "External Network Calls Inside Transactions",
        "HIGH",
        CAT_DB,
        "runtime",
        "db,http",
    ),
    _c(69, "Race Conditions / Check-Then-Write", "HIGH", CAT_DB, "runtime", "db"),
    _c(70, "Unsafe Database Migrations", "HIGH", CAT_DB, "runtime", "db"),
    _c(71, "Blocking I/O Inside Async Code", "HIGH", CAT_BE, "pattern", "http"),
    _c(72, "Missing Network Timeouts", "HIGH", CAT_BE, "pattern", "http"),
    _c(73, "Retry Storms", "HIGH", CAT_BE, "pattern", "http"),
    _c(
        74,
        "Missing Circuit Breaking / Graceful Degradation",
        "HIGH",
        CAT_BE,
        "runtime",
        "http",
    ),
    _c(75, "Missing Connection Pooling", "HIGH", CAT_BE, "pattern", "db"),
    _c(76, "Repeated Expensive Initialization", "HIGH", CAT_BE, "runtime"),
    _c(77, "Missing Caching", "HIGH", CAT_BE, "runtime"),
    _c(78, "Incorrect Cache Invalidation", "HIGH", CAT_BE, "runtime"),
    _c(79, "Unbounded Memory Consumption", "HIGH", CAT_BE, "pattern"),
    _c(80, "No Performance Budgets", "HIGH", CAT_BE, "runtime"),
    _c(81, "Excessive JavaScript Bundle Size", "HIGH", CAT_FE, "runtime", "frontend"),
    _c(82, "Missing Code Splitting", "HIGH", CAT_FE, "runtime", "frontend"),
    _c(83, "Excessive Re-Renders", "HIGH", CAT_FE, "runtime", "frontend"),
    _c(84, "API Waterfalls", "HIGH", CAT_FE, "runtime", "frontend"),
    _c(85, "Duplicate Frontend API Calls", "HIGH", CAT_FE, "runtime", "frontend"),
    _c(86, "Oversized API Payloads", "HIGH", CAT_FE, "runtime", "http"),
    _c(87, "Unoptimized Images and Media", "HIGH", CAT_FE, "runtime", "frontend"),
    _c(88, "Poor Core Web Vitals", "HIGH", CAT_FE, "runtime", "frontend"),
    _c(89, "Main-Thread Blocking", "HIGH", CAT_FE, "runtime", "frontend"),
    _c(90, "Missing Loading Strategy", "HIGH", CAT_FE, "runtime", "frontend"),
    _c(91, "Poor Error States", "HIGH", CAT_UX, "runtime", "frontend"),
    _c(92, "Missing Empty States", "HIGH", CAT_UX, "runtime", "frontend"),
    _c(
        93,
        "Dangerous Actions Without Safeguards",
        "HIGH",
        CAT_UX,
        "pattern",
        "frontend",
    ),
    _c(94, "Duplicate Submission", "HIGH", CAT_UX, "runtime", "frontend,http"),
    _c(95, "User Input Lost Unexpectedly", "HIGH", CAT_UX, "runtime", "frontend"),
    _c(
        96,
        "Broken Keyboard & Accessibility Workflows",
        "HIGH",
        CAT_UX,
        "runtime",
        "frontend",
    ),
    _c(97, "Mobile / Responsive Layout Failure", "HIGH", CAT_UX, "runtime", "frontend"),
    _c(98, "Inconsistent Design System", "MEDIUM", CAT_UX, "runtime", "frontend"),
    _c(
        99, "Workflow Requires Unnecessary Steps", "HIGH", CAT_UX, "runtime", "frontend"
    ),
    _c(
        100,
        "Technically Complete but Operationally Unusable",
        "HIGH",
        CAT_UX,
        "runtime",
    ),
    _c(
        101, "Missing Object Ownership Validation", "CRITICAL", CAT_API, "authz", "http"
    ),
    _c(
        102, "Broken Function-Level Authorization", "CRITICAL", CAT_API, "authz", "http"
    ),
    _c(103, "API Accepts Privileged Fields", "CRITICAL", CAT_API, "pattern", "http"),
    _c(
        104,
        "HTTP Method Authorization Inconsistencies",
        "HIGH",
        CAT_API,
        "authz",
        "http",
    ),
    _c(105, "Accidentally Public API Endpoints", "HIGH", CAT_API, "authz", "http"),
    _c(106, "Old API Versions Bypass Security", "HIGH", CAT_API, "runtime", "http"),
    _c(
        107,
        "Forgotten / Undocumented API Endpoints",
        "HIGH",
        CAT_API,
        "runtime",
        "http",
    ),
    _c(108, "Overly Permissive API Serialization", "HIGH", CAT_API, "pattern", "http"),
    _c(109, "Excessive Nested Data Exposure", "HIGH", CAT_API, "runtime", "http"),
    _c(110, "Missing Request Body Limits", "HIGH", CAT_API, "runtime", "http"),
    _c(111, "Missing Query Complexity Limits", "HIGH", CAT_API, "runtime", "http"),
    _c(112, "Unbounded Bulk Operations", "HIGH", CAT_API, "runtime", "http"),
    _c(113, "Pagination Can Be Bypassed", "HIGH", CAT_API, "pattern", "http"),
    _c(114, "Expensive Arbitrary Filtering", "HIGH", CAT_API, "pattern", "http,db"),
    _c(115, "Missing Idempotency", "HIGH", CAT_API, "runtime", "http"),
    _c(116, "Incorrect API Retry Behavior", "HIGH", CAT_API, "runtime", "http"),
    _c(117, "Inconsistent Timeout Stack", "HIGH", CAT_API, "runtime", "http"),
    _c(
        118,
        "Long-Running Work Executed Synchronously",
        "HIGH",
        CAT_API,
        "pattern",
        "http",
    ),
    _c(
        119, "Missing Request Cancellation Handling", "HIGH", CAT_API, "runtime", "http"
    ),
    _c(
        120,
        "Missing API Observability & Correlation IDs",
        "HIGH",
        CAT_API,
        "observe",
        "http",
    ),
)

CHECK_COUNT = len(CHECKS)
CHECK_BY_ID: dict[int, Check] = {item.id: item for item in CHECKS}

if CHECK_COUNT != 120:
    raise RuntimeError(f"audit catalog must contain 120 checks, found {CHECK_COUNT}")
if sorted(CHECK_BY_ID) != list(range(1, 121)):
    raise RuntimeError("audit catalog ids must be 1..120 with no gaps")
