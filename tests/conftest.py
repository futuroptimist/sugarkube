"""Test fixtures and configuration helpers."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Iterable, List

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


def require_tools(tools: Iterable[str]) -> None:
    """Skip the current test when required system tools are missing."""

    missing: List[str] = []
    for tool in tools:
        result = subprocess.run([
            "which",
            tool,
        ], capture_output=True, text=True)
        if result.returncode != 0:
            missing.append(tool)

    if missing:
        # TODO: Package the required CLI tools with the test environment so suites don't skip.
        # Root cause: Some contributors run the tests on minimal images lacking networking utils.
        # Estimated fix: 1h to document the dependencies and add them to CI bootstrap.
        pytest.skip(f"Required tools not available: {', '.join(sorted(missing))}")


def ensure_root_privileges() -> None:
    """Skip when we cannot create network namespaces due to insufficient privileges."""

    result = subprocess.run(["id", "-u"], capture_output=True, text=True)
    if result.stdout.strip() == "0":
        return

    probe = subprocess.run(["unshare", "-n", "true"], capture_output=True, text=True)
    if probe.returncode != 0:
        # TODO: Grant network namespace capabilities in CI or provide a stub harness for tests.
        # Root cause: Creating namespaces requires elevated privileges that may be blocked.
        # Estimated fix: 1h to run tests with the needed capabilities or mock namespace usage.
        pytest.skip("Insufficient privileges for network namespace operations")
