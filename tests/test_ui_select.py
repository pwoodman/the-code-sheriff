from __future__ import annotations

from pathlib import Path

from quality_gates.config import QualityConfig, load_config
from quality_gates.gates.ui import run_ui
from quality_gates.models import GateResult
from quality_gates.ui_select import detect_ui_project, discover_specs, select_specs


def _app(root: Path) -> None:
    (root / "playwright.config.ts").write_text(
        "export default { testDir: 'e2e' };\n", encoding="utf-8"
    )
    e2e = root / "e2e"
    e2e.mkdir()
    (e2e / "helpers.ts").write_text(
        "export const cartPath = '../src/components/Cart';\n", encoding="utf-8"
    )
    (e2e / "checkout.spec.ts").write_text(
        """
import { test } from '@playwright/test';
import { cartPath } from './helpers';
void cartPath;
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
    (root / "src" / "app" / "checkout").mkdir(parents=True)
    (root / "src" / "app" / "checkout" / "page.tsx").write_text(
        "import { Cart } from '../../components/Cart';\n"
        "export default function Checkout() { return Cart(); }\n",
        encoding="utf-8",
    )
    (root / "src" / "components").mkdir(parents=True)
    (root / "src" / "components" / "Cart.tsx").write_text(
        "export function Cart() { return null; }\n", encoding="utf-8"
    )
    (root / "src" / "lib").mkdir(parents=True)
    (root / "src" / "lib" / "format.ts").write_text(
        "export const fmt = (n: number) => n.toString();\n", encoding="utf-8"
    )
    (root / "src" / "components" / "Checkout.tsx").write_text(
        "export function CheckoutForm() { return null; }\n", encoding="utf-8"
    )


def test_detects_playwright_config(tmp_path: Path) -> None:
    _app(tmp_path)
    project = detect_ui_project(tmp_path)
    assert project is not None
    assert project.framework == "playwright"


def test_ignores_unit_tests_without_playwright_import(tmp_path: Path) -> None:
    _app(tmp_path)
    (tmp_path / "src" / "lib" / "format.test.ts").write_text(
        "import { describe } from 'vitest';\ndescribe('fmt', () => {});\n",
        encoding="utf-8",
    )
    config = QualityConfig()
    project = detect_ui_project(tmp_path)
    assert project is not None
    names = [path.name for path in discover_specs(tmp_path, config, project)]
    assert "checkout.spec.ts" in names
    assert "format.test.ts" not in names


def test_selects_spec_that_changed(tmp_path: Path) -> None:
    _app(tmp_path)
    config = QualityConfig()
    project = detect_ui_project(tmp_path)
    assert project is not None
    selection = select_specs(tmp_path, config, project, ["e2e/login.spec.ts"])
    names = [path.name for path in selection.specs]
    assert names == ["login.spec.ts"]
    assert not selection.run_all


def test_selects_via_route_goto(tmp_path: Path) -> None:
    _app(tmp_path)
    config = QualityConfig()
    project = detect_ui_project(tmp_path)
    assert project is not None
    selection = select_specs(tmp_path, config, project, ["src/app/checkout/page.tsx"])
    names = [path.name for path in selection.specs]
    assert "checkout.spec.ts" in names
    assert "login.spec.ts" not in names


def test_similar_name_without_a_touch_is_ignored(tmp_path: Path) -> None:
    _app(tmp_path)
    config = QualityConfig()
    project = detect_ui_project(tmp_path)
    assert project is not None
    selection = select_specs(tmp_path, config, project, ["src/components/Checkout.tsx"])
    assert selection.specs == []


def test_selects_via_relative_import(tmp_path: Path) -> None:
    _app(tmp_path)
    config = QualityConfig()
    project = detect_ui_project(tmp_path)
    assert project is not None
    selection = select_specs(tmp_path, config, project, ["e2e/helpers.ts"])
    names = [path.name for path in selection.specs]
    assert "checkout.spec.ts" in names
    assert "login.spec.ts" not in names


def test_selects_via_page_import_graph(tmp_path: Path) -> None:
    _app(tmp_path)
    config = QualityConfig()
    project = detect_ui_project(tmp_path)
    assert project is not None
    selection = select_specs(tmp_path, config, project, ["src/components/Cart.tsx"])
    names = [path.name for path in selection.specs]
    assert "checkout.spec.ts" in names
    assert "login.spec.ts" not in names


def test_unrelated_source_selects_nothing(tmp_path: Path) -> None:
    _app(tmp_path)
    config = QualityConfig()
    project = detect_ui_project(tmp_path)
    assert project is not None
    selection = select_specs(tmp_path, config, project, ["src/lib/format.ts"])
    assert selection.specs == []


def test_root_layout_runs_all(tmp_path: Path) -> None:
    _app(tmp_path)
    (tmp_path / "src" / "app" / "layout.tsx").write_text(
        "export default function Root({ children }) { return children; }\n",
        encoding="utf-8",
    )
    config = QualityConfig()
    project = detect_ui_project(tmp_path)
    assert project is not None
    selection = select_specs(tmp_path, config, project, ["src/app/layout.tsx"])
    assert selection.run_all
    assert len(selection.specs) == 2


def test_unrelated_diff_selects_nothing(tmp_path: Path) -> None:
    _app(tmp_path)
    config = QualityConfig()
    project = detect_ui_project(tmp_path)
    assert project is not None
    selection = select_specs(tmp_path, config, project, ["README.md"])
    assert selection.specs == []
    assert not selection.run_all


def test_shared_config_runs_all(tmp_path: Path) -> None:
    _app(tmp_path)
    config = QualityConfig()
    project = detect_ui_project(tmp_path)
    assert project is not None
    selection = select_specs(tmp_path, config, project, ["playwright.config.ts"])
    assert selection.run_all
    assert len(selection.specs) == 2


def test_coverage_map_inverts(tmp_path: Path) -> None:
    _app(tmp_path)
    reports = tmp_path / ".quality-reports"
    reports.mkdir()
    (reports / "ui-coverage.json").write_text(
        '{"e2e/login.spec.ts": ["src/lib/format.ts"]}\n',
        encoding="utf-8",
    )
    config = QualityConfig()
    project = detect_ui_project(tmp_path)
    assert project is not None
    selection = select_specs(tmp_path, config, project, ["src/lib/format.ts"])
    names = [path.name for path in selection.specs]
    assert "login.spec.ts" in names


def test_force_all(tmp_path: Path) -> None:
    _app(tmp_path)
    config = QualityConfig()
    project = detect_ui_project(tmp_path)
    assert project is not None
    selection = select_specs(tmp_path, config, project, ["README.md"], force_all=True)
    assert selection.run_all
    assert len(selection.specs) == 2


def test_ui_gate_skips_without_project(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    result = run_ui(tmp_path, QualityConfig())
    assert result.status == "skip"
    assert "Playwright" in result.notes[0]


def test_ui_gate_skips_on_github(tmp_path: Path, monkeypatch) -> None:
    _app(tmp_path)
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.delenv("QUALITY_UI_ON_GITHUB", raising=False)
    result = run_ui(tmp_path, QualityConfig())
    assert result.status == "skip"
    assert "GitHub" in result.notes[0]


def test_ui_gate_skips_when_compile_failed(tmp_path: Path, monkeypatch) -> None:
    _app(tmp_path)
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    failed = GateResult(name="compile", status="fail")
    result = run_ui(tmp_path, QualityConfig(), compile_result=failed)
    assert result.status == "skip"
    assert "compile failed" in result.notes[0]


def test_ui_list_only_selects_from_diff(tmp_path: Path, monkeypatch) -> None:
    _app(tmp_path)
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    monkeypatch.setattr(
        "quality_gates.gates.ui.git_changed_names",
        lambda _root, _base: ["src/app/checkout/page.tsx"],
    )
    monkeypatch.setattr(
        "quality_gates.gates.ui.git_base_ref",
        lambda _explicit=None: "HEAD",
    )
    result = run_ui(tmp_path, QualityConfig(), list_only=True)
    assert result.status == "pass"
    joined = " ".join(result.notes)
    assert "checkout.spec.ts" in joined
    assert "login.spec.ts" not in joined


def test_loads_ui_config(tmp_path: Path) -> None:
    (tmp_path / "quality.toml").write_text(
        """
[quality.ui]
select = "all"
framework = "cypress"
on_github = true
spec_dirs = ["cypress/e2e"]
coverage_map = "cov.json"

[quality.ui.path_aliases]
"@/" = "app/"
""".strip()
        + "\n",
        encoding="utf-8",
    )
    config = load_config(tmp_path)
    assert config.ui_select == "all"
    assert config.ui_framework == "cypress"
    assert config.ui_on_github is True
    assert config.ui_spec_dirs == ["cypress/e2e"]
    assert config.ui_path_aliases["@/"] == "app/"
    assert config.ui_coverage_map == "cov.json"
    assert "ui" in config.fail_on
