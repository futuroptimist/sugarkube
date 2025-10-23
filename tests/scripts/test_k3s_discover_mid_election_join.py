"""Regression tests for mid-election server discovery in k3s-discover."""
from __future__ import annotations

import os
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

    # Provide a long-running avahi-publish-service implementation so the helper keeps a PID.
    _write_stub(
        bin_dir / "avahi-publish-service",
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        f"echo START:\"$@\" >> '{publish_log}'\n"
        f"if [[ \"$*\" == *\"phase=server\"* ]]; then touch '{server_flag}'; fi\n"
        "trap 'echo TERM >> \"" + str(publish_log) + "\"; exit 0' TERM INT\n"
        "while true; do read -r -t 1 _ || true; done\n",
    )

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
        "mode='bootstrap'\n"
        f"flag='{server_flag}'\n"
        "for arg in \"$@\"; do\n"
        "  if [ \"$arg\" = '--ignore-local' ]; then\n"
        "    mode='server'\n"
        "  fi\n"
        "done\n"
        "if [ ! -f \"$state\" ]; then\n"
        "  printf '0 0\n' >\"$state\"\n"
        "fi\n"
        "read -r server_count bootstrap_count <\"$state\"\n"
        "if [ \"$mode\" = 'server' ]; then\n"
        "  server_count=$((server_count + 1))\n"
        "  if [ $server_count -ge $threshold ]; then\n"
        "    cat <<'EOF'\n"
        "=;eth0;IPv4;k3s API sugar/dev on sugarkube0;_https._tcp;local;"
        "sugarkube0.local;192.168.50.10;6443;txt=k3s=1;txt=cluster=sugar;"
        "txt=env=dev;txt=role=server;txt=leader=sugarkube0.local;txt=phase=server\n"
        "EOF\n"
        "  fi\n"
        "else\n"
        "  bootstrap_count=$((bootstrap_count + 1))\n"
        "fi\n"
        "local_host=$(hostname -s)\n"
        "if [ -f \"$flag\" ]; then\n"
        "  cat <<EOF\n"
        "=;eth0;IPv4;k3s-sugar-dev@${local_host}.local (server);_k3s-sugar-dev._tcp;local;${local_host}.local;192.0.2.10;6443;"
        "txt=k3s=1;txt=cluster=sugar;txt=env=dev;txt=role=server;txt=leader=${local_host}.local;txt=phase=server\n"
        "EOF\n"
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
            "SUGARKUBE_TEST_STATE": str(state_file),
            "SUGARKUBE_TEST_SERVER_THRESHOLD": "9",
            "SH_LOG_PATH": str(sh_log),
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
    assert "server advertisement confirmed" in result.stderr
    assert "Joining as additional HA server via https://sugarkube0.local:6443" in result.stderr

    sh_log_contents = sh_log.read_text(encoding="utf-8")
    assert "--cluster-init" not in sh_log_contents
    assert "--server https://sugarkube0.local:6443" in sh_log_contents

    publish_contents = publish_log.read_text(encoding="utf-8")
    assert "START:" in publish_contents
    assert "TERM" in publish_contents

