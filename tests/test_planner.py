from quality_gates.change_manifest import Change, ChangeManifest
from quality_gates.config import QualityConfig
from quality_gates.planner import build_plan, write_plan


def test_plan_has_prerequisites_and_change_inputs() -> None:
    manifest = ChangeManifest(
        "available",
        "base",
        "target",
        "tree",
        "digest",
        (Change("modified", "src/app.py"),),
    )
    plan = build_plan(
        ["security", "compile", "ui"], QualityConfig(fail_on=["compile"]), manifest
    )

    assert plan[1].prerequisites == ("security",)
    assert plan[2].prerequisites == ("compile",)
    assert plan[1].required is True
    assert plan[0].inputs == ("src/app.py",)


def test_plan_is_persisted_for_reports(tmp_path) -> None:
    path = write_plan(tmp_path, build_plan(["lint"], QualityConfig(), None))

    assert '"name": "lint"' in path.read_text(encoding="utf-8")


def test_render_plan_explains_selection_and_exclusions() -> None:
    from quality_gates.planner import render_plan

    plan = build_plan(["lint"], QualityConfig(), None)
    rendered = render_plan(plan)

    assert "Quality execution plan:" in rendered
    assert "- lint: required;" in rendered
    assert "Excluded gates:" in rendered
    assert "Summary:" in rendered
