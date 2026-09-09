"""Poll the tree and rerun cheap gates. Stdlib only — no extra dependency."""

from __future__ import annotations

import time
from collections.abc import Callable
from pathlib import Path

from quality_gates.config import QualityConfig
from quality_gates.detect import iter_project_files


def snapshot(root: Path, config: QualityConfig) -> dict[str, tuple[int, int]]:
    """Return path → (mtime_ns, size) so same-second Windows writes still differ."""
    stamps: dict[str, tuple[int, int]] = {}
    for path in iter_project_files(root, config):
        try:
            info = path.stat()
            stamps[path.as_posix()] = (info.st_mtime_ns, info.st_size)
        except OSError:
            continue
    return stamps


def watch_loop(
    root: Path,
    config: QualityConfig,
    run: Callable[[], None],
    *,
    interval: float = 1.5,
    cycles: int | None = None,
) -> int:
    """Rerun ``run`` when project files change. ``cycles`` is for tests."""
    last = snapshot(root, config)
    seen = 0
    while cycles is None or seen < cycles:
        time.sleep(interval)
        current = snapshot(root, config)
        if current != last:
            last = current
            run()
        seen += 1
    return 0
