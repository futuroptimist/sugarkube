"""Coverage for the legacy docs-verify wrapper."""

from __future__ import annotations

import subprocess
from pathlib import Path


def test_shell_wrapper_announces_deprecation_and_forwards() -> None:
    """The shell wrapper should warn and forward to the CLI in dry-run mode."""

    repo_root = Path(__file__).resolve().parents[1]
    script = repo_root / "scripts" / "docs_verify.sh"
    result = subprocess.run(
        ["bash", str(script), "--dry-run"],
        check=False,
        capture_output=True,
        text=True,
        cwd=repo_root,
    )

    assert result.returncode == 0
    stderr = result.stderr.lower()
    assert "deprecated" in stderr
    assert "docs verify" in stderr

    stdout = result.stdout
    assert "pyspelling -c .spellcheck.yaml" in stdout
    assert "linkchecker --no-warnings README.md docs/" in stdout
