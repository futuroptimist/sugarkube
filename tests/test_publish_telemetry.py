from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from urllib import error as urlerror

import pytest

MODULE_PATH = Path(__file__).resolve().parent.parent / "scripts" / "publish_telemetry.py"
SPEC = importlib.util.spec_from_file_location("publish_telemetry", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)  # type: ignore[arg-type]


def test_env_flag_variants():
    assert MODULE.env_flag("YES") is True
    assert MODULE.env_flag("0", default=True) is False
    assert MODULE.env_flag(None, default=True) is True


def test_read_text_handles_missing(tmp_path):
    path = tmp_path / "missing.txt"
    assert MODULE.read_text(path) == ""


def test_read_text_strips_content(tmp_path):
    path = tmp_path / "data.txt"
    path.write_text(" value \n", encoding="utf-8")
    assert MODULE.read_text(path) == "value"


def test_parse_verifier_output_errors():
    with pytest.raises(MODULE.TelemetryError, match="empty"):
        MODULE.parse_verifier_output(" ")
    with pytest.raises(MODULE.TelemetryError, match="valid JSON"):
        MODULE.parse_verifier_output("not-json")
    with pytest.raises(MODULE.TelemetryError, match="checks"):
        MODULE.parse_verifier_output(json.dumps({"data": []}))
    with pytest.raises(MODULE.TelemetryError, match="empty after"):
        MODULE.parse_verifier_output(json.dumps({"checks": [123]}))


def test_parse_verifier_output_filters_invalid_entries():
    payload = {
        "checks": [
            {"name": "ready", "status": "pass"},
            {"name": "projects", "status": "fail"},
            "skip-me",
            {"name": "broken"},
        ]
    }
    checks = MODULE.parse_verifier_output(json.dumps(payload))
    assert checks == [
        {"name": "ready", "status": "pass"},
        {"name": "projects", "status": "fail"},
    ]


def test_summarise_checks_reports_counts():
    checks = [
        {"name": "one", "status": "pass"},
        {"name": "two", "status": "fail"},
        {"name": "three", "status": "skip"},
        {"name": "four", "status": "weird"},
    ]
    summary = MODULE.summarise_checks(checks)
    assert summary["total"] == 4
    assert summary["passed"] == 1
    assert summary["failed"] == 1
    assert summary["skipped"] == 1
    assert summary["other"] == 1
    assert summary["failed_checks"] == ["two"]


def test_fingerprint_sources_collects_identifiers(monkeypatch):
    def fake_read_text(path: Path) -> str:
        mapping = {
            Path("/etc/machine-id"): "abc",
            Path("/var/lib/dbus/machine-id"): "",
            Path("/proc/cpuinfo"): "Serial\t: 0000000012345678\nOther: value",  # noqa: E501
            Path("/proc/device-tree/model"): "Pi\x00Model",
        }
        return mapping.get(path, "")

    monkeypatch.setattr(MODULE, "read_text", fake_read_text)
    sources = MODULE.fingerprint_sources()
    assert any(entry.startswith("/etc/machine-id:") for entry in sources)
    assert "cpu-serial:0000000012345678" in sources
    assert any(entry.startswith("model:Pi") for entry in sources)


def test_hashed_identifier_falls_back_to_uuid(monkeypatch):
    monkeypatch.setattr(MODULE, "fingerprint_sources", lambda: [])
    monkeypatch.setattr(MODULE.uuid, "getnode", lambda: 0x42)
    expected = hashlib.sha256("uuid:42".encode("utf-8")).hexdigest()
    assert MODULE.hashed_identifier() == expected


def test_collect_os_release(monkeypatch):
    data = "# comment\nID=raspbian\nVERSION=1\nEXTRA=value\n"

    def fake_read_text(path: Path) -> str:
        if path == Path("/etc/os-release"):
            return data
        return ""

    monkeypatch.setattr(MODULE, "read_text", fake_read_text)
    result = MODULE.collect_os_release()
    assert result["ID"] == "raspbian"
    assert result["VERSION"] == "1"
    assert "EXTRA" in result


def test_read_uptime_variants(monkeypatch):
    def uptime_text(path: Path) -> str:
        return "123.4 567" if path == Path("/proc/uptime") else ""

    monkeypatch.setattr(MODULE, "read_text", uptime_text)
    assert MODULE.read_uptime() == pytest.approx(123.4)

    def invalid_uptime(path: Path) -> str:
        return "invalid" if path == Path("/proc/uptime") else ""

    monkeypatch.setattr(MODULE, "read_text", invalid_uptime)
    assert MODULE.read_uptime() is None


def test_collect_environment(monkeypatch):
    monkeypatch.setattr(MODULE, "read_uptime", lambda: 42.8)

    class FakeUname(SimpleNamespace):
        sysname = "Linux"
        release = "6.6"

    monkeypatch.setattr(MODULE.os, "uname", lambda: FakeUname())
    monkeypatch.setattr(
        MODULE,
        "read_text",
        lambda path: "Pi\x00Model" if path == Path("/proc/device-tree/model") else "",
    )
    monkeypatch.setattr(
        MODULE,
        "collect_os_release",
        lambda: {"ID": "raspbian", "VERSION": "1", "PRETTY_NAME": "Raspbian"},
    )
    env = MODULE.collect_environment()
    assert env["uptime_seconds"] == 42
    assert env["kernel"] == "Linux 6.6"
    assert env["hardware_model"] == "PiModel"
    assert env["os_release"] == {
        "ID": "raspbian",
        "PRETTY_NAME": "Raspbian",
        "VERSION": "1",
    }


def test_parse_tags_handles_spacing():
    assert MODULE.parse_tags(" lab,pi , ") == ["lab", "pi"]
    assert MODULE.parse_tags(None) == []


def test_build_payload_handles_empty_optional_sections():
    payload = MODULE.build_payload(
        checks=[],
        identifier="node",
        env_snapshot={"kernel": "Linux"},
        errors=[],
        tags=[],
    )
    assert "errors" not in payload
    assert "tags" not in payload
    assert payload["verifier"]["summary"]["total"] == 0


def test_build_payload_includes_summary_and_tags():
    checks = [
        {"name": "ready", "status": "pass"},
        {"name": "projects", "status": "fail"},
    ]
    env = {"kernel": "Linux 6.1"}
    payload = MODULE.build_payload(
        checks=checks,
        identifier="abc123",
        env_snapshot=env,
        errors=["verifier_timeout"],
        tags=["lab", "pi"],
    )
    assert payload["instance"] == {"id": "abc123"}
    assert payload["environment"] == env
    assert payload["errors"] == ["verifier_timeout"]
    assert payload["tags"] == ["lab", "pi"]
    summary = payload["verifier"]["summary"]
    assert summary["total"] == 2
    assert summary["failed_checks"] == ["projects"]


def test_discover_verifier_path_explicit(tmp_path, monkeypatch):
    path = tmp_path / "verifier.sh"
    path.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    path.chmod(0o755)
    result = MODULE.discover_verifier_path(str(path))
    assert result == str(path)


def test_discover_verifier_path_env_and_which(monkeypatch, tmp_path):
    env_path = tmp_path / "env.sh"
    env_path.write_text("#!/bin/sh\n", encoding="utf-8")
    env_path.chmod(0o755)
    monkeypatch.setenv("SUGARKUBE_TELEMETRY_VERIFIER", str(env_path))
    assert MODULE.discover_verifier_path(None) == str(env_path)

    def fake_access(path, mode):
        return False

    monkeypatch.setattr(MODULE.os, "access", fake_access)
    monkeypatch.setattr(MODULE.shutil, "which", lambda candidate: str(env_path))
    assert MODULE.discover_verifier_path("nonexistent") == str(env_path)

    monkeypatch.delenv("SUGARKUBE_TELEMETRY_VERIFIER", raising=False)
    monkeypatch.setattr(MODULE.shutil, "which", lambda candidate: None)
    monkeypatch.setattr(MODULE.os, "access", lambda path, mode: False)
    assert MODULE.discover_verifier_path("missing") is None


def test_run_verifier_success(monkeypatch):
    output = json.dumps({"checks": [{"name": "ready", "status": "pass"}]})

    def fake_run(*args, **kwargs):
        assert kwargs["timeout"] == 5
        return SimpleNamespace(stdout=output)

    monkeypatch.setattr(MODULE.subprocess, "run", fake_run)
    checks, errors = MODULE.run_verifier("/bin/verify", 5)
    assert checks == [{"name": "ready", "status": "pass"}]
    assert errors == []


def test_run_verifier_timeout(monkeypatch):
    def fake_run(*args, **kwargs):
        raise MODULE.subprocess.TimeoutExpired(cmd=["verify"], timeout=1)

    monkeypatch.setattr(MODULE.subprocess, "run", fake_run)
    checks, errors = MODULE.run_verifier("/bin/verify", 1)
    assert checks == []
    assert errors == ["verifier_timeout"]


def test_run_verifier_called_process_error(monkeypatch):
    payload = json.dumps({"checks": [{"name": "x", "status": "fail"}]})

    def fake_run(*args, **kwargs):
        raise MODULE.subprocess.CalledProcessError(
            returncode=2,
            cmd=["verify"],
            output=payload,
        )

    monkeypatch.setattr(MODULE.subprocess, "run", fake_run)
    checks, errors = MODULE.run_verifier("/bin/verify", 1)
    assert checks == [{"name": "x", "status": "fail"}]
    assert errors == ["verifier_exit_2"]


def test_run_verifier_called_process_error_with_invalid_output(monkeypatch):
    def fake_run(*args, **kwargs):
        raise MODULE.subprocess.CalledProcessError(
            returncode=3,
            cmd=["verify"],
            output="oops",
        )

    monkeypatch.setattr(MODULE.subprocess, "run", fake_run)
    checks, errors = MODULE.run_verifier("/bin/verify", 1)
    assert checks == []
    assert errors[0] == "verifier_exit_3"
    assert any("output" in entry or "invalid" in entry for entry in errors)


def test_run_verifier_not_found(monkeypatch):
    def fake_run(*args, **kwargs):
        raise FileNotFoundError("missing")

    monkeypatch.setattr(MODULE.subprocess, "run", fake_run)
    with pytest.raises(MODULE.TelemetryError, match="verifier not found"):
        MODULE.run_verifier("/bin/verify", 1)


def test_send_payload_success(monkeypatch):
    captured = {}

    class DummyResponse:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def read(self):
            captured["read"] = True

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        captured["data"] = json.loads(request.data.decode("utf-8"))
        captured["auth"] = request.get_header("Authorization")
        return DummyResponse()

    monkeypatch.setattr(MODULE.urllib.request, "urlopen", fake_urlopen)
    payload = {"hello": "world"}
    MODULE.send_payload(payload, endpoint="https://example.com", auth_bearer="token", timeout=3)
    assert captured["url"] == "https://example.com"
    assert captured["data"] == payload
    assert captured["auth"] == "Bearer token"
    assert captured["read"] is True


def test_send_payload_http_error(monkeypatch):
    def fake_urlopen(request, timeout):
        raise urlerror.HTTPError(request.full_url, 500, "boom", hdrs=None, fp=None)

    monkeypatch.setattr(MODULE.urllib.request, "urlopen", fake_urlopen)
    with pytest.raises(MODULE.TelemetryError, match="HTTP 500"):
        MODULE.send_payload({}, endpoint="https://example.com", auth_bearer=None, timeout=1)


def test_send_payload_url_error(monkeypatch):
    def fake_urlopen(request, timeout):
        raise urlerror.URLError("offline")

    monkeypatch.setattr(MODULE.urllib.request, "urlopen", fake_urlopen)
    with pytest.raises(MODULE.TelemetryError, match="offline"):
        MODULE.send_payload({}, endpoint="https://example.com", auth_bearer=None, timeout=1)


def test_parse_args_success(monkeypatch):
    monkeypatch.setenv("SUGARKUBE_TELEMETRY_TIMEOUT", "5")
    monkeypatch.setenv("SUGARKUBE_TELEMETRY_VERIFIER_TIMEOUT", "6")
    args = MODULE.parse_args(["--endpoint", "https://example.com", "--dry-run"])
    assert args.timeout == 5.0
    assert args.verifier_timeout == 6.0
    assert args.dry_run is True


def test_parse_args_rejects_invalid_timeout(monkeypatch):
    monkeypatch.setenv("SUGARKUBE_TELEMETRY_TIMEOUT", "ten")
    with pytest.raises(MODULE.TelemetryError, match="--timeout"):
        MODULE.parse_args([])


def test_parse_args_rejects_blank_verifier_timeout(monkeypatch):
    monkeypatch.setenv("SUGARKUBE_TELEMETRY_VERIFIER_TIMEOUT", "   ")
    with pytest.raises(MODULE.TelemetryError, match="--verifier-timeout"):
        MODULE.parse_args([])


def test_main_disabled_logs_notice(monkeypatch, capsys):
    monkeypatch.delenv("SUGARKUBE_TELEMETRY_ENABLE", raising=False)
    assert MODULE.main([]) == 0
    stderr = capsys.readouterr().err
    assert "telemetry disabled" in stderr


def test_main_errors_when_verifier_missing(monkeypatch):
    monkeypatch.setenv("SUGARKUBE_TELEMETRY_ENABLE", "true")
    monkeypatch.setattr(MODULE, "discover_verifier_path", lambda explicit: None)
    with pytest.raises(MODULE.TelemetryError, match="could not be located"):
        MODULE.main(["--endpoint", "https://example.com"])


def test_main_dry_run_success(monkeypatch, capsys):
    monkeypatch.setattr(MODULE, "discover_verifier_path", lambda explicit: "/bin/verify")
    monkeypatch.setattr(
        MODULE,
        "run_verifier",
        lambda path, timeout: ([{"name": "ready", "status": "pass"}], ["note"]),
    )
    monkeypatch.setattr(MODULE, "hashed_identifier", lambda salt="": "id")
    monkeypatch.setattr(MODULE, "collect_environment", lambda: {"kernel": "Linux"})
    monkeypatch.setattr(MODULE, "parse_tags", lambda raw: ["lab"])

    def fail_send(*_args, **_kwargs):
        raise AssertionError("send_payload should not be called during dry run")

    monkeypatch.setattr(MODULE, "send_payload", fail_send)
    assert MODULE.main(["--dry-run", "--endpoint", "https://example.com"]) == 0
    out = capsys.readouterr().out
    payload = json.loads(out)
    assert payload["errors"] == ["note"]
    assert payload["tags"] == ["lab"]


def test_main_errors_when_endpoint_missing(monkeypatch):
    monkeypatch.setattr(MODULE, "discover_verifier_path", lambda explicit: "/bin/verify")
    monkeypatch.setattr(MODULE, "run_verifier", lambda path, timeout: ([], []))
    monkeypatch.setattr(MODULE, "hashed_identifier", lambda salt="": "id")
    monkeypatch.setattr(MODULE, "collect_environment", lambda: {})
    monkeypatch.setattr(MODULE, "parse_tags", lambda raw: [])
    with pytest.raises(MODULE.TelemetryError, match="endpoint not configured"):
        MODULE.main(["--force"])


def test_main_upload_success(monkeypatch):
    monkeypatch.setattr(MODULE, "discover_verifier_path", lambda explicit: "/bin/verify")
    monkeypatch.setattr(MODULE, "run_verifier", lambda path, timeout: ([], []))
    monkeypatch.setattr(MODULE, "hashed_identifier", lambda salt="": "id")
    monkeypatch.setattr(MODULE, "collect_environment", lambda: {})
    monkeypatch.setattr(MODULE, "parse_tags", lambda raw: [])
    called = {}

    def fake_send(payload, *, endpoint, auth_bearer, timeout):
        called["payload"] = payload
        called["endpoint"] = endpoint
        called["auth"] = auth_bearer
        called["timeout"] = timeout

    monkeypatch.setattr(MODULE, "send_payload", fake_send)
    assert (
        MODULE.main(
            [
                "--force",
                "--endpoint",
                "https://example.com",
                "--token",
                "secret",
                "--timeout",
                "3",
            ]
        )
        == 0
    )
    assert called["endpoint"] == "https://example.com"
    assert called["auth"] == "secret"
    assert called["timeout"] == 3.0
    assert called["payload"]["instance"] == {"id": "id"}


def test_main_handles_send_failure(monkeypatch):
    monkeypatch.setattr(MODULE, "discover_verifier_path", lambda explicit: "/bin/verify")
    monkeypatch.setattr(MODULE, "run_verifier", lambda path, timeout: ([], []))
    monkeypatch.setattr(MODULE, "hashed_identifier", lambda salt="": "id")
    monkeypatch.setattr(MODULE, "collect_environment", lambda: {})
    monkeypatch.setattr(MODULE, "parse_tags", lambda raw: [])

    def fake_send(*args, **kwargs):
        raise MODULE.TelemetryError("upload failed")

    monkeypatch.setattr(MODULE, "send_payload", fake_send)
    with pytest.raises(MODULE.TelemetryError, match="upload failed"):
        MODULE.main(["--force", "--endpoint", "https://example.com"])
