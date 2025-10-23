import os
import subprocess
from pathlib import Path

SCRIPT = str(Path(__file__).resolve().parents[2] / "scripts" / "k3s-discover.sh")


def _hostname_short() -> str:
    return subprocess.check_output(["hostname", "-s"], text=True).strip()


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
            f"=;eth0;IPv4;k3s-sugar-dev@{hostname}.local (bootstrap);"
            f"_k3s-sugar-dev._tcp;local;{hostname}.local;"
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
        "SUGARKUBE_MDNS_SERVER_RETRIES": "1",
        "SUGARKUBE_MDNS_SERVER_DELAY": "0",
    })

    result = subprocess.run(
        ["bash", SCRIPT, "--test-bootstrap-publish"],
        env=env,
        text=True,
        capture_output=True,
        check=True,
    )

    # Ensure the helper logged its launch and termination
    log_contents = log_path.read_text(encoding="utf-8")
    assert "START:" in log_contents
    assert "TERM" in log_contents

    assert "-H" in log_contents
    assert f"-H {hostname}.local" in log_contents
    assert "_k3s-sugar-dev._tcp" in log_contents
    assert "cluster=sugar" in log_contents
    assert "env=dev" in log_contents
    assert f"leader={hostname}.local" in log_contents
    assert "role=bootstrap" in log_contents
    assert "phase=bootstrap" in log_contents

    # Service file should have been cleaned up by the EXIT trap
    service_file = tmp_path / "avahi" / "k3s-sugar-dev.service"
    assert not service_file.exists()

    # stderr should mention that avahi-publish-service is advertising the bootstrap role
    assert "avahi-publish-service advertising bootstrap" in result.stderr
    assert "phase=self-check target-phase=bootstrap host=" in result.stderr


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
        "SUGARKUBE_MDNS_SERVER_RETRIES": "1",
        "SUGARKUBE_MDNS_SERVER_DELAY": "0",
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
        "SUGARKUBE_MDNS_SERVER_RETRIES": "1",
        "SUGARKUBE_MDNS_SERVER_DELAY": "0",
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

    assert "phase=self-check target-phase=bootstrap host=HostMixed.LOCAL" in result.stderr
    assert "observed=hostmixed.local" in result.stderr


def test_server_publish_confirms_and_retires_bootstrap(tmp_path):
    hostname = _hostname_short()
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log_path = tmp_path / "publish.log"
    count_path = tmp_path / "browse-count"

    publisher_stub = bin_dir / "avahi-publish-service"
    publisher_stub.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        "phase=unknown\n"
        "for arg in \"$@\"; do\n"
        "  case \"$arg\" in\n"
        "    *role=bootstrap*) phase=bootstrap ;;\n"
        "    *role=server*) phase=server ;;\n"
        "  esac\n"
        "done\n"
        f"echo \"START:$phase:$*\" >> '{log_path}'\n"
        "trap 'echo TERM:$phase >> \"" + str(log_path) + "\"; exit 0' TERM INT\n"
        "while true; do sleep 1; done\n",
        encoding="utf-8",
    )
    publisher_stub.chmod(0o755)

    systemctl_stub = bin_dir / "systemctl"
    systemctl_stub.write_text(
        "#!/usr/bin/env bash\n"
        "exit 0\n",
        encoding="utf-8",
    )
    systemctl_stub.chmod(0o755)

    browse_stub = bin_dir / "avahi-browse"
    browse_stub.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        f"count_file='{count_path}'\n"
        "service=\"\"\n"
        "for arg in \"$@\"; do\n"
        "  service=\"$arg\"\n"
        "done\n"
        "if [[ \"$service\" != '_k3s-sugar-dev._tcp' ]]; then\n"
        "  exit 0\n"
        "fi\n"
        "count=0\n"
        "if [ -f \"$count_file\" ]; then\n"
        "  count=$(cat \"$count_file\")\n"
        "fi\n"
        "count=$((count + 1))\n"
        "echo \"$count\" > \"$count_file\"\n"
        "if [ \"$count\" -le 2 ]; then\n"
        f"  printf '%s\\n' \"=;eth0;IPv4;k3s-sugar-dev@{hostname}.local (bootstrap);"
        f"_k3s-sugar-dev._tcp;local;{hostname}.local;192.0.2.10;6443;"
        "txt=k3s=1;txt=cluster=sugar;txt=env=dev;txt=role=bootstrap;"
        f"txt=leader={hostname}.local;txt=phase=bootstrap;txt=state=pending\"\n"
        "elif [ \"$count\" -lt 4 ]; then\n"
        "  exit 0\n"
        "else\n"
        "  printf '%s\\n' \"=;eth0;IPv4;k3s-sugar-dev@{hostname}.local (server);"
        f"_k3s-sugar-dev._tcp;local;{hostname}.local;192.0.2.10;6443;"
        "txt=k3s=1;txt=cluster=sugar;txt=env=dev;txt=role=server;"
        f"txt=leader={hostname}.local;txt=phase=server;txt=state=ready\"\n"
        "fi\n",
        encoding="utf-8",
    )
    browse_stub.chmod(0o755)

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

    result = subprocess.run(
        ["bash", SCRIPT, "--test-server-publish"],
        env=env,
        text=True,
        capture_output=True,
        check=True,
    )

    log_lines = [line for line in log_path.read_text(encoding="utf-8").splitlines() if line]
    assert any(line.startswith("START:bootstrap") for line in log_lines)
    assert any(line.startswith("START:server") for line in log_lines)
    assert any(line == "TERM:bootstrap" for line in log_lines)
    assert any(line == "TERM:server" for line in log_lines)

    bootstrap_term_index = log_lines.index("TERM:bootstrap")
    server_start_index = next(
        i for i, line in enumerate(log_lines) if line.startswith("START:server")
    )
    assert bootstrap_term_index > server_start_index

    assert "phase=self-check target-phase=server host=" in result.stderr
    assert "attempt=3/5" in result.stderr


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
        "SUGARKUBE_MDNS_BOOT_RETRIES": "2",
        "SUGARKUBE_MDNS_BOOT_DELAY": "0",
        "SUGARKUBE_MDNS_SERVER_RETRIES": "1",
        "SUGARKUBE_MDNS_SERVER_DELAY": "0",
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
