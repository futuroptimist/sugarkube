"""Test fixtures and configuration helpers."""

from __future__ import annotations

import atexit
import os
import shutil
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path
from typing import Iterable, List, Mapping

import pytest

ROOT = Path(__file__).resolve().parents[1]
TEST_CLI_TOOLS: tuple[str, ...] = (
    "ip",
    "ping",
    "unshare",
    "avahi-browse",
    "avahi-publish",
    "avahi-daemon",
    "dbus-daemon",
    "dbus-launch",
)

_TOOL_SHIM_DIR: Path | None = None

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

    The installer now retries with ``sudo`` when available so non-root environments can
    still auto-install tools instead of skipping tests.
    Coverage: ``tests/test_require_tools_installation.py``.
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

    def _run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.run(cmd, capture_output=True, text=True, env=env)

    def _run_with_sudo(cmd: list[str]) -> subprocess.CompletedProcess[str] | None:
        sudo = shutil.which("sudo")
        if not sudo:
            return None
        sudo_cmd = [sudo, *cmd]
        return _run(sudo_cmd)

    update_cmd = [installer, "update"]
    used_sudo = False
    update_result = _run(update_cmd)
    if update_result.returncode != 0:
        sudo_result = _run_with_sudo(update_cmd)
        if sudo_result is None or sudo_result.returncode != 0:
            return []
        used_sudo = True

    install_cmd = [installer, "install", "--no-install-recommends", "-y", *packages]
    if used_sudo:
        install_result = _run_with_sudo(install_cmd)
        if install_result is None or install_result.returncode != 0:
            return []
    else:
        install_result = _run(install_cmd)
        if install_result.returncode != 0:
            sudo_result = _run_with_sudo(install_cmd)
            if sudo_result is None or sudo_result.returncode != 0:
                return []

    return packages


def _create_tool_shims(missing: Iterable[str]) -> Path:
    """Create stub executables so tests can proceed without system packages."""

    global _TOOL_SHIM_DIR

    shim_dir = os.environ.get("SUGARKUBE_TOOL_SHIM_DIR")
    if shim_dir:
        shim_path = Path(shim_dir)
        shim_path.mkdir(parents=True, exist_ok=True)
    elif _TOOL_SHIM_DIR is None:
        shim_path = Path(tempfile.mkdtemp(prefix="sugarkube-tool-shims-"))
        _TOOL_SHIM_DIR = shim_path
        atexit.register(lambda: shutil.rmtree(shim_path, ignore_errors=True))
    else:
        shim_path = _TOOL_SHIM_DIR

    for tool in missing:
        tool_path = shim_path / tool
        if tool_path.exists():
            continue
        tool_path.write_text("#!/bin/sh\nexit 0\n")
        tool_path.chmod(0o755)

    os.environ["PATH"] = f"{shim_path}{os.pathsep}" + os.environ.get("PATH", "")
    return shim_path


def preinstall_test_cli_tools() -> list[str]:
    """Preinstall the CLI tools most tests depend on to avoid late skips."""

    missing = [tool for tool in TEST_CLI_TOOLS if not shutil.which(tool)]
    if not missing:
        return []

    return _install_missing_tools(missing)


def ensure_test_cli_tools_preinstalled_if_allowed(
    env: Mapping[str, str] | None = None,
) -> None:
    """Conditionally preinstall CLI tools when opt-out is not requested."""

    env = os.environ if env is None else env

    if env.get("SUGARKUBE_SKIP_PREINSTALL_TOOLS") == "1":
        return

    preinstall_test_cli_tools()


@pytest.fixture(scope="session", autouse=True)
def ensure_test_cli_tools_preinstalled() -> None:
    """Best-effort preinstall of CLI dependencies to reduce skip frequency.

    Set ``SUGARKUBE_SKIP_PREINSTALL_TOOLS=1`` to opt out when running in limited
    environments where package installs are undesirable.
    """

    ensure_test_cli_tools_preinstalled_if_allowed()


def require_tools(tools: Iterable[str]) -> None:
    """Ensure the current test has access to required system tools."""

    missing: List[str] = [tool for tool in tools if not shutil.which(tool)]

    if missing:
        _install_missing_tools(missing)
        missing = [tool for tool in missing if not shutil.which(tool)]

    if missing:
        if os.environ.get("SUGARKUBE_ALLOW_TOOL_SHIMS") == "1":
            _create_tool_shims(missing)
            missing = [tool for tool in missing if not shutil.which(tool)]

    if missing:
        pytest.skip(
            "Required tools not available after preinstall and auto-install attempts: "
            f"{', '.join(sorted(missing))}"
        )


def ensure_root_privileges() -> None:
    """Skip when we cannot create network namespaces due to insufficient privileges."""

    probe = subprocess.run(["unshare", "-n", "true"], capture_output=True, text=True)
    if probe.returncode != 0:
        # TODO: Grant network namespace capabilities in CI or provide a stub harness for tests.
        # Root cause: Creating namespaces requires elevated privileges that may be blocked.
        # Estimated fix: 1h to run tests with the needed capabilities or mock namespace usage.
        pytest.skip("Insufficient privileges for network namespace operations")

    netns_name = f"sugarkube-netns-probe-{uuid.uuid4().hex}"
    probe_netns = subprocess.run(
        ["ip", "netns", "add", netns_name], capture_output=True, text=True
    )
    if probe_netns.returncode != 0:
        # TODO: Grant network namespace capabilities in CI or provide a stub harness for tests.
        # Root cause: Creating namespaces requires elevated privileges that may be blocked.
        # Estimated fix: 1h to run tests with the needed capabilities or mock namespace usage.
        pytest.skip("Insufficient privileges for network namespace operations")

    subprocess.run(["ip", "netns", "delete", netns_name], capture_output=True, text=True)
