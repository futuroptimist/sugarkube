import os
import subprocess
import textwrap
import time
from pathlib import Path

SCRIPT = str(Path(__file__).resolve().parents[2] / "scripts" / "k3s-discover.sh")


def _hostname_short() -> str:
    return subprocess.check_output(["hostname", "-s"], text=True).strip()


def _write_publish_stub(bin_dir: Path, command_log: Path, start_file: Path) -> None:
    script = textwrap.dedent(
        f"""\
        #!/usr/bin/env python3
        import signal
        import sys
        import time
        from pathlib import Path

        command_log = Path({str(command_log)!r})
        start_file = Path({str(start_file)!r})

        cmd = " ".join(sys.argv[1:])
        command_log.write_text(cmd, encoding="utf-8")
        print(f"START:{{cmd}}", flush=True)
        start_file.write_text(str(time.time()), encoding="utf-8")

        def _handler(signum, frame):
            print("TERM", flush=True)
            sys.exit(0)

        signal.signal(signal.SIGTERM, _handler)
        signal.signal(signal.SIGINT, _handler)

        while True:
            time.sleep(1)
        """
    )
    stub = bin_dir / "avahi-publish-service"
    stub.write_text(script, encoding="utf-8")
    stub.chmod(0o755)


def _write_static_browse_stub(bin_dir: Path, lines: list[str]) -> None:
    rendered = "\n".join(lines)
    script = textwrap.dedent(
        f"""\
        #!/usr/bin/env bash
        set -euo pipefail
        cat <<'EOF'
        {rendered}
        EOF
        """
    )
    stub = bin_dir / "avahi-browse"
    stub.write_text(script, encoding="utf-8")
    stub.chmod(0o755)


def _base_env(tmp_path: Path, publish_log: Path) -> dict[str, str]:
    env = os.environ.copy()
    env.update(
        {
            "ALLOW_NON_ROOT": "1",
            "PATH": f"{tmp_path / 'bin'}:{env.get('PATH', '')}",
            "SUGARKUBE_AVAHI_SERVICE_DIR": str(tmp_path / "avahi"),
            "SUGARKUBE_BOOTSTRAP_PUBLISH_LOG": str(publish_log),
            "SUGARKUBE_CLUSTER": "sugar",
            "SUGARKUBE_ENV": "dev",
            "SUGARKUBE_MDNS_SELF_CHECK_ATTEMPTS": "1",
            "SUGARKUBE_MDNS_SELF_CHECK_DELAY": "0",
            "SUGARKUBE_TOKEN": "dummy",
        }
    )
    return env


def test_bootstrap_publish_uses_avahi_publish(tmp_path: Path) -> None:
    hostname = _hostname_short().lower()
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()

    publish_log = tmp_path / "publish.log"
    command_log = tmp_path / "publish_command.txt"
    start_file = tmp_path / "publish_start.txt"

    _write_publish_stub(bin_dir, command_log, start_file)

    _write_static_browse_stub(
        bin_dir,
        [
            (
                "=;eth0;IPv4;"
                f"k3s API sugar/dev [bootstrap] on {hostname};_https._tcp;local;"
                f"{hostname}.local;192.0.2.10;6443;"
                "txt=k3s=1;txt=cluster=sugar;txt=env=dev;txt=role=bootstrap;"
                f"txt=leader={hostname}.local;txt=state=pending;txt=phase=bootstrap"
            )
        ],
    )

    env = _base_env(tmp_path, publish_log)

    result = subprocess.run(
        ["bash", SCRIPT, "--test-bootstrap-publish"],
        env=env,
        text=True,
        capture_output=True,
        check=True,
    )

    log_contents = publish_log.read_text(encoding="utf-8")
    assert "START:" in log_contents
    assert "TERM" in log_contents
    assert "phase=bootstrap" in log_contents
    assert f"leader={hostname}.local" in log_contents
    assert "-H" in log_contents

    cmd_contents = command_log.read_text(encoding="utf-8")
    assert "-H" in cmd_contents
    assert f"leader={hostname}.local" in cmd_contents

    service_file = tmp_path / "avahi" / "k3s-sugar-dev.service"
    assert not service_file.exists()

    assert "phase=self-check status=confirmed" in result.stderr


def test_bootstrap_publish_handles_trailing_dot_hostname(tmp_path: Path) -> None:
    hostname = _hostname_short().lower()
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()

    publish_log = tmp_path / "publish.log"
    command_log = tmp_path / "publish_command.txt"
    start_file = tmp_path / "publish_start.txt"

    _write_publish_stub(bin_dir, command_log, start_file)

    _write_static_browse_stub(
        bin_dir,
        [
            (
                "=;eth0;IPv4;"
                f"k3s API sugar/dev [bootstrap] on {hostname}.local.;_https._tcp;local.;"
                f"{hostname}.LOCAL.;192.0.2.10;6443;"
                "txt=k3s=1;txt=cluster=sugar;txt=env=dev;txt=role=bootstrap;"
                f"txt=leader={hostname}.LOCAL.;txt=state=pending;txt=phase=bootstrap"
            )
        ],
    )

    env = _base_env(tmp_path, publish_log)

    result = subprocess.run(
        ["bash", SCRIPT, "--test-bootstrap-publish"],
        env=env,
        text=True,
        capture_output=True,
        check=True,
    )

    log_contents = publish_log.read_text(encoding="utf-8")
    assert "START:" in log_contents
    assert "TERM" in log_contents
    assert "phase=bootstrap" in log_contents

    assert "phase=self-check status=confirmed" in result.stderr


def test_bootstrap_publish_fails_without_mdns(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()

    publish_log = tmp_path / "publish.log"
    command_log = tmp_path / "publish_command.txt"
    start_file = tmp_path / "publish_start.txt"

    _write_publish_stub(bin_dir, command_log, start_file)

    browse_script = textwrap.dedent(
        """\
        #!/usr/bin/env bash
        set -euo pipefail
        # Emit nothing to simulate missing adverts
        """
    )
    browse = bin_dir / "avahi-browse"
    browse.write_text(browse_script, encoding="utf-8")
    browse.chmod(0o755)

    env = _base_env(tmp_path, publish_log)
    env["SUGARKUBE_MDNS_SELF_CHECK_ATTEMPTS"] = "2"

    result = subprocess.run(
        ["bash", SCRIPT, "--test-bootstrap-publish"],
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode != 0
    assert "phase=self-check status=timeout" in result.stderr

    service_file = tmp_path / "avahi" / "k3s-sugar-dev.service"
    assert not service_file.exists()


def test_publish_binds_host_and_self_check_delays(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()

    publish_log = tmp_path / "publish.log"
    command_log = tmp_path / "publish_command.txt"
    start_file = tmp_path / "publish_start.txt"

    _write_publish_stub(bin_dir, command_log, start_file)

    delay_check = tmp_path / "delay_ok"

    browse_script = textwrap.dedent(
        f"""\
        #!/usr/bin/env python3
        import sys
        import time
        from pathlib import Path

        start_file = Path({str(start_file)!r})
        delay_file = Path({str(delay_check)!r})

        start = float(start_file.read_text(encoding='utf-8'))
        now = time.time()
        if now - start < 0.95:
            print("delay-too-short", file=sys.stderr)
            sys.exit(5)

        delay_file.write_text("ok", encoding='utf-8')

        lines = [
            "=;eth0;IPv4;k3s API sugar/dev [bootstrap] on HostMixed;_https._tcp;local.;",
            "HOSTMIXED.LOCAL.;192.0.2.10;6443;",
            "txt=k3s=1;txt=cluster=sugar;txt=env=dev;txt=role=bootstrap;",
            "txt=leader=HOSTMIXED.LOCAL.;txt=state=pending;txt=phase=bootstrap",
        ]
        for line in lines:
            print(line)
        """
    )
    browse = bin_dir / "avahi-browse"
    browse.write_text(browse_script, encoding="utf-8")
    browse.chmod(0o755)

    env = _base_env(tmp_path, publish_log)
    env.update(
        {
            "SUGARKUBE_MDNS_HOST": "HostMixed.LOCAL.",
            "SUGARKUBE_MDNS_SELF_CHECK_ATTEMPTS": "1",
        }
    )

    result = subprocess.run(
        ["bash", SCRIPT, "--test-bootstrap-publish"],
        env=env,
        text=True,
        capture_output=True,
        check=True,
    )

    log_contents = publish_log.read_text(encoding="utf-8")
    assert "-H HostMixed.LOCAL" in log_contents
    assert "phase=bootstrap" in log_contents

    cmd_contents = command_log.read_text(encoding="utf-8")
    assert "-H HostMixed.LOCAL" in cmd_contents

    assert delay_check.exists()

    assert "phase=self-check status=confirmed" in result.stderr
    assert "host=HostMixed.LOCAL attempt=1/1." in result.stderr
