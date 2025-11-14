"""End-to-end test covering k3s-discover fail-open recovery."""

import os
import shutil
import signal
import subprocess
import textwrap
import time
from pathlib import Path
from typing import Dict, Iterable, List, Tuple

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = REPO_ROOT / "scripts"
DISCOVER_SCRIPT = SCRIPTS_DIR / "k3s-discover.sh"

pytestmark = pytest.mark.skipif(
    os.environ.get("AVAHI_AVAILABLE") != "1",
    reason="AVAHI_AVAILABLE=1 not set (requires Avahi daemon and root permissions)",
)


def _require_tools(tools: Iterable[str]) -> None:
    missing = [tool for tool in tools if shutil.which(tool) is None]
    if missing:
        pytest.skip(f"Required tools not available: {', '.join(sorted(missing))}")


def _require_root() -> None:
    if os.geteuid() == 0:
        return
    result = subprocess.run(
        ["unshare", "-n", "true"], capture_output=True, text=True, check=False
    )
    if result.returncode != 0:
        pytest.skip("Insufficient privileges for network namespace operations")


@pytest.fixture
def netns_pair() -> Dict[str, str]:
    _require_tools(["ip", "ping"])
    _require_root()

    leader_ns = "discover-leader"
    follower_ns = "discover-follower"
    veth_leader = "veth-disc-lead"
    veth_follower = "veth-disc-follow"
    cleanup: List[List[str]] = []

    def run(cmd: List[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.run(cmd, check=True, capture_output=True, text=True)

    try:
        run(["ip", "netns", "add", leader_ns])
        cleanup.append(["ip", "netns", "del", leader_ns])
        run(["ip", "netns", "add", follower_ns])
        cleanup.append(["ip", "netns", "del", follower_ns])

        run([
            "ip",
            "link",
            "add",
            veth_leader,
            "type",
            "veth",
            "peer",
            "name",
            veth_follower,
        ])
        cleanup.append(["ip", "link", "del", veth_leader])

        run(["ip", "link", "set", veth_leader, "netns", leader_ns])
        run(["ip", "link", "set", veth_follower, "netns", follower_ns])

        run([
            "ip",
            "netns",
            "exec",
            leader_ns,
            "ip",
            "addr",
            "add",
            "192.168.203.1/24",
            "dev",
            veth_leader,
        ])
        run([
            "ip",
            "netns",
            "exec",
            follower_ns,
            "ip",
            "addr",
            "add",
            "192.168.203.2/24",
            "dev",
            veth_follower,
        ])

        for ns, iface in ((leader_ns, veth_leader), (follower_ns, veth_follower)):
            run(["ip", "netns", "exec", ns, "ip", "link", "set", "lo", "up"])
            run(["ip", "netns", "exec", ns, "ip", "link", "set", iface, "up"])

        time.sleep(0.5)

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
                "192.168.203.2",
            ],
            capture_output=True,
            text=True,
        )
        if ping.returncode != 0:
            pytest.skip("Network namespace connectivity test failed")

        yield {
            "leader_ns": leader_ns,
            "follower_ns": follower_ns,
            "leader_veth": veth_leader,
            "follower_veth": veth_follower,
        }
    finally:
        for cmd in reversed(cleanup):
            subprocess.run(cmd, capture_output=True, text=True)


class NamespaceAvahi:
    def __init__(self, namespace: str, tmp_path: Path) -> None:
        self.namespace = namespace
        self.tmp_path = tmp_path
        self.dbus_pid: int | None = None
        self.dbus_address: str | None = None
        self.avahi_proc: subprocess.Popen[str] | None = None

    def start(self) -> None:
        _require_tools(["dbus-daemon", "avahi-daemon"])
        runtime_dir = self.tmp_path / f"avahi-{self.namespace}"
        runtime_dir.mkdir(parents=True, exist_ok=True)

        result = subprocess.run(
            [
                "ip",
                "netns",
                "exec",
                self.namespace,
                "dbus-daemon",
                "--system",
                "--fork",
                "--print-address",
                "--print-pid",
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        lines = [line.strip() for line in result.stdout.splitlines() if line.strip()]
        address = next((line for line in lines if line.startswith("unix:")), None)
        pid_line = next((line for line in lines if line.isdigit()), None)
        if not address or not pid_line:
            raise RuntimeError("Failed to start dbus-daemon inside namespace")
        self.dbus_address = address
        self.dbus_pid = int(pid_line)

        self.avahi_proc = subprocess.Popen(
            [
                "ip",
                "netns",
                "exec",
                self.namespace,
                "env",
                f"DBUS_SYSTEM_BUS_ADDRESS={self.dbus_address}",
                "avahi-daemon",
                "--no-drop-root",
                "--no-rlimits",
                "--no-chroot",
                "--debug",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        time.sleep(1.0)
        if self.avahi_proc.poll() is not None:
            stderr = ""
            if self.avahi_proc.stderr:
                stderr = self.avahi_proc.stderr.read()
            raise RuntimeError(f"avahi-daemon exited early: {stderr}")

    def stop(self) -> None:
        if self.avahi_proc:
            self.avahi_proc.terminate()
            try:
                self.avahi_proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.avahi_proc.kill()
                self.avahi_proc.wait(timeout=2)
        if self.dbus_pid:
            try:
                os.kill(self.dbus_pid, signal.SIGTERM)
            except ProcessLookupError:
                pass


def _wait_for_browse(
    namespace: str,
    dbus_address: str,
    service_type: str,
    service_name: str,
    timeout: float = 8.0,
) -> None:
    _require_tools(["avahi-browse"])
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = subprocess.run(
            [
                "ip",
                "netns",
                "exec",
                namespace,
                "env",
                f"DBUS_SYSTEM_BUS_ADDRESS={dbus_address}",
                "avahi-browse",
                "-t",
                "-r",
                service_type,
                "-p",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode == 0 and service_name in result.stdout:
            return
        time.sleep(0.5)
    pytest.skip("Service not discoverable across namespaces")


def _write_executable(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
    path.chmod(0o755)


def _prepare_stub_bin(
    tmp_path: Path,
    install_log: Path,
    follower_iface: str,
) -> Tuple[Path, Dict[str, str]]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()

    real_avahi_browse = shutil.which("avahi-browse")
    real_avahi_resolve = shutil.which("avahi-resolve")
    real_getent = shutil.which("getent")
    real_ip = shutil.which("ip")

    if not all([real_avahi_browse, real_avahi_resolve, real_getent, real_ip]):
        pytest.skip("Real avahi and system utilities are required")

    _write_executable(
        bin_dir / "systemctl",
        "#!/usr/bin/env bash\nexit 0\n",
    )
    _write_executable(
        bin_dir / "sleep",
        "#!/usr/bin/env bash\nexit 0\n",
    )
    for tool in ["iptables", "ip6tables", "apt-get", "curl", "openssl", "nft"]:
        _write_executable(bin_dir / tool, "#!/usr/bin/env bash\nexit 0\n")

    _write_executable(
        bin_dir / "configure_avahi.sh",
        "#!/usr/bin/env bash\nexit 0\n",
    )
    _write_executable(
        bin_dir / "k3s-install-iptables.sh",
        "#!/usr/bin/env bash\nexit 0\n",
    )
    _write_executable(
        bin_dir / "check_apiready.sh",
        textwrap.dedent(
            """#!/usr/bin/env bash
            set -euo pipefail
            printf 'ready %s %s\n' "${SERVER_HOST:-}" "${SERVER_IP:-}" >> "${SUGARKUBE_TEST_INSTALL_LOG}"
            exit 0
            """
        ),
    )
    for script_name in ["check_time_sync.sh", "flag-parity.sh", "l4_probe.sh"]:
        _write_executable(bin_dir / script_name, "#!/usr/bin/env bash\nexit 0\n")

    _write_executable(
        bin_dir / "join-gate.sh",
        textwrap.dedent(
            """#!/usr/bin/env bash
            set -euo pipefail
            if [ "${1:-}" = "wait" ] || [ "${1:-}" = "release" ]; then
              exit 0
            fi
            exit 0
            """
        ),
    )

    _write_executable(
        bin_dir / "elect_leader.sh",
        "#!/usr/bin/env bash\nprintf 'winner=no\nkey=test-key\n'\n",
    )
    _write_executable(bin_dir / "mdns_selfcheck.sh", "#!/usr/bin/env bash\nexit 0\n")
    _write_executable(bin_dir / "mdns_diag.sh", "#!/usr/bin/env bash\nexit 0\n")
    _write_executable(bin_dir / "net_diag.sh", "#!/usr/bin/env bash\nexit 0\n")

    _write_executable(
        bin_dir / "sudo",
        "#!/usr/bin/env bash\nexec \"$@\"\n",
    )

    _write_executable(
        bin_dir / "ip",
        f"#!/usr/bin/env bash\nexec {real_ip} \"$@\"\n",
    )

    _write_executable(
        bin_dir / "avahi-browse",
        textwrap.dedent(
            f"""#!/usr/bin/env bash
            if [ \"${{SUGARKUBE_TEST_DISABLE_BROWSE:-0}}\" = \"1\" ]; then
              echo \"Simulated avahi-browse failure\" >&2
              exit 2
            fi
            exec {real_avahi_browse} \"$@\"
            """
        ),
    )

    _write_executable(
        bin_dir / "avahi-resolve",
        f"#!/usr/bin/env bash\nexec {real_avahi_resolve} \"$@\"\n",
    )

    _write_executable(
        bin_dir / "getent",
        textwrap.dedent(
            f"""#!/usr/bin/env bash
            set -euo pipefail
            if [ \"${{1:-}}\" = \"hosts\" ]; then
              case \"${{2:-}}\" in
                leader-mdns.local)
                  printf '192.168.203.1 %s\n' \"${{2}}\"
                  exit 0
                  ;;
                sugarkube0.local)
                  exit 2
                  ;;
              esac
            fi
            exec {real_getent} \"$@\"
            """
        ),
    )

    _write_executable(
        bin_dir / "install_k3s_stub.sh",
        textwrap.dedent(
            """#!/usr/bin/env bash
            set -euo pipefail
            log_path="${SUGARKUBE_TEST_INSTALL_LOG}"
            run_tag="${RUN_TAG:-unknown}"
            printf 'run=%s K3S_URL=%s SERVER_IP=%s\n' \\
              "${run_tag}" "${K3S_URL:-}" "${SERVER_IP:-}" >> "${log_path}"
            exit 0
            """
        ),
    )

    env = {
        "PATH": f"{bin_dir}:{os.environ.get('PATH', '')}",
        "SUGARKUBE_K3S_INSTALL_SCRIPT": str(bin_dir / "install_k3s_stub.sh"),
        "SUGARKUBE_TEST_INSTALL_LOG": str(install_log),
        "SUGARKUBE_CONFIGURE_AVAHI_BIN": str(bin_dir / "configure_avahi.sh"),
        "SUGARKUBE_API_READY_CHECK_BIN": str(bin_dir / "check_apiready.sh"),
        "SUGARKUBE_TIME_SYNC_BIN": str(bin_dir / "check_time_sync.sh"),
        "SUGARKUBE_SERVER_FLAG_PARITY_BIN": str(bin_dir / "flag-parity.sh"),
        "SUGARKUBE_L4_PROBE_BIN": str(bin_dir / "l4_probe.sh"),
        "SUGARKUBE_JOIN_GATE_BIN": str(bin_dir / "join-gate.sh"),
        "SUGARKUBE_MDNS_DIAG_BIN": str(bin_dir / "mdns_diag.sh"),
        "SUGARKUBE_NET_DIAG_BIN": str(bin_dir / "net_diag.sh"),
        "SUGARKUBE_ELECT_LEADER_BIN": str(bin_dir / "elect_leader.sh"),
        "SUGARKUBE_MDNS_SELF_CHECK_BIN": str(bin_dir / "mdns_selfcheck.sh"),
        "SUGARKUBE_SUDO_BIN": str(bin_dir / "sudo"),
        "SUGARKUBE_MDNS_INTERFACE": follower_iface,
    }
    return bin_dir, env


def _read_install_records(log_path: Path) -> Dict[str, Dict[str, str]]:
    if not log_path.exists():
        return {}
    records: Dict[str, Dict[str, str]] = {}
    for line in log_path.read_text(encoding="utf-8").splitlines():
        parts = line.strip().split()
        if not parts:
            continue
        entry: Dict[str, str] = {}
        for part in parts:
            if "=" in part:
                key, value = part.split("=", 1)
                entry[key] = value
        if "run" in entry:
            records[entry["run"]] = entry
    return records


def _run_discover(
    namespace: str,
    env: Dict[str, str],
    timeout: float = 60.0,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["ip", "netns", "exec", namespace, "bash", str(DISCOVER_SCRIPT)],
        capture_output=True,
        text=True,
        timeout=timeout,
        env=env,
    )


def test_discovery_failopen_then_canonical(tmp_path: Path, netns_pair: Dict[str, str]) -> None:
    _require_tools(["avahi-publish"])

    leader_avahi = NamespaceAvahi(netns_pair["leader_ns"], tmp_path)
    follower_avahi = NamespaceAvahi(netns_pair["follower_ns"], tmp_path)
    leader_avahi.start()
    follower_avahi.start()

    service_name = "k3s-discover"
    service_type = "_k3s-sugar-dev._tcp"
    publish_proc = subprocess.Popen(
        [
            "ip",
            "netns",
            "exec",
            netns_pair["leader_ns"],
            "env",
            f"DBUS_SYSTEM_BUS_ADDRESS={leader_avahi.dbus_address}",
            "avahi-publish",
            "-s",
            "-H",
            "leader-mdns.local",
            service_name,
            service_type,
            "6443",
            "cluster=sugar",
            "env=dev",
            "role=server",
            "phase=steady",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    try:
        _wait_for_browse(
            netns_pair["follower_ns"],
            follower_avahi.dbus_address or "",
            service_type,
            service_name,
        )

        install_log = tmp_path / "install.log"
        if install_log.exists():
            install_log.unlink()
        bin_dir, stub_env = _prepare_stub_bin(
            tmp_path, install_log, netns_pair["follower_veth"]
        )

        base_env = {
            **os.environ,
            **stub_env,
            "PATH": f"{bin_dir}:{os.environ.get('PATH', '')}",
            "DBUS_SYSTEM_BUS_ADDRESS": follower_avahi.dbus_address or "",
            "SUGARKUBE_CLUSTER": "sugar",
            "SUGARKUBE_ENV": "dev",
            "SUGARKUBE_SERVERS": "3",
            "SUGARKUBE_TOKEN": "unit-test-token",
            "SUGARKUBE_SKIP_SYSTEMCTL": "1",
            "SUGARKUBE_DISABLE_JOIN_GATE": "1",
            "SUGARKUBE_MDNS_ABSENCE_GATE": "0",
            "SUGARKUBE_SKIP_MDNS_SELF_CHECK": "1",
            "SUGARKUBE_TEST_FAST_JOIN": "1",
            "DISCOVERY_WAIT_SECS": "0",
            "FOLLOWER_REELECT_SECS": "0",
            "SUGARKUBE_API_READY_TIMEOUT": "2",
            "SUGARKUBE_API_READY_INTERVAL": "0.1",
            "ALLOW_NON_ROOT": "1",
        }

        env_failopen = {
            **base_env,
            "RUN_TAG": "failopen",
            "SUGARKUBE_TEST_DISABLE_BROWSE": "1",
            "SUGARKUBE_DISCOVERY_FAILOPEN_TIMEOUT": "0",
            "SUGARKUBE_DISCOVERY_FAILOPEN": "1",
        }
        result_fail = _run_discover(netns_pair["follower_ns"], env_failopen, timeout=40.0)
        assert result_fail.returncode == 0, result_fail.stderr
        assert "event=discovery_failopen_tracking_started" in result_fail.stderr
        assert "event=discovery_failopen_success" in result_fail.stderr

        records = _read_install_records(install_log)
        fail_line = records.get("failopen")
        assert fail_line is not None, "Fail-open install record not captured"
        assert fail_line.get("K3S_URL") == "https://sugarkube0.local:6443"

        env_canonical = {
            **base_env,
            "RUN_TAG": "canonical",
            "SUGARKUBE_TEST_DISABLE_BROWSE": "0",
            "SUGARKUBE_DISCOVERY_FAILOPEN_TIMEOUT": "15",
            "SUGARKUBE_DISCOVERY_FAILOPEN": "1",
        }
        result_canonical = _run_discover(
            netns_pair["follower_ns"], env_canonical, timeout=40.0
        )
        assert result_canonical.returncode == 0, result_canonical.stderr
        assert "event=mdns_select" in result_canonical.stderr
        assert "host=\"leader-mdns.local\"" in result_canonical.stderr
        assert "event=discovery_failopen_success" not in result_canonical.stderr

        records = _read_install_records(install_log)
        canonical_line = records.get("canonical")
        assert canonical_line is not None, "Canonical join install record missing"
        assert canonical_line.get("K3S_URL") == "https://leader-mdns.local:6443"
    finally:
        publish_proc.terminate()
        try:
            publish_proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            publish_proc.kill()
            publish_proc.wait(timeout=2)
        leader_avahi.stop()
        follower_avahi.stop()
