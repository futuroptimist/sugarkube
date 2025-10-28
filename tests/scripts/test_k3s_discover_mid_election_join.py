"""Regression tests for mid-election server discovery in k3s-discover."""
from __future__ import annotations

import os
import signal
import subprocess
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "k3s-discover.sh"


def _write_stub(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
    path.chmod(0o755)


def test_join_when_server_advertises_during_election(tmp_path: Path) -> None:
    """A server coming online mid-election should cause a join, not bootstrap."""

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()

    state_file = tmp_path / "mdns-state.txt"
    sh_log = tmp_path / "sh.log"
    publish_log = tmp_path / "publish.log"
    server_flag = tmp_path / "server-published"

    # Stub sleep to avoid delays in the control-flow.
    _write_stub(bin_dir / "sleep", "#!/usr/bin/env bash\nexit 0\n")

    # Stub systemctl to avoid touching the host service manager.
    _write_stub(bin_dir / "systemctl", "#!/usr/bin/env bash\nexit 0\n")

    # Pretend the API port starts listening immediately after the installer runs.
    _write_stub(
        bin_dir / "ss",
        "#!/usr/bin/env bash\n" "echo 'LISTEN'\n" "exit 0\n",
    )

    # Provide long-running Avahi publisher implementations so the helper keeps a PID.
    publisher_stub = (
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        f"echo START:\"$@\" >> '{publish_log}'\n"
        f"if [[ \"$*\" == *\"phase=server\"* ]]; then touch '{server_flag}'; fi\n"
        "trap 'echo TERM >> \"" + str(publish_log) + "\"; exit 0' TERM INT\n"
        "while true; do read -r -t 1 _ || true; done\n"
    )
    _write_stub(bin_dir / "avahi-publish-service", publisher_stub)
    _write_stub(bin_dir / "avahi-publish", publisher_stub)

    # Emit an installation script that immediately exits successfully.
    _write_stub(
        bin_dir / "curl",
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        "cat <<'SCRIPT'\n"
        "#!/usr/bin/env sh\n"
        "exit 0\n"
        "SCRIPT\n",
    )

    _write_stub(
        bin_dir / "apt-get",
        "#!/usr/bin/env bash\n"
        "exit 0\n",
    )

    _write_stub(
        bin_dir / "avahi-resolve",
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        "if [ $# -ge 2 ]; then\n"
        "  echo \"$2 192.0.2.10\"\n"
        "else\n"
        "  exit 1\n"
        "fi\n",
    )

    # Capture invocations of sh -s - server ... from the installer pipeline.
    _write_stub(
        bin_dir / "sh",
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        "if [ -n \"${SH_LOG_PATH:-}\" ]; then\n"
        "  printf '%s\\n' \"$*\" >> \"${SH_LOG_PATH}\"\n"
        "fi\n"
        "cat >/dev/null\n"
        "exit 0\n",
    )

    # Simulate avahi-browse output: after enough server queries, emit a server advert.
    _write_stub(
        bin_dir / "avahi-browse",
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        'state="${SUGARKUBE_TEST_STATE}"\n'
        'threshold="${SUGARKUBE_TEST_SERVER_THRESHOLD:-9}"\n'
        'server_flag="${SUGARKUBE_TEST_SERVER_FLAG}"\n'
        "service_type=''\n"
        "for arg in \"$@\"; do\n"
        "  case \"$arg\" in\n"
        "    _k3s-join-lock._tcp)\n"
        "      exit 1\n"
        "      ;;\n"
        "    -*|--*)\n"
        "      continue\n"
        "      ;;\n"
        "    *)\n"
        "      service_type=\"$arg\"\n"
        "      ;;\n"
        "  esac\n"
        "done\n"
        "cluster=${SUGARKUBE_CLUSTER:-sugar}\n"
        "environment=${SUGARKUBE_ENV:-dev}\n"
        "target_type=\"_k3s-${cluster}-${environment}._tcp\"\n"
        "if [ \"$service_type\" = \"$target_type\" ] && [ -n \"${SUGARKUBE_EXPECTED_HOST:-}\" ] "
        "&& [ -f \"$server_flag\" ]; then\n"
        "  expected_host=\"${SUGARKUBE_EXPECTED_HOST}\"\n"
        "  cat <<EOF\n"
        "=;eth0;IPv4;k3s-${cluster}-${environment}@${expected_host} (server);"
        "$target_type;local;${expected_host};192.0.2.20;6443;txt=k3s=1;"
        "txt=cluster=${cluster};txt=env=${environment};txt=role=server;"
        "txt=leader=${expected_host};txt=phase=server\n"
        "EOF\n"
        "  exit 0\n"
        "fi\n"
        "if [ ! -f \"$state\" ]; then\n"
        "  printf '0 0\n' >\"$state\"\n"
        "fi\n"
        "read -r server_count bootstrap_count <\"$state\"\n"
        "mode='bootstrap'\n"
        "if [ \"$service_type\" = \"$target_type\" ]; then\n"
        "  mode='server'\n"
        "fi\n"
        "for arg in \"$@\"; do\n"
        "  if [ \"$arg\" = '--ignore-local' ]; then\n"
        "    mode='server'\n"
        "  fi\n"
        "done\n"
        "if [ \"$mode\" = 'server' ]; then\n"
        "  server_count=$((server_count + 1))\n"
        "  if [ $server_count -ge $threshold ]; then\n"
        "    local_host=sugarkube0\n"
        "    cat <<EOF\n"
        "=;eth0;IPv4;k3s-${cluster}-${environment}@${local_host}.local (server);"
        "$target_type;local;${local_host}.local;192.0.2.10;6443;txt=k3s=1;"
        "txt=cluster=${cluster};txt=env=${environment};txt=role=server;"
        "txt=leader=${local_host}.local;txt=phase=server\n"
        "EOF\n"
        "  fi\n"
        "else\n"
        "  bootstrap_count=$((bootstrap_count + 1))\n"
        "fi\n"
        "printf '%s %s\n' \"$server_count\" \"$bootstrap_count\" >\"$state\"\n"
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
            "SUGARKUBE_TOKEN": "dummy",
            "DISCOVERY_ATTEMPTS": "3",
            "DISCOVERY_WAIT_SECS": "0",
            "SUGARKUBE_AVAHI_SERVICE_DIR": str(tmp_path / "avahi"),
            "SUGARKUBE_RUNTIME_DIR": str(tmp_path / "run"),
            "SUGARKUBE_TEST_STATE": str(state_file),
            "SUGARKUBE_TEST_SERVER_THRESHOLD": "9",
            "SUGARKUBE_TEST_SERVER_FLAG": str(server_flag),
            "SH_LOG_PATH": str(sh_log),
            "SUGARKUBE_MDNS_DBUS": "0",
        }
    )

    result = subprocess.run(
        ["bash", str(SCRIPT)],
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "event=mdns_selfcheck outcome=confirmed" in result.stderr
    assert "phase=install_join" in result.stderr

    wait_idx = result.stderr.find("event=join_gate action=wait outcome=ok")
    acquire_idx = result.stderr.find("event=join_gate action=acquire outcome=ok")
    release_idx = result.stderr.find("event=join_gate action=release outcome=ok")

    assert wait_idx != -1, result.stderr
    assert acquire_idx != -1, result.stderr
    assert release_idx != -1, result.stderr
    assert wait_idx < acquire_idx < release_idx
    join_log_idx = result.stderr.find("phase=install_join")
    assert join_log_idx != -1, result.stderr
    assert acquire_idx < join_log_idx < release_idx

    sh_log_contents = sh_log.read_text(encoding="utf-8")
    assert "--cluster-init" not in sh_log_contents
    assert "--server https://sugarkube0.local:6443" in sh_log_contents

    publish_contents = publish_log.read_text(encoding="utf-8")
    assert "START:" in publish_contents

    runtime_dir = tmp_path / "run"
    server_pid_file = runtime_dir / "mdns-sugar-dev-server.pid"
    assert server_pid_file.exists()

    server_pid = int(server_pid_file.read_text(encoding="utf-8").strip())
    assert server_pid > 0

    try:
        os.kill(server_pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    finally:
        # Ensure the stub terminates to avoid leaking background publishers between tests.
        server_pid_file.unlink(missing_ok=True)
