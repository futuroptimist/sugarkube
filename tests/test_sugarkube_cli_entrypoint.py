"""Ensure the top-level sugarkube command proxies to the toolkit CLI."""

from __future__ import annotations

import subprocess
from pathlib import Path


def test_sugarkube_script_invokes_cli() -> None:
    """scripts/sugarkube should execute the toolkit CLI entry point."""

    script = Path(__file__).resolve().parents[1] / "scripts" / "sugarkube"
    assert script.exists(), "scripts/sugarkube entry point is missing"

    result = subprocess.run(
        [str(script), "docs", "verify", "--dry-run"],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert "pyspelling -c .spellcheck.yaml" in result.stdout
    assert "linkchecker --no-warnings README.md docs/" in result.stdout
