import os
import subprocess
import textwrap
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
    assert "avahi-publish-service advertising bootstrap" in result.stderr
    assert "phase=self-check host=" in result.stderr


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
    assert "advertisement not reported" in result.stderr

    service_file = tmp_path / "avahi" / "k3s-sugar-dev.service"
    assert not service_file.exists()


def test_bootstrap_to_server_flow_waits_for_server_phase(tmp_path):
    hostname = _hostname_short()
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log_path = tmp_path / "publish.log"
    state_path = tmp_path / "browse-count"

    publish_stub = textwrap.dedent(
        f"""\
        #!/usr/bin/env bash
        set -euo pipefail
        LOG_FILE='{log_path}'
        cmd="$*"
        printf 'START:%s\\n' "$cmd" >> "$LOG_FILE"
        trap 'printf "TERM:%s\\n" "$cmd" >> '"'"'$LOG_FILE'"'"'; exit 0' TERM INT
        while true; do sleep 1; done
        """
    ).lstrip()
    stub = bin_dir / "avahi-publish-service"
    stub.write_text(publish_stub, encoding="utf-8")
    stub.chmod(0o755)

    (bin_dir / "systemctl").write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    (bin_dir / "systemctl").chmod(0o755)
    (bin_dir / "sleep").write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    (bin_dir / "sleep").chmod(0o755)

    browse_stub = textwrap.dedent(
        f"""\
        #!/usr/bin/env bash
        set -euo pipefail
        if [ "$#" -eq 0 ]; then
            exit 0
        fi
        service="${{@: -1}}"
        if [ "$service" != "_k3s-sugar-dev._tcp" ]; then
            exit 0
        fi
        state_file='{state_path}'
        count=0
        if [ -f "$state_file" ]; then
            count=$(cat "$state_file")
        fi
        count=$((count + 1))
        printf '%s' "$count" >"$state_file"
        bootstrap="=;eth0;IPv4;k3s-sugar-dev@{hostname}.local (bootstrap);_k3s-sugar-dev._tcp;local;{hostname}.local;192.0.2.10;6443;txt=k3s=1;txt=cluster=sugar;txt=env=dev;txt=role=bootstrap;txt=leader={hostname}.local;txt=phase=bootstrap;txt=state=pending"
        server="=;eth0;IPv4;k3s-sugar-dev@{hostname}.local (server);_k3s-sugar-dev._tcp;local;{hostname}.local;192.0.2.10;6443;txt=k3s=1;txt=cluster=sugar;txt=env=dev;txt=role=server;txt=leader={hostname}.local;txt=phase=server;txt=state=ready"
        if [ "$count" -eq 1 ]; then
            printf '%s\n' "$bootstrap"
        elif [ "$count" -eq 2 ]; then
            printf '%s\n' "$bootstrap"
        else
            printf '%s\n' "$bootstrap"
            printf '%s\n' "$server"
        fi
        """
    ).lstrip()
    browse = bin_dir / "avahi-browse"
    browse.write_text(browse_stub, encoding="utf-8")
    browse.chmod(0o755)

    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{bin_dir}:{env.get('PATH', '')}",
            "SUGARKUBE_CLUSTER": "sugar",
            "SUGARKUBE_ENV": "dev",
            "ALLOW_NON_ROOT": "1",
            "SUGARKUBE_AVAHI_SERVICE_DIR": str(tmp_path / "avahi"),
            "SUGARKUBE_TOKEN": "dummy",
            "SUGARKUBE_MDNS_HOST": f"{hostname}.local",
            "SUGARKUBE_MDNS_BOOT_RETRIES": "1",
            "SUGARKUBE_MDNS_BOOT_DELAY": "0",
            "SUGARKUBE_MDNS_SERVER_RETRIES": "3",
            "SUGARKUBE_MDNS_SERVER_DELAY": "0",
        }
    )

    result = subprocess.run(
        ["bash", SCRIPT, "--test-bootstrap-to-server"],
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr

    log_lines = [line for line in log_path.read_text(encoding="utf-8").splitlines() if line]
    assert any("phase=bootstrap" in line for line in log_lines)
    assert any("phase=server" in line for line in log_lines)

    bootstrap_start = next(i for i, line in enumerate(log_lines) if "phase=bootstrap" in line)
    server_start = next(i for i, line in enumerate(log_lines) if "phase=server" in line)
    assert bootstrap_start < server_start

    count = int(state_path.read_text(encoding="utf-8"))
    assert count == 3

    assert "bootstrap advertisement confirmed" in result.stderr
    assert "server advertisement confirmed" in result.stderr
