"""End-to-end test exercising k3s-discover fail-open fallback and recovery."""

from __future__ import annotations

import os
import random
import shutil
import string
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Tuple

from tests.conftest import ensure_root_privileges, require_tools

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO_ROOT / "scripts"
K3S_DISCOVER = SCRIPTS_DIR / "k3s-discover.sh"

DBUS_STARTUP_TIMEOUT_SECS = 5
DBUS_POLL_INTERVAL_SECS = 0.1
AVAHI_STARTUP_DELAY_SECS = 1
SERVICE_PUBLICATION_DELAY_SECS = 2
PROCESS_TERMINATION_TIMEOUT_SECS = 5


pytestmark = pytest.mark.skipif(
    os.environ.get("AVAHI_AVAILABLE") != "1",
    reason="AVAHI_AVAILABLE=1 not set (requires Avahi daemon and root permissions)",
)


def _unique_name(prefix: str) -> str:
    suffix = "".join(random.choices(string.ascii_lowercase + string.digits, k=6))
    return f"{prefix}-{suffix}"


@dataclass
class NamespaceProcesses:
    name: str
    veth: str
    ip: str
    bus_path: Path
    runtime_dir: Path
    dbus: subprocess.Popen[str]
    avahi: subprocess.Popen[str]


def _setup_namespace_pair() -> Tuple[Dict[str, str], List[List[str]]]:
    leader_ns = _unique_name("discover-leader")
    follower_ns = _unique_name("discover-follower")
    leader_veth = _unique_name("veth-dl")
    follower_veth = _unique_name("veth-df")
    leader_ip = "192.168.120.1"
    follower_ip = "192.168.120.2"

    cleanup_commands: List[List[str]] = []

    subprocess.run(["ip", "netns", "add", leader_ns], check=True, capture_output=True)
    cleanup_commands.append(["ip", "netns", "del", leader_ns])

    subprocess.run(["ip", "netns", "add", follower_ns], check=True, capture_output=True)
    cleanup_commands.append(["ip", "netns", "del", follower_ns])

    subprocess.run(
        ["ip", "link", "add", leader_veth, "type", "veth", "peer", "name", follower_veth],
        check=True,
        capture_output=True,
    )
    cleanup_commands.append(["ip", "link", "del", leader_veth])

    subprocess.run(
        ["ip", "link", "set", leader_veth, "netns", leader_ns],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["ip", "link", "set", follower_veth, "netns", follower_ns],
        check=True,
        capture_output=True,
    )

    subprocess.run(
        [
            "ip",
            "netns",
            "exec",
            leader_ns,
            "ip",
            "addr",
            "add",
            f"{leader_ip}/24",
            "dev",
            leader_veth,
        ],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        [
            "ip",
            "netns",
            "exec",
            follower_ns,
            "ip",
            "addr",
            "add",
            f"{follower_ip}/24",
            "dev",
            follower_veth,
        ],
        check=True,
        capture_output=True,
    )

    subprocess.run(
        ["ip", "netns", "exec", leader_ns, "ip", "link", "set", "lo", "up"],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["ip", "netns", "exec", leader_ns, "ip", "link", "set", leader_veth, "up"],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["ip", "netns", "exec", follower_ns, "ip", "link", "set", "lo", "up"],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["ip", "netns", "exec", follower_ns, "ip", "link", "set", follower_veth, "up"],
        check=True,
        capture_output=True,
    )

    ping = subprocess.run(
        [
            "ip",
            "netns",
            "exec",
            leader_ns,
            "ping",
            "-c",
            "1",
            "-W",
            "2",
            follower_ip,
        ],
        capture_output=True,
        text=True,
    )
    if ping.returncode != 0:
        # TODO: Stabilize the network namespace ping path in CI to avoid spurious skips.
        # Root cause: Kernel or container limitations sometimes prevent namespace-to-namespace
        #   pings, so the harness bails out instead of exercising fail-open behavior.
        # Estimated fix: 2h to mock the connectivity check or provision CAP_NET_ADMIN reliably.
        pytest.skip("Network namespace connectivity test failed")

    return (
        {
            "leader_ns": leader_ns,
            "leader_veth": leader_veth,
            "leader_ip": leader_ip,
            "follower_ns": follower_ns,
            "follower_veth": follower_veth,
            "follower_ip": follower_ip,
        },
        cleanup_commands,
    )


def _start_dbus(namespace: str, bus_path: Path) -> subprocess.Popen[str]:
    bus_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ip",
        "netns",
        "exec",
        namespace,
        "dbus-daemon",
        f"--address=unix:path={bus_path}",
        "--config-file=/usr/share/dbus-1/system.conf",
        "--nofork",
        "--nopidfile",
    ]
    proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    deadline = time.time() + DBUS_STARTUP_TIMEOUT_SECS
    while time.time() < deadline:
        if bus_path.exists():
            return proc
        time.sleep(DBUS_POLL_INTERVAL_SECS)
    proc.terminate()
    proc.wait(timeout=PROCESS_TERMINATION_TIMEOUT_SECS)
    raise RuntimeError(f"dbus-daemon did not create bus socket at {bus_path}")


def _start_avahi(namespace: str, bus_path: Path, runtime_dir: Path) -> subprocess.Popen[str]:
    runtime_dir.mkdir(parents=True, exist_ok=True)
    for path in ("/run/dbus", "/run/avahi-daemon"):
        subprocess.run(
            ["ip", "netns", "exec", namespace, "mkdir", "-p", path],
            check=True,
            capture_output=True,
        )
    env_prefix = [
        "env",
        f"DBUS_SYSTEM_BUS_ADDRESS=unix:path={bus_path}",
        f"XDG_RUNTIME_DIR={runtime_dir}",
    ]
    cmd = [
        "ip",
        "netns",
        "exec",
        namespace,
        *env_prefix,
        "avahi-daemon",
        "--debug",
        "--no-drop-root",
        "--no-chroot",
        "--no-rlimits",
    ]
    proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    # Allow Avahi time to register with D-Bus and expose services before proceeding.
    time.sleep(AVAHI_STARTUP_DELAY_SECS)
    return proc


def _start_publisher(
    namespace: str,
    bus_path: Path,
    runtime_dir: Path,
    service_name: str,
    service_type: str,
    port: int,
    canonical_host: str,
    leader_ip: str,
) -> subprocess.Popen[str]:
    env_prefix = [
        "env",
        f"DBUS_SYSTEM_BUS_ADDRESS=unix:path={bus_path}",
        f"XDG_RUNTIME_DIR={runtime_dir}",
    ]
    txt_records = [
        "txt=role=server",
        "txt=phase=server",
        f"txt=host={canonical_host}",
        f"txt=ip4={leader_ip}",
        f"txt=leader={canonical_host}",
    ]
    cmd = [
        "ip",
        "netns",
        "exec",
        namespace,
        *env_prefix,
        "avahi-publish",
        "-s",
        service_name,
        service_type,
        str(port),
        "--host",
        canonical_host,
        *txt_records,
    ]
    return subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _write_executable(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
    path.chmod(0o755)


def _create_stub_bin(
    bin_dir: Path,
    *,
    canonical_host: str,
    fallback_host: str,
    leader_ip: str,
) -> Dict[str, Path]:
    """Create stub executables that emulate system tooling used by k3s-discover tests.

    The stubs wrap or replace binaries such as ``systemctl``, ``k3s-install`` and
    ``avahi-browse`` so the harness can observe interactions without mutating the
    host system. Some simply exit successfully, while others log arguments or
    proxy to the real binary with deterministic responses for the test scenario.

    Args:
        bin_dir: Directory in which to place the stub executables.
        canonical_host: Canonical host name advertised via mDNS.
        fallback_host: Host name used when fail-open mode is triggered.
        leader_ip: IP address returned for both canonical and fallback host lookups.

    Returns:
        Mapping of stub names to their file paths for convenient lookup.
    """
    bin_dir.mkdir(parents=True, exist_ok=True)

    stubs: Dict[str, Path] = {}

    for name in ("systemctl", "iptables", "ip6tables", "curl", "openssl", "journalctl"):
        stub = bin_dir / name
        _write_executable(stub, "#!/bin/bash\nexit 0\n")
        stubs[name] = stub

    sleep_stub = bin_dir / "sleep"
    _write_executable(sleep_stub, "#!/bin/bash\nexit 0\n")
    stubs["sleep"] = sleep_stub

    configure_avahi_stub = bin_dir / "configure_avahi.sh"
    _write_executable(configure_avahi_stub, "#!/bin/bash\nexit 0\n")
    stubs["configure_avahi"] = configure_avahi_stub

    wait_avahi_stub = bin_dir / "wait_for_avahi_dbus.sh"
    _write_executable(wait_avahi_stub, "#!/bin/bash\nexit 0\n")
    stubs["wait_for_avahi_dbus"] = wait_avahi_stub

    mdns_diag_stub = bin_dir / "mdns_diag.sh"
    _write_executable(mdns_diag_stub, "#!/bin/bash\nexit 0\n")
    stubs["mdns_diag"] = mdns_diag_stub

    net_diag_stub = bin_dir / "net_diag.sh"
    _write_executable(net_diag_stub, "#!/bin/bash\nexit 0\n")
    stubs["net_diag"] = net_diag_stub

    install_stub = bin_dir / "k3s-install.sh"
    _write_executable(
        install_stub,
        """#!/bin/bash
set -euo pipefail
log_path="${K3S_INSTALL_LOG:?}"
{
  echo "MODE=$1"
  echo "K3S_URL=${K3S_URL:-}"
  if [ -n "${SERVER_IP:-}" ]; then
    echo "SERVER_IP=${SERVER_IP}"
  fi
} >>"${log_path}"
exit 0
""",
    )
    stubs["k3s_install"] = install_stub

    check_api_stub = bin_dir / "check_apiready.sh"
    _write_executable(
        check_api_stub,
        """#!/bin/bash
set -euo pipefail
log_path="${CHECK_API_LOG:?}"
echo "host=${SERVER_HOST:-} ip=${SERVER_IP:-} port=${SERVER_PORT:-}" >>"${log_path}"
exit 0
""",
    )
    stubs["check_apiready"] = check_api_stub

    real_getent = shutil.which("getent")
    if real_getent is None:
        # TODO: Bundle getent in the test environment so the stub harness can proxy calls.
        # Root cause: The getent utility is missing on minimal containers, blocking DNS stubbing.
        # Estimated fix: 30m to install the package in CI and note the dependency locally.
        pytest.skip("getent not available for stub harness")
    getent_stub = bin_dir / "getent"
    _write_executable(
        getent_stub,
        f"""#!/bin/bash
set -e
if [ "$#" -ge 2 ]; then
  case "$1 $2" in
    "hosts {fallback_host}")
      echo "{leader_ip} {fallback_host}"
      exit 0
      ;;
    "hosts {canonical_host}")
      echo "{leader_ip} {canonical_host}"
      exit 0
      ;;
    "ahostsv4 {fallback_host}")
      echo "{leader_ip} {fallback_host}"
      exit 0
      ;;
    "ahostsv4 {canonical_host}")
      echo "{leader_ip} {canonical_host}"
      exit 0
      ;;
  esac
fi
exec "{real_getent}" "$@"
""",
    )
    stubs["getent"] = getent_stub

    real_avahi_browse = shutil.which("avahi-browse")
    if real_avahi_browse is None:
        # TODO: Provide an avahi-browse shim for stub mode when the binary is unavailable.
        # Root cause: Some environments omit Avahi tooling, preventing the harness from setting
        #   up the browse stub used by the fail-open tests.
        # Estimated fix: 45m to vendor a tiny shell shim or add the package to CI images.
        pytest.skip("avahi-browse not available for stub harness")
    avahi_browse_stub = bin_dir / "avahi-browse"
    _write_executable(
        avahi_browse_stub,
        f"""#!/bin/bash
mode="${{AVAHI_STUB_MODE:-real}}"
if [ "${{mode}}" = "fail" ]; then
  echo "avahi-browse stub forcing failure" >&2
  exit 2
fi
exec "{real_avahi_browse}" "$@"
""",
    )
    stubs["avahi_browse"] = avahi_browse_stub

    real_avahi_resolve = shutil.which("avahi-resolve")
    if real_avahi_resolve is not None:
        avahi_resolve_stub = bin_dir / "avahi-resolve"
        _write_executable(
            avahi_resolve_stub,
            f"#!/bin/bash\nexec \"{real_avahi_resolve}\" \"$@\"\n",
        )
        stubs["avahi_resolve"] = avahi_resolve_stub

    return stubs
def _safe_terminate_wait(proc: subprocess.Popen[str], timeout: float = PROCESS_TERMINATION_TIMEOUT_SECS) -> None:
    """Best-effort termination helper that never raises during cleanup."""

    try:
        proc.terminate()
    except Exception:
        pass
    try:
        proc.wait(timeout=timeout)
    except Exception:
        pass


@pytest.fixture
def discover_harness(tmp_path: Path):
    """Provision isolated namespaces, Avahi services and binary stubs for tests.

    Two network namespaces (``leader`` and ``follower``) are created and linked via
    a veth pair. Each namespace runs its own ``dbus-daemon`` and ``avahi-daemon``
    instance so discovery traffic is fully isolated. A publisher in the leader
    namespace announces canonical metadata while a directory of stub executables
    replaces system tooling (``systemctl``, ``k3s-install``, diagnostics, etc.) so
    interactions can be observed safely.  The fixture yields a dictionary with
    namespace metadata, running process handles, stub locations and log directories
    used by the tests. All processes, namespaces and temporary files are torn down
    after the test, even when failures occur.
    """

    require_tools([
        "avahi-daemon",
        "avahi-publish",
        "avahi-browse",
        "dbus-daemon",
        "ip",
        "unshare",
    ])
    ensure_root_privileges()

    ns_info, cleanup_commands = _setup_namespace_pair()
    leader_state = tmp_path / "leader"
    follower_state = tmp_path / "follower"

    leader_bus = leader_state / "dbus" / "system_bus_socket"
    follower_bus = follower_state / "dbus" / "system_bus_socket"
    leader_runtime = leader_state / "runtime"
    follower_runtime = follower_state / "runtime"

    dbus_leader = _start_dbus(ns_info["leader_ns"], leader_bus)
    dbus_follower = _start_dbus(ns_info["follower_ns"], follower_bus)

    avahi_leader = _start_avahi(ns_info["leader_ns"], leader_bus, leader_runtime)
    avahi_follower = _start_avahi(ns_info["follower_ns"], follower_bus, follower_runtime)

    cluster = "sugar"
    environment = "dev"
    canonical_host = "sugarkube-leader.local"
    fallback_host = "sugarkube0.local"
    service_name = f"k3s-{cluster}-{environment}@sugarkube-leader (server)"
    service_type = f"_k3s-{cluster}-{environment}._tcp"

    publisher = _start_publisher(
        ns_info["leader_ns"],
        leader_bus,
        leader_runtime,
        service_name,
        service_type,
        6443,
        canonical_host,
        ns_info["leader_ip"],
    )

    # Give the Avahi publisher time to broadcast the service before discovery attempts.
    time.sleep(SERVICE_PUBLICATION_DELAY_SECS)

    bin_dir = tmp_path / "bin"
    stubs = _create_stub_bin(
        bin_dir,
        canonical_host=canonical_host,
        fallback_host=fallback_host,
        leader_ip=ns_info["leader_ip"],
    )

    base_env = os.environ.copy()
    base_env.update(
        {
            "PATH": f"{bin_dir}:{base_env.get('PATH', '')}",
            "ALLOW_NON_ROOT": "1",
            "SUGARKUBE_SKIP_SYSTEMCTL": "1",
            "SUGARKUBE_SKIP_MDNS_SELF_CHECK": "1",
            "SUGARKUBE_MDNS_ABSENCE_GATE": "0",
            "SUGARKUBE_MDNS_WIRE_PROOF": "0",
            "SUGARKUBE_DISCOVERY_DIAG_THRESHOLD": "100",
            "SUGARKUBE_DISCOVERY_FAILOPEN_TIMEOUT": "0",
            "SUGARKUBE_DISCOVERY_FAILOPEN": "1",
            "SUGARKUBE_TEST_SKIP_PUBLISH_SLEEP": "1",
            "SUGARKUBE_CLUSTER": cluster,
            "SUGARKUBE_ENV": environment,
            "SUGARKUBE_SERVERS": "1",
            "SUGARKUBE_TOKEN": "unit-test-token",
            "SUGARKUBE_K3S_INSTALL_SCRIPT": str(stubs["k3s_install"]),
            "SUGARKUBE_API_READY_CHECK_BIN": str(stubs["check_apiready"]),
            "SUGARKUBE_CONFIGURE_AVAHI_BIN": str(stubs["configure_avahi"]),
            "SUGARKUBE_MDNS_DIAG_BIN": str(stubs["mdns_diag"]),
            "SUGARKUBE_NET_DIAG_BIN": str(stubs["net_diag"]),
            "DBUS_SYSTEM_BUS_ADDRESS": f"unix:path={follower_bus}",
            "XDG_RUNTIME_DIR": str(follower_runtime),
        }
    )

    log_dir = tmp_path / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)

    harness = {
        "ns": ns_info,
        "cleanup": cleanup_commands,
        "leader": NamespaceProcesses(
            name=ns_info["leader_ns"],
            veth=ns_info["leader_veth"],
            ip=ns_info["leader_ip"],
            bus_path=leader_bus,
            runtime_dir=leader_runtime,
            dbus=dbus_leader,
            avahi=avahi_leader,
        ),
        "follower": NamespaceProcesses(
            name=ns_info["follower_ns"],
            veth=ns_info["follower_veth"],
            ip=ns_info["follower_ip"],
            bus_path=follower_bus,
            runtime_dir=follower_runtime,
            dbus=dbus_follower,
            avahi=avahi_follower,
        ),
        "publisher": publisher,
        "canonical_host": canonical_host,
        "fallback_host": fallback_host,
        "bin_dir": bin_dir,
        "base_env": base_env,
        "log_dir": log_dir,
    }

    try:
        yield harness
    finally:
        _safe_terminate_wait(publisher)
        _safe_terminate_wait(harness["leader"].avahi)
        _safe_terminate_wait(harness["leader"].dbus)
        _safe_terminate_wait(harness["follower"].avahi)
        _safe_terminate_wait(harness["follower"].dbus)
        for command in reversed(cleanup_commands):
            try:
                subprocess.run(command, capture_output=True)
            except Exception:
                pass


def _run_discover(
    harness: Dict[str, object], *, stub_mode: str, log_prefix: str, timeout: int = 120
) -> Tuple[subprocess.CompletedProcess[str], Path, Path]:
    """Execute ``k3s-discover.sh`` within the follower namespace and capture logs.

    Args:
        harness: Harness dictionary produced by :func:`discover_harness`.
        stub_mode: Behaviour for the Avahi stub (``"fail"`` or ``"real"``).
        log_prefix: Prefix applied to generated log filenames.
        timeout: Maximum seconds to wait for the subprocess to exit.

    Returns:
        Tuple containing the subprocess result, install log path and API-ready log path.
    """
    env = dict(harness["base_env"])
    env["AVAHI_STUB_MODE"] = stub_mode

    log_dir: Path = harness["log_dir"]  # type: ignore[assignment]
    install_log = log_dir / f"{log_prefix}_install.log"
    api_log = log_dir / f"{log_prefix}_apiready.log"
    if install_log.exists():
        install_log.unlink()
    if api_log.exists():
        api_log.unlink()
    env["K3S_INSTALL_LOG"] = str(install_log)
    env["CHECK_API_LOG"] = str(api_log)

    follower_ns = harness["ns"]["follower_ns"]  # type: ignore[index]
    result = subprocess.run(
        ["ip", "netns", "exec", follower_ns, "bash", str(K3S_DISCOVER)],
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    return result, install_log, api_log


def _read_log_lines(path: Path) -> List[str]:
    if not path.exists():
        return []
    return path.read_text(encoding="utf-8").splitlines()


def test_failopen_then_recovers_with_canonical_metadata(discover_harness):
    """Exercise fail-open join and subsequent recovery once mDNS metadata is available.

    First run configures the Avahi stub to fail, forcing ``k3s-discover`` to rely on
    the fallback ``K3S_URL`` metadata. A second run restores normal Avahi behaviour
    and asserts the script rejoins using the canonical host advertised over mDNS.
    """

    result_fail, install_fail, api_fail = _run_discover(
        discover_harness, stub_mode="fail", log_prefix="failopen"
    )

    assert result_fail.returncode == 0, result_fail.stderr
    assert "event=discovery_failopen_success" in result_fail.stderr
    assert "event=failopen_join" in result_fail.stderr

    fail_env_lines = _read_log_lines(install_fail)
    assert any(
        line.strip() == "K3S_URL=https://sugarkube0.local:6443" for line in fail_env_lines
    ), fail_env_lines

    fail_api_lines = _read_log_lines(api_fail)
    assert any("host=sugarkube0.local" in line for line in fail_api_lines), fail_api_lines

    result_normal, install_normal, api_normal = _run_discover(
        discover_harness, stub_mode="real", log_prefix="canonical"
    )

    assert result_normal.returncode == 0, result_normal.stderr
    assert "event=mdns_select" in result_normal.stderr
    assert "host=\"sugarkube-leader.local\"" in result_normal.stderr

    normal_env_lines = _read_log_lines(install_normal)
    assert any(
        line.strip() == "K3S_URL=https://sugarkube-leader.local:6443"
        for line in normal_env_lines
    ), normal_env_lines

    normal_api_lines = _read_log_lines(api_normal)
    assert any("host=sugarkube-leader.local" in line for line in normal_api_lines), normal_api_lines
