import os
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]


def _write_executable(path: Path, content: str) -> None:
    path.write_text(textwrap.dedent(content), encoding="utf-8")
    path.chmod(0o755)


def test_just_up_dev_two_nodes(tmp_path):
    if shutil.which("just") is None:
        pytest.skip("just binary is required for this test")

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log_path = tmp_path / "commands.log"
    run_dir = tmp_path / "run"
    avahi_dir = tmp_path / "avahi"
    state_dir = tmp_path / "state"
    systemd_dir = tmp_path / "systemd"
    cmdline_path = tmp_path / "cmdline.txt"
    cmdline_path.write_text("console=tty1\n", encoding="utf-8")
    proc_cmdline_path = tmp_path / "proc_cmdline"
    proc_cmdline_path.write_text("console=tty1\n", encoding="utf-8")
    nsswitch_path = tmp_path / "nsswitch.conf"
    nsswitch_path.write_text("hosts: files dns\n", encoding="utf-8")

    _write_executable(
        bin_dir / "sudo",
        f"""#!/usr/bin/env bash
        set -euo pipefail
        echo "sudo:$@" >> "{log_path}"
        while [ "$#" -gt 0 ]; do
          case "$1" in
            -E|--preserve-env|--login)
              shift
              continue
              ;;
            --preserve-env=*)
              shift
              continue
              ;;
            *)
              break
              ;;
          esac
        done
        if [ "$#" -eq 0 ]; then
          exit 0
        fi
        exec "$@"
        """,
    )

    _write_executable(
        bin_dir / "apt-get",
        f"""#!/usr/bin/env bash
        set -euo pipefail
        echo "apt-get:$@" >> "{log_path}"
        exit 0
        """,
    )

    _write_executable(
        bin_dir / "systemctl",
        f"""#!/usr/bin/env bash
        set -euo pipefail
        echo "systemctl:$@" >> "{log_path}"
        exit 0
        """,
    )

    _write_executable(
        bin_dir / "ip",
        f"""#!/usr/bin/env bash
        set -euo pipefail
        if [ "$#" -ge 5 ] && [ "$1" = "-4" ] && [ "$2" = "-o" ] \
          && [ "$3" = "addr" ] && [ "$4" = "show" ]; then
          printf '%s\n' '1: eth0    inet 192.0.2.10/24 brd 192.0.2.255 scope global eth0'
          exit 0
        fi
        echo "ip:$@" >> "{log_path}"
        exit 1
        """,
    )

    _write_executable(
        bin_dir / "ss",
        """#!/usr/bin/env bash
        set -euo pipefail
        run_dir="${SUGARKUBE_RUNTIME_DIR:-/run/sugarkube}"
        if [ -f "${run_dir}/server-ready" ]; then
          echo "LISTEN 0      128      0.0.0.0:6443 0.0.0.0:*"
          exit 0
        fi
        exit 1
        """,
    )

    _write_executable(
        bin_dir / "timeout",
        f"""#!/usr/bin/env bash
        set -euo pipefail
        echo "timeout:$@" >> "{log_path}"
        exit 1
        """,
    )

    _write_executable(
        bin_dir / "curl",
        f"""#!/usr/bin/env python3
        import pathlib
        import sys

        log = pathlib.Path("{log_path}")
        log.parent.mkdir(parents=True, exist_ok=True)
        with log.open("a", encoding="utf-8") as handle:
            handle.write("curl:" + " ".join(sys.argv[1:]) + "\n")

        script = "#!/usr/bin/env bash\\n"
        script += "echo \"install:$@\" >> \"" + str(log) + "\"\\n"
        script += "exit 0\\n"
        sys.stdout.write(script)
        """,
    )

    _write_executable(
        bin_dir / "avahi-publish-service",
        f"""#!/usr/bin/env bash
        set -euo pipefail
        echo "avahi-publish-service:$@" >> "{log_path}"
        run_dir="${{SUGARKUBE_RUNTIME_DIR:-/run/sugarkube}}"
        phase="bootstrap"
        if [[ "$*" == *"phase=server"* ]]; then
          phase="server"
        fi
        service_name=""
        for arg in "$@"; do
          case "$arg" in
            k3s-*-*@*)
              service_name="$arg"
              ;;
          esac
        done
        touch "${{run_dir}}/publish-${{phase}}"
        count_file="${{run_dir}}/publish-${{phase}}-count"
        current=0
        if [ -f "${{count_file}}" ]; then
          current="$(cat "${{count_file}}" 2>/dev/null || echo 0)"
        fi
        current=$((current + 1))
        printf '%s\n' "${{current}}" >"${{count_file}}"
        if [ "$phase" = "server" ]; then
          touch "${{run_dir}}/server-ready"
        fi
        if [ -n "${{service_name}}" ]; then
          echo "Established under name '${{service_name}}'" >&2
        fi
        trap 'echo "avahi-publish-service:TERM:${{phase}}" >> "{log_path}"; exit 0' TERM INT
        while true; do sleep 1; done
        """,
    )

    _write_executable(
        bin_dir / "avahi-publish-address",
        f"""#!/usr/bin/env bash
        set -euo pipefail
        echo "avahi-publish-address:$@" >> "{log_path}"
        trap 'echo "avahi-publish-address:TERM" >> "{log_path}"; exit 0' TERM INT
        while true; do sleep 1; done
        """,
    )

    _write_executable(
        bin_dir / "avahi-browse",
        f"""#!/usr/bin/env python3
        import os
        import pathlib
        import sys

        log = pathlib.Path("{log_path}")
        with log.open("a", encoding="utf-8") as handle:
            handle.write("avahi-browse:" + " ".join(sys.argv[1:]) + "\n")

        if len(sys.argv) == 0:
            raise SystemExit(0)

        service = sys.argv[-1]
        if service != "_k3s-sugar-dev._tcp":
            raise SystemExit(0)

        phase = os.environ.get("JUST_UP_TEST_PHASE", "bootstrap")
        run_dir = pathlib.Path(os.environ.get("SUGARKUBE_RUNTIME_DIR", "/run/sugarkube"))
        local_host = os.environ.get("SUGARKUBE_MDNS_HOST", "pi0.local")
        primary = os.environ.get("JUST_UP_PRIMARY_HOST", "pi0.local")
        lines = []

        bootstrap_addr = os.environ.get("JUST_UP_BOOTSTRAP_ADDR", "192.0.2.10")
        server_addr = os.environ.get("JUST_UP_SERVER_ADDR", "192.0.2.10")

        fail_once = os.environ.get("JUST_UP_FAIL_SERVER_ONCE") == "1"
        publish_server_count = 0
        count_path = run_dir / "publish-server-count"
        if count_path.exists():
            try:
                publish_server_count = int(count_path.read_text(encoding="utf-8").strip() or "0")
            except Exception:
                publish_server_count = 0

        publish_bootstrap_count = 0
        bootstrap_count_path = run_dir / "publish-bootstrap-count"
        if bootstrap_count_path.exists():
            try:
                publish_bootstrap_count = int(
                    bootstrap_count_path.read_text(encoding="utf-8").strip() or "0"
                )
            except Exception:
                publish_bootstrap_count = 0

        fail_local_server = bool(
            fail_once and phase == "join" and publish_server_count <= 1
        )

        fail_bootstrap_once = os.environ.get("JUST_UP_FAIL_BOOTSTRAP_ONCE") == "1"
        fail_local_bootstrap = bool(
            fail_bootstrap_once and phase == "bootstrap" and publish_bootstrap_count <= 1
        )

        suppress_bootstrap = os.environ.get("JUST_UP_SUPPRESS_BOOTSTRAP_BROWSE") == "1"
        suppress_server = os.environ.get("JUST_UP_SUPPRESS_SERVER_BROWSE") == "1"

        if (
            run_dir / "publish-server"
        ).exists() and not fail_local_server and not (suppress_server and phase == "join"):
            lines.append(
                "=;eth0;IPv4;k3s-sugar-dev@" + local_host + " (server);"
                + "_k3s-sugar-dev._tcp;local;" + local_host + ";"
                + server_addr
                + ";6443;"
                + "txt=k3s=1;txt=cluster=sugar;txt=env=dev;txt=role=server;"
                + "txt=leader=" + local_host + ";txt=phase=server"
            )

        if (
            phase == "bootstrap"
            and (run_dir / "publish-bootstrap").exists()
            and not fail_local_bootstrap
            and not suppress_bootstrap
        ):
            lines.append(
                "=;eth0;IPv4;k3s-sugar-dev@" + local_host + " (bootstrap);"
                + "_k3s-sugar-dev._tcp;local;" + local_host + ";"
                + bootstrap_addr
                + ";6443;"
                + "txt=k3s=1;txt=cluster=sugar;txt=env=dev;txt=role=bootstrap;"
                + "txt=leader=" + local_host + ";txt=phase=bootstrap;txt=state=pending"
            )

        if phase == "join":
            lines.append(
                "=;eth0;IPv4;k3s-sugar-dev@" + primary + " (server);"
                + "_k3s-sugar-dev._tcp;local;" + primary + ";"
                + server_addr
                + ";6443;"
                + "txt=k3s=1;txt=cluster=SUGAR ;txt=ENV=DEV ;txt=role=server;"
                + "txt=leader=" + primary + ";txt=phase=server"
            )

        if lines:
            sys.stdout.write("\n".join(lines) + "\n")
        """,
    )

    _write_executable(
        bin_dir / "grep",
        f"""#!/usr/bin/env python3
        import os
        import pathlib
        import subprocess
        import sys

        log = pathlib.Path("{log_path}")
        with log.open("a", encoding="utf-8") as handle:
            handle.write("grep:" + " ".join(sys.argv[1:]) + "\n")

        args = sys.argv[1:]
        if args and args[-1] == "/etc/nsswitch.conf":
            args[-1] = os.environ["TEST_NSSWITCH"]
        result = subprocess.run(["/bin/grep", *args])
        raise SystemExit(result.returncode)
        """,
    )

    _write_executable(
        bin_dir / "sed",
        f"""#!/usr/bin/env python3
        import os
        import pathlib
        import re
        import sys

        log = pathlib.Path("{log_path}")
        with log.open("a", encoding="utf-8") as handle:
            handle.write("sed:" + " ".join(sys.argv[1:]) + "\n")

        args = sys.argv[1:]
        if len(args) != 3 or args[0] != "-i" or args[2] != "/etc/nsswitch.conf":
            raise SystemExit("unsupported sed invocation")

        pattern = args[1]
        target = pathlib.Path(os.environ["TEST_NSSWITCH"])
        if not pattern.startswith("s/"):
            raise SystemExit("unexpected sed pattern")

        _, expr, remainder = pattern.split("/", 2)
        replacement, _ = remainder.rsplit("/", 1)
        content = target.read_text(encoding="utf-8")
        updated = re.sub(expr, replacement, content, flags=re.MULTILINE)
        target.write_text(updated, encoding="utf-8")
        """,
    )

    _write_executable(
        bin_dir / "pgrep",
        f"""#!/usr/bin/env bash
        set -euo pipefail
        echo "pgrep:$@" >> "{log_path}"
        exit 1
        """,
    )

    env_common = os.environ.copy()
    env_common.update(
        {
            "PATH": f"{bin_dir}:{env_common.get('PATH', '')}",
            "SUGARKUBE_RUNTIME_DIR": str(run_dir),
            "SUGARKUBE_AVAHI_SERVICE_DIR": str(avahi_dir),
            "SUGARKUBE_STATE_DIR": str(state_dir),
            "SUGARKUBE_SYSTEMD_DIR": str(systemd_dir),
            "SUGARKUBE_CMDLINE_PATH": str(cmdline_path),
            "SUGARKUBE_PROC_CMDLINE_PATH": str(proc_cmdline_path),
            "SUGARKUBE_CONFIGURE_AVAHI": "0",
            "SUGARKUBE_DISABLE_WLAN_DURING_BOOTSTRAP": "0",
            "SUGARKUBE_SET_K3S_NODE_IP": "0",
            "SUGARKUBE_SKIP_SYSTEMCTL": "1",
            "SUGARKUBE_SERVERS": "2",
            "SUGARKUBE_TOKEN": "dummy",
            "SUGARKUBE_ALLOW_ROOTLESS_DEPS": "1",
            "TEST_NSSWITCH": str(nsswitch_path),
            "JUST_UP_PRIMARY_HOST": "pi0.local",
            "JUST_UP_LOG": str(log_path),
            "ALLOW_NON_ROOT": "1",
            "SUGARKUBE_MDNS_PUBLISH_ADDR": "192.0.2.10",
            "SUGARKUBE_MDNS_BOOT_RETRIES": "1",
            "SUGARKUBE_MDNS_BOOT_DELAY": "0",
            "SUGARKUBE_MDNS_SERVER_RETRIES": "1",
            "SUGARKUBE_MDNS_SERVER_DELAY": "0",
        }
    )

    env_bootstrap = env_common.copy()
    env_bootstrap.update(
        {
            "SUGARKUBE_MDNS_HOST": "pi0.local",
            "JUST_UP_TEST_PHASE": "bootstrap",
            "JUST_UP_BOOTSTRAP_ADDR": "",
            "JUST_UP_FAIL_BOOTSTRAP_ONCE": "1",
        }
    )

    result_bootstrap = subprocess.run(
        ["just", "up", "dev"],
        cwd=REPO_ROOT,
        env=env_bootstrap,
        text=True,
        capture_output=True,
    )
    assert result_bootstrap.returncode == 0, result_bootstrap.stderr
    assert "advertisement omitted address" in result_bootstrap.stderr
    assert "WARN: bootstrap advertisement for pi0.local not visible" in result_bootstrap.stderr
    assert (
        "Bootstrap advertisement observed for pi0.local after restarting Avahi publishers."
        in result_bootstrap.stderr
    )

    bootstrap_count_path = run_dir / "publish-bootstrap-count"
    if bootstrap_count_path.exists():
        bootstrap_value = int(bootstrap_count_path.read_text(encoding="utf-8").strip() or "0")
        assert bootstrap_value >= 2

    publish_count = run_dir / "publish-server-count"
    if publish_count.exists():
        publish_count.unlink()

    env_join = env_common.copy()
    env_join.update(
        {
            "SUGARKUBE_MDNS_HOST": "pi1.local",
            "JUST_UP_TEST_PHASE": "join",
            "JUST_UP_FAIL_SERVER_ONCE": "1",
        }
    )

    result_join = subprocess.run(
        ["just", "up", "dev"],
        cwd=REPO_ROOT,
        env=env_join,
        text=True,
        capture_output=True,
    )
    assert result_join.returncode == 0, result_join.stderr
    assert "Joining as additional HA server" in result_join.stderr
    assert "WARN: server advertisement for pi1.local not visible" in result_join.stderr
    assert (
        "Server advertisement observed for pi1.local after restarting Avahi publishers."
        in result_join.stderr
    )

    env_bootstrap_assume = env_common.copy()
    env_bootstrap_assume.update(
        {
            "SUGARKUBE_MDNS_HOST": "pi2.local",
            "JUST_UP_TEST_PHASE": "bootstrap",
            "JUST_UP_SUPPRESS_BOOTSTRAP_BROWSE": "1",
            "JUST_UP_BOOTSTRAP_ADDR": "",
        }
    )

    result_assume = subprocess.run(
        ["just", "up", "dev"],
        cwd=REPO_ROOT,
        env=env_bootstrap_assume,
        text=True,
        capture_output=True,
    )
    assert result_assume.returncode == 0, result_assume.stderr
    assert (
        "WARN: bootstrap advertisement for pi2.local not visible via mDNS; "
        "Avahi publish logs report service establishment; assuming success." in result_assume.stderr
    )
    assert (
        "Bootstrap advertisement assumed visible for pi2.local based on Avahi publish logs."
        in result_assume.stderr
    )

    log_contents = log_path.read_text(encoding="utf-8")
    assert "avahi-publish-service:" in log_contents
    assert "-a" not in log_contents
    assert "avahi-publish-address:" in log_contents
    assert "sudo:apt-get update" in log_contents
    assert "sudo:apt-get install" in log_contents
    assert "glib2.0-bin" in log_contents
    assert "tcpdump" in log_contents
    assert "hosts: files mdns4_minimal" in nsswitch_path.read_text(encoding="utf-8")

    # Ensure both bootstrap and server advertisements were logged
    assert log_contents.count("phase=bootstrap") >= 1
    assert log_contents.count("phase=server") >= 2

    if publish_count.exists():
        count_value = int(publish_count.read_text(encoding="utf-8").strip() or "0")
        assert count_value >= 2
