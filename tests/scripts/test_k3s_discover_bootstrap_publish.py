import os
import subprocess
import time
from pathlib import Path

SCRIPT = str(Path(__file__).resolve().parents[2] / "scripts" / "k3s-discover.sh")


def _hostname_short() -> str:
    return subprocess.check_output(["hostname", "-s"], text=True).strip()


def test_bootstrap_publish_uses_avahi_publish(tmp_path):
    hostname = _hostname_short()
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log_path = tmp_path / "publish.log"
    runtime_dir = tmp_path / "run"
    runtime_dir.mkdir()

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
        "SUGARKUBE_MDNS_SELF_CHECK_ATTEMPTS": "1",
        "SUGARKUBE_MDNS_SELF_CHECK_DELAY": "0",
        "SUGARKUBE_RUNTIME_DIR": str(runtime_dir),
    })

    proc = subprocess.Popen(
        ["bash", SCRIPT, "--test-bootstrap-publish"],
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    pidfile = runtime_dir / "mdns-sugar-dev-bootstrap.pid"
    observed_pid = False
    for _ in range(50):
        if pidfile.exists():
            pid_text = pidfile.read_text(encoding="utf-8").strip()
            if pid_text:
                try:
                    pid_value = int(pid_text)
                    os.kill(pid_value, 0)
                except (OSError, ValueError):
                    pass
                else:
                    observed_pid = True
                    break
        if proc.poll() is not None:
            break
        time.sleep(0.1)

    stdout, stderr = proc.communicate()
    assert proc.returncode == 0, stderr
    assert observed_pid, f"bootstrap pidfile {pidfile} was not observed while publishing"
    assert not pidfile.exists()

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

    # stderr should mention that avahi-publish-service is advertising the bootstrap role
    assert "avahi-publish-service advertising bootstrap" in stderr
    assert "phase=self-check host=" in stderr


def test_bootstrap_publish_handles_trailing_dot_hostname(tmp_path):
    hostname = _hostname_short()
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log_path = tmp_path / "publish.log"
    runtime_dir = tmp_path / "run"
    runtime_dir.mkdir()

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
        "SUGARKUBE_MDNS_SELF_CHECK_ATTEMPTS": "1",
        "SUGARKUBE_MDNS_SELF_CHECK_DELAY": "0",
        "SUGARKUBE_RUNTIME_DIR": str(runtime_dir),
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

    assert "Avahi did not report bootstrap advertisement" not in result.stderr


def test_publish_binds_host_and_self_check_delays(tmp_path):
    """Mixed-case hosts with trailing dots should still self-confirm after the publish delay."""

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log_path = tmp_path / "publish.log"
    runtime_dir = tmp_path / "run"
    runtime_dir.mkdir()

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
        "SUGARKUBE_MDNS_SELF_CHECK_ATTEMPTS": "1",
        "SUGARKUBE_MDNS_SELF_CHECK_DELAY": "0",
        "SUGARKUBE_MDNS_HOST": "HostMixed.LOCAL.",
        "SUGARKUBE_RUNTIME_DIR": str(runtime_dir),
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

    assert "phase=self-check host=HostMixed.LOCAL" in result.stderr
    assert "observed=hostmixed.local" in result.stderr


def test_bootstrap_publish_fails_without_mdns(tmp_path):
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
        "SUGARKUBE_MDNS_SELF_CHECK_ATTEMPTS": "2",
        "SUGARKUBE_MDNS_SELF_CHECK_DELAY": "0",
    })

    result = subprocess.run(
        ["bash", SCRIPT, "--test-bootstrap-publish"],
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode != 0
    assert "advertisement not reported" in result.stderr

    service_file = tmp_path / "avahi" / "k3s-sugar-dev.service"
    assert not service_file.exists()
