import fcntl
import os
import pty
import select
import stat
import subprocess
import termios
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
LIFECYCLE = ROOT / "scripts/observability_node_heartbeat.sh"
DELIVERY = ROOT / "scripts/healthchecks-heartbeat.sh"
UUID = "12345678-1234-" + "4234-8234-123456789abc"
CANARY = "https://hc-ping.com/" + UUID


def stub_tools(tmp_path, hostname="sugarkube4"):
    bindir = tmp_path / "bin"
    bindir.mkdir()
    audit = tmp_path / "audit"
    (bindir / "hostname").write_text(f"#!/bin/sh\nprintf '%s\\n' {hostname}\n")
    (bindir / "systemctl").write_text(
        '#!/bin/sh\nprintf \'%s\\n\' "$*" >>"$AUDIT"\n'
        'case "$1 $2" in\n'
        " 'is-enabled --quiet'|'is-active --quiet') exit 0;;\n"
        " 'is-enabled sugarkube-healthchecks-heartbeat.timer') echo enabled;;\n"
        " 'is-active sugarkube-healthchecks-heartbeat.timer') echo active;;\n"
        " 'show sugarkube-healthchecks-heartbeat.service') echo success;;\n"
        "esac\n"
    )
    for item in bindir.iterdir():
        item.chmod(0o755)
    env = os.environ | {
        "PATH": f"{bindir}:{os.environ['PATH']}",
        "AUDIT": str(audit),
        "SUGARKUBE_HOSTNAME_CMD": str(bindir / "hostname"),
        "SUGARKUBE_SYSTEMCTL": str(bindir / "systemctl"),
        "SUGARKUBE_HEARTBEAT_ROOT": str(tmp_path / "root"),
    }
    return env, audit


def run(action, env, environment="staging"):
    return subprocess.run(
        [str(LIFECYCLE), action, environment],
        env=env,
        text=True,
        capture_output=True,
        timeout=5,
        check=False,
    )


@pytest.mark.parametrize("environment", ["", "prod", "production", "dev", "mystery"])
def test_environment_guard_precedes_mutation(tmp_path, environment):
    env, audit = stub_tools(tmp_path)
    result = run("status", env, environment)
    assert result.returncode == 2
    assert "env=staging explicitly" in result.stderr
    assert not audit.exists()


def test_hostname_guard_uses_canonical_inventory(tmp_path):
    env, audit = stub_tools(tmp_path, "not-a-staging-node")
    result = run("uninstall", env)
    assert result.returncode == 2
    assert "not a canonical staging node" in result.stderr
    assert not audit.exists()


def test_missing_systemctl_has_actionable_error(tmp_path):
    env, _ = stub_tools(tmp_path)
    env["SUGARKUBE_SYSTEMCTL"] = str(tmp_path / "missing-systemctl")
    result = run("status", env)
    assert result.returncode == 2
    assert "required tool is unavailable" in result.stderr


def test_install_rejects_noninteractive_input(tmp_path):
    env, _ = stub_tools(tmp_path)
    result = subprocess.run(
        [str(LIFECYCLE), "install", "staging"],
        input=CANARY + "\n",
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 2
    assert "controlling terminal" in result.stderr
    assert CANARY not in result.stdout + result.stderr


def interactive_install(tmp_path, env, secret=CANARY):
    master, slave = pty.openpty()

    def make_controlling_terminal():
        os.setsid()
        fcntl.ioctl(0, termios.TIOCSCTTY, 0)

    process = subprocess.Popen(
        [str(LIFECYCLE), "install", "staging"],
        stdin=slave,
        stdout=slave,
        stderr=slave,
        env=env,
        close_fds=True,
        preexec_fn=make_controlling_terminal,
    )
    os.close(slave)
    output = b""
    deadline = time.monotonic() + 5
    while b"Rotated Healthchecks.io ping URL:" not in output:
        assert time.monotonic() < deadline
        ready, _, _ = select.select([master], [], [], 0.2)
        if ready:
            try:
                output += os.read(master, 4096)
            except OSError:
                break
    os.write(master, secret.encode() + b"\n")
    while process.poll() is None:
        ready, _, _ = select.select([master], [], [], 0.2)
        if ready:
            try:
                output += os.read(master, 4096)
            except OSError:
                break
    try:
        while True:
            output += os.read(master, 4096)
    except OSError:
        pass
    os.close(master)
    return process.wait(timeout=5), output.decode(errors="replace")


def test_atomic_install_rotation_order_and_secret_canary(tmp_path):
    env, audit = stub_tools(tmp_path)
    rc, output = interactive_install(tmp_path, env)
    assert rc == 0
    credential = tmp_path / "root/etc/sugarkube/healthchecks-heartbeat.url"
    assert credential.read_text().strip() == CANARY
    assert stat.S_IMODE(credential.stat().st_mode) == 0o600
    assert CANARY not in output
    commands = audit.read_text()
    expected_order = (
        "daemon-reload\n"
        "enable sugarkube-healthchecks-heartbeat.timer\n"
        "start sugarkube-healthchecks-heartbeat.timer"
    )
    assert expected_order in commands
    assert CANARY not in commands and UUID not in commands
    new = "https://hc-ping.com/" + "abcdefab-cdef-" + "4abc-8def-abcdefabcdef"
    rc, output = interactive_install(tmp_path, env, new)
    assert rc == 0 and credential.read_text().strip() == new
    for path in (tmp_path / "root").rglob("*"):
        if path.is_file() and path != credential:
            content = path.read_text(errors="ignore")
            assert CANARY not in content and UUID not in content


@pytest.mark.parametrize(
    "bad",
    [
        "",
        "http://hc-ping.com/x",
        "https://example.com/" + UUID,
        CANARY + "/fail",
        CANARY + "/start",
        CANARY + "?x=1",
        CANARY + "#x",
        CANARY + "\nextra",
    ],
)
def test_strict_url_validation_is_redacted(tmp_path, bad):
    env, audit = stub_tools(tmp_path)
    rc, output = interactive_install(tmp_path, env, bad)
    assert rc != 0
    if bad:
        assert bad not in output
    assert not audit.exists()


def test_status_verify_and_uninstall_are_sanitized_and_scoped(tmp_path):
    env, audit = stub_tools(tmp_path)
    rc, _ = interactive_install(tmp_path, env)
    assert rc == 0
    unrelated = tmp_path / "root/etc/sugarkube/unrelated"
    unrelated.write_text("keep")
    for action in ("status", "verify"):
        result = run(action, env)
        assert result.returncode == 0
        assert CANARY not in result.stdout + result.stderr
        assert UUID not in result.stdout + result.stderr
    denied = run("uninstall", env)
    assert denied.returncode != 0
    env["SUGARKUBE_HEARTBEAT_CONFIRM"] = "REMOVE"
    removed = run("uninstall", env)
    assert removed.returncode == 0 and unrelated.read_text() == "keep"
    assert not (tmp_path / "root/etc/sugarkube/healthchecks-heartbeat.url").exists()


def test_units_have_credentials_cadence_and_hardening():
    service = (ROOT / "scripts/systemd/sugarkube-healthchecks-heartbeat.service").read_text()
    timer = (ROOT / "scripts/systemd/sugarkube-healthchecks-heartbeat.timer").read_text()
    assert "LoadCredential=ping-url:" in service
    assert "ExecStart=/usr/local/libexec/sugarkube-healthchecks-heartbeat" in service
    assert "hc-ping" not in service and "ProtectSystem=strict" in service
    assert "OnBootSec=30s" in timer and "OnUnitActiveSec=1min" in timer
    assert "Persistent=true" in timer


def test_delivery_failure_is_bounded_and_redacted(tmp_path):
    credential_dir = tmp_path / "credentials"
    credential_dir.mkdir()
    (credential_dir / "ping-url").write_text(CANARY + "\n")
    # The production script fixes curl's absolute path; inspect its finite bounds
    # and exercise rejection before network access deterministically.
    source = DELIVERY.read_text()
    assert "--connect-timeout 3" in source and "--max-time 10" in source
    assert "--retry 2" in source and "--retry-max-time 25" in source
    (credential_dir / "ping-url").write_text(CANARY + "/fail\n")
    result = subprocess.run(
        [str(DELIVERY)],
        env=os.environ | {"CREDENTIALS_DIRECTORY": str(credential_dir)},
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode != 0
    assert CANARY not in result.stdout + result.stderr
