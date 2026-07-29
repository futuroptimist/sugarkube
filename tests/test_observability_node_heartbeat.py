from __future__ import annotations

import importlib.util
import stat
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
LIFECYCLE_PATH = ROOT / "scripts/observability_node_heartbeat.py"
DELIVERY_PATH = ROOT / "scripts/sugarkube_healthcheck_heartbeat.py"
SERVICE_PATH = ROOT / "scripts/systemd/sugarkube-healthcheck-heartbeat.service"
TIMER_PATH = ROOT / "scripts/systemd/sugarkube-healthcheck-heartbeat.timer"


def load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def canary_url() -> str:
    # Deliberately assembled so no credential-shaped URL is committed to a fixture.
    uuid = "12345678" + "-1234-4234-a234-" + "123456789abc"
    return "https://" + "hc-ping.com/" + uuid


@pytest.fixture
def lifecycle(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    module = load(LIFECYCLE_PATH, "heartbeat_lifecycle")
    monkeypatch.setenv("SUGARKUBE_HEARTBEAT_TEST_ROOT", str(tmp_path / "root"))
    monkeypatch.setenv("SUGARKUBE_HEARTBEAT_TEST_HOSTNAME", "sugarkube3")
    calls: list[tuple[str, ...]] = []

    def fake_run(*args: str, check: bool = True):
        calls.append(args)
        output = (
            "success\n"
            if "show" in args
            else "enabled\n"
            if "is-enabled" in args
            else "active\n"
        )
        return subprocess.CompletedProcess(args, 0, output, "")

    monkeypatch.setattr(module, "run", fake_run)
    return module, tmp_path / "root", calls


@pytest.mark.parametrize("environment", ["", "dev", "prod", "production", "STAGING"])
def test_environment_guard_fails_closed(lifecycle, environment: str):
    module, _, _ = lifecycle
    with pytest.raises(SystemExit, match="explicit env=staging"):
        module.guard(environment)


def test_hostname_comes_from_canonical_inventory(
    lifecycle, monkeypatch: pytest.MonkeyPatch
):
    module, _, _ = lifecycle
    assert module.guard("staging") == "sugarkube3"
    monkeypatch.setenv("SUGARKUBE_HEARTBEAT_TEST_HOSTNAME", "other-node")
    with pytest.raises(SystemExit, match="canonical staging node inventory"):
        module.guard("staging")


@pytest.mark.parametrize(
    "value",
    [
        "",
        "http://hc-ping.com/x",
        "https://example.com/x",
        "https://hc-ping.com/not-a-uuid",
        "/fail",
        "?x=1",
        "#x",
        "\nextra",
    ],
)
def test_strict_url_validation(
    lifecycle, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, value: str
):
    module, _, _ = lifecycle
    tty = tmp_path / "tty"
    tty.write_text(
        (canary_url() + value) if value.startswith(("/", "?", "#", "\n")) else value
    )
    monkeypatch.setenv("SUGARKUBE_HEARTBEAT_TEST_TTY", str(tty))
    monkeypatch.setattr(
        module.getpass,
        "getpass",
        lambda prompt, stream: stream.read().removesuffix("\n"),
    )
    with pytest.raises(SystemExit, match="canonical HTTPS"):
        module.read_secret()


def test_install_rotation_permissions_order_and_no_secret_leak(
    lifecycle, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys
):
    module, root, calls = lifecycle
    tty = tmp_path / "tty"
    tty.write_text(canary_url() + "\n")
    monkeypatch.setenv("SUGARKUBE_HEARTBEAT_TEST_TTY", str(tty))
    monkeypatch.setattr(
        module.getpass, "getpass", lambda prompt, stream: stream.readline().rstrip("\n")
    )
    module.install("staging")
    credential = root / "etc/sugarkube/healthcheck-ping-url"
    assert stat.S_IMODE(credential.stat().st_mode) == 0o600
    assert calls == [
        ("systemctl", "daemon-reload"),
        ("systemctl", "enable", module.TIMER),
        ("systemctl", "start", module.TIMER),
    ]
    first_inode = credential.stat().st_ino
    tty.write_text(canary_url() + "\n")
    module.install("staging")
    assert credential.stat().st_ino != first_inode
    visible = capsys.readouterr().out + capsys.readouterr().err + repr(calls)
    assert canary_url() not in visible
    assert canary_url().rsplit("/", 1)[1] not in visible
    for path in (root / "etc/systemd/system", root / "usr/local/libexec"):
        assert canary_url() not in "".join(p.read_text() for p in path.iterdir())


def test_exported_secret_and_missing_tty_are_refused(
    lifecycle, monkeypatch: pytest.MonkeyPatch
):
    module, _, _ = lifecycle
    monkeypatch.setenv("SUGARKUBE_HEALTHCHECK_PING_URL", canary_url())
    with pytest.raises(SystemExit, match="exported credentials are refused"):
        module.read_secret()
    monkeypatch.delenv("SUGARKUBE_HEALTHCHECK_PING_URL")
    monkeypatch.delenv("SUGARKUBE_HEARTBEAT_TEST_TTY", raising=False)
    with pytest.raises(SystemExit, match="controlling terminal"):
        module.read_secret()


def test_status_verify_and_uninstall_are_sanitized_and_scoped(lifecycle, capsys):
    module, root, calls = lifecycle
    credential = root / "etc/sugarkube/healthcheck-ping-url"
    credential.parent.mkdir(parents=True)
    credential.write_text(canary_url())
    credential.chmod(0o600)
    unrelated = root / "etc/keep-me"
    unrelated.write_text("untouched")
    module.status("staging")
    module.verify("staging")
    with pytest.raises(SystemExit, match="requires --confirm"):
        module.uninstall("staging", "wrong")
    module.uninstall("staging", "sugarkube3")
    output = capsys.readouterr().out
    assert canary_url() not in output
    assert canary_url().rsplit("/", 1)[1] not in output
    assert unrelated.exists() and not credential.exists()
    assert ("systemctl", "disable", "--now", module.TIMER) in calls
    assert ("systemctl", "start", module.SERVICE) in calls


def test_unit_hardening_credential_and_minute_cadence():
    service = SERVICE_PATH.read_text()
    timer = TIMER_PATH.read_text()
    assert "LoadCredential=ping-url:/etc/sugarkube/healthcheck-ping-url" in service
    assert "ExecStart=/usr/local/libexec/sugarkube-healthcheck-heartbeat" in service
    assert "hc-ping.com" not in service
    for setting in (
        "NoNewPrivileges=yes",
        "ProtectSystem=strict",
        "PrivateTmp=yes",
        "RestrictAddressFamilies=AF_INET AF_INET6",
    ):
        assert setting in service
    assert "OnBootSec=30s" in timer
    assert "OnUnitActiveSec=1min" in timer
    assert "Persistent=true" in timer


def test_missing_systemctl_is_a_sanitized_error(monkeypatch: pytest.MonkeyPatch):
    module = load(LIFECYCLE_PATH, "heartbeat_missing_tool")
    monkeypatch.setattr(
        module.subprocess,
        "run",
        lambda *a, **k: (_ for _ in ()).throw(FileNotFoundError()),
    )
    with pytest.raises(SystemExit, match="required tool 'systemctl' is unavailable"):
        module.run("systemctl", "is-active", module.TIMER)


def test_delivery_rejects_malformed_and_sanitizes_bounded_failure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys
):
    module = load(DELIVERY_PATH, "heartbeat_delivery")
    (tmp_path / "ping-url").write_text(canary_url() + "/fail")
    monkeypatch.setenv("CREDENTIALS_DIRECTORY", str(tmp_path))
    assert module.main() == 1
    assert canary_url() not in capsys.readouterr().err
    (tmp_path / "ping-url").write_text(canary_url())
    attempts = []
    monkeypatch.setattr(module.time, "sleep", lambda _: None)
    monkeypatch.setattr(
        module.urllib.request,
        "urlopen",
        lambda *a, **k: (
            attempts.append((a, k))
            or (_ for _ in ()).throw(OSError("secret-safe failure"))
        ),
    )
    assert module.main() == 1
    assert len(attempts) == module.ATTEMPTS
    assert all(
        call[1]["timeout"] == module.REQUEST_TIMEOUT_SECONDS for call in attempts
    )
    output = capsys.readouterr().err
    assert canary_url() not in output and canary_url().rsplit("/", 1)[1] not in output


def test_secret_scanner_rejects_realistic_healthchecks_url():
    diff = "+++ b/file\n+" + canary_url() + "\n"
    result = subprocess.run(
        [sys.executable, "scripts/scan-secrets.py"],
        input=diff,
        text=True,
        capture_output=True,
        cwd=ROOT,
    )
    assert result.returncode != 0
