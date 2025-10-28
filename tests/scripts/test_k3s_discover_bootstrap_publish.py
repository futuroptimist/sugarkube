import os
import subprocess
import time
from pathlib import Path

SCRIPT = str(Path(__file__).resolve().parents[2] / "scripts" / "k3s-discover.sh")


def _hostname_short() -> str:
    return subprocess.check_output(["hostname", "-s"], text=True).strip()


def _write_avahi_publish_address_stub(bin_dir: Path, log_path: Path) -> None:
    stub = bin_dir / "avahi-publish-address"
    stub.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        f"echo \"ADDR:$*\" >> '{log_path}'\n"
        "trap 'exit 0' TERM INT\n"
        "while true; do sleep 1; done\n",
        encoding="utf-8",
    )
    stub.chmod(0o755)


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
        "RUN_DIR=\"${SUGARKUBE_RUNTIME_DIR:-/run/sugarkube}\"\n"
        "phase_label=bootstrap\n"
        "if [[ \"$*\" == *\"phase=server\"* ]]; then\n"
        "  phase_label=server\n"
        "fi\n"
        "pid_file=\"${RUN_DIR}/mdns-sugar-dev-${phase_label}.pid\"\n"
        "for _ in $(seq 1 50); do\n"
        "  if [ -f \"${pid_file}\" ] && grep -q \"$$\" \"${pid_file}\"; then\n"
        f"    echo \"PIDFILE_OK:${{phase_label}}\" >> '{log_path}'\n"
        "    break\n"
        "  fi\n"
        "  sleep 0.05\n"
        "done\n"
        "trap 'echo TERM >> \"" + str(log_path) + "\"; exit 0' TERM INT\n"
        "while true; do sleep 1; done\n",
        encoding="utf-8",
    )
    stub.chmod(0o755)

    _write_avahi_publish_address_stub(bin_dir, log_path)

    browse = bin_dir / "avahi-browse"
    browse.write_text(
        (
            "#!/usr/bin/env bash\n"
            "set -euo pipefail\n"
            "cat <<'EOF'\n"
            f"=;eth0;IPv4;k3s-sugar-dev@{hostname}.local (bootstrap);_k3s-sugar-dev._tcp;local;{hostname}.local;"
            "192.0.2.55;6443;txt=k3s=1;txt=cluster=sugar;txt=env=dev;txt=role=bootstrap;"
            f"txt=leader={hostname}.local;txt=phase=bootstrap;txt=state=pending\n"
            "EOF\n"
        ),
        encoding="utf-8",
    )
    browse.chmod(0o755)

    systemctl = bin_dir / "systemctl"
    systemctl.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        f"echo \"SYSTEMCTL:$*\" >> '{log_path}'\n",
        encoding="utf-8",
    )
    systemctl.chmod(0o755)

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
        "SUGARKUBE_RUNTIME_DIR": str(tmp_path / "run"),
        "SUGARKUBE_SKIP_SYSTEMCTL": "1",
        "SUGARKUBE_MDNS_DBUS": "0",
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
    assert "-s -H" in log_contents
    assert "PIDFILE_OK:bootstrap" in log_contents

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
    expected = (
        f"phase=self-check host={hostname}.local observed={hostname}.local; "
        "bootstrap advertisement confirmed."
    )
    assert expected in result.stderr


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
        "RUN_DIR=\"${SUGARKUBE_RUNTIME_DIR:-/run/sugarkube}\"\n"
        "phase_label=bootstrap\n"
        "if [[ \"$*\" == *\"phase=server\"* ]]; then\n"
        "  phase_label=server\n"
        "fi\n"
        "pid_file=\"${RUN_DIR}/mdns-sugar-dev-${phase_label}.pid\"\n"
        "for _ in $(seq 1 50); do\n"
        "  if [ -f \"${pid_file}\" ] && grep -q \"$$\" \"${pid_file}\"; then\n"
        f"    echo \"PIDFILE_OK:${{phase_label}}\" >> '{log_path}'\n"
        "    break\n"
        "  fi\n"
        "  sleep 0.05\n"
        "done\n"
        "trap 'echo TERM >> \"" + str(log_path) + "\"; exit 0' TERM INT\n"
        "while true; do sleep 1; done\n",
        encoding="utf-8",
    )
    stub.chmod(0o755)

    _write_avahi_publish_address_stub(bin_dir, log_path)

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
        "SUGARKUBE_RUNTIME_DIR": str(tmp_path / "run"),
        "SUGARKUBE_SKIP_SYSTEMCTL": "1",
        "SUGARKUBE_MDNS_DBUS": "0",
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
    assert "-s -H" in log_contents
    assert f"leader={hostname}.local" in log_contents
    assert "PIDFILE_OK:bootstrap" in log_contents

    expected = (
        f"phase=self-check host={hostname}.local observed={hostname}.local; "
        "bootstrap advertisement confirmed."
    )
    assert expected in result.stderr


def test_bootstrap_publish_warns_on_address_mismatch(tmp_path):
    hostname = _hostname_short()
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log_path = tmp_path / "publish.log"

    stub = bin_dir / "avahi-publish-service"
    stub.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        f"echo \"START:$*\" >> '{log_path}'\n"
        "RUN_DIR=\"${SUGARKUBE_RUNTIME_DIR:-/run/sugarkube}\"\n"
        "pid_file=\"${RUN_DIR}/mdns-sugar-dev-bootstrap.pid\"\n"
        "for _ in $(seq 1 50); do\n"
        "  if [ -f \"${pid_file}\" ] && grep -q \"$$\" \"${pid_file}\"; then\n"
        f"    echo \"PIDFILE_OK:bootstrap\" >> '{log_path}'\n"
        "    break\n"
        "  fi\n"
        "  sleep 0.05\n"
        "done\n"
        "trap 'echo TERM >> \"" + str(log_path) + "\"; exit 0' TERM INT\n"
        "while true; do sleep 1; done\n",
        encoding="utf-8",
    )
    stub.chmod(0o755)

    _write_avahi_publish_address_stub(bin_dir, log_path)

    browse = bin_dir / "avahi-browse"
    browse.write_text(
        (
            "#!/usr/bin/env bash\n"
            "set -euo pipefail\n"
            "cat <<'EOF'\n"
            f"=;eth0;IPv4;k3s-sugar-dev@{hostname}.local (bootstrap);_k3s-sugar-dev._tcp;local;{hostname}.local;"
            "198.51.100.10;6443;txt=k3s=1;txt=cluster=sugar;txt=env=dev;txt=role=bootstrap;"
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
        "SUGARKUBE_TOKEN": "dummy",
        "SUGARKUBE_MDNS_BOOT_RETRIES": "1",
        "SUGARKUBE_MDNS_BOOT_DELAY": "0",
        "SUGARKUBE_MDNS_PUBLISH_ADDR": "192.0.2.55",
        "SUGARKUBE_RUNTIME_DIR": str(tmp_path / "run"),
        "SUGARKUBE_SKIP_SYSTEMCTL": "1",
        "SUGARKUBE_MDNS_ALLOW_ADDR_MISMATCH": "1",
        "SUGARKUBE_MDNS_DBUS": "0",
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
    assert "PIDFILE_OK:bootstrap" in log_contents

    warning = (
        f"WARN: bootstrap advertisement observed from {hostname}.local without expected addr "
        "192.0.2.55; continuing."
    )
    confirm = (
        f"phase=self-check host={hostname}.local observed={hostname}.local; "
        "bootstrap advertisement confirmed."
    )
    assert warning in result.stderr
    assert confirm in result.stderr


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
        "RUN_DIR=\"${SUGARKUBE_RUNTIME_DIR:-/run/sugarkube}\"\n"
        "phase_label=bootstrap\n"
        "if [[ \"$*\" == *\"phase=server\"* ]]; then\n"
        "  phase_label=server\n"
        "fi\n"
        "pid_file=\"${RUN_DIR}/mdns-sugar-dev-${phase_label}.pid\"\n"
        "for _ in $(seq 1 50); do\n"
        "  if [ -f \"${pid_file}\" ] && grep -q \"$$\" \"${pid_file}\"; then\n"
        f"    echo \"PIDFILE_OK:${{phase_label}}\" >> '{log_path}'\n"
        "    break\n"
        "  fi\n"
        "  sleep 0.05\n"
        "done\n"
        "trap 'echo TERM >> \"" + str(log_path) + "\"; exit 0' TERM INT\n"
        "while true; do sleep 1; done\n",
        encoding="utf-8",
    )
    stub.chmod(0o755)

    _write_avahi_publish_address_stub(bin_dir, log_path)

    browse = bin_dir / "avahi-browse"
    browse.write_text(
        (
            "#!/usr/bin/env bash\n"
            "set -euo pipefail\n"
            "cat <<'EOF'\n"
            "=;eth0;IPv4;k3s-sugar-dev@HostMixed.LOCAL.local (bootstrap);_k3s-sugar-dev._tcp;local.;"
            "hostmixed.local.local.;192.0.2.10;6443;"
            "txt=k3s=1;txt=cluster=sugar;txt=env=dev;txt=role=bootstrap;"
            "txt=leader=hostmixed.local.local.;txt=phase=bootstrap;txt=state=pending\n"
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
        "SUGARKUBE_RUNTIME_DIR": str(tmp_path / "run"),
        "SUGARKUBE_SKIP_SYSTEMCTL": "1",
        "SUGARKUBE_MDNS_DBUS": "0",
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
    assert "-s -H" in log_contents
    assert "-H HostMixed.LOCAL" in log_contents
    assert "leader=HostMixed.LOCAL" in log_contents
    assert "PIDFILE_OK:bootstrap" in log_contents

    expected = (
        "phase=self-check host=HostMixed.LOCAL observed=hostmixed.local; "
        "bootstrap advertisement confirmed."
    )
    assert expected in result.stderr


def test_bootstrap_publish_omits_address_flag(tmp_path):
    hostname = _hostname_short()
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log_path = tmp_path / "publish.log"

    stub = bin_dir / "avahi-publish-service"
    stub.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        f"echo \"ARGS:$*\" >> '{log_path}'\n"
        "trap 'exit 0' TERM INT\n"
        "sleep 0.25\n",
        encoding="utf-8",
    )
    stub.chmod(0o755)

    _write_avahi_publish_address_stub(bin_dir, log_path)

    browse = bin_dir / "avahi-browse"
    browse.write_text(
        (
            "#!/usr/bin/env bash\n"
            "set -euo pipefail\n"
            "cat <<'EOF'\n"
            f"=;eth0;IPv4;k3s-sugar-dev@{hostname}.local (bootstrap);_k3s-sugar-dev._tcp;local;{hostname}.local;"
            "192.0.2.55;6443;txt=k3s=1;txt=cluster=sugar;txt=env=dev;txt=role=bootstrap;"
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
        "SUGARKUBE_TOKEN": "dummy",
        "SUGARKUBE_MDNS_BOOT_RETRIES": "1",
        "SUGARKUBE_MDNS_BOOT_DELAY": "0",
        "SUGARKUBE_RUNTIME_DIR": str(tmp_path / "run"),
        "SUGARKUBE_MDNS_PUBLISH_ADDR": "192.0.2.55",
        "SUGARKUBE_SKIP_SYSTEMCTL": "1",
        "SUGARKUBE_MDNS_DBUS": "0",
    })

    subprocess.run(
        ["bash", SCRIPT, "--test-bootstrap-publish"],
        env=env,
        text=True,
        capture_output=True,
        check=True,
    )

    log_contents = log_path.read_text(encoding="utf-8")
    assert "ARGS:" in log_contents
    assert "-a" not in log_contents
    assert "ADDR:" in log_contents
    assert f"ADDR:{hostname}.local 192.0.2.55" in log_contents


def test_bootstrap_publish_retries_until_mdns_visible(tmp_path):
    hostname = _hostname_short()
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log_path = tmp_path / "publish.log"
    count_path = tmp_path / "browse.count"

    stub = bin_dir / "avahi-publish-service"
    stub.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        f"echo \"START:$*\" >> '{log_path}'\n"
        "RUN_DIR=\"${SUGARKUBE_RUNTIME_DIR:-/run/sugarkube}\"\n"
        "phase_label=bootstrap\n"
        "if [[ \"$*\" == *\"phase=server\"* ]]; then\n"
        "  phase_label=server\n"
        "fi\n"
        "pid_file=\"${RUN_DIR}/mdns-sugar-dev-${phase_label}.pid\"\n"
        "for _ in $(seq 1 50); do\n"
        "  if [ -f \"${pid_file}\" ] && grep -q \"$$\" \"${pid_file}\"; then\n"
        f"    echo \"PIDFILE_OK:${{phase_label}}\" >> '{log_path}'\n"
        "    break\n"
        "  fi\n"
        "  sleep 0.05\n"
        "done\n"
        "trap 'echo TERM >> \"" + str(log_path) + "\"; exit 0' TERM INT\n"
        "while true; do sleep 1; done\n",
        encoding="utf-8",
    )
    stub.chmod(0o755)

    _write_avahi_publish_address_stub(bin_dir, log_path)

    browse = bin_dir / "avahi-browse"
    browse.write_text(
        (
            "#!/usr/bin/env bash\n"
            "set -euo pipefail\n"
            f"COUNT_FILE='{count_path}'\n"
            "service_type=\"${@: -1}\"\n"
            "if [ \"${service_type}\" != \"_k3s-sugar-dev._tcp\" ]; then\n"
            "  exit 0\n"
            "fi\n"
            "count=0\n"
            "if [ -f \"${COUNT_FILE}\" ]; then\n"
            "  count=$(cat \"${COUNT_FILE}\")\n"
            "fi\n"
            "count=$((count + 1))\n"
            "echo \"${count}\" > \"${COUNT_FILE}\"\n"
            "if [ \"${count}\" -lt 3 ]; then\n"
            "  exit 0\n"
            "fi\n"
            "cat <<'EOF'\n"
            f"=;eth0;IPv4;k3s-sugar-dev@{hostname}.local (bootstrap);_k3s-sugar-dev._tcp;local;{hostname}.local;"
            "192.0.2.55;6443;txt=k3s=1;txt=cluster=sugar;txt=env=dev;txt=role=bootstrap;"
            f"txt=leader={hostname}.local;txt=phase=bootstrap;txt=state=pending;txt=addr=192.0.2.55\n"
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
        "SUGARKUBE_MDNS_BOOT_RETRIES": "5",
        "SUGARKUBE_MDNS_BOOT_DELAY": "0.05",
        "SUGARKUBE_RUNTIME_DIR": str(tmp_path / "run"),
        "SUGARKUBE_MDNS_PUBLISH_ADDR": "192.0.2.60",
        "SUGARKUBE_SKIP_SYSTEMCTL": "1",
        "SUGARKUBE_MDNS_DBUS": "0",
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
    assert "PIDFILE_OK:bootstrap" in log_contents
    assert "TERM" in log_contents

    browse_count = int(count_path.read_text(encoding="utf-8"))
    assert browse_count >= 3

    expected = (
        f"phase=self-check host={hostname}.local observed={hostname}.local; "
        "bootstrap advertisement confirmed."
    )
    assert expected in result.stderr
    assert "WARN: bootstrap advertisement observed" in result.stderr


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
        "RUN_DIR=\"${SUGARKUBE_RUNTIME_DIR:-/run/sugarkube}\"\n"
        "phase_label=bootstrap\n"
        "if [[ \"$*\" == *\"phase=server\"* ]]; then\n"
        f"  touch '{flag_path}'\n"
        "  phase_label=server\n"
        "fi\n"
        "pid_file=\"${RUN_DIR}/mdns-sugar-dev-${phase_label}.pid\"\n"
        "for _ in $(seq 1 50); do\n"
        "  if [ -f \"${pid_file}\" ] && grep -q \"$$\" \"${pid_file}\"; then\n"
        f"    echo \"PIDFILE_OK:${{phase_label}}\" >> '{log_path}'\n"
        "    break\n"
        "  fi\n"
        "  sleep 0.05\n"
        "done\n"
        "trap 'echo TERM >> \"" + str(log_path) + "\"; exit 0' TERM INT\n"
        "while true; do sleep 1; done\n",
        encoding="utf-8",
    )
    stub.chmod(0o755)

    _write_avahi_publish_address_stub(bin_dir, log_path)

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
            f"=;eth0;IPv4;k3s-sugar-dev@{hostname}.local (server);_k3s-sugar-dev._tcp;local;{hostname}.local;{hostname}.local;6443;"
            f"txt=k3s=1;txt=cluster=sugar;txt=env=dev;txt=role=server;txt=leader={hostname}.local;txt=phase=server;"
            f"txt=addr={hostname}.local\n"
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
        "SUGARKUBE_MDNS_PUBLISH_ADDR": "192.0.2.60",
        "SUGARKUBE_RUNTIME_DIR": str(tmp_path / "run"),
        "SUGARKUBE_SKIP_SYSTEMCTL": "1",
        "SUGARKUBE_MDNS_DBUS": "0",
    })

    result = subprocess.run(
        ["bash", SCRIPT, "--test-bootstrap-server-flow"],
        env=env,
        text=True,
        capture_output=True,
        check=True,
    )

    runtime_dir = tmp_path / "run"
    bootstrap_pid_file = runtime_dir / "mdns-sugar-dev-bootstrap.pid"
    server_pid_file = runtime_dir / "mdns-sugar-dev-server.pid"

    log_contents = log_path.read_text(encoding="utf-8")
    assert log_contents.count("START:") >= 2
    assert "-s -H" in log_contents
    assert "phase=bootstrap" in log_contents
    assert "phase=server" in log_contents
    assert "PIDFILE_OK:bootstrap" in log_contents
    assert "PIDFILE_OK:server" in log_contents
    assert flag_path.exists()

    assert not bootstrap_pid_file.exists()
    server_pid = int(server_pid_file.read_text(encoding="utf-8").strip())
    assert server_pid > 0
    os.kill(server_pid, 0)

    bootstrap_msg = (
        f"phase=self-check host={hostname}.local observed={hostname}.local; "
        "bootstrap advertisement confirmed."
    )
    server_msg = (
        f"phase=self-check host={hostname}.local observed={hostname}.local; "
        "server advertisement confirmed."
    )
    warn_msg = (
        "[k3s-discover mdns] WARN: expected IPv4 192.0.2.60 for "
        f"{hostname}.local but advertisement reported non-IP {hostname}.local; "
        "assuming match after 5 attempts"
    )
    assert bootstrap_msg in result.stderr
    assert server_msg in result.stderr
    assert warn_msg in result.stderr
    assert result.stderr.find(bootstrap_msg) < result.stderr.find(server_msg)

    cleanup_env = env.copy()
    subprocess.run(
        ["bash", str(Path(__file__).resolve().parents[2] / "scripts" / "cleanup_mdns_publishers.sh")],
        env=cleanup_env,
        text=True,
        capture_output=True,
        check=True,
    )

    for _ in range(50):
        check = subprocess.run(
            ["pgrep", "-af", "_k3s-sugar-dev._tcp"],
            text=True,
            capture_output=True,
        )
        if check.returncode != 0:
            break
        time.sleep(0.05)
    else:
        raise AssertionError(f"dynamic publisher still running after cleanup: {check.stdout}")

    assert not server_pid_file.exists()

    log_contents = log_path.read_text(encoding="utf-8")
    assert log_contents.count("TERM") >= 1

    browse_calls = int(count_path.read_text(encoding="utf-8").strip())
    assert browse_calls >= 2


def test_join_prefers_registration_address(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    sh_log = tmp_path / "sh.log"
    publish_log = tmp_path / "publish.log"
    openssl_state = tmp_path / "openssl-host.txt"

    def _write_stub(name: str, content: str) -> None:
        path = bin_dir / name
        path.write_text(content, encoding="utf-8")
        path.chmod(0o755)

    _write_stub(
        "check_apiready.sh",
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        "exit 0\n",
    )

    _write_stub("sleep", "#!/usr/bin/env bash\nexit 0\n")
    _write_stub("systemctl", "#!/usr/bin/env bash\nexit 0\n")
    _write_stub("iptables", "#!/usr/bin/env bash\nexit 0\n")
    _write_stub("ip6tables", "#!/usr/bin/env bash\nexit 0\n")
    _write_stub("apt-get", "#!/usr/bin/env bash\nexit 0\n")

    _write_stub(
        "join-gate.sh",
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        "case \"${1:-}\" in\n"
        "  wait|acquire|release) exit 0 ;;\n"
        "  *) exit 1 ;;\n"
        "esac\n",
    )

    server_host = "sugarkube0.local"
    vip_host = "vip.sugar.test"
    l4_probe_log = tmp_path / "l4-probe.log"

    _write_stub(
        "l4-probe.sh",
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        f"printf '%s %s\\n' \"${1:-}\" \"${2:-}\" >> '{l4_probe_log}'\n"
        f"if [ \"${{1:-}}\" != \"{server_host}\" ]; then\n"
        "  echo 'unexpected host' >&2\n"
        "  exit 9\n"
        "fi\n"
        "if [ \"${2:-}\" != '6443,2379,2380' ]; then\n"
        "  echo 'unexpected ports' >&2\n"
        "  exit 10\n"
        "fi\n"
        "echo ok\n"
        "exit 0\n",
    )

    _write_stub("parity-check.sh", "#!/usr/bin/env bash\nexit 0\n")
    _write_stub("time-check.sh", "#!/usr/bin/env bash\nexit 0\n")
    _write_stub("ss", "#!/usr/bin/env bash\n"
                "echo 'LISTEN'\n"
                "exit 0\n")

    _write_stub(
        "avahi-browse",
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        f"cat <<'EOF'\n"
        f"=;eth0;IPv4;k3s-sugar-dev@{server_host} (server);_k3s-sugar-dev._tcp;local;{server_host};"
        "192.0.2.10;6443;txt=k3s=1;txt=cluster=sugar;txt=env=dev;"
        f"txt=role=server;txt=leader={server_host};txt=phase=server\n"
        "EOF\n",
    )

    _write_stub("avahi-resolve", "#!/usr/bin/env bash\nexit 0\n")

    _write_stub(
        "avahi-publish-service",
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        f"echo \"SERVICE:$*\" >> '{publish_log}'\n"
        "trap 'exit 0' TERM INT\n"
        "while true; do sleep 1; done\n",
    )

    _write_stub(
        "avahi-publish",
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        f"echo \"PUBLISH:$*\" >> '{publish_log}'\n"
        "trap 'exit 0' TERM INT\n"
        "while true; do sleep 1; done\n",
    )

    _write_stub(
        "curl",
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        "for arg in \"$@\"; do\n"
        "  if [[ $arg == *'/cacerts' ]]; then\n"
        "    echo 'dummy-ca'\n"
        "    exit 0\n"
        "  fi\n"
        "done\n"
        "if [[ \"$*\" == *'https://get.k3s.io'* ]]; then\n"
        "  cat <<'SCRIPT'\n"
        "#!/usr/bin/env sh\n"
        "exit 0\n"
        "SCRIPT\n"
        "  exit 0\n"
        "fi\n"
        "cat\n",
    )

    _write_stub(
        "openssl",
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        f"state='{openssl_state}'\n"
        "cmd=\"${1:-}\"\n"
        "shift || true\n"
        "case \"${cmd}\" in\n"
        "  s_client)\n"
        "    host=''\n"
        "    while [ $# -gt 0 ]; do\n"
        "      if [ \"${1:-}\" = '-connect' ] && [ $# -gt 1 ]; then\n"
        "        host=${2%%:*}\n"
        "        break\n"
        "      fi\n"
        "      shift\n"
        "    done\n"
        f"    printf '%s' \"${{host:-}}\" > '{openssl_state}'\n"
        "    echo 'mock-certificate'\n"
        "    exit 0\n"
        "    ;;\n"
        "  x509)\n"
        "    host=''\n"
        f"    if [ -f '{openssl_state}' ]; then\n"
        f"      host=$(cat '{openssl_state}')\n"
        "    fi\n"
        "    echo 'X509v3 Subject Alternative Name:'\n"
        "    if [ -n \"${host}\" ]; then\n"
        "      echo \"    DNS:${host}\"\n"
        "    else\n"
        "      echo '    DNS:placeholder'\n"
        "    fi\n"
        "    exit 0\n"
        "    ;;\n"
        "  *)\n"
        "    exit 0\n"
        "    ;;\n"
        "esac\n",
    )

    _write_stub(
        "sh",
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        f"printf '%s\\n' \"$*\" >> '{sh_log}'\n"
        f"printf 'ENV:K3S_URL=%s\\n' \"${{K3S_URL:-}}\" >> '{sh_log}'\n"
        "cat >/dev/null\n"
        "exit 0\n",
    )

    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{bin_dir}:{env.get('PATH', '')}",
            "ALLOW_NON_ROOT": "1",
            "SUGARKUBE_CLUSTER": "sugar",
            "SUGARKUBE_ENV": "dev",
            "SUGARKUBE_SERVERS": "3",
            "SUGARKUBE_TOKEN": "dummy-token",
            "SUGARKUBE_AVAHI_SERVICE_DIR": str(tmp_path / "avahi"),
            "SUGARKUBE_RUNTIME_DIR": str(tmp_path / "run"),
            "SUGARKUBE_MDNS_PUBLISH_ADDR": "192.0.2.55",
            "SUGARKUBE_SKIP_SYSTEMCTL": "1",
            "SUGARKUBE_MDNS_DBUS": "0",
            "SUGARKUBE_MDNS_BOOT_RETRIES": "1",
            "SUGARKUBE_MDNS_BOOT_DELAY": "0",
            "SUGARKUBE_SKIP_MDNS_SELF_CHECK": "1",
            "SUGARKUBE_L4_PROBE_BIN": str(bin_dir / "l4-probe.sh"),
            "SUGARKUBE_JOIN_GATE_BIN": str(bin_dir / "join-gate.sh"),
            "SUGARKUBE_API_READY_CHECK_BIN": str(bin_dir / "check_apiready.sh"),
            "SUGARKUBE_SERVER_FLAG_PARITY_BIN": str(bin_dir / "parity-check.sh"),
            "SUGARKUBE_TIME_SYNC_BIN": str(bin_dir / "time-check.sh"),
            "SUGARKUBE_API_REGADDR": vip_host,
            "DISCOVERY_ATTEMPTS": "1",
            "DISCOVERY_WAIT_SECS": "0",
            "SH_LOG_PATH": str(sh_log),
        }
    )

    result = subprocess.run(
        ["bash", SCRIPT],
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr

    sh_contents = sh_log.read_text(encoding="utf-8")
    assert "--server https://vip.sugar.test:6443" in sh_contents
    assert "ENV:K3S_URL=\n" in sh_contents
    assert "--server https://sugarkube0.local:6443" not in sh_contents

    assert "discovered_server=sugarkube0.local" in result.stderr
    assert l4_probe_log.read_text(encoding="utf-8").strip() == \
        f"{server_host} 6443,2379,2380"


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
        "RUN_DIR=\"${SUGARKUBE_RUNTIME_DIR:-/run/sugarkube}\"\n"
        "phase_label=bootstrap\n"
        "if [[ \"$*\" == *\"phase=server\"* ]]; then\n"
        "  phase_label=server\n"
        "fi\n"
        "pid_file=\"${RUN_DIR}/mdns-sugar-dev-${phase_label}.pid\"\n"
        "for _ in $(seq 1 50); do\n"
        "  if [ -f \"${pid_file}\" ] && grep -q \"$$\" \"${pid_file}\"; then\n"
        f"    echo \"PIDFILE_OK:${{phase_label}}\" >> '{log_path}'\n"
        "    break\n"
        "  fi\n"
        "  sleep 0.05\n"
        "done\n"
        "trap 'echo TERM >> \"" + str(log_path) + "\"; exit 0' TERM INT\n"
        "while true; do sleep 1; done\n",
        encoding="utf-8",
    )
    stub.chmod(0o755)

    _write_avahi_publish_address_stub(bin_dir, log_path)

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
        "SUGARKUBE_RUNTIME_DIR": str(tmp_path / "run"),
        "SUGARKUBE_SKIP_SYSTEMCTL": "1",
        "SUGARKUBE_MDNS_DBUS": "0",
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
