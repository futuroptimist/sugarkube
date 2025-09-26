import importlib.util
import json
import runpy
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import List, Tuple

import pytest

MODULE_PATH = Path(__file__).resolve().parent.parent / "scripts" / "sugarkube_teams.py"
SPEC = importlib.util.spec_from_file_location("scripts.sugarkube_teams", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules.setdefault("scripts.sugarkube_teams", MODULE)
sys.modules.setdefault("sugarkube_teams", MODULE)
SPEC.loader.exec_module(MODULE)  # type: ignore[arg-type]


class _Recorder(BaseHTTPRequestHandler):
    records: List[Tuple[str, bytes, str]] = []

    def do_POST(self):  # noqa: N802 - http.server naming
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length)
        _Recorder.records.append((self.command, body, self.path))
        self.send_response(200)
        self.end_headers()

    def do_PUT(self):  # noqa: N802 - http.server naming
        self.do_POST()

    def log_message(self, *_args, **_kwargs):  # pragma: no cover - quiet test output
        return


@pytest.fixture()
def http_server(tmp_path):
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Recorder)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        thread.join()
        _Recorder.records.clear()


def _write_env(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "teams.env"
    path.write_text(text)
    return path


def test_slack_notification(monkeypatch, tmp_path, http_server):
    env_path = _write_env(
        tmp_path,
        "\n".join(
            [
                'SUGARKUBE_TEAMS_ENABLE="true"',
                f'SUGARKUBE_TEAMS_URL="http://127.0.0.1:{http_server.server_port}"',
                'SUGARKUBE_TEAMS_USERNAME="tester"',
            ]
        ),
    )
    monkeypatch.setenv("SUGARKUBE_TEAMS_ENV", str(env_path))
    notifier = MODULE.TeamsNotifier.from_env()
    notifier.notify(
        event="first-boot",
        status="success",
        lines=["Test slack"],
        fields={"Overall": "PASS"},
    )
    assert len(_Recorder.records) == 1
    method, body, path = _Recorder.records[0]
    assert method == "POST"
    assert path == "/"
    payload = json.loads(body)
    assert "Sugarkube first boot" in payload["text"]
    assert payload["username"] == "tester"
    assert payload["attachments"][0]["fields"][0]["title"] == "Overall"


def test_matrix_notification(monkeypatch, tmp_path, http_server):
    env_path = _write_env(
        tmp_path,
        "\n".join(
            [
                'SUGARKUBE_TEAMS_ENABLE="true"',
                'SUGARKUBE_TEAMS_KIND="matrix"',
                f'SUGARKUBE_TEAMS_URL="http://127.0.0.1:{http_server.server_port}"',
                'SUGARKUBE_TEAMS_MATRIX_ROOM="!room:example.org"',
            ]
        ),
    )
    monkeypatch.setenv("SUGARKUBE_TEAMS_ENV", str(env_path))
    monkeypatch.setenv("SUGARKUBE_TEAMS_TOKEN", "syt_secret")
    notifier = MODULE.TeamsNotifier.from_env()
    notifier.notify(
        event="ssd-clone",
        status="failed",
        lines=["Return code: 2"],
        fields={"Target": "/dev/sda"},
    )
    assert len(_Recorder.records) == 1
    method, body, path = _Recorder.records[0]
    assert method == "PUT"
    assert path.startswith("/_matrix/client/v3/rooms/%21room%3Aexample.org/send/m.room.message/")
    payload = json.loads(body)
    assert payload["msgtype"] == "m.notice"
    assert "Return code: 2" in payload["body"]
    assert "Target" in payload["formatted_body"]


def test_disabled_notification_skips_requests(monkeypatch, tmp_path, http_server):
    env_path = _write_env(
        tmp_path,
        "\n".join(
            [
                'SUGARKUBE_TEAMS_ENABLE="false"',
                f'SUGARKUBE_TEAMS_URL="http://127.0.0.1:{http_server.server_port}"',
            ]
        ),
    )
    monkeypatch.setenv("SUGARKUBE_TEAMS_ENV", str(env_path))
    notifier = MODULE.TeamsNotifier.from_env()
    notifier.notify(event="first-boot", status="success", lines=["skip"], fields={})
    assert _Recorder.records == []


def test_open_request_without_tls(monkeypatch):
    called = {}

    def fake_urlopen(_request, *, context, timeout):  # noqa: ARG001 - signature compliance
        called["context"] = context
        called["timeout"] = timeout
        return context

    class DummyResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):  # noqa: ANN001
            return False

        def read(self):
            return b"ok"

    def wrapped_urlopen(*args, **kwargs):  # noqa: ANN001 - forwarded args
        fake_urlopen(*args, **kwargs)
        return DummyResponse()

    monkeypatch.setattr(MODULE.urllib.request, "urlopen", wrapped_urlopen)
    request = MODULE.urllib.request.Request("https://example.invalid")
    MODULE._open_request(request, verify_tls=False, timeout=2.5)  # noqa: SLF001
    context = called["context"]
    assert context is not None
    assert context.check_hostname is False
    assert context.verify_mode == MODULE.ssl.CERT_NONE
    assert called["timeout"] == 2.5


def test_discord_notification(monkeypatch, tmp_path, http_server):
    env_path = _write_env(
        tmp_path,
        "\n".join(
            [
                'SUGARKUBE_TEAMS_ENABLE="true"',
                'SUGARKUBE_TEAMS_KIND="discord"',
                f'SUGARKUBE_TEAMS_URL="http://127.0.0.1:{http_server.server_port}"',
                'SUGARKUBE_TEAMS_USERNAME="Sugarkube"',
                'SUGARKUBE_TEAMS_ICON="https://example.com/icon.png"',
            ]
        ),
    )
    monkeypatch.setenv("SUGARKUBE_TEAMS_ENV", str(env_path))
    notifier = MODULE.TeamsNotifier.from_env()
    notifier.notify(
        event="first-boot",
        status="info",
        lines=["Disk resized", "Services online"],
        fields={"Overall": "PASS", "K3s": "Ready"},
    )
    assert len(_Recorder.records) == 1
    method, body, _path = _Recorder.records[0]
    assert method == "POST"
    payload = json.loads(body)
    assert payload["content"].startswith("\u2139\ufe0f Sugarkube first boot")
    assert payload["username"] == "Sugarkube"
    assert payload["avatar_url"] == "https://example.com/icon.png"
    embed = payload["embeds"][0]
    assert embed["title"].startswith("\u2139\ufe0f Sugarkube first boot")
    assert "Disk resized" in embed["description"]
    field_names = {field["name"] for field in embed["fields"]}
    assert field_names == {"Overall", "K3s"}


def test_parse_env_file_missing(tmp_path):
    path = tmp_path / "missing.env"
    assert MODULE._parse_env_file(path) == {}  # noqa: SLF001


def test_parse_env_file_ignores_comments(tmp_path):
    path = tmp_path / "env"
    path.write_text("# comment\nKEY=value\ninvalid-line\n")
    data = MODULE._parse_env_file(path)  # noqa: SLF001
    assert data == {"KEY": "value"}


def test_format_heading_without_emoji():
    heading = MODULE._format_heading("custom", "alert")  # noqa: SLF001
    assert heading.startswith("Sugarkube")


def test_build_plaintext_empty_lines():
    message = MODULE._build_plaintext("Heading", ["", " "])  # noqa: SLF001
    assert message == "Heading"


def test_send_slack_requires_url():
    config = MODULE.TeamsConfig(
        enable=True,
        url="",
        kind="slack",
        timeout=1.0,
        verify_tls=True,
        username=None,
        icon=None,
        matrix_room=None,
        auth_credential=None,
    )
    with pytest.raises(MODULE.TeamsNotificationError):
        MODULE._send_slack(config, "hello", {})  # noqa: SLF001


def test_send_slack_error(monkeypatch):
    config = MODULE.TeamsConfig(
        enable=True,
        url="https://example.invalid",
        kind="slack",
        timeout=1.0,
        verify_tls=True,
        username="user",
        icon=":icon:",
        matrix_room=None,
        auth_credential=None,
    )

    def raise_error(*args, **kwargs):  # noqa: ANN001
        raise MODULE.urllib.error.URLError("bad")

    monkeypatch.setattr(MODULE, "_open_request", raise_error)
    with pytest.raises(MODULE.TeamsNotificationError):
        MODULE._send_slack(config, "hi", {"Field": "Value"})  # noqa: SLF001


def test_send_matrix_requires_all_config():
    config = MODULE.TeamsConfig(
        enable=True,
        url="https://matrix.invalid",
        kind="matrix",
        timeout=1.0,
        verify_tls=True,
        username=None,
        icon=None,
        matrix_room=None,
        auth_credential=None,
    )
    with pytest.raises(MODULE.TeamsNotificationError):
        MODULE._send_matrix(config, "heading", [], {})  # noqa: SLF001


def test_send_matrix_error(monkeypatch):
    config = MODULE.TeamsConfig(
        enable=True,
        url="https://matrix.invalid",
        kind="matrix",
        timeout=1.0,
        verify_tls=True,
        username=None,
        icon=None,
        matrix_room="!room:example",
        auth_credential="token",
    )

    def raise_error(*args, **kwargs):  # noqa: ANN001
        raise MODULE.urllib.error.URLError("bad")

    monkeypatch.setattr(MODULE, "_open_request", raise_error)
    with pytest.raises(MODULE.TeamsNotificationError):
        MODULE._send_matrix(config, "heading", [], {})  # noqa: SLF001


def test_send_discord_requires_url():
    config = MODULE.TeamsConfig(
        enable=True,
        url="",
        kind="discord",
        timeout=1.0,
        verify_tls=True,
        username=None,
        icon=None,
        matrix_room=None,
        auth_credential=None,
    )
    with pytest.raises(MODULE.TeamsNotificationError):
        MODULE._send_discord(config, "heading", [], {})  # noqa: SLF001


def test_send_discord_error(monkeypatch):
    config = MODULE.TeamsConfig(
        enable=True,
        url="https://discord.invalid",
        kind="discord",
        timeout=1.0,
        verify_tls=True,
        username=None,
        icon=None,
        matrix_room=None,
        auth_credential=None,
    )

    def raise_error(*args, **kwargs):  # noqa: ANN001
        raise MODULE.urllib.error.URLError("bad")

    monkeypatch.setattr(MODULE, "_open_request", raise_error)
    with pytest.raises(MODULE.TeamsNotificationError):
        MODULE._send_discord(config, "heading", [], {})  # noqa: SLF001


def test_load_config_env_precedence(tmp_path):
    env_path = _write_env(
        tmp_path,
        "\n".join(
            [
                "SUGARKUBE_TEAMS_ENABLE=yes",
                "SUGARKUBE_TEAMS_URL=https://example.invalid/webhook",
                "SUGARKUBE_TEAMS_KIND=matrix",
                "SUGARKUBE_TEAMS_TIMEOUT=5.5",
                "SUGARKUBE_TEAMS_VERIFY_TLS=no",
                "SUGARKUBE_TEAMS_USERNAME=from-file",
                "SUGARKUBE_TEAMS_ICON=from-file",
                "SUGARKUBE_TEAMS_MATRIX_ROOM=!room:file",
            ]
        ),
    )
    config = MODULE.load_config(
        {
            "SUGARKUBE_TEAMS_ENV": str(env_path),
            "SUGARKUBE_TEAMS_USERNAME": "override",
            "SUGARKUBE_TEAMS_TOKEN": "secret",
        }
    )
    assert config.enable is True
    assert config.url == "https://example.invalid/webhook"
    assert config.kind == "matrix"
    assert config.timeout == 5.5
    assert config.verify_tls is False
    assert config.username == "override"
    assert config.icon == "from-file"
    assert config.matrix_room == "!room:file"
    assert config.auth_credential == "secret"


def test_load_config_invalid_timeout(tmp_path):
    env_path = _write_env(
        tmp_path,
        "\n".join(
            [
                "SUGARKUBE_TEAMS_ENABLE=true",
                "SUGARKUBE_TEAMS_TIMEOUT=abc",
            ]
        ),
    )
    with pytest.raises(MODULE.TeamsNotificationError):
        MODULE.load_config({"SUGARKUBE_TEAMS_ENV": str(env_path)})


def test_parse_fields_error():
    with pytest.raises(MODULE.TeamsNotificationError):
        MODULE._parse_fields(["missing-value"])  # noqa: SLF001


def test_parse_fields_success():
    fields = MODULE._parse_fields(["Key=Value", "Other = Data"])  # noqa: SLF001
    assert fields == {"Key": "Value", "Other": "Data"}


def test_main_handles_notification_error(monkeypatch, tmp_path, capsys):
    env_path = _write_env(
        tmp_path,
        "\n".join(
            [
                "SUGARKUBE_TEAMS_ENABLE=true",
                "SUGARKUBE_TEAMS_URL=https://example.invalid",
            ]
        ),
    )

    class FailingNotifier:
        enabled = True

        @classmethod
        def from_env(cls):  # noqa: D401, ANN101, ANN201 - simple stub
            return cls()

        def notify(self, **_kwargs):  # noqa: D401, ANN101, ANN204 - stub method
            raise MODULE.TeamsNotificationError("boom")

    monkeypatch.setenv("SUGARKUBE_TEAMS_ENV", str(env_path))
    monkeypatch.setattr(MODULE, "TeamsNotifier", FailingNotifier)
    result = MODULE.main(["--event", "first-boot", "--status", "info"])
    assert result == 1
    captured = capsys.readouterr()
    assert "sugarkube-teams error" in captured.err


def test_main_success(monkeypatch, tmp_path):
    env_path = _write_env(
        tmp_path,
        "\n".join(
            [
                "SUGARKUBE_TEAMS_ENABLE=true",
                "SUGARKUBE_TEAMS_URL=https://example.invalid",
            ]
        ),
    )

    class QuietNotifier:
        enabled = True

        @classmethod
        def from_env(cls):  # noqa: ANN101, ANN201
            return cls()

        def notify(self, **_kwargs):  # noqa: ANN101, ANN204
            return None

    monkeypatch.setenv("SUGARKUBE_TEAMS_ENV", str(env_path))
    monkeypatch.setattr(MODULE, "TeamsNotifier", QuietNotifier)
    assert MODULE.main(["--event", "first-boot", "--status", "success"]) == 0


def test_main_warns_when_disabled(monkeypatch, tmp_path, capsys):
    env_path = _write_env(
        tmp_path,
        "\n".join(
            [
                "SUGARKUBE_TEAMS_ENABLE=false",
                "SUGARKUBE_TEAMS_URL=https://example.invalid",
            ]
        ),
    )

    class DisabledNotifier:
        enabled = False

        @classmethod
        def from_env(cls):  # noqa: ANN101, ANN201
            return cls()

        def notify(self, **_kwargs):  # noqa: ANN101, ANN204
            raise AssertionError("notification should not be attempted when disabled")

    monkeypatch.setenv("SUGARKUBE_TEAMS_ENV", str(env_path))
    monkeypatch.setattr(MODULE, "TeamsNotifier", DisabledNotifier)
    assert MODULE.main(["--event", "first-boot", "--status", "info"]) == 0
    captured = capsys.readouterr()
    assert "warning" in captured.err.lower()
    assert "disabled" in captured.err.lower()


def test_module_entrypoint(monkeypatch, tmp_path):
    env_path = _write_env(
        tmp_path,
        "\n".join(
            [
                "SUGARKUBE_TEAMS_ENABLE=false",
                "SUGARKUBE_TEAMS_URL=https://example.invalid",
            ]
        ),
    )

    monkeypatch.setenv("SUGARKUBE_TEAMS_ENV", str(env_path))
    argv = ["sugarkube_teams.py", "--event", "first-boot", "--status", "success"]
    monkeypatch.setattr(sys, "argv", argv)
    with pytest.raises(SystemExit) as exc:
        runpy.run_path(str(MODULE_PATH), run_name="__main__")
    assert exc.value.code == 0
