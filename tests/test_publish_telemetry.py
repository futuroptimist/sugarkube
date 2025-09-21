from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import types
import urllib.error
from pathlib import Path

import pytest

MODULE_PATH = Path(__file__).resolve().parent.parent / "scripts" / "publish_telemetry.py"
SPEC = importlib.util.spec_from_file_location("publish_telemetry", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)  # type: ignore[arg-type]


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


@pytest.mark.parametrize(
    "raw, message",
    [
        ("", "empty"),
        ("not-json", "valid JSON"),
        (json.dumps({}), "checks array"),
        (json.dumps({"checks": ["junk"]}), "empty after filtering"),
    ],
)
def test_parse_verifier_output_errors(raw, message):
    with pytest.raises(MODULE.TelemetryError, match=message):
        MODULE.parse_verifier_output(raw)


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


def test_env_flag_and_coerce_timeout(monkeypatch):
    assert MODULE.env_flag(None, default=True) is True
    assert MODULE.env_flag("YES") is True
    assert MODULE.env_flag("0") is False

    assert MODULE.coerce_timeout(None, default=5.0, env_var="X", flag="--x") == 5.0
    assert MODULE.coerce_timeout(3, default=0.0, env_var="X", flag="--x") == 3.0
    assert MODULE.coerce_timeout("4.5", default=0.0, env_var="X", flag="--x") == 4.5

    with pytest.raises(MODULE.TelemetryError, match="expected a number"):
        MODULE.coerce_timeout("   ", default=0.0, env_var="Y", flag="--y")
    with pytest.raises(MODULE.TelemetryError, match="--z"):
        MODULE.coerce_timeout("abc", default=0.0, env_var="Z", flag="--z")


def test_hashed_identifier_uses_salt(monkeypatch):
    def fake_sources():
        return ["machine-id:abc", "cpu-serial:123"]

    monkeypatch.setattr(MODULE, "fingerprint_sources", fake_sources)
    no_salt = MODULE.hashed_identifier(salt="")
    salted = MODULE.hashed_identifier(salt="pepper")
    assert no_salt != salted
    assert len(no_salt) == 64
    assert len(salted) == 64


def test_hashed_identifier_falls_back_to_uuid(monkeypatch):
    monkeypatch.setattr(MODULE, "fingerprint_sources", lambda: [])
    monkeypatch.setattr(MODULE.uuid, "getnode", lambda: 0xABCDEF)
    digest = MODULE.hashed_identifier(salt="")
    assert digest == MODULE.hashlib.sha256("uuid:abcdef".encode()).hexdigest()


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


def test_build_payload_omits_optional_fields_when_empty(monkeypatch):
    checks = []
    payload = MODULE.build_payload(
        checks=checks,
        identifier="xyz",
        env_snapshot={},
        errors=[],
        tags=[],
    )
    assert "errors" not in payload
    assert "tags" not in payload
    assert payload["verifier"]["checks"] == []


def test_read_text_handles_missing(tmp_path):
    path = tmp_path / "data.txt"
    assert MODULE.read_text(path) == ""
    path.write_text(" hello \n")
    assert MODULE.read_text(path) == "hello"


def test_fingerprint_sources_collects_known_ids(monkeypatch):
    def fake_read_text(path):
        mapping = {
            Path("/etc/machine-id"): "mid",
            Path("/var/lib/dbus/machine-id"): "dbus",
            Path("/proc/cpuinfo"): "Serial\t: 1234\n",
            Path("/proc/device-tree/model"): "Pi\x00",
        }
        return mapping.get(path, "")

    monkeypatch.setattr(MODULE, "read_text", fake_read_text)
    sources = MODULE.fingerprint_sources()
    assert "Pi" in "".join(sources)
    assert any(entry.startswith("cpu-serial:") for entry in sources)


def test_collect_os_release_and_environment(monkeypatch):
    def fake_read_text(path: Path) -> str:
        if "os-release" in str(path):
            return "ID=raspbian\nVERSION=11\nEXTRA=ignored"
        return "model\x00"

    monkeypatch.setattr(MODULE, "read_text", fake_read_text)
    monkeypatch.setattr(MODULE, "read_uptime", lambda: 123.4)

    class FakeUname(types.SimpleNamespace):
        sysname: str
        release: str

    monkeypatch.setattr(MODULE.os, "uname", lambda: FakeUname(sysname="Linux", release="6.8"))

    env = MODULE.collect_environment()
    assert env["uptime_seconds"] == 123
    assert env["kernel"] == "Linux 6.8"
    assert env["hardware_model"] == "model"
    assert env["os_release"] == {"ID": "raspbian", "VERSION": "11"}


def test_read_uptime_invalid(monkeypatch):
    monkeypatch.setattr(MODULE, "read_text", lambda path: "")
    assert MODULE.read_uptime() is None
    monkeypatch.setattr(MODULE, "read_text", lambda path: "not-a-number")
    assert MODULE.read_uptime() is None
    monkeypatch.setattr(MODULE, "read_text", lambda path: "12.7 34")
    assert MODULE.read_uptime() == 12.7


def test_parse_tags_trims_entries():
    assert MODULE.parse_tags(None) == []
    assert MODULE.parse_tags("a, b , ,c") == ["a", "b", "c"]


def test_discover_verifier_path_explicit_and_env(monkeypatch, tmp_path):
    script = tmp_path / "verifier.sh"
    script.write_text("#!/bin/sh\nexit 0\n")
    script.chmod(0o755)
    assert MODULE.discover_verifier_path(str(script)) == str(script)

    monkeypatch.setenv("SUGARKUBE_TELEMETRY_VERIFIER", str(script))
    assert MODULE.discover_verifier_path(None) == str(script)


def test_discover_verifier_path_which(monkeypatch):
    monkeypatch.delenv("SUGARKUBE_TELEMETRY_VERIFIER", raising=False)

    monkeypatch.setattr(Path, "is_file", lambda self: False)
    monkeypatch.setattr(MODULE.os, "access", lambda path, mode: False)
    monkeypatch.setattr(
        MODULE.shutil,
        "which",
        lambda candidate: "/bin/true" if candidate == "pi_node_verifier.sh" else None,
    )
    assert MODULE.discover_verifier_path(None) == "/bin/true"


def test_run_verifier_success(monkeypatch):
    payload = {"checks": [{"name": "ready", "status": "pass"}]}

    def fake_run(*_, **__):
        return types.SimpleNamespace(stdout=json.dumps(payload))

    monkeypatch.setattr(MODULE.subprocess, "run", fake_run)
    checks, errors = MODULE.run_verifier("/bin/true", 10)
    assert errors == []
    assert checks[0]["name"] == "ready"


def test_run_verifier_errors(monkeypatch):
    def raise_not_found(*args, **kwargs):
        raise FileNotFoundError()

    monkeypatch.setattr(MODULE.subprocess, "run", raise_not_found)
    with pytest.raises(MODULE.TelemetryError, match="not found"):
        MODULE.run_verifier("/missing", 1)

    def raise_timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd=args[0], timeout=1)

    monkeypatch.setattr(MODULE.subprocess, "run", raise_timeout)
    checks, errors = MODULE.run_verifier("/bin/true", 1)
    assert checks == []
    assert "verifier_timeout" in errors

    def raise_called(*args, **kwargs):
        exc = subprocess.CalledProcessError(2, args[0], output=json.dumps({"checks": []}))
        raise exc

    monkeypatch.setattr(MODULE.subprocess, "run", raise_called)
    checks, errors = MODULE.run_verifier("/bin/true", 1)
    assert errors[0] == "verifier_exit_2"
    assert checks == []

    def raise_called_invalid(*args, **kwargs):
        exc = subprocess.CalledProcessError(3, args[0], output="not json")
        raise exc

    monkeypatch.setattr(MODULE.subprocess, "run", raise_called_invalid)
    checks, errors = MODULE.run_verifier("/bin/true", 1)
    assert "verifier_exit_3" in errors[0]
    assert any("valid JSON" in err or "verifier" in err for err in errors[1:])


def test_send_payload_success_and_errors(monkeypatch):
    captured = {}

    class DummyResponse:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def read(self):
            captured["read"] = True

    monkeypatch.setattr(MODULE.urllib.request, "urlopen", lambda *a, **k: DummyResponse())
    MODULE.send_payload({}, endpoint="https://example", auth_bearer="abc", timeout=5)
    assert captured["read"] is True

    def raise_http(*args, **kwargs):
        raise urllib.error.HTTPError("https://example", 500, "err", hdrs=None, fp=None)

    monkeypatch.setattr(MODULE.urllib.request, "urlopen", raise_http)
    with pytest.raises(MODULE.TelemetryError, match="HTTP 500"):
        MODULE.send_payload({}, endpoint="https://example", auth_bearer=None, timeout=5)

    def raise_url(*args, **kwargs):
        raise urllib.error.URLError("boom")

    monkeypatch.setattr(MODULE.urllib.request, "urlopen", raise_url)
    with pytest.raises(MODULE.TelemetryError, match="boom"):
        MODULE.send_payload({}, endpoint="https://example", auth_bearer=None, timeout=5)


def test_parse_args_rejects_invalid_timeout(monkeypatch):
    monkeypatch.setenv("SUGARKUBE_TELEMETRY_TIMEOUT", "ten")
    with pytest.raises(MODULE.TelemetryError, match="--timeout"):
        MODULE.parse_args([])


def test_parse_args_rejects_blank_verifier_timeout(monkeypatch):
    monkeypatch.setenv("SUGARKUBE_TELEMETRY_VERIFIER_TIMEOUT", "   ")
    with pytest.raises(MODULE.TelemetryError, match="--verifier-timeout"):
        MODULE.parse_args([])


def test_main_respects_enable_flag(monkeypatch, capsys):
    monkeypatch.setattr(MODULE, "log", lambda message: sys.stderr.write(f"LOG:{message}\n"))
    monkeypatch.setattr(MODULE, "discover_verifier_path", lambda explicit: "/bin/true")
    monkeypatch.setattr(MODULE, "run_verifier", lambda *a, **k: ([], []))
    monkeypatch.setattr(MODULE, "hashed_identifier", lambda **_: "id")
    monkeypatch.setattr(MODULE, "collect_environment", lambda: {})
    monkeypatch.setattr(MODULE, "parse_tags", lambda _: [])
    monkeypatch.setattr(MODULE, "build_payload", lambda **_: {})
    monkeypatch.setattr(MODULE, "send_payload", lambda *a, **k: None)

    monkeypatch.delenv("SUGARKUBE_TELEMETRY_ENABLE", raising=False)
    assert MODULE.main(["--endpoint", "https://example", "--verifier", "/bin/true"]) == 0
    assert "disabled" in capsys.readouterr().err


def test_main_dry_run_prints_payload(monkeypatch, capsys):
    monkeypatch.setenv("SUGARKUBE_TELEMETRY_ENABLE", "false")
    monkeypatch.setattr(MODULE, "discover_verifier_path", lambda explicit: "/bin/true")

    def ready_check(*args, **kwargs):
        return ([{"name": "ready", "status": "pass"}], [])

    monkeypatch.setattr(MODULE, "run_verifier", ready_check)
    monkeypatch.setattr(MODULE, "hashed_identifier", lambda **_: "id")
    monkeypatch.setattr(MODULE, "collect_environment", lambda: {"kernel": "Linux"})
    monkeypatch.setattr(MODULE, "send_payload", lambda *a, **k: None)

    result = MODULE.main(["--dry-run", "--verifier", "/bin/true"])
    assert result == 0
    out = capsys.readouterr().out
    assert "verifier" in out


def test_main_requires_endpoint(monkeypatch):
    monkeypatch.setenv("SUGARKUBE_TELEMETRY_ENABLE", "true")
    monkeypatch.setattr(MODULE, "discover_verifier_path", lambda explicit: "/bin/true")
    monkeypatch.setattr(MODULE, "run_verifier", lambda *a, **k: ([], []))
    monkeypatch.setattr(MODULE, "hashed_identifier", lambda **_: "id")
    monkeypatch.setattr(MODULE, "collect_environment", lambda: {})
    monkeypatch.setattr(MODULE, "parse_tags", lambda _: [])
    monkeypatch.setattr(MODULE, "build_payload", lambda **_: {})
    monkeypatch.setattr(MODULE, "send_payload", lambda *a, **k: None)

    with pytest.raises(MODULE.TelemetryError, match="endpoint"):
        MODULE.main(["--verifier", "/bin/true"])


def test_main_uploads_and_prints_payload(monkeypatch, capsys):
    monkeypatch.setenv("SUGARKUBE_TELEMETRY_ENABLE", "true")

    monkeypatch.setattr(MODULE, "discover_verifier_path", lambda explicit: explicit or "/bin/true")

    def timeout_error(*args, **kwargs):
        return [], ["verifier_timeout"]

    monkeypatch.setattr(MODULE, "run_verifier", timeout_error)
    monkeypatch.setattr(MODULE, "hashed_identifier", lambda **_: "id")
    monkeypatch.setattr(MODULE, "collect_environment", lambda: {"kernel": "Linux"})
    monkeypatch.setattr(MODULE, "parse_tags", MODULE.parse_tags)
    monkeypatch.setattr(MODULE, "send_payload", lambda *a, **k: None)

    result = MODULE.main(
        [
            "--endpoint",
            "https://example",
            "--verifier",
            "/bin/true",
            "--tags",
            "alpha,beta",
            "--print-payload",
        ]
    )
    assert result == 0
    out = capsys.readouterr().out
    assert '"tags"' in out


def test_main_missing_verifier(monkeypatch):
    monkeypatch.setenv("SUGARKUBE_TELEMETRY_ENABLE", "true")
    monkeypatch.setattr(MODULE, "discover_verifier_path", lambda explicit: None)
    with pytest.raises(MODULE.TelemetryError, match="could not be located"):
        MODULE.main(["--endpoint", "https://example"])
