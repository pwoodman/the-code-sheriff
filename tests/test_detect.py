from __future__ import annotations

from pathlib import Path

from quality_gates.ci_plan import github_runs_full_suite
from quality_gates.config import DEFAULT_GITHUB_GATES, load_config
from quality_gates.detect import detect_languages
from quality_gates.paths import repo_root


def test_detects_listed_languages(tmp_path: Path) -> None:
    files = {
        "src/App.tsx": "export const App = () => null;\n",
        "src/main.ts": "export const n = 1;\n",
        "src/util.js": "export const x = 1;\n",
        "pkg/hello.go": "package pkg\n",
        "lib.rs": "fn main() {}\n",
        "Hello.java": "class Hello {}\n",
        "Hello.cs": "class Hello {}\n",
        "app.py": "x = 1\n",
        "query.sql": "SELECT 1;\n",
    }
    for rel, content in files.items():
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    info = detect_languages(tmp_path, load_config(tmp_path))
    assert set(info["languages"]) == {
        "csharp",
        "javascript",
        "typescript",
        "react",
        "rust",
        "go",
        "python",
        "java",
        "sql",
    }
    assert info["toolchains"] == [
        "csharp",
        "node",
        "rust",
        "go",
        "python",
        "java",
        "sql",
    ]
    assert info["gate_languages"] == [
        "csharp",
        "javascript",
        "rust",
        "go",
        "python",
        "java",
        "sql",
    ]


def test_excludes_vendor_and_venv(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "ok.py").write_text("x = 1\n", encoding="utf-8")
    nested = tmp_path / "node_modules" / "pkg"
    nested.mkdir(parents=True)
    (nested / "index.js").write_text("var x = 1\n", encoding="utf-8")
    info = detect_languages(tmp_path, load_config(tmp_path))
    assert info["languages"] == ["python"]


def test_skips_unknown_hidden_dirs_but_keeps_github(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("x = 1\n", encoding="utf-8")
    indexer = tmp_path / ".zvec-grep" / "files.zvec"
    indexer.mkdir(parents=True)
    (indexer / "lock.json").write_text("{}\n", encoding="utf-8")
    (tmp_path / ".cursor").mkdir()
    (tmp_path / ".cursor" / "notes.py").write_text("eval(1)\n", encoding="utf-8")
    workflows = tmp_path / ".github" / "workflows"
    workflows.mkdir(parents=True)
    (workflows / "ci.yml").write_text("name: ci\n", encoding="utf-8")
    from quality_gates.detect import iter_project_files

    files = {
        path.relative_to(tmp_path).as_posix()
        for path in iter_project_files(tmp_path, load_config(tmp_path))
    }
    assert "src/app.py" in files
    assert ".github/workflows/ci.yml" in files
    assert not any(path.startswith(".zvec-grep") for path in files)
    assert not any(path.startswith(".cursor") for path in files)


def test_language_filter_from_toml(tmp_path: Path) -> None:
    (tmp_path / "quality.toml").write_text(
        '[quality]\nlanguages = ["python", "go"]\n',
        encoding="utf-8",
    )
    (tmp_path / "a.py").write_text("x = 1\n", encoding="utf-8")
    (tmp_path / "a.go").write_text("package a\n", encoding="utf-8")
    (tmp_path / "a.rs").write_text("fn main() {}\n", encoding="utf-8")
    info = detect_languages(tmp_path, load_config(tmp_path))
    assert info["languages"] == ["go", "python"]


def test_this_repo_detects_python_and_dogfoods_full_github_suite() -> None:
    root = repo_root()
    assert root is not None
    config = load_config(root)
    info = detect_languages(root, config)
    assert "python" in info["languages"]
    assert "python" in info["gate_languages"]
    assert config.ci_mode == "both"
    assert github_runs_full_suite(config)
    assert config.ci_github_gates[:2] == ["format", "lint"]
    assert DEFAULT_GITHUB_GATES[:2] == ["format", "lint"]
