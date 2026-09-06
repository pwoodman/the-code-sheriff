"""Pure change classification shared by planning and risk verification."""

from __future__ import annotations

_TRIGGERS = {
    "migration": ("migration", "migrations/", "alembic", "schema.sql", "prisma/schema"),
    "authorization": ("auth", "permission", "tenant", "ownership", "rbac", "acl"),
    "resilience": (
        "retry",
        "idempot",
        "timeout",
        "queue",
        "payment",
        "concurr",
        "async",
    ),
    "mutation": ("parser", "validate", "validator", "algorithm", "crypto", "pricing"),
    "performance": ("benchmark", "performance", "hotpath", "query", "bundle"),
}


def triggered_capabilities(paths: list[str]) -> set[str]:
    # Names in documentation, reports, and test fixtures describe risk but do
    # not alter a production surface.  Classify executable/configuration files
    # only, preventing a README from scheduling a database worker.
    relevant = [
        path.lower()
        for path in paths
        if path.lower().endswith(
            (
                ".py",
                ".pyi",
                ".js",
                ".ts",
                ".tsx",
                ".go",
                ".rs",
                ".java",
                ".cs",
                ".sql",
                ".graphql",
                ".proto",
                ".yaml",
                ".yml",
            )
        )
        and "/tests/" not in f"/{path.lower()}"
        and "/fixtures/" not in f"/{path.lower()}"
    ]
    lowered = "\n".join(relevant)
    return {
        name
        for name, markers in _TRIGGERS.items()
        if any(marker in lowered for marker in markers)
    }
