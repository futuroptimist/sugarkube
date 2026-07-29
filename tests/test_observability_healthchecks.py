import os
import pty
import subprocess
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DELIVERY = ROOT / "scripts/healthchecks_heartbeat.sh"
LIFECYCLE = ROOT / "scripts/observability_healthchecks.sh"
CANARY_UUID = "12345678" + "-1234-4123-8123-123456789abc"
CANARY = "https://hc-ping.com/" + CANARY_UUID


def run_with_tty(command, entered, env):
    master, slave = pty.openpty()
    env = env | {"SUGARKUBE_HEARTBEAT_TEST_TTY": os.ttyname(slave)}
    process = subprocess.Popen(
        command, env=env, stdin=slave, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
    )
    time.sleep(0.1)
    os.write(master, (entered + "\n").encode())
    stdout, stderr = process.communicate(timeout=8)
    os.close(master)
    os.close(slave)
    return process.returncode, stdout, stderr


def lifecycle_env(tmp_path):
    root = tmp_path / "root"
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "hostname").write_text("#!/bin/sh\nprintf 'sugarkube4\\n'\n")
    (bin_dir / "systemctl").write_text(
        '#!/bin/sh\nprintf \'%s\\n\' "$*" >>"$SYSTEMCTL_AUDIT"\n'
        'case "$*" in\n'
        "  *is-enabled*) exit 0 ;;\n"
        "  *'ActiveState --value'*) printf 'inactive\\n' ;;\n"
        "  *'Result --value'*) printf 'success\\n' ;;\n"
        "esac\n"
    )
    for item in bin_dir.iterdir():
        item.chmod(0o755)
    audit = tmp_path / "systemctl.audit"
    return (
        root,
        audit,
        os.environ
        | {
            "PATH": f"{bin_dir}:{os.environ['PATH']}",
            "SUGARKUBE_HEARTBEAT_ROOT": str(root),
            "SUGARKUBE_HEARTBEAT_SYSTEMCTL": str(bin_dir / "systemctl"),
            "SYSTEMCTL_AUDIT": str(audit),
        },
    )


@pytest.mark.parametrize(
    "value",
    [
        "",
        "http://hc-ping.com/x",
        "https://example.com/x",
        "https://hc-ping.com/x",
        CANARY + "/fail",
        CANARY + "/start",
        CANARY + "?x=1",
        CANARY + "#x",
        CANARY + "\nextra",
    ],
)
def test_strict_validation_rejects_invalid_values_without_disclosure(value):
    result = subprocess.run(
        [DELIVERY, "--validate-stdin"],
        input=value + "\n",
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode != 0
    assert not value or value not in result.stdout + result.stderr


def test_strict_validation_accepts_uuid_url_silently():
    result = subprocess.run(
        [DELIVERY, "--validate-stdin"],
        input=CANARY + "\n",
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0
    assert result.stdout == result.stderr == ""


def test_delivery_is_bounded_and_never_puts_secret_in_argv_or_output(tmp_path):
    credentials = tmp_path / "credentials"
    credentials.mkdir()
    (credentials / "healthchecks-url").write_text(CANARY + "\n")
    audit = tmp_path / "audit"
    stub = tmp_path / "curl"
    stub.write_text(f"#!/bin/sh\nprintf '%s\\n' \"$*\" >'{audit}'\ncat >/dev/null\nexit 7\n")
    stub.chmod(0o755)
    env = os.environ | {
        "CREDENTIALS_DIRECTORY": str(credentials),
        "PATH": f"{tmp_path}:{os.environ['PATH']}",
    }
    result = subprocess.run(
        [DELIVERY], env=env, text=True, capture_output=True, check=False, timeout=5
    )
    combined = result.stdout + result.stderr + audit.read_text()
    assert result.returncode != 0
    assert CANARY not in combined and CANARY_UUID not in combined
    assert "--connect-timeout 5" in audit.read_text()
    assert "--max-time 10" in audit.read_text()
    assert "--retry 2" in audit.read_text()


def test_systemd_assets_use_credentials_hardening_and_minute_cadence():
    service = (ROOT / "scripts/systemd/sugarkube-healthchecks-heartbeat.service").read_text()
    timer = (ROOT / "scripts/systemd/sugarkube-healthchecks-heartbeat.timer").read_text()
    assert "LoadCredential=healthchecks-url:" in service
    assert "ExecStart=/usr/local/lib/sugarkube/healthchecks-heartbeat" in service
    assert "NoNewPrivileges=yes" in service and "ProtectSystem=strict" in service
    assert "OnBootSec=20s" in timer and "OnUnitActiveSec=1min" in timer
    assert "Persistent=true" in timer and "WantedBy=timers.target" in timer
    assert CANARY not in service + timer


@pytest.mark.parametrize("environment", ["", "dev", "prod", "production", "env=staging"])
def test_environment_guard_precedes_mutation(environment, tmp_path):
    result = subprocess.run(
        [LIFECYCLE, "install", environment],
        env=os.environ | {"SUGARKUBE_HEARTBEAT_ROOT": str(tmp_path)},
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode != 0
    assert not any(tmp_path.rglob("*"))


def test_just_interface_and_lifecycle_security_contracts():
    justfile = (ROOT / "justfile").read_text()
    lifecycle = LIFECYCLE.read_text()
    for action in ("install", "status", "verify", "uninstall"):
        assert f"observability-heartbeat-{action} env=''" in justfile
    assert 'enable --now "$TIMER"' in lifecycle
    assert lifecycle.index("daemon-reload") < lifecycle.index('enable --now "$TIMER"')
    assert "chmod 0600" in lifecycle and 'mv -f "$tmp" "$credential_path"' in lifecycle
    assert "disable --now" in lifecycle
    assert "Healthchecks.io and PagerDuty configuration was not changed" in lifecycle
    assert "HEALTHCHECKS_URL" in lifecycle and "controlling terminal" in lifecycle


def test_install_rotation_status_verify_and_scoped_uninstall(tmp_path):
    root, audit, env = lifecycle_env(tmp_path)
    code, stdout, stderr = run_with_tty([LIFECYCLE, "install", "staging"], CANARY, env)
    assert code == 0, stderr
    credential = root / "etc/sugarkube/healthchecks-url"
    assert credential.stat().st_mode & 0o777 == 0o600
    assert credential.read_text().strip() == CANARY
    first_audit = audit.read_text()
    assert first_audit.index("daemon-reload") < first_audit.index(
        "enable --now sugarkube-healthchecks-heartbeat.timer"
    )
    assert CANARY not in stdout + stderr + first_audit

    rotated_uuid = "abcdefab" + "-cdef-4abc-8def-abcdefabcdef"
    rotated = "https://hc-ping.com/" + rotated_uuid
    code, stdout, stderr = run_with_tty([LIFECYCLE, "install", "staging"], rotated, env)
    assert code == 0, stderr
    assert credential.read_text().strip() == rotated
    assert credential.stat().st_mode & 0o777 == 0o600
    assert rotated not in stdout + stderr + audit.read_text()

    status = subprocess.run(
        [LIFECYCLE, "status", "staging"], env=env, text=True, capture_output=True, check=False
    )
    assert status.returncode == 0
    assert "hostname=sugarkube4" in status.stdout and "period=1min" in status.stdout
    assert rotated not in status.stdout + status.stderr
    verify = subprocess.run(
        [LIFECYCLE, "verify", "staging"],
        env=env,
        text=True,
        capture_output=True,
        check=False,
        timeout=5,
    )
    assert verify.returncode == 0
    assert "recurring timer remains enabled" in verify.stdout
    assert rotated not in verify.stdout + verify.stderr + audit.read_text()

    unrelated = root / "etc/systemd/system/unrelated.service"
    unrelated.write_text("keep")
    code, stdout, stderr = run_with_tty([LIFECYCLE, "uninstall", "staging"], "sugarkube4", env)
    assert code == 0, stderr
    assert unrelated.read_text() == "keep"
    assert not credential.exists()
    assert not (root / "etc/systemd/system/sugarkube-healthchecks-heartbeat.timer").exists()
    assert "disable --now sugarkube-healthchecks-heartbeat.timer" in audit.read_text()
    assert rotated not in stdout + stderr + audit.read_text()


def test_hostname_guard_and_piped_install_rejection(tmp_path):
    root, audit, env = lifecycle_env(tmp_path)
    hostname_stub = Path(env["PATH"].split(":", 1)[0]) / "hostname"
    hostname_stub.write_text("#!/bin/sh\nprintf 'unexpected-node\\n'\n")
    hostname_stub.chmod(0o755)
    rejected = subprocess.run(
        [LIFECYCLE, "install", "staging"],
        env=env,
        input=CANARY + "\n",
        text=True,
        capture_output=True,
        check=False,
    )
    assert rejected.returncode != 0 and "canonical staging inventory" in rejected.stderr
    assert not audit.exists()
    hostname_stub.write_text("#!/bin/sh\nprintf 'sugarkube3\\n'\n")
    piped = subprocess.run(
        [LIFECYCLE, "install", "staging"],
        env=env,
        input=CANARY + "\n",
        text=True,
        capture_output=True,
        check=False,
    )
    assert piped.returncode != 0 and "interactive terminal" in piped.stderr
    assert CANARY not in piped.stdout + piped.stderr
