"""Regression tests for mid-election server discovery in k3s-discover."""
from __future__ import annotations

import os
import signal
import subprocess
import textwrap
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "k3s-discover.sh"


def _write_stub(path: Path, content: str) -> None:
    content = content.lstrip("\n")
    if content.startswith("\\\n"):
        content = content[2:]
    lines = content.splitlines()
    indents = [
        len(line) - len(line.lstrip(" \t"))
        for line in lines
        if line.strip() and line[0] in (" ", "\t")
    ]
    if indents:
        trim = min(indents)
        prefix = " " * trim
        lines = [line[len(prefix) :] if line.startswith(prefix) else line for line in lines]
    content = "\n".join(lines)
    if content and content[-1] != "\n":
        content += "\n"
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
    parity_log = tmp_path / "parity.log"

    _write_stub(
        bin_dir / "check_apiready.sh",
        textwrap.dedent(
            """\
            #!/usr/bin/env bash
            set -euo pipefail
            message='ts=stub level=info event=apiready outcome=ok'
            if [ -n "${SERVER_HOST:-}" ]; then
              printf '%s host="%s"\n' "$message" "${SERVER_HOST}" >&2
            else
              printf '%s\n' "$message" >&2
            fi
            exit 0
            """
        ),
    )

    # Stub sleep to avoid delays in the control-flow.
    _write_stub(bin_dir / "sleep", "#!/usr/bin/env bash\nexit 0\n")

    # Stub systemctl to avoid touching the host service manager.
    _write_stub(bin_dir / "systemctl", "#!/usr/bin/env bash\nexit 0\n")

    # Provide minimal stubs for iptables tooling so the installer preflight succeeds.
    _write_stub(bin_dir / "iptables", "#!/usr/bin/env bash\nexit 0\n")
    _write_stub(bin_dir / "ip6tables", "#!/usr/bin/env bash\nexit 0\n")
    _write_stub(bin_dir / "apt-get", "#!/usr/bin/env bash\nexit 0\n")

    _write_stub(
        bin_dir / "parity-check.sh",
        textwrap.dedent(
            f"""\
            #!/usr/bin/env bash
            set -euo pipefail
            echo parity >> '{parity_log}'
            exit 99
            """
        ),
    )

    # Pretend the API port starts listening immediately after the installer runs.
    _write_stub(
        bin_dir / "ss",
        textwrap.dedent(
            """\
            #!/usr/bin/env bash
            echo 'LISTEN'
            exit 0
            """
        ),
    )

    # Provide a long-running avahi-publish-service implementation so the helper keeps a PID.
    _write_stub(
        bin_dir / "avahi-publish-service",
        textwrap.dedent(
            f"""\
            #!/usr/bin/env bash
            set -euo pipefail
            echo START:"$@" >> '{publish_log}'
            if [[ "$*" == *"phase=server"* ]]; then
              touch '{server_flag}'
            fi
            trap 'echo TERM >> "{publish_log}"; exit 0' TERM INT
            while true; do
              read -r -t 1 _ || true
            done
            """
        ),
    )

    _write_stub(
        bin_dir / "avahi-publish",
        textwrap.dedent(
            f"""\
            #!/usr/bin/env bash
            set -euo pipefail
            echo PUBLISH:"$@" >> '{publish_log}'
            if [[ "$*" == *"phase=server"* ]]; then
              touch '{server_flag}'
            fi
            trap 'exit 0' TERM INT
            while true; do
              read -r -t 1 _ || true
            done
            """
        ),
    )

    _write_stub(
        bin_dir / "avahi-resolve",
        textwrap.dedent(
            """\
            #!/usr/bin/env bash
            set -euo pipefail
            if [ "${1:-}" = '-n' ]; then
              printf '%s\t%s\n' "${2:-}" '192.0.2.10'
              exit 0
            fi
            exit 0
            """
        ),
    )

    # Emit an installation script that immediately exits successfully.
    _write_stub(
        bin_dir / "curl",
        textwrap.dedent(
            """\
            #!/usr/bin/env bash
            set -euo pipefail
            cat <<'SCRIPT'
            #!/usr/bin/env sh
            exit 0
            SCRIPT
            """
        ),
    )

    _write_stub(bin_dir / "l4_probe.sh", "#!/usr/bin/env bash\nexit 0\n")

    _write_stub(
        bin_dir / "join_gate_stub.sh",
        textwrap.dedent(
            """\
            #!/usr/bin/env bash
            set -euo pipefail
            case "${1:-}" in
              wait|acquire|release)
                exit 0
                ;;
              *)
                exit 0
                ;;
            esac
            """
        ),
    )

    # Capture invocations of sh -s - server ... from the installer pipeline.
    _write_stub(
        bin_dir / "sh",
        textwrap.dedent(
            """\
            #!/usr/bin/env bash
            set -euo pipefail
            if [ -n "${SH_LOG_PATH:-}" ]; then
              printf '%s\n' "$*" >> "${SH_LOG_PATH}"
            fi
            cat >/dev/null
            exit 0
            """
        ),
    )

    # Simulate avahi-browse output: after enough server queries, emit a server advert.
    _write_stub(
        bin_dir / "avahi-browse",
        textwrap.dedent(
            f"""\
            #!/usr/bin/env bash
            set -euo pipefail
              for arg in "$@"; do
                if [ "$arg" = '--all' ]; then
                  printf '%s\n' \
                    '=;eth0;IPv4;dummy;_dummy._tcp;local;'\
                    'dummy.local;192.0.2.1;1234;txt=foo=bar'
                  exit 0
                fi
              done
            state="${{SUGARKUBE_TEST_STATE}}"
            threshold="${{SUGARKUBE_TEST_SERVER_THRESHOLD:-9}}"
            mode='bootstrap'
            flag='{server_flag}'
            for arg in "$@"; do
              if [ "$arg" = '--ignore-local' ]; then
                mode='server'
              fi
            done
            if [ ! -f "$state" ]; then
              printf '0 0\n' >"$state"
            fi
            read -r server_count bootstrap_count <"$state"
            if [ "$mode" = 'server' ]; then
              server_count=$((server_count + 1))
              if [ "$server_count" -ge "$threshold" ]; then
                printf '%s\n' \
                  '=;eth0;IPv4;k3s API sugar/dev on sugarkube0;_https._tcp;local;' \
                  'sugarkube0.local;192.168.50.10;6443;txt=k3s=1;txt=cluster=sugar;' \
                  'txt=env=dev;txt=role=server;txt=leader=sugarkube0.local;txt=phase=server'
              fi
            else
              bootstrap_count=$((bootstrap_count + 1))
            fi
            local_host=$(hostname -s)
              if [ -f "$flag" ]; then
                printf '%s\n' \
                  "=;eth0;IPv4;k3s-sugar-dev@${{local_host}}.local (server);_k3s-sugar-dev._tcp;"\
                  "local;${{local_host}}.local;192.0.2.10;6443;"\
                  "txt=k3s=1;txt=cluster=sugar;txt=env=dev;txt=role=server;"\
                  "txt=leader=${{local_host}}.local;txt=phase=server"
              fi
            printf '%s %s\n' "$server_count" "$bootstrap_count" >"$state"
            exit 0
            """
        ),
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
            "SUGARKUBE_TEST_SERVER_THRESHOLD": "1",
            "SH_LOG_PATH": str(sh_log),
            "SUGARKUBE_MDNS_DBUS": "0",
            "SUGARKUBE_API_READY_CHECK_BIN": str(bin_dir / "check_apiready.sh"),
            "SUGARKUBE_SERVER_FLAG_PARITY_BIN": str(bin_dir / "parity-check.sh"),
            "SUGARKUBE_L4_PROBE_BIN": str(bin_dir / "l4_probe.sh"),
            "SUGARKUBE_JOIN_GATE_BIN": str(bin_dir / "join_gate_stub.sh"),
            "SUGARKUBE_DISABLE_JOIN_GATE": "1",
            "SUGARKUBE_MDNS_ABSENCE_GATE": "0",
            "SUGARKUBE_TEST_FAST_JOIN": "1",
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
    fast_mode = "mode=fast" in result.stderr
    assert (
        "event=mdns_selfcheck outcome=confirmed" in result.stderr
        or fast_mode
    )
    assert "phase=install_join" in result.stderr

    if "event=join_gate action=skip" in result.stderr:
        assert "event=join outcome=fast_path" in result.stderr
    else:
        assert "event=join_gate action=wait" in result.stderr
        assert "event=join_gate action=acquire" in result.stderr
        assert "event=join_gate action=release" in result.stderr

    assert not parity_log.exists(), "Parity helper should be skipped when sources are absent"

    if sh_log.exists():
        sh_log_contents = sh_log.read_text(encoding="utf-8")
        assert "--cluster-init" not in sh_log_contents
        assert "--server https://sugarkube0.local:6443" in sh_log_contents
    else:
        assert fast_mode, "Fast join should be the only path without installer logs"

    if publish_log.exists():
        publish_contents = publish_log.read_text(encoding="utf-8")
        assert "START:" in publish_contents
    else:
        assert fast_mode, "Fast join should be the only path without publisher activity"

    runtime_dir = tmp_path / "run"
    server_pid_file = runtime_dir / "mdns-sugar-dev-server.pid"
    if server_pid_file.exists():
        server_pid = int(server_pid_file.read_text(encoding="utf-8").strip())
        assert server_pid > 0
        try:
            os.kill(server_pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        finally:
            # Ensure the stub terminates to avoid leaking background publishers between tests.
            server_pid_file.unlink(missing_ok=True)
    else:
        assert fast_mode, "Fast join should be the only path without server publisher PID state"
