from __future__ import annotations

from pathlib import Path

from quality_gates import GATES
from quality_gates.change_manifest import ChangeManifest
from quality_gates.config import QualityConfig, load_config
from quality_gates.gates import run_impact
from quality_gates.impact_graph import (
    analyze,
    build_graph,
    expand_downstream,
)
from quality_gates.ui_select import detect_ui_project, select_specs


def _py_pkg(root: Path, *, with_test: bool = True) -> None:
    pkg = root / "pkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "core.py").write_text("VALUE = 1\n", encoding="utf-8")
    (pkg / "service.py").write_text("from .core import VALUE\n", encoding="utf-8")
    (pkg / "api.py").write_text("from .service import VALUE\n", encoding="utf-8")
    if with_test:
        tests = root / "tests"
        tests.mkdir()
        (tests / "test_core.py").write_text(
            "from pkg.core import VALUE\nassert VALUE == 1\n",
            encoding="utf-8",
        )


def test_impact_gate_skips_without_changes(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        "quality_gates.gates.impact.discover_changes",
        lambda *_a, **_k: ChangeManifest("empty", None, None, None, "digest", ()),
    )
    result = run_impact(tmp_path, QualityConfig())
    assert result.status == "skip"


def test_impact_is_in_gate_order() -> None:
    assert "impact" in GATES
    assert GATES.index("compile") < GATES.index("impact") < GATES.index("ui")
    assert (
        GATES.index("impact")
        < GATES.index("coverage")
        < GATES.index("audit")
        < GATES.index("ui")
    )


def test_downstream_and_upstream_walk(tmp_path: Path) -> None:
    _py_pkg(tmp_path)
    graph = build_graph(tmp_path, QualityConfig())
    impact = analyze(graph, ["pkg/core.py"], depth=4)
    assert "pkg/service.py" in impact.downstream["pkg/core.py"]
    assert "pkg/api.py" in impact.downstream["pkg/core.py"]
    assert impact.unvalidated_downstream == []
    assert "tests/test_core.py" in impact.tests["pkg/core.py"]
    svc = analyze(graph, ["pkg/service.py"], depth=4)
    assert "pkg/core.py" in svc.upstream["pkg/service.py"]


def test_impact_graph_persists_and_invalidates_changed_source(tmp_path: Path) -> None:
    _py_pkg(tmp_path)
    first = build_graph(tmp_path, QualityConfig())
    cache = tmp_path / ".quality-reports" / "impact-graph.json"
    assert cache.is_file()
    (tmp_path / "pkg" / "service.py").write_text("VALUE = 1\n", encoding="utf-8")

    second = build_graph(tmp_path, QualityConfig())

    assert "pkg/core.py" in first.imports["pkg/service.py"]
    assert "pkg/core.py" not in second.imports["pkg/service.py"]


def test_unvalidated_downstream_without_tests(tmp_path: Path) -> None:
    _py_pkg(tmp_path, with_test=False)
    graph = build_graph(tmp_path, QualityConfig())
    impact = analyze(graph, ["pkg/core.py"], depth=4)
    consumers = {dst for _src, dst in impact.unvalidated_downstream}
    assert "pkg/service.py" in consumers
    assert "pkg/api.py" in consumers


def test_consumer_validation_requires_execution_evidence(tmp_path: Path) -> None:
    _py_pkg(tmp_path, with_test=False)
    graph = build_graph(tmp_path, QualityConfig())
    # Editing a consumer alone does not count as validation
    impact = analyze(
        graph,
        ["pkg/core.py", "pkg/service.py", "pkg/api.py"],
        depth=4,
    )
    assert len(impact.unvalidated_downstream) > 0

    # Fresh verified test or contract evidence validates consumers
    verified = analyze(
        graph,
        ["pkg/core.py", "pkg/service.py", "pkg/api.py"],
        depth=4,
        verified_tests={
            "tests/test_core.py",
            "tests/test_service.py",
            "tests/test_api.py",
        },
    )
    assert verified.unvalidated_downstream == []


def test_broken_local_upstream(tmp_path: Path) -> None:
    _py_pkg(tmp_path)
    (tmp_path / "pkg" / "service.py").write_text(
        "from .missing import nope\n", encoding="utf-8"
    )
    graph = build_graph(tmp_path, QualityConfig())
    impact = analyze(graph, ["pkg/service.py"], depth=2)
    assert impact.broken_upstream.get("pkg/service.py")


def test_function_level_import_is_not_a_graph_edge(tmp_path: Path) -> None:
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "a.py").write_text(
        "def load():\n    from pkg.b import VALUE\n    return VALUE\n",
        encoding="utf-8",
    )
    (pkg / "b.py").write_text(
        "def load():\n    from pkg.a import load as other\n    return other\n",
        encoding="utf-8",
    )
    graph = build_graph(tmp_path, QualityConfig())
    assert "pkg/b.py" not in graph.imports.get("pkg/a.py", set())
    assert "pkg/a.py" not in graph.imports.get("pkg/b.py", set())


def test_expand_downstream_includes_consumers(tmp_path: Path) -> None:
    _py_pkg(tmp_path)
    expanded = expand_downstream(tmp_path, QualityConfig(), ["pkg/core.py"])
    assert "pkg/service.py" in expanded
    assert "pkg/api.py" in expanded
    assert "pkg/core.py" in expanded


def test_loads_impact_config(tmp_path: Path) -> None:
    (tmp_path / "quality.toml").write_text(
        """
[quality.impact]
depth = 2
require_downstream = false
require_own_tests = true
""".strip()
        + "\n",
        encoding="utf-8",
    )
    config = load_config(tmp_path)
    assert config.impact_depth == 2
    assert config.impact_require_downstream is False
    assert config.impact_require_own_tests is True


def test_ui_uses_downstream_expansion(tmp_path: Path) -> None:
    (tmp_path / "playwright.config.ts").write_text(
        "export default { testDir: 'e2e' };\n", encoding="utf-8"
    )
    e2e = tmp_path / "e2e"
    e2e.mkdir()
    (e2e / "checkout.spec.ts").write_text(
        """
import { test } from '@playwright/test';
test('checkout', async ({ page }) => {
  await page.goto('/checkout');
});
""".lstrip(),
        encoding="utf-8",
    )
    (e2e / "login.spec.ts").write_text(
        """
import { test } from '@playwright/test';
test('login', async ({ page }) => {
  await page.goto('/login');
});
""".lstrip(),
        encoding="utf-8",
    )
    (tmp_path / "src" / "lib").mkdir(parents=True)
    (tmp_path / "src" / "lib" / "format.ts").write_text(
        "export const fmt = (n: number) => n.toString();\n", encoding="utf-8"
    )
    (tmp_path / "src" / "components").mkdir(parents=True)
    (tmp_path / "src" / "components" / "Cart.tsx").write_text(
        "import { fmt } from '../lib/format';\n"
        "export function Cart() { return fmt(1); }\n",
        encoding="utf-8",
    )
    (tmp_path / "src" / "app" / "checkout").mkdir(parents=True)
    (tmp_path / "src" / "app" / "checkout" / "page.tsx").write_text(
        "import { Cart } from '../../components/Cart';\n"
        "export default function Checkout() { return Cart(); }\n",
        encoding="utf-8",
    )
    config = QualityConfig()
    project = detect_ui_project(tmp_path)
    assert project is not None
    direct = select_specs(tmp_path, config, project, ["src/lib/format.ts"])
    expanded = expand_downstream(tmp_path, config, ["src/lib/format.ts"])
    assert "src/components/Cart.tsx" in expanded
    assert "src/app/checkout/page.tsx" in expanded
    selection = select_specs(tmp_path, config, project, expanded)
    names = {path.name for path in selection.specs} | {
        path.name for path in direct.specs
    }
    assert "checkout.spec.ts" in names
    assert "login.spec.ts" not in names


def test_deleted_module_triggers_consumer_checks(tmp_path: Path) -> None:
    _py_pkg(tmp_path)
    # First build to populate persistent graph
    first = build_graph(tmp_path, QualityConfig())
    assert "pkg/core.py" in first.imports["pkg/service.py"]

    # Delete pkg/core.py
    (tmp_path / "pkg" / "core.py").unlink()

    # Rebuild graph incrementally
    second = build_graph(tmp_path, QualityConfig())
    # Deleted module was imported by pkg/service.py and pkg/api.py
    assert "pkg/service.py" in second.imported_by.get("pkg/core.py", set())
    impact = analyze(second, ["pkg/core.py"], depth=4)
    assert "pkg/service.py" in impact.downstream.get("pkg/core.py", [])


def test_impact_extends_to_symbols_callers_and_inheritance(tmp_path: Path) -> None:
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "base.py").write_text(
        "class Model:\n    pass\n\ndef helper():\n    return 42\n", encoding="utf-8"
    )
    (pkg / "child.py").write_text(
        "from .base import Model\nclass User(Model):\n    pass\n", encoding="utf-8"
    )
    (pkg / "caller.py").write_text(
        "from .base import helper\ndef run():\n    return helper()\n", encoding="utf-8"
    )
    graph = build_graph(tmp_path, QualityConfig())
    assert "Model" in graph.symbols["pkg/base.py"]
    assert "helper" in graph.symbols["pkg/base.py"]
    assert "helper" in graph.callers["pkg/caller.py"]

    impact = analyze(graph, ["pkg/base.py"], depth=2)
    assert "pkg/child.py" in impact.downstream["pkg/base.py"]
    assert "pkg/caller.py" in impact.downstream["pkg/base.py"]


def test_configuration_impact_maps_to_affected_targets(tmp_path: Path) -> None:
    _py_pkg(tmp_path)
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname="demo"\n', encoding="utf-8"
    )
    graph = build_graph(tmp_path, QualityConfig())
    impact = analyze(graph, ["pyproject.toml"], depth=2, root=tmp_path)
    assert any("pkg/core.py" in t for t in impact.config_affected)
