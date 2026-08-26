import os
import stat
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
LIFECYCLE = ROOT / "scripts" / "observability_node_heartbeat.sh"
DELIVERY = ROOT / "scripts" / "sugarkube-node-heartbeat"
SERVICE = ROOT / "scripts/systemd/sugarkube-node-heartbeat.service"
TIMER = ROOT / "scripts/systemd/sugarkube-node-heartbeat.timer"


def canary():
    uuid = "12345678" + "-1234-4123-8123-123456789abc"
    return "https://" + "hc-ping.com/" + uuid, uuid


@pytest.fixture
def harness(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    calls = tmp_path / "calls"
    systemctl = bin_dir / "systemctl"
    systemctl.write_text(
        """#!/bin/sh
printf '%s\\n' "$*" >>"$CALLS"
case "$1 $2" in
  'is-enabled --quiet'|'is-active --quiet') exit 0 ;;
  'is-enabled '*) echo enabled ;;
  'is-active '*) echo active ;;
  'show '*) echo success ;;
esac
"""
    )
    systemctl.chmod(0o755)
    hostname = bin_dir / "hostname"
    hostname.write_text("#!/bin/sh\nprintf '%s\\n' \"${TEST_HOST:-sugarkube3}\"\n")
    hostname.chmod(0o755)
    tty = tmp_path / "tty"
    tty.write_text("")
    env = os.environ | {
        "SUGARKUBE_HEARTBEAT_ROOT": str(tmp_path / "root"),
        "SUGARKUBE_HEARTBEAT_TTY": str(tty),
        "SUGARKUBE_HEARTBEAT_TEST_NONTTY": "1",
        "SYSTEMCTL_BIN": str(systemctl),
        "HOSTNAME_BIN": str(hostname),
        "CALLS": str(calls),
    }
    return tmp_path, tty, calls, env


def run_lifecycle(harness, action, environment="staging", tty_text=None, **extra):
    _, tty, _, env = harness
    if tty_text is not None:
        tty.write_text(tty_text)
    return subprocess.run(
        [str(LIFECYCLE), action, environment],
        text=True,
        capture_output=True,
        env=env | {key: str(value) for key, value in extra.items()},
        check=False,
    )


@pytest.mark.parametrize("environment", ["", "dev", "production", "bogus"])
def test_environment_guard_precedes_mutation(harness, environment):
    result = run_lifecycle(harness, "install", environment)
    assert result.returncode
    assert "env=staging or env=prod is required" in result.stderr
    assert not harness[2].exists()


def test_hostname_guard_uses_canonical_inventory(harness):
    result = run_lifecycle(harness, "install", TEST_HOST="not-a-node")
    assert result.returncode
    assert "canonical staging node" in result.stderr


@pytest.mark.parametrize("host", ["sugarkube0", "sugarkube1", "sugarkube2"])
def test_production_inventory_accepts_each_node(harness, host):
    url, _ = canary()
    result = run_lifecycle(harness, "install", "prod", tty_text=url + "\n", TEST_HOST=host)
    assert result.returncode == 0, result.stderr
    assert f"Installed node heartbeat for {host}" in result.stdout


def test_production_inventory_rejects_staging_node(harness):
    result = run_lifecycle(harness, "install", "prod", TEST_HOST="sugarkube3")
    assert result.returncode
    assert "canonical prod node" in result.stderr


def test_install_rotation_permissions_order_and_no_canary_leaks(harness):
    url, uuid = canary()
    result = run_lifecycle(harness, "install", tty_text=url + "\n")
    assert result.returncode == 0, result.stderr
    credential = harness[0] / "root/etc/sugarkube/node-heartbeat/ping-url"
    assert credential.read_text() == url + "\n"
    assert stat.S_IMODE(credential.stat().st_mode) == 0o600
    calls = harness[2].read_text().splitlines()
    assert calls == [
        "daemon-reload",
        "enable sugarkube-node-heartbeat.timer",
        "start sugarkube-node-heartbeat.timer",
    ]
    result = run_lifecycle(harness, "install", tty_text=url + "\n")
    assert result.returncode == 0
    public = [result.stdout, result.stderr, harness[2].read_text()]
    public += [
        path.read_text()
        for path in (harness[0] / "root").rglob("*")
        if path.is_file() and path != credential
    ]
    assert all(url not in value and uuid not in value for value in public)


@pytest.mark.parametrize(
    "value",
    [
        "",
        "http://hc-ping.com/not-secret",
        "https://example.invalid/not-secret",
        "https://hc-ping.com/not-a-uuid",
    ],
)
def test_install_rejects_malformed_urls_without_echo(harness, value):
    result = run_lifecycle(harness, "install", tty_text=value + "\n")
    assert result.returncode
    if value:
        assert value not in result.stdout + result.stderr


@pytest.mark.parametrize("suffix", ["/fail", "/start", "?x=y", "#fragment"])
def test_install_rejects_url_extras_and_multiline(harness, suffix):
    url, _ = canary()
    result = run_lifecycle(harness, "install", tty_text=url + suffix + "\n")
    assert result.returncode
    assert url not in result.stdout + result.stderr


def test_install_refuses_environment_secret(harness):
    url, _ = canary()
    result = run_lifecycle(harness, "install", tty_text=url + "\n", PING_URL=url)
    assert result.returncode
    assert "environment variables are refused" in result.stderr
    assert url not in result.stdout + result.stderr


def test_status_and_verify_are_sanitized(harness):
    url, uuid = canary()
    assert run_lifecycle(harness, "install", tty_text=url + "\n").returncode == 0
    for action in ("status", "verify"):
        result = run_lifecycle(harness, action)
        assert result.returncode == 0, result.stderr
        assert url not in result.stdout + result.stderr
        assert uuid not in result.stdout + result.stderr
    assert "start sugarkube-node-heartbeat.service" in harness[2].read_text()


def test_uninstall_confirmation_and_scope(harness):
    url, _ = canary()
    assert run_lifecycle(harness, "install", tty_text=url + "\n").returncode == 0
    unrelated = harness[0] / "root/etc/systemd/system/unrelated.service"
    unrelated.write_text("keep")
    cancelled = run_lifecycle(harness, "uninstall", tty_text="no\n")
    assert cancelled.returncode
    result = run_lifecycle(harness, "uninstall", tty_text="uninstall\n")
    assert result.returncode == 0
    assert unrelated.read_text() == "keep"
    assert not (harness[0] / "root/etc/sugarkube/node-heartbeat/ping-url").exists()
    assert "disable --now sugarkube-node-heartbeat.timer" in harness[2].read_text()


def test_unit_assets_cadence_credentials_and_hardening():
    service = SERVICE.read_text()
    timer = TIMER.read_text()
    assert "LoadCredential=ping-url:/etc/sugarkube/node-heartbeat/ping-url" in service
    assert "ExecStart=/usr/local/libexec/sugarkube-node-heartbeat" in service
    assert "ProtectSystem=strict" in service
    assert "OnBootSec=30s" in timer
    assert "OnUnitActiveSec=1min" in timer
    assert "Persistent=true" in timer


def test_delivery_keeps_secret_out_of_argv_output_and_bounds_failure(tmp_path):
    url, uuid = canary()
    credential_dir = tmp_path / "credentials"
    credential_dir.mkdir()
    (credential_dir / "ping-url").write_text(url + "\n")
    argv_log = tmp_path / "argv"
    curl = tmp_path / "curl"
    curl.write_text("#!/bin/sh\nprintf '%s\\n' \"$*\" >\"$ARGV_LOG\"\ncat >/dev/null\nexit 7\n")
    curl.chmod(0o755)
    result = subprocess.run(
        [str(DELIVERY)],
        text=True,
        capture_output=True,
        env=os.environ
        | {
            "CREDENTIALS_DIRECTORY": str(credential_dir),
            "PATH": f"{tmp_path}:{os.environ['PATH']}",
            "ARGV_LOG": str(argv_log),
        },
        check=False,
    )
    assert result.returncode
    assert "delivery failed" in result.stderr
    evidence = result.stdout + result.stderr + argv_log.read_text()
    assert url not in evidence and uuid not in evidence
    args = argv_log.read_text()
    assert "--connect-timeout 5" in args
    assert "--max-time 15" in args
    assert "--retry 2" in args


@pytest.mark.parametrize("trailing_newline", [False, True])
def test_delivery_accepts_single_line_credential(tmp_path, trailing_newline):
    url, _ = canary()
    credential_dir = tmp_path / "credentials"
    credential_dir.mkdir()
    (credential_dir / "ping-url").write_text(url + ("\n" if trailing_newline else ""))
    curl = tmp_path / "curl"
    curl.write_text("#!/bin/sh\ncat >/dev/null\n")
    curl.chmod(0o755)
    result = subprocess.run(
        [str(DELIVERY)],
        text=True,
        capture_output=True,
        env=os.environ
        | {
            "CREDENTIALS_DIRECTORY": str(credential_dir),
            "PATH": f"{tmp_path}:{os.environ['PATH']}",
        },
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "delivered successfully" in result.stdout


def test_delivery_rejects_multiline_credential_without_running_curl(tmp_path):
    url, uuid = canary()
    credential_dir = tmp_path / "credentials"
    credential_dir.mkdir()
    (credential_dir / "ping-url").write_text(url + "\nextra\n")
    result = subprocess.run(
        [str(DELIVERY)],
        text=True,
        capture_output=True,
        env=os.environ | {"CREDENTIALS_DIRECTORY": str(credential_dir)},
        check=False,
    )
    assert result.returncode
    assert "format is invalid" in result.stderr
    assert url not in result.stdout + result.stderr
    assert uuid not in result.stdout + result.stderr


def test_delivery_rejects_blank_extra_line_without_leaking_canary(tmp_path):
    url, uuid = canary()
    credential_dir = tmp_path / "credentials"
    credential_dir.mkdir()
    (credential_dir / "ping-url").write_text(url + "\n\n")
    result = subprocess.run(
        [str(DELIVERY)],
        text=True,
        capture_output=True,
        env=os.environ | {"CREDENTIALS_DIRECTORY": str(credential_dir)},
        check=False,
    )
    assert result.returncode
    assert url not in result.stdout + result.stderr
    assert uuid not in result.stdout + result.stderr


def test_delivery_rejects_second_line_without_trailing_newline(tmp_path):
    url, _ = canary()
    credential_dir = tmp_path / "credentials"
    credential_dir.mkdir()
    (credential_dir / "ping-url").write_text(url + "\nextra")
    result = subprocess.run(
        [str(DELIVERY)],
        text=True,
        capture_output=True,
        env=os.environ | {"CREDENTIALS_DIRECTORY": str(credential_dir)},
        check=False,
    )
    assert result.returncode
    assert "format is invalid" in result.stderr


@pytest.mark.parametrize("content", ["", "\n", "\n\n"])
def test_delivery_rejects_empty_or_blank_credentials(tmp_path, content):
    credential_dir = tmp_path / "credentials"
    credential_dir.mkdir()
    (credential_dir / "ping-url").write_text(content)
    result = subprocess.run(
        [str(DELIVERY)],
        text=True,
        capture_output=True,
        env=os.environ | {"CREDENTIALS_DIRECTORY": str(credential_dir)},
        check=False,
    )
    assert result.returncode
    assert "credential" in result.stderr


def test_delivery_rejects_trailing_bytes_without_leaking_canary(tmp_path):
    url, uuid = canary()
    credential_dir = tmp_path / "credentials"
    credential_dir.mkdir()
    (credential_dir / "ping-url").write_text(url + " ")
    result = subprocess.run(
        [str(DELIVERY)],
        text=True,
        capture_output=True,
        env=os.environ | {"CREDENTIALS_DIRECTORY": str(credential_dir)},
        check=False,
    )
    assert result.returncode
    assert url not in result.stdout + result.stderr
    assert uuid not in result.stdout + result.stderr


def test_verify_requires_root_before_systemctl_mutation():
    script = LIFECYCLE.read_text()
    verify_body = script.split("verify_heartbeat() {", 1)[1].split("\n}", 1)[0]
    assert verify_body.index("require_root") < verify_body.index('"${SYSTEMCTL}" start')


def test_missing_systemctl_is_actionable(harness):
    result = run_lifecycle(harness, "status", SYSTEMCTL_BIN="definitely-not-a-tool")
    assert result.returncode
    assert "required tool is missing" in result.stderr


def test_justfile_exposes_node_heartbeat_recipes():
    text = (ROOT / "justfile").read_text()
    for action in ("install", "status", "verify", "uninstall"):
        assert f"observability-node-heartbeat-{action} env=''" in text


def test_operations_runbook_uses_privilege_for_all_lifecycle_commands():
    operations = (ROOT / "docs/observability-operations.md").read_text()
    for action in ("install", "status", "verify", "uninstall"):
        command = f"sudo just observability-node-heartbeat-{action} env=staging"
        assert command in operations
