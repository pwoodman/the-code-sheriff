from __future__ import annotations

import ast
import json
import re
from collections import defaultdict, deque
from dataclasses import dataclass, field
from pathlib import Path

from quality_gates.config import QualityConfig
from quality_gates.detect import iter_project_files
from quality_gates.js_resolve import resolve_js_module

PY_FROM = re.compile(r"^\s*from\s+(\.*[\w.]*)\s+import\s+([^\n\\]+)", re.M)
PY_IMPORT = re.compile(r"^\s*import\s+([\w.]+)", re.M)
JS_IMPORT = re.compile(
    r"""(?:from\s+['"]([^'"]+)['"]|import\(\s*['"]([^'"]+)['"]\s*\)|require\(\s*['"]([^'"]+)['"]\s*\))"""
)
GO_IMPORT = re.compile(r"""import\s+(?:[\w.]+\s+)?["']([^"']+)["']""")
GO_IMPORT_BLOCK = re.compile(r"import\s*\((.*?)\)", re.S)
GO_QUOTED = re.compile(r'["\']([^"\']+)["\']')
RS_MOD = re.compile(r"^\s*(?:pub\s+)?mod\s+(\w+)\s*;", re.M)
RS_CRATE = re.compile(r"^\s*use\s+crate::([\w:]+)", re.M)
RS_SUPER = re.compile(r"^\s*use\s+super::([\w:]+)", re.M)
JAVA_IMPORT = re.compile(r"^\s*import\s+(?:static\s+)?([\w.]+)\s*;", re.M)
SOURCE_SUFFIXES = {
    ".py",
    ".pyi",
    ".ts",
    ".tsx",
    ".js",
    ".jsx",
    ".mjs",
    ".cjs",
    ".go",
    ".rs",
    ".java",
    ".cs",
    ".vue",
    ".svelte",
}
JS_SUFFIXES = {".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".vue", ".svelte"}


@dataclass
class ImportGraph:
    files: set[str] = field(default_factory=set)
    imports: dict[str, set[str]] = field(default_factory=lambda: defaultdict(set))
    imported_by: dict[str, set[str]] = field(default_factory=lambda: defaultdict(set))
    broken: dict[str, list[str]] = field(default_factory=lambda: defaultdict(list))


@dataclass
class Impact:
    changed: list[str]
    upstream: dict[str, list[str]]
    downstream: dict[str, list[str]]
    broken_upstream: dict[str, list[str]]
    tests: dict[str, list[str]]
    unvalidated_downstream: list[tuple[str, str]]
    untested_changes: list[str]


def is_source(path: str) -> bool:
    lower = path.replace("\\", "/").lower()
    return Path(lower).suffix in SOURCE_SUFFIXES


def is_test(path: str) -> bool:
    posix = path.replace("\\", "/").lower()
    name = Path(posix).name
    if name.startswith("test_") or name.endswith("_test.py"):
        return True
    if ".spec." in name or ".test." in name or ".cy." in name:
        return True
    parts = posix.split("/")
    return "tests" in parts or "test" in parts or "__tests__" in parts


def build_graph(root: Path, config: QualityConfig) -> ImportGraph:
    graph = ImportGraph()
    aliases = config.ui_path_aliases
    index = _file_index(root, config)
    graph.files = set(index)
    packages = _python_packages(root, index)
    go_module = _go_module(root)

    for rel, path in index.items():
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if len(text) > 400_000:
            continue
        suffix = path.suffix.lower()
        resolved: list[str] = []
        unresolved: list[str] = []
        if suffix in {".py", ".pyi"}:
            resolved, unresolved = _python_deps(rel, text, index, packages, root)
        elif suffix in JS_SUFFIXES:
            resolved, unresolved = _js_deps(path, text, root, aliases, index)
        elif suffix == ".go":
            resolved, unresolved = _go_deps(rel, text, index, go_module)
        elif suffix == ".rs":
            resolved, unresolved = _rust_deps(rel, text, index)
        elif suffix == ".java":
            resolved, unresolved = _java_deps(text, index)
        for target in resolved:
            if target == rel:
                continue
            graph.imports[rel].add(target)
            graph.imported_by[target].add(rel)
        if unresolved:
            graph.broken[rel].extend(unresolved)
    return graph


def analyze(
    graph: ImportGraph,
    changed: list[str],
    *,
    depth: int,
) -> Impact:
    changed_src = [
        _norm(name) for name in changed if is_source(name) and not is_test(name)
    ]
    changed_set = set(changed_src) | {
        _norm(name) for name in changed if is_source(name)
    }
    upstream: dict[str, list[str]] = {}
    downstream: dict[str, list[str]] = {}
    broken: dict[str, list[str]] = {}
    tests: dict[str, list[str]] = {}
    unvalidated: list[tuple[str, str]] = []
    untested: list[str] = []

    for name in changed_src:
        up = _walk(graph.imports, name, depth)
        down = _walk(graph.imported_by, name, depth)
        upstream[name] = sorted(up)
        downstream[name] = sorted(down)
        if graph.broken.get(name):
            broken[name] = list(graph.broken[name])
        covers = covering_tests(graph, name)
        tests[name] = sorted(covers)
        if not covers:
            untested.append(name)
        for consumer in down:
            if is_test(consumer):
                continue
            if consumer in changed_set:
                continue
            if covers or covering_tests(graph, consumer):
                continue
            unvalidated.append((name, consumer))

    return Impact(
        changed=changed_src,
        upstream=upstream,
        downstream=downstream,
        broken_upstream=broken,
        tests=tests,
        unvalidated_downstream=unvalidated,
        untested_changes=untested,
    )


def covering_tests(graph: ImportGraph, rel: str) -> set[str]:
    found: set[str] = set()
    for importer in graph.imported_by.get(rel, ()):
        if is_test(importer):
            found.add(importer)
    stem = Path(rel).stem
    if stem == "__init__":
        stem = Path(rel).parent.name
    if len(stem) < 3:
        return found
    collapsed = stem.replace("-", "").replace("_", "").lower()
    for candidate in graph.files:
        if not is_test(candidate):
            continue
        name = Path(candidate).stem.lower()
        for prefix in ("test_",):
            if name.startswith(prefix):
                name = name[len(prefix) :]
        if name.endswith("_test"):
            name = name[: -len("_test")]
        for suffix in (".spec", ".test", ".cy"):
            if name.endswith(suffix):
                name = name[: -len(suffix)]
        if name.replace("-", "").replace("_", "") == collapsed:
            found.add(candidate)
    return found


def expand_downstream(
    root: Path,
    config: QualityConfig,
    changed: list[str] | None,
    *,
    graph: ImportGraph | None = None,
) -> list[str]:
    names = [_norm(item) for item in (changed or [])]
    if not names:
        return []
    built = graph or build_graph(root, config)
    extra: set[str] = set(names)
    depth = max(1, config.impact_depth)
    for name in names:
        if not is_source(name):
            continue
        extra.update(_walk(built.imported_by, name, depth))
    return sorted(extra)


def dump_impact(root: Path, impact: Impact) -> None:
    out = root / ".quality-reports"
    try:
        out.mkdir(parents=True, exist_ok=True)
        payload = {
            "changed": impact.changed,
            "upstream": impact.upstream,
            "downstream": impact.downstream,
            "broken_upstream": impact.broken_upstream,
            "tests": impact.tests,
            "unvalidated_downstream": [
                {"changed": src, "consumer": dst}
                for src, dst in impact.unvalidated_downstream
            ],
            "untested_changes": impact.untested_changes,
        }
        (out / "impact.json").write_text(
            json.dumps(payload, indent=2) + "\n", encoding="utf-8"
        )
    except OSError:
        return


def _walk(edges: dict[str, set[str]], start: str, depth: int) -> set[str]:
    seen: set[str] = set()
    queue: deque[tuple[str, int]] = deque([(start, 0)])
    while queue:
        node, hops = queue.popleft()
        if hops >= depth:
            continue
        for nxt in edges.get(node, ()):
            if nxt in seen or nxt == start:
                continue
            seen.add(nxt)
            queue.append((nxt, hops + 1))
    return seen


def _file_index(root: Path, config: QualityConfig) -> dict[str, Path]:
    index: dict[str, Path] = {}
    for path in iter_project_files(root, config):
        if path.suffix.lower() not in SOURCE_SUFFIXES:
            continue
        rel = _rel(root, path)
        index[rel] = path
    return index


def _python_packages(root: Path, index: dict[str, Path]) -> set[str]:
    names: set[str] = set()
    for rel in index:
        if not rel.endswith(".py") and not rel.endswith(".pyi"):
            continue
        parts = rel.split("/")
        if "src" in parts:
            src_at = parts.index("src")
            rest = parts[src_at + 1 :]
            if rest:
                names.add(rest[0].replace(".py", "").replace(".pyi", ""))
        elif parts:
            names.add(parts[0].replace(".py", "").replace(".pyi", ""))
    src = root / "src"
    if src.is_dir():
        for child in src.iterdir():
            if child.is_dir() and not child.name.startswith("."):
                names.add(child.name)
    return {name for name in names if name and name != "__init__"}


def _python_deps(
    rel: str,
    text: str,
    index: dict[str, Path],
    packages: set[str],
    root: Path,
) -> tuple[list[str], list[str]]:
    current = root / rel
    resolved: list[str] = []
    unresolved: list[str] = []
    for module, imported in _module_level_python_imports(text):
        if imported:
            if module in {"__future__", "typing", "typing_extensions"}:
                continue
            if module.startswith("."):
                hits = _resolve_python_relative(current, module, imported, root, index)
                if hits:
                    resolved.extend(hits)
                else:
                    unresolved.append(module or imported.strip().split(",")[0])
                continue
            hit = _resolve_python_abs(module, index, root)
            if hit:
                resolved.append(hit)
            elif _looks_local(module, packages):
                unresolved.append(module)
            continue
        if module.split(".")[0] in {
            "os",
            "sys",
            "re",
            "json",
            "pathlib",
            "typing",
            "dataclasses",
            "collections",
            "subprocess",
            "argparse",
            "tomllib",
        }:
            continue
        hit = _resolve_python_abs(module, index, root)
        if hit:
            resolved.append(hit)
        elif _looks_local(module, packages):
            unresolved.append(module)
    return resolved, unresolved


def _module_level_python_imports(text: str) -> list[tuple[str, str]]:
    """Runtime imports that execute while the module loads.

    Function-level and `if TYPE_CHECKING` imports are deferred (or erased) and
    are not initialization cycles.
    """
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return _regex_python_imports(text)
    found: list[tuple[str, str]] = []
    for node in tree.body:
        found.extend(_import_record(node))
        if isinstance(node, ast.If) and not _is_type_checking(node):
            for child in [*node.body, *node.orelse]:
                found.extend(_import_record(child))
    return found


def _regex_python_imports(text: str) -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    for match in PY_FROM.finditer(text):
        found.append((match.group(1), match.group(2)))
    for match in PY_IMPORT.finditer(text):
        found.append((match.group(1), ""))
    return found


def _import_record(node: ast.AST) -> list[tuple[str, str]]:
    if isinstance(node, ast.ImportFrom):
        module = "." * node.level + (node.module or "")
        imported = ", ".join(alias.name for alias in node.names if alias.name)
        return [(module, imported)]
    if isinstance(node, ast.Import):
        return [(alias.name, "") for alias in node.names]
    return []


def _is_type_checking(node: ast.If) -> bool:
    test = node.test
    if isinstance(test, ast.Name) and test.id == "TYPE_CHECKING":
        return True
    return isinstance(test, ast.Attribute) and test.attr == "TYPE_CHECKING"


def _resolve_python_abs(module: str, index: dict[str, Path], root: Path) -> str | None:
    parts = [part for part in module.split(".") if part]
    if not parts:
        return None
    candidates = [
        Path(*parts).with_suffix(".py").as_posix(),
        Path(*parts).with_suffix(".pyi").as_posix(),
        (Path(*parts) / "__init__.py").as_posix(),
        ("src/" + Path(*parts).with_suffix(".py").as_posix()),
        ("src/" + (Path(*parts) / "__init__.py").as_posix()),
    ]
    for candidate in candidates:
        if candidate in index:
            return candidate
    # suffix match: quality_gates.config → src/quality_gates/config.py
    tail = "/".join(parts)
    for rel in index:
        if rel.endswith("/" + tail + ".py") or rel.endswith(
            "/" + tail + "/__init__.py"
        ):
            return rel
        if rel == tail + ".py":
            return rel
    _ = root
    return None


def _resolve_python_relative(
    current: Path,
    module: str,
    imported: str,
    root: Path,
    index: dict[str, Path],
) -> list[str]:
    dots = len(module) - len(module.lstrip("."))
    rest = module[dots:]
    base = current.parent
    for _ in range(max(0, dots - 1)):
        base = base.parent
    hits: list[str] = []
    if rest:
        target = base.joinpath(*rest.split("."))
        hit = _existing_py(target, root, index)
        if hit:
            hits.append(hit)
        return hits
    for name in _import_names(imported):
        hit = _existing_py(base / name, root, index)
        if hit:
            hits.append(hit)
    return hits


def _existing_py(target: Path, root: Path, index: dict[str, Path]) -> str | None:
    for candidate in (
        target.with_suffix(".py"),
        target.with_suffix(".pyi"),
        target / "__init__.py",
    ):
        try:
            rel = _rel(root, candidate)
        except ValueError:
            continue
        if rel in index or candidate.is_file():
            return rel
    return None


def _import_names(clause: str) -> list[str]:
    names: list[str] = []
    for raw in clause.split(","):
        token = raw.strip()
        if not token or token.startswith("(") or token.startswith("#"):
            continue
        token = token.split(" as ")[0].strip().strip("()")
        if token.isidentifier():
            names.append(token)
    return names


def _looks_local(module: str, packages: set[str]) -> bool:
    first = module.lstrip(".").split(".")[0]
    return first in packages


def _js_deps(
    path: Path,
    text: str,
    root: Path,
    aliases: dict[str, str],
    index: dict[str, Path],
) -> tuple[list[str], list[str]]:
    resolved: list[str] = []
    unresolved: list[str] = []
    for match in JS_IMPORT.finditer(text):
        spec = next((group for group in match.groups() if group), "")
        if not spec or spec.startswith("node:"):
            continue
        hit = _resolve_js(path, spec, root, aliases, index)
        if hit:
            resolved.append(hit)
        elif spec.startswith(".") or spec.startswith("@/"):
            unresolved.append(spec)
    return resolved, unresolved


def _resolve_js(
    current: Path,
    spec: str,
    root: Path,
    aliases: dict[str, str],
    index: dict[str, Path],
) -> str | None:
    candidate = resolve_js_module(current, spec, root, aliases)
    if candidate is None:
        return None
    rel = _rel(root, candidate)
    if rel in index or candidate.is_file():
        return rel
    return None


def _go_module(root: Path) -> str:
    path = root / "go.mod"
    if not path.is_file():
        return ""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return ""
    for line in text.splitlines():
        if line.startswith("module "):
            return line.split()[1].strip()
    return ""


def _go_deps(
    rel: str, text: str, index: dict[str, Path], module: str
) -> tuple[list[str], list[str]]:
    specs: list[str] = []
    specs.extend(GO_IMPORT.findall(text))
    for block in GO_IMPORT_BLOCK.findall(text):
        specs.extend(GO_QUOTED.findall(block))
    resolved: list[str] = []
    unresolved: list[str] = []
    current_dir = str(Path(rel).parent)
    for spec in specs:
        if spec.startswith("./") or spec.startswith("../"):
            target = _norm(str(Path(current_dir) / spec))
            hit = _go_file(target, index)
            if hit:
                resolved.append(hit)
            else:
                unresolved.append(spec)
            continue
        if module and spec.startswith(module + "/"):
            tail = spec[len(module) + 1 :]
            hit = _go_file(tail, index)
            if hit:
                resolved.append(hit)
    return resolved, unresolved


def _go_file(dir_or_file: str, index: dict[str, Path]) -> str | None:
    trimmed = _norm(dir_or_file).rstrip("/")
    for rel in index:
        if not rel.endswith(".go"):
            continue
        if rel == trimmed + ".go":
            return rel
        if (
            rel.startswith(trimmed + "/")
            and rel.count("/") == trimmed.count("/") + 1
            and not rel.endswith("_test.go")
        ):
            return rel
    return None


def _rust_deps(
    rel: str, text: str, index: dict[str, Path]
) -> tuple[list[str], list[str]]:
    resolved: list[str] = []
    parent = str(Path(rel).parent)
    crate_root = "src" if rel.startswith("src/") else parent
    for name in RS_MOD.findall(text):
        for candidate in (
            f"{parent}/{name}.rs",
            f"{parent}/{name}/mod.rs",
        ):
            if candidate in index:
                resolved.append(candidate)
    for path in RS_CRATE.findall(text):
        parts = path.split("::")
        if not parts:
            continue
        for candidate in (
            f"{crate_root}/{parts[0]}.rs",
            f"{crate_root}/{parts[0]}/mod.rs",
            f"{crate_root}/{'/'.join(parts)}.rs",
        ):
            if candidate in index:
                resolved.append(candidate)
    for path in RS_SUPER.findall(text):
        name = path.split("::")[0]
        for candidate in (f"{parent}/{name}.rs", f"{parent}/{name}/mod.rs"):
            if candidate in index:
                resolved.append(candidate)
    return resolved, []


def _java_deps(text: str, index: dict[str, Path]) -> tuple[list[str], list[str]]:
    resolved: list[str] = []
    for module in JAVA_IMPORT.findall(text):
        simple = module.split(".")[-1]
        if not simple or simple == "*":
            continue
        suffix = "/" + simple + ".java"
        for rel in index:
            if rel.endswith(suffix):
                resolved.append(rel)
                break
    return resolved, []


def _rel(root: Path, path: Path) -> str:
    try:
        return _norm(path.resolve().relative_to(root.resolve()).as_posix())
    except ValueError:
        return _norm(path.as_posix())


def _norm(value: str) -> str:
    return value.replace("\\", "/").lstrip("./")
