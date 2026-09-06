from __future__ import annotations

import runpy
import sys
from unittest.mock import patch


def test_main_invocation() -> None:
    with patch.object(sys, "argv", ["quality", "--help"]):
        try:
            runpy.run_module("quality_gates.__main__", run_name="__main__")
        except SystemExit as exc:
            assert exc.code == 0
