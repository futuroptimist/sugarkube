import os
import subprocess
import time
from pathlib import Path

SCRIPT = str(Path(__file__).resolve().parents[2] / "scripts" / "k3s-discover.sh")
CLEANUP = Path(__file__).resolve().parents[2] / "scripts" / "cleanup_mdns_publishers.sh"


def _pid_path(cluster: str, env: str, phase: str) -> Path:
    return Path(f"/run/sugarkube/mdns-{cluster}-{env}-{phase}.pid")


def _wait_for_live_pid(path: Path, timeout: float = 10.0) -> int:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if path.exists():
            pid_text = path.read_text(encoding="utf-8").strip()
            if pid_text:
                try:
                    pid = int(pid_text)
                except ValueError:
                    time.sleep(0.1)
                    continue
                try:
                    os.kill(pid, 0)
                except ProcessLookupError:
                    time.sleep(0.1)
                    continue
                else:
                    return pid
        time.sleep(0.1)
    raise AssertionError(f"Timed out waiting for live PID file {path}")


def _hostname_short() -> str:
    return subprocess.check_output(["hostname", "-s"], text=True).strip()


def _wait_for_pid_exit(pid: int, timeout: float = 10.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return
        time.sleep(0.1)
    raise AssertionError(f"Process {pid} still running after {timeout}s")


def _wait_for_pattern_absence(pattern: str, timeout: float = 10.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        result = subprocess.run(
            ["pgrep", "-af", pattern],
            text=True,
            capture_output=True,
        )
        if result.returncode != 0:
            return
        time.sleep(0.1)
    raise AssertionError(f"Processes matching '{pattern}' still running after {timeout}s")


def test_bootstrap_publish_uses_avahi_publish(tmp_path):
    hostname = _hostname_short()
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log_path = tmp_path / "publish.log"

    stub = bin_dir / "avahi-publish-service"
    stub.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        f"echo \"START:$*\" >> '{log_path}'\n"
        "trap 'echo TERM >> \"" + str(log_path) + "\"; exit 0' TERM INT\n"
        "while true; do sleep 1; done\n",
        encoding="utf-8",
    )
    stub.chmod(0o755)

    browse = bin_dir / "avahi-browse"
    browse.write_text(
        (
            "#!/usr/bin/env bash\n"
            "set -euo pipefail\n"
            "cat <<'EOF'\n"
            f"=;eth0;IPv4;k3s-sugar-dev@{hostname}.local (bootstrap);_k3s-sugar-dev._tcp;local;{hostname}.local;"
            "192.0.2.10;6443;txt=k3s=1;txt=cluster=sugar;txt=env=dev;txt=role=bootstrap;"
            f"txt=leader={hostname}.local;txt=phase=bootstrap;txt=state=pending\n"
            "EOF\n"
        ),
        encoding="utf-8",
    )
    browse.chmod(0o755)

    env = os.environ.copy()
    env.update({
        "PATH": f"{bin_dir}:{env.get('PATH', '')}",
        "SUGARKUBE_CLUSTER": "sugar",
        "SUGARKUBE_ENV": "dev",
        "ALLOW_NON_ROOT": "1",
        "SUGARKUBE_AVAHI_SERVICE_DIR": str(tmp_path / "avahi"),
        "SUGARKUBE_TOKEN": "dummy",  # bypass token requirement
        "SUGARKUBE_MDNS_BOOT_RETRIES": "1",
        "SUGARKUBE_MDNS_BOOT_DELAY": "0",
    })

    proc = subprocess.Popen(
        ["bash", SCRIPT, "--test-bootstrap-publish"],
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    bootstrap_pid_path = _pid_path("sugar", "dev", "bootstrap")
    stdout = ""
    stderr = ""
    cleanup_env = env.copy()
    try:
        _wait_for_live_pid(bootstrap_pid_path)
        stdout, stderr = proc.communicate(timeout=20)
    finally:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=5)
        subprocess.run(["bash", str(CLEANUP)], env=cleanup_env, check=False, text=True)

    assert proc.returncode == 0

    # Ensure the helper logged its launch and termination
    log_contents = log_path.read_text(encoding="utf-8")
    assert "START:" in log_contents
    assert "TERM" in log_contents

    assert "-H" in log_contents
    assert f"-H {hostname}.local" in log_contents
    assert f"_k3s-sugar-dev._tcp" in log_contents
    assert f"cluster=sugar" in log_contents
    assert f"env=dev" in log_contents
    assert f"leader={hostname}.local" in log_contents
    assert "role=bootstrap" in log_contents
    assert "phase=bootstrap" in log_contents

    # Service file should have been cleaned up by the EXIT trap
    service_file = tmp_path / "avahi" / "k3s-sugar-dev.service"
    assert not service_file.exists()

    assert not bootstrap_pid_path.exists()

    # stderr should mention that avahi-publish-service is advertising the bootstrap role
    assert "avahi-publish-service advertising bootstrap" in stderr
    expected = (
        f"phase=self-check host={hostname}.local observed={hostname}.local; "
        "bootstrap advertisement confirmed."
    )
    assert expected in stderr


def test_bootstrap_publish_handles_trailing_dot_hostname(tmp_path):
    hostname = _hostname_short()
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log_path = tmp_path / "publish.log"

    stub = bin_dir / "avahi-publish-service"
    stub.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        f"echo \"START:$*\" >> '{log_path}'\n"
        "trap 'echo TERM >> \"" + str(log_path) + "\"; exit 0' TERM INT\n"
        "while true; do sleep 1; done\n",
        encoding="utf-8",
    )
    stub.chmod(0o755)

    browse = bin_dir / "avahi-browse"
    browse.write_text(
        (
            "#!/usr/bin/env bash\n"
            "set -euo pipefail\n"
            "cat <<'EOF'\n"
            f"=;eth0;IPv4;k3s-sugar-dev@{hostname}.local (bootstrap);_k3s-sugar-dev._tcp;local.;"
            f"{hostname}.local.;192.0.2.10;6443;"
            "txt=k3s=1;txt=cluster=sugar;txt=env=dev;txt=role=bootstrap;"
            f"txt=leader={hostname}.local.;txt=phase=bootstrap;txt=state=pending\n"
            "EOF\n"
        ),
        encoding="utf-8",
    )
    browse.chmod(0o755)

    env = os.environ.copy()
    env.update({
        "PATH": f"{bin_dir}:{env.get('PATH', '')}",
        "SUGARKUBE_CLUSTER": "sugar",
        "SUGARKUBE_ENV": "dev",
        "ALLOW_NON_ROOT": "1",
        "SUGARKUBE_AVAHI_SERVICE_DIR": str(tmp_path / "avahi"),
        "SUGARKUBE_TOKEN": "dummy",
        "SUGARKUBE_MDNS_BOOT_RETRIES": "1",
        "SUGARKUBE_MDNS_BOOT_DELAY": "0",
    })

    result = subprocess.run(
        ["bash", SCRIPT, "--test-bootstrap-publish"],
        env=env,
        text=True,
        capture_output=True,
        check=True,
    )

    log_contents = log_path.read_text(encoding="utf-8")
    assert "START:" in log_contents
    assert "TERM" in log_contents
    assert f"leader={hostname}.local" in log_contents

    expected = (
        f"phase=self-check host={hostname}.local observed={hostname}.local; "
        "bootstrap advertisement confirmed."
    )
    assert expected in result.stderr


def test_publish_binds_host_and_self_check_delays(tmp_path):
    """Mixed-case hosts with trailing dots should still self-confirm after the publish delay."""

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log_path = tmp_path / "publish.log"

    stub = bin_dir / "avahi-publish-service"
    stub.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        f"echo \"START:$*\" >> '{log_path}'\n"
        "trap 'echo TERM >> \"" + str(log_path) + "\"; exit 0' TERM INT\n"
        "while true; do sleep 1; done\n",
        encoding="utf-8",
    )
    stub.chmod(0o755)

    browse = bin_dir / "avahi-browse"
    browse.write_text(
        (
            "#!/usr/bin/env bash\n"
            "set -euo pipefail\n"
            "cat <<'EOF'\n"
            "=;eth0;IPv4;k3s-sugar-dev@HostMixed.LOCAL (bootstrap);_k3s-sugar-dev._tcp;local.;"
            "hostmixed.local.;192.0.2.10;6443;"
            "txt=k3s=1;txt=cluster=sugar;txt=env=dev;txt=role=bootstrap;"
            "txt=leader=hostmixed.local.;txt=phase=bootstrap;txt=state=pending\n"
            "EOF\n"
        ),
        encoding="utf-8",
    )
    browse.chmod(0o755)

    env = os.environ.copy()
    env.update({
        "PATH": f"{bin_dir}:{env.get('PATH', '')}",
        "SUGARKUBE_CLUSTER": "sugar",
        "SUGARKUBE_ENV": "dev",
        "ALLOW_NON_ROOT": "1",
        "SUGARKUBE_AVAHI_SERVICE_DIR": str(tmp_path / "avahi"),
        "SUGARKUBE_TOKEN": "dummy",
        "SUGARKUBE_MDNS_BOOT_RETRIES": "1",
        "SUGARKUBE_MDNS_BOOT_DELAY": "0",
        "SUGARKUBE_MDNS_HOST": "HostMixed.LOCAL.",
    })

    result = subprocess.run(
        ["bash", SCRIPT, "--test-bootstrap-publish"],
        env=env,
        text=True,
        capture_output=True,
        check=True,
    )

    log_contents = log_path.read_text(encoding="utf-8")
    assert "START:" in log_contents
    assert "TERM" in log_contents
    assert "-H HostMixed.LOCAL" in log_contents
    assert "leader=HostMixed.LOCAL" in log_contents

    expected = (
        "phase=self-check host=HostMixed.LOCAL observed=hostmixed.local; "
        "bootstrap advertisement confirmed."
    )
    assert expected in result.stderr


def test_bootstrap_publish_waits_for_server_advert_before_retiring_bootstrap(tmp_path):
    hostname = _hostname_short()
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log_path = tmp_path / "publish.log"
    flag_path = tmp_path / "server.ready"
    count_path = tmp_path / "browse.count"

    stub = bin_dir / "avahi-publish-service"
    stub.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        f"echo \"START:$*\" >> '{log_path}'\n"
        f"if [[ \"$*\" == *\"phase=server\"* ]]; then touch '{flag_path}'; fi\n"
        "trap 'echo TERM >> \"" + str(log_path) + "\"; exit 0' TERM INT\n"
        "while true; do sleep 1; done\n",
        encoding="utf-8",
    )
    stub.chmod(0o755)

    browse = bin_dir / "avahi-browse"
    browse.write_text(
        (
            "#!/usr/bin/env bash\n"
            "set -euo pipefail\n"
            f"COUNT_FILE='{count_path}'\n"
            f"FLAG='{flag_path}'\n"
            "service_type=\"${@: -1}\"\n"
            "if [ \"${service_type}\" != '_k3s-sugar-dev._tcp' ]; then\n"
            "  exit 0\n"
            "fi\n"
            "count=0\n"
            "if [ -f \"${COUNT_FILE}\" ]; then\n"
            "  count=$(cat \"${COUNT_FILE}\")\n"
            "fi\n"
            "count=$((count + 1))\n"
            "echo \"${count}\" > \"${COUNT_FILE}\"\n"
            "cat <<'EOF'\n"
            f"=;eth0;IPv4;k3s-sugar-dev@{hostname}.local (bootstrap);_k3s-sugar-dev._tcp;local;{hostname}.local;192.0.2.10;6443;"
            f"txt=k3s=1;txt=cluster=sugar;txt=env=dev;txt=role=bootstrap;txt=leader={hostname}.local;txt=phase=bootstrap;txt=state=pending\n"
            "EOF\n"
            "if [ -f \"${FLAG}\" ] && [ \"${count}\" -ge 2 ]; then\n"
            "  cat <<'EOF'\n"
            f"=;eth0;IPv4;k3s-sugar-dev@{hostname}.local (server);_k3s-sugar-dev._tcp;local;{hostname}.local;192.0.2.10;6443;"
            f"txt=k3s=1;txt=cluster=sugar;txt=env=dev;txt=role=server;txt=leader={hostname}.local;txt=phase=server\n"
            "EOF\n"
            "fi\n"
        ),
        encoding="utf-8",
    )
    browse.chmod(0o755)

    systemctl_stub = bin_dir / "systemctl"
    systemctl_stub.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        "exit 0\n",
        encoding="utf-8",
    )
    systemctl_stub.chmod(0o755)

    env = os.environ.copy()
    env.update({
        "PATH": f"{bin_dir}:{env.get('PATH', '')}",
        "SUGARKUBE_CLUSTER": "sugar",
        "SUGARKUBE_ENV": "dev",
        "ALLOW_NON_ROOT": "1",
        "SUGARKUBE_AVAHI_SERVICE_DIR": str(tmp_path / "avahi"),
        "SUGARKUBE_TOKEN": "dummy",
        "SUGARKUBE_MDNS_BOOT_RETRIES": "1",
        "SUGARKUBE_MDNS_BOOT_DELAY": "0",
        "SUGARKUBE_MDNS_SERVER_RETRIES": "5",
        "SUGARKUBE_MDNS_SERVER_DELAY": "0",
    })

    proc = subprocess.Popen(
        ["bash", SCRIPT, "--test-bootstrap-server-flow"],
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    bootstrap_pid_path = _pid_path("sugar", "dev", "bootstrap")
    server_pid_path = _pid_path("sugar", "dev", "server")
    cleanup_env = env.copy()
    stdout = ""
    stderr = ""
    cleanup_result = None
    server_pid = None
    try:
        _wait_for_live_pid(bootstrap_pid_path)
        _wait_for_live_pid(server_pid_path)
        stdout, stderr = proc.communicate(timeout=40)
        assert proc.returncode == 0

        assert not bootstrap_pid_path.exists()
        assert server_pid_path.exists()
        server_pid_text = server_pid_path.read_text(encoding="utf-8").strip()
        assert server_pid_text
        server_pid = int(server_pid_text)
        os.kill(server_pid, 0)

        assert flag_path.exists()

        bootstrap_msg = (
            f"phase=self-check host={hostname}.local observed={hostname}.local; "
            "bootstrap advertisement confirmed."
        )
        server_msg = (
            f"phase=self-check host={hostname}.local observed={hostname}.local; "
            "server advertisement confirmed."
        )
        assert bootstrap_msg in stderr
        assert server_msg in stderr
        assert stderr.find(bootstrap_msg) < stderr.find(server_msg)

        browse_calls = int(count_path.read_text(encoding="utf-8").strip())
        assert browse_calls >= 2

        cleanup_result = subprocess.run(
            ["bash", str(CLEANUP)],
            env=cleanup_env,
            text=True,
            capture_output=True,
            check=False,
        )
    finally:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=5)
        subprocess.run(["bash", str(CLEANUP)], env=cleanup_env, check=False, text=True)

    assert cleanup_result is not None
    assert cleanup_result.returncode == 0
    assert not server_pid_path.exists()

    time.sleep(0.5)

    if server_pid is not None:
        try:
            _wait_for_pid_exit(server_pid)
        except AssertionError:
            _wait_for_pattern_absence("avahi-publish-service.*_k3s-sugar-dev")

    _wait_for_pattern_absence("avahi-publish-service.*_k3s-sugar-dev")
    log_contents = log_path.read_text(encoding="utf-8")
    assert log_contents.count("START:") >= 2
    assert log_contents.count("TERM") >= 1
    assert "phase=bootstrap" in log_contents
    assert "phase=server" in log_contents

def test_bootstrap_publish_fails_without_mdns(tmp_path):
    hostname = _hostname_short()
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log_path = tmp_path / "publish.log"

    stub = bin_dir / "avahi-publish-service"
    stub.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        f"echo \"START:$*\" >> '{log_path}'\n"
        "trap 'echo TERM >> \"" + str(log_path) + "\"; exit 0' TERM INT\n"
        "while true; do sleep 1; done\n",
        encoding="utf-8",
    )
    stub.chmod(0o755)

    browse = bin_dir / "avahi-browse"
    browse.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        "# Emit nothing to simulate missing adverts\n",
        encoding="utf-8",
    )
    browse.chmod(0o755)

    env = os.environ.copy()
    env.update({
        "PATH": f"{bin_dir}:{env.get('PATH', '')}",
        "SUGARKUBE_CLUSTER": "sugar",
        "SUGARKUBE_ENV": "dev",
        "ALLOW_NON_ROOT": "1",
        "SUGARKUBE_AVAHI_SERVICE_DIR": str(tmp_path / "avahi"),
        "SUGARKUBE_TOKEN": "dummy",
        "SUGARKUBE_MDNS_BOOT_RETRIES": "2",
        "SUGARKUBE_MDNS_BOOT_DELAY": "0",
    })

    result = subprocess.run(
        ["bash", SCRIPT, "--test-bootstrap-publish"],
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode != 0
    expected_failure = (
        f"Unable to confirm bootstrap advertisement for {hostname}.local; "
        "aborting to avoid split brain"
    )
    assert expected_failure in result.stderr

    service_file = tmp_path / "avahi" / "k3s-sugar-dev.service"
    assert not service_file.exists()
