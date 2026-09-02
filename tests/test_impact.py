from __future__ import annotations

from pathlib import Path

from quality_gates import GATES
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
        "quality_gates.gates.impact.git_changed_names", lambda *_a, **_k: None
    )
    monkeypatch.setattr(
        "quality_gates.gates.impact.git_base_ref", lambda *_a, **_k: None
    )
    result = run_impact(tmp_path, QualityConfig())
    assert result.status == "skip"


def test_impact_is_in_gate_order() -> None:
    assert "impact" in GATES
    assert GATES.index("compile") < GATES.index("impact") < GATES.index("ui")


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


def test_unvalidated_downstream_without_tests(tmp_path: Path) -> None:
    _py_pkg(tmp_path, with_test=False)
    graph = build_graph(tmp_path, QualityConfig())
    impact = analyze(graph, ["pkg/core.py"], depth=4)
    consumers = {dst for _src, dst in impact.unvalidated_downstream}
    assert "pkg/service.py" in consumers
    assert "pkg/api.py" in consumers


def test_updated_consumer_counts_as_validated(tmp_path: Path) -> None:
    _py_pkg(tmp_path, with_test=False)
    graph = build_graph(tmp_path, QualityConfig())
    impact = analyze(
        graph,
        ["pkg/core.py", "pkg/service.py", "pkg/api.py"],
        depth=4,
    )
    assert impact.unvalidated_downstream == []


def test_broken_local_upstream(tmp_path: Path) -> None:
    _py_pkg(tmp_path)
    (tmp_path / "pkg" / "service.py").write_text(
        "from .missing import nope\n", encoding="utf-8"
    )
    graph = build_graph(tmp_path, QualityConfig())
    impact = analyze(graph, ["pkg/service.py"], depth=2)
    assert impact.broken_upstream.get("pkg/service.py")


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
