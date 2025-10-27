"""Guard shellcheck regressions for mdns_selfcheck.sh."""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "mdns_selfcheck.sh"


@pytest.mark.skipif(shutil.which("shellcheck") is None, reason="shellcheck not installed")
def test_mdns_selfcheck_shellcheck_passes_without_unreachable_warning() -> None:
    result = subprocess.run(
        ["shellcheck", "-S", "info", "-x", str(SCRIPT)],
        capture_output=True,
        text=True,
        check=False,
    )
    stdout = result.stdout or ""
    stderr = result.stderr or ""
    combined = stdout + "\n" + stderr
    assert result.returncode == 0, combined
    assert "SC2317" not in combined, combined
