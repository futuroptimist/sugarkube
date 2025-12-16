"""Test fixtures and configuration helpers."""

from __future__ import annotations

import atexit
import os
import shutil
import subprocess
import sys
import tempfile
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


@pytest.fixture(scope="session")
def ensure_just_available() -> Path:
    """Install just once per test session when it is not already available."""

    existing = shutil.which("just")
    if existing:
        return Path(existing)

    bin_dir = Path(tempfile.mkdtemp(prefix="sugarkube-just-"))
    atexit.register(lambda: shutil.rmtree(bin_dir, ignore_errors=True))

    env = os.environ.copy()
    env["SUGARKUBE_JUST_BIN_DIR"] = str(bin_dir)

    result = subprocess.run(
        ["/bin/bash", str(ROOT / "scripts" / "install_just.sh")],
        capture_output=True,
        env=env,
        text=True,
    )

    if result.returncode != 0:
        pytest.fail(f"Failed to install just: {result.stderr}")

    os.environ["PATH"] = f"{bin_dir}{os.pathsep}" + os.environ.get("PATH", "")

    located = shutil.which("just")
    if not located:
        pytest.fail("just not available after installation")

    return Path(located)


def _install_missing_tools(missing: Iterable[str]) -> list[str]:
    """Best-effort installer for common CLI dependencies used by the tests.

    Note:
        Installation attempts via apt-get require elevated privileges (root or sudo).
        If the tests are run as a non-root user, installation will silently fail,
        which is the intended behavior. If the required tools remain unavailable
        after the attempt, the test will be skipped as before.
    """

    installer = shutil.which("apt-get")
    if not installer:
        return []

    package_map = {
        "ip": "iproute2",
        "ping": "iputils-ping",
        "unshare": "util-linux",
        "avahi-browse": "avahi-utils",
        "avahi-publish": "avahi-utils",
        "avahi-daemon": "avahi-daemon",
        "dbus-daemon": "dbus",
        "dbus-launch": "dbus-x11",
    }

    packages = sorted({package_map.get(tool, tool) for tool in missing})
    if not packages:
        return []

    env = os.environ.copy()
    env.setdefault("DEBIAN_FRONTEND", "noninteractive")

    update_result = subprocess.run(
        [installer, "update"], capture_output=True, text=True, env=env
    )
    if update_result.returncode != 0:
        return []

    install_cmd = [installer, "install", "--no-install-recommends", "-y", *packages]
    install_result = subprocess.run(install_cmd, capture_output=True, text=True, env=env)
    if install_result.returncode != 0:
        return []

    return packages


def require_tools(tools: Iterable[str]) -> None:
    """Ensure the current test has access to required system tools."""

    missing: List[str] = [tool for tool in tools if not shutil.which(tool)]

    if missing:
        _install_missing_tools(missing)
        missing = [tool for tool in missing if not shutil.which(tool)]

    if missing:
        if os.environ.get("CI"):
            pytest.fail(
                "Required tools not available after attempted installation; install them in CI"
            )
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
