"""Test fixtures and configuration helpers."""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

# Ensure the project root is importable so ``sitecustomize`` is discovered by
# subprocesses spawned in tests.  ``sys.path`` adjustments affect the current
# interpreter while the ``PYTHONPATH`` export keeps child interpreters aligned.
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _export_pythonpath(monkeypatch: pytest.MonkeyPatch) -> None:
    path_str = str(ROOT)
    pythonpath = os.environ.get("PYTHONPATH")
    if not pythonpath:
        monkeypatch.setenv("PYTHONPATH", path_str)
        return
    parts = pythonpath.split(os.pathsep)
    if path_str in parts:
        return
    parts.insert(0, path_str)
    monkeypatch.setenv("PYTHONPATH", os.pathsep.join(parts))


@pytest.fixture(autouse=True)
def enable_subprocess_coverage(monkeypatch: pytest.MonkeyPatch) -> None:
    """Propagate coverage configuration to subprocesses under test."""

    monkeypatch.setenv("COVERAGE_PROCESS_START", str(ROOT / ".coveragerc"))
    _export_pythonpath(monkeypatch)
