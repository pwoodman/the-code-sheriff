from __future__ import annotations

from quality_gates.review.context import (
    changed_paths,
    new_side_lines,
    partition_review_units,
    split_diff_files,
)


def test_context_helpers() -> None:
    diff = """diff --git a/src/app.py b/src/app.py
--- a/src/app.py
+++ b/src/app.py
@@ -1,2 +1,3 @@
 x = 1
+y = 2
"""
    assert "src/app.py" in changed_paths(diff)
    files = split_diff_files(diff)
    assert len(files) == 1
    lines = new_side_lines(diff)
    assert "src/app.py" in lines
    _packed, reviewed, _unreviewed = partition_review_units(diff, limit=1000)
    assert "src/app.py" in reviewed
