from __future__ import annotations

import importlib.util
import json
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


def test_env_flag_variants():
    assert MODULE.env_flag(None) is False
    assert MODULE.env_flag(None, default=True) is True
    assert MODULE.env_flag("YES") is True
    assert MODULE.env_flag("0") is False


def test_coerce_timeout_accepts_numbers():
    assert MODULE.coerce_timeout(5, default=1, env_var="X", flag="--x") == 5.0
    assert MODULE.coerce_timeout(3.2, default=1, env_var="X", flag="--x") == 3.2
    assert MODULE.coerce_timeout("4.5", default=1, env_var="X", flag="--x") == 4.5


@pytest.mark.parametrize(
    "value,expected",
    [
        (None, 7.0),
        ("", r"invalid --x value"),
        ("abc", r"set X to a number"),
    ],
)
def test_coerce_timeout_invalid_inputs(value, expected):
    if isinstance(expected, float):
        assert MODULE.coerce_timeout(value, default=7.0, env_var="X", flag="--x") == expected
    else:
        with pytest.raises(MODULE.TelemetryError, match=expected):
            MODULE.coerce_timeout(value, default=7.0, env_var="X", flag="--x")


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
    "payload,match",
    [
        ("", "empty"),
        ("not json", "valid JSON"),
        (json.dumps({}), "checks array"),
        (json.dumps({"checks": ["oops"]}), "empty after filtering"),
    ],
)
def test_parse_verifier_output_errors(payload, match):
    with pytest.raises(MODULE.TelemetryError, match=match):
        MODULE.parse_verifier_output(payload)


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
    monkeypatch.setattr(MODULE.uuid, "getnode", lambda: 0x1234)
    digest = MODULE.hashed_identifier(salt="")
    assert digest == MODULE.hashlib.sha256("uuid:1234".encode()).hexdigest()


def test_read_text_handles_missing(tmp_path):
    missing = tmp_path / "missing.txt"
    assert MODULE.read_text(missing) == ""
    present = tmp_path / "present.txt"
    present.write_text("hello\n", encoding="utf-8")
    assert MODULE.read_text(present) == "hello"


def test_fingerprint_sources_collects_identifiers(monkeypatch):
    data = {
        Path("/etc/machine-id"): "abc",
        Path("/var/lib/dbus/machine-id"): "",
        Path("/proc/cpuinfo"): "Serial\t:\t000000001234abcd\n",
        Path("/proc/device-tree/model"): "Pi\x00",
    }

    def fake_read_text(path):
        return data.get(path, "")

    monkeypatch.setattr(MODULE, "read_text", fake_read_text)
    sources = MODULE.fingerprint_sources()
    assert "cpu-serial:000000001234abcd" in sources
    assert "model:Pi\x00" in sources
    assert any(str(Path("/etc/machine-id")) in s for s in sources)


def test_collect_os_release_filters_keys():
    payload = """ID=debian\nIGNORE=1\nPRETTY_NAME="Debian"\n#COMMENT\n"""
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(MODULE, "read_text", lambda path: payload)
    try:
        info = MODULE.collect_os_release()
    finally:
        monkeypatch.undo()
    assert info == {"ID": "debian", "IGNORE": "1", "PRETTY_NAME": "Debian"}


def test_read_uptime_parses_and_handles_failure(monkeypatch):
    monkeypatch.setattr(MODULE, "read_text", lambda path: "12.5 0.0")
    assert MODULE.read_uptime() == 12.5
    monkeypatch.setattr(MODULE, "read_text", lambda path: "bad data")
    assert MODULE.read_uptime() is None


def test_collect_environment_compiles_snapshot(monkeypatch):
    monkeypatch.setattr(MODULE, "read_uptime", lambda: 42.8)

    class FakeUname(types.SimpleNamespace):
        sysname = "Linux"
        release = "6.1"

    monkeypatch.setattr(MODULE.os, "uname", lambda: FakeUname())
    monkeypatch.setattr(MODULE, "read_text", lambda path: "Model\x00")
    monkeypatch.setattr(
        MODULE,
        "collect_os_release",
        lambda: {"ID": "raspbian", "UNUSED": "x", "PRETTY_NAME": "Raspbian"},
    )
    snapshot = MODULE.collect_environment()
    assert snapshot["uptime_seconds"] == 42
    assert snapshot["kernel"] == "Linux 6.1"
    assert snapshot["hardware_model"] == "Model"
    assert snapshot["os_release"] == {"ID": "raspbian", "PRETTY_NAME": "Raspbian"}


def test_parse_tags_splits_values():
    assert MODULE.parse_tags(None) == []
    assert MODULE.parse_tags(" a, b ,,c ") == ["a", "b", "c"]


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


def test_build_payload_omits_optional_fields():
    checks = [{"name": "ready", "status": "pass"}]
    payload = MODULE.build_payload(
        checks=checks,
        identifier="id",
        env_snapshot={},
        errors=[],
        tags=[],
    )
    assert "errors" not in payload
    assert "tags" not in payload


def test_discover_verifier_path_prefers_explicit(tmp_path, monkeypatch):
    explicit = tmp_path / "verifier.sh"
    explicit.write_text("#!/bin/sh\n", encoding="utf-8")
    explicit.chmod(0o755)
    env = tmp_path / "env.sh"
    env.write_text("#!/bin/sh\n", encoding="utf-8")
    env.chmod(0o755)
    monkeypatch.setenv("SUGARKUBE_TELEMETRY_VERIFIER", str(env))
    found = MODULE.discover_verifier_path(str(explicit))
    assert found == str(explicit)
    found_env = MODULE.discover_verifier_path(None)
    assert found_env == str(env)


def test_discover_verifier_path_uses_which(monkeypatch):
    monkeypatch.setenv("PATH", "/bin")
    monkeypatch.setattr(
        MODULE.shutil,
        "which",
        lambda value: "/usr/bin/tool" if value == "tool" else None,
    )
    monkeypatch.setattr(MODULE.Path, "is_file", lambda self: False)
    assert MODULE.discover_verifier_path("tool") == "/usr/bin/tool"


def test_run_verifier_success(monkeypatch):
    result = types.SimpleNamespace(stdout=json.dumps({"checks": [{"name": "x", "status": "pass"}]}))

    def fake_run(*args, **kwargs):
        return result

    monkeypatch.setattr(MODULE.subprocess, "run", fake_run)
    checks, errors = MODULE.run_verifier("/bin/true", timeout=1.0)
    assert checks == [{"name": "x", "status": "pass"}]
    assert errors == []


def test_run_verifier_handles_timeout(monkeypatch):
    def fake_run(*args, **kwargs):
        raise MODULE.subprocess.TimeoutExpired(cmd="cmd", timeout=1)

    monkeypatch.setattr(MODULE.subprocess, "run", fake_run)
    checks, errors = MODULE.run_verifier("/bin/true", timeout=1.0)
    assert checks == []
    assert errors == ["verifier_timeout"]


def test_run_verifier_handles_called_process_error(monkeypatch):
    exc = MODULE.subprocess.CalledProcessError(1, "cmd", output=json.dumps({"checks": []}))

    def fake_run(*args, **kwargs):
        raise exc

    monkeypatch.setattr(MODULE.subprocess, "run", fake_run)
    checks, errors = MODULE.run_verifier("/bin/true", timeout=1.0)
    assert checks == []
    assert "verifier_exit_1" in errors
    assert any("empty after filtering" in err for err in errors)


def test_run_verifier_missing_binary(monkeypatch):
    def fake_run(*args, **kwargs):
        raise FileNotFoundError

    monkeypatch.setattr(MODULE.subprocess, "run", fake_run)
    with pytest.raises(MODULE.TelemetryError, match="verifier not found"):
        MODULE.run_verifier("/missing", timeout=1.0)


def test_run_verifier_parsing_failure(monkeypatch):
    result = types.SimpleNamespace(stdout="not json")
    monkeypatch.setattr(MODULE.subprocess, "run", lambda *a, **k: result)
    checks, errors = MODULE.run_verifier("/bin/true", timeout=1.0)
    assert checks == []
    assert errors and "verifier output was not valid JSON" in errors[0]


class DummyResponse:
    def __init__(self, status=200):
        self.status = status

    def read(self):  # pragma: no cover - invoked for side effect
        return b""

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_send_payload_success(monkeypatch):
    captured = {}

    def fake_urlopen(request, timeout):
        captured["timeout"] = timeout
        captured["endpoint"] = request.full_url
        captured["headers"] = dict(request.headers)
        return DummyResponse()

    monkeypatch.setattr(MODULE.urllib.request, "urlopen", fake_urlopen)
    MODULE.send_payload(
        {"hello": "world"}, endpoint="https://example", auth_bearer="t", timeout=5.0
    )
    assert captured["timeout"] == 5.0
    assert captured["endpoint"] == "https://example"
    assert captured["headers"]["Authorization"] == "Bearer t"


def test_send_payload_raises_http_error(monkeypatch):
    error = urllib.error.HTTPError("https://example", 500, "err", hdrs=None, fp=None)
    monkeypatch.setattr(
        MODULE.urllib.request,
        "urlopen",
        lambda *a, **k: (_ for _ in ()).throw(error),
    )
    with pytest.raises(MODULE.TelemetryError, match="HTTP 500"):
        MODULE.send_payload({}, endpoint="https://example", auth_bearer=None, timeout=1.0)


def test_send_payload_raises_url_error(monkeypatch):
    error = urllib.error.URLError("boom")
    monkeypatch.setattr(
        MODULE.urllib.request,
        "urlopen",
        lambda *a, **k: (_ for _ in ()).throw(error),
    )
    with pytest.raises(MODULE.TelemetryError, match="boom"):
        MODULE.send_payload({}, endpoint="https://example", auth_bearer=None, timeout=1.0)


def test_parse_args_rejects_invalid_timeout(monkeypatch):
    monkeypatch.setenv("SUGARKUBE_TELEMETRY_TIMEOUT", "ten")
    with pytest.raises(MODULE.TelemetryError, match="--timeout"):
        MODULE.parse_args([])


def test_parse_args_rejects_blank_verifier_timeout(monkeypatch):
    monkeypatch.setenv("SUGARKUBE_TELEMETRY_VERIFIER_TIMEOUT", "   ")
    with pytest.raises(MODULE.TelemetryError, match="--verifier-timeout"):
        MODULE.parse_args([])


def test_parse_args_populates_defaults(monkeypatch):
    monkeypatch.setenv("SUGARKUBE_TELEMETRY_ENDPOINT", "https://example")
    args = MODULE.parse_args(["--timeout", "3", "--verifier-timeout", "4"])
    assert args.endpoint == "https://example"
    assert args.timeout == 3.0
    assert args.verifier_timeout == 4.0


def test_main_respects_disabled_flag(monkeypatch, capsys):
    monkeypatch.setattr(
        MODULE,
        "parse_args",
        lambda argv=None: MODULE.argparse.Namespace(
            endpoint="",
            auth_bearer=None,
            salt="",
            tags="",
            timeout=MODULE.DEFAULT_TIMEOUT,
            verifier_timeout=MODULE.DEFAULT_VERIFIER_TIMEOUT,
            verifier=None,
            dry_run=False,
            force=False,
            print_payload=False,
        ),
    )
    monkeypatch.setenv("SUGARKUBE_TELEMETRY_ENABLE", "false")
    rc = MODULE.main([])
    assert rc == 0
    captured = capsys.readouterr()
    assert "telemetry disabled" in captured.err


def test_main_dry_run_prints_payload(monkeypatch, capsys):
    args = MODULE.argparse.Namespace(
        endpoint="",
        auth_bearer=None,
        salt="salt",
        tags="tag1,tag2",
        timeout=MODULE.DEFAULT_TIMEOUT,
        verifier_timeout=MODULE.DEFAULT_VERIFIER_TIMEOUT,
        verifier=None,
        dry_run=True,
        force=False,
        print_payload=False,
    )
    monkeypatch.setattr(MODULE, "parse_args", lambda argv=None: args)
    monkeypatch.setattr(MODULE, "discover_verifier_path", lambda explicit: "/bin/true")

    def fake_run_verifier(path, timeout):
        return ([{"name": "x", "status": "pass"}], [])

    monkeypatch.setattr(MODULE, "run_verifier", fake_run_verifier)
    monkeypatch.setattr(MODULE, "hashed_identifier", lambda salt: "id")
    monkeypatch.setattr(MODULE, "collect_environment", lambda: {"env": "val"})
    rc = MODULE.main([])
    assert rc == 0
    out = capsys.readouterr().out
    payload = json.loads(out)
    assert payload["instance"] == {"id": "id"}
    assert payload["verifier"]["checks"]


def test_main_requires_endpoint_when_uploading(monkeypatch):
    args = MODULE.argparse.Namespace(
        endpoint="",
        auth_bearer=None,
        salt="",
        tags="",
        timeout=MODULE.DEFAULT_TIMEOUT,
        verifier_timeout=MODULE.DEFAULT_VERIFIER_TIMEOUT,
        verifier=None,
        dry_run=False,
        force=True,
        print_payload=False,
    )
    monkeypatch.setattr(MODULE, "parse_args", lambda argv=None: args)
    monkeypatch.setattr(MODULE, "discover_verifier_path", lambda explicit: "/bin/true")
    monkeypatch.setattr(MODULE, "run_verifier", lambda path, timeout: ([], []))
    monkeypatch.setattr(MODULE, "hashed_identifier", lambda salt: "id")
    monkeypatch.setattr(MODULE, "collect_environment", lambda: {})
    with pytest.raises(MODULE.TelemetryError, match="telemetry endpoint not configured"):
        MODULE.main([])


def test_main_uploads_payload(monkeypatch):
    sent = {}
    args = MODULE.argparse.Namespace(
        endpoint="https://example",
        auth_bearer="tok",
        salt="",
        tags="one,two",
        timeout=MODULE.DEFAULT_TIMEOUT,
        verifier_timeout=MODULE.DEFAULT_VERIFIER_TIMEOUT,
        verifier=None,
        dry_run=False,
        force=True,
        print_payload=True,
    )

    monkeypatch.setattr(MODULE, "parse_args", lambda argv=None: args)
    monkeypatch.setattr(MODULE, "discover_verifier_path", lambda explicit: "/bin/true")

    def fake_run_verifier(path, timeout):
        return ([{"name": "x", "status": "pass"}], ["warn"])

    monkeypatch.setattr(MODULE, "run_verifier", fake_run_verifier)
    monkeypatch.setattr(MODULE, "hashed_identifier", lambda salt: "id")
    monkeypatch.setattr(MODULE, "collect_environment", lambda: {"env": "val"})

    def capture_send_payload(payload, **kwargs):
        sent.update({"payload": payload, **kwargs})

    monkeypatch.setattr(MODULE, "send_payload", capture_send_payload)
    rc = MODULE.main([])
    assert rc == 0
    assert sent["endpoint"] == "https://example"
    assert sent["auth_bearer"] == "tok"
    assert sent["payload"]["errors"] == ["warn"]
