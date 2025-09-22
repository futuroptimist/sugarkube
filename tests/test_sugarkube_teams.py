import importlib.util
import json
import sys
from pathlib import Path

import pytest

MODULE_PATH = Path(__file__).resolve().parent.parent / "scripts" / "sugarkube_teams.py"
SPEC = importlib.util.spec_from_file_location("sugarkube_teams", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)  # type: ignore[arg-type]


def test_render_messages_formats_metadata():
    plain, html_message = MODULE.render_messages(
        "first-boot",
        "success",
        "Checks completed",
        metadata={"overall": "pass", "summary": {"k3s": "pass"}},
        label="pi-a",
    )
    assert plain.startswith("✅ pi-a · first-boot: Checks completed")
    assert "- overall: pass" in plain
    assert json.dumps({"k3s": "pass"}, sort_keys=True) in plain
    assert "<li><code>overall</code>" in html_message
    assert "Checks completed" in html_message


def test_notify_event_dry_run_prints(monkeypatch, capsys):
    delivered = MODULE.notify_event(
        "ssd-clone",
        "info",
        "Dry run",
        destinations=MODULE.Destinations(webhook_url=None, matrix=None),
        dry_run=True,
    )
    assert delivered is True
    captured = capsys.readouterr()
    assert "ssd-clone" in captured.out


def test_notify_event_targets_all_destinations(monkeypatch):
    calls = []

    def fake_webhook(url, message, timeout):  # noqa: ANN001 - signature defined by module
        calls.append(("webhook", url, timeout, message))

    def fake_matrix(config, plain, html_message):  # noqa: ANN001
        calls.append(("matrix", config.homeserver, config.room, plain, html_message))

    monkeypatch.setattr(MODULE, "send_webhook", fake_webhook)
    monkeypatch.setattr(MODULE, "send_matrix", fake_matrix)

    destinations = MODULE.Destinations(
        webhook_url="https://example.com/hook",
        matrix=MODULE.MatrixConfig(
            homeserver="https://matrix.example.com",
            room="!room:matrix.example.com",
            auth_key="token",
            timeout=5.0,
        ),
    )

    delivered = MODULE.notify_event(
        "ssd-clone",
        "warning",
        "No target",
        metadata={"hostname": "pi-a"},
        destinations=destinations,
        timeout=3.0,
    )

    assert delivered is True
    assert calls[0][0] == "webhook"
    assert calls[1][0] == "matrix"
    assert calls[0][2] == 3.0
    assert "pi-a" in calls[1][3]


def test_destinations_from_env(monkeypatch):
    monkeypatch.setenv("SUGARKUBE_TEAMS_WEBHOOK_URL", "https://example.com/hook")
    monkeypatch.setenv("SUGARKUBE_MATRIX_HOMESERVER", "https://matrix.example.com")
    monkeypatch.setenv("SUGARKUBE_MATRIX_ROOM", "!room:matrix.example.com")
    monkeypatch.setenv("SUGARKUBE_MATRIX_ACCESS_TOKEN", "token")
    dest = MODULE.destinations_from_env()
    assert dest.webhook_url == "https://example.com/hook"
    assert dest.matrix is not None
    assert dest.matrix.homeserver == "https://matrix.example.com"
    assert dest.matrix.room == "!room:matrix.example.com"
    assert dest.matrix.auth_key == "token"


def test_destinations_from_env_rejects_bad_timeout(monkeypatch):
    monkeypatch.setenv("SUGARKUBE_MATRIX_HOMESERVER", "https://matrix.example.com")
    monkeypatch.setenv("SUGARKUBE_MATRIX_ROOM", "!room:matrix.example.com")
    monkeypatch.setenv("SUGARKUBE_MATRIX_ACCESS_TOKEN", "token")
    monkeypatch.setenv("SUGARKUBE_MATRIX_TIMEOUT", "not-a-number")
    with pytest.raises(MODULE.NotificationError):
        MODULE.destinations_from_env()
