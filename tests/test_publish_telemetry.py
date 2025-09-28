from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import types
from pathlib import Path

import pytest

MODULE_PATH = Path(__file__).resolve().parent.parent / "scripts" / "publish_telemetry.py"
SPEC = importlib.util.spec_from_file_location("publish_telemetry", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)  # type: ignore[arg-type]


def test_env_flag_variations():
    assert MODULE.env_flag(None) is False
    assert MODULE.env_flag(None, default=True) is True
    assert MODULE.env_flag(" YES ") is True
    assert MODULE.env_flag("0") is False


def test_coerce_timeout_handles_inputs():
    assert MODULE.coerce_timeout(None, default=7.0, env_var="X", flag="--x") == pytest.approx(7.0)
    assert MODULE.coerce_timeout(5, default=3.0, env_var="Y", flag="--y") == pytest.approx(5.0)
    assert MODULE.coerce_timeout(" 4.5 ", default=1.0, env_var="Z", flag="--z") == pytest.approx(
        4.5
    )
    with pytest.raises(MODULE.TelemetryError, match="--w"):
        MODULE.coerce_timeout("", default=1.0, env_var="W", flag="--w")
    with pytest.raises(MODULE.TelemetryError, match="number"):
        MODULE.coerce_timeout("nope", default=1.0, env_var="W", flag="--w")


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
        (json.dumps({}), "checks"),
        (json.dumps({"checks": [None]}), "empty"),
    ],
)
def test_parse_verifier_output_rejects_invalid_payloads(payload, match):
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


def test_read_text_trims_and_handles_errors(tmp_path, monkeypatch):
    sample = tmp_path / "sample.txt"
    sample.write_text(" value \n", encoding="utf-8")
    assert MODULE.read_text(sample) == "value"

    def boom(*args, **kwargs):  # noqa: ANN001, ANN002
        raise OSError

    monkeypatch.setattr(Path, "read_text", boom)
    assert MODULE.read_text(sample) == ""


def test_fingerprint_sources_collects_expected_fields(monkeypatch):
    values = {
        Path("/etc/machine-id"): "abc123",
        Path("/var/lib/dbus/machine-id"): "",
        Path("/proc/cpuinfo"): "Serial\t: 0000abcd\nOther: 1\n",
        Path("/proc/device-tree/model"): "Pi 5\x00",
    }

    def fake_read_text(path):
        return values.get(path, "")

    monkeypatch.setattr(MODULE, "read_text", fake_read_text)
    sources = MODULE.fingerprint_sources()
    assert "cpu-serial:0000abcd" in sources
    assert any(piece.startswith("/etc/machine-id") for piece in sources)
    assert "model:Pi 5\x00" in sources


def test_hashed_identifier_uses_uuid_fallback(monkeypatch):
    monkeypatch.setattr(MODULE, "fingerprint_sources", lambda: [])
    monkeypatch.setattr(MODULE.uuid, "getnode", lambda: 0xABCDEF)  # noqa: ARG005
    expected = MODULE.hashlib.sha256("uuid:abcdef".encode("utf-8")).hexdigest()
    assert MODULE.hashed_identifier() == expected


def test_collect_os_release_parses_pairs(monkeypatch):
    raw = """# comment\nNAME=Ubuntu\nID=ubuntu\nPRETTY_NAME=\"Ubuntu\"\n"""
    monkeypatch.setattr(MODULE, "read_text", lambda path: raw)
    parsed = MODULE.collect_os_release()
    assert parsed == {"NAME": "Ubuntu", "ID": "ubuntu", "PRETTY_NAME": "Ubuntu"}


def test_collect_os_release_handles_missing(monkeypatch):
    monkeypatch.setattr(MODULE, "read_text", lambda path: "")
    assert MODULE.collect_os_release() == {}


def test_read_uptime_handles_invalid(monkeypatch):
    monkeypatch.setattr(MODULE, "read_text", lambda path: "123.45 0.00")
    assert MODULE.read_uptime() == pytest.approx(123.45)
    monkeypatch.setattr(MODULE, "read_text", lambda path: "not-a-number")
    assert MODULE.read_uptime() is None


def test_read_uptime_handles_missing(monkeypatch):
    monkeypatch.setattr(MODULE, "read_text", lambda path: "")
    assert MODULE.read_uptime() is None


def test_collect_environment_builds_snapshot(monkeypatch):
    monkeypatch.setattr(MODULE, "read_uptime", lambda: 12.7)

    def fake_uname():
        return types.SimpleNamespace(sysname="Linux", release="6.1")

    monkeypatch.setattr(MODULE.os, "uname", fake_uname)
    monkeypatch.setattr(MODULE, "read_text", lambda path: "Pi 5\x00")
    monkeypatch.setattr(
        MODULE,
        "collect_os_release",
        lambda: {"ID": "raspbian", "VERSION": "12"},
    )
    snapshot = MODULE.collect_environment()
    assert snapshot["uptime_seconds"] == 12
    assert snapshot["kernel"] == "Linux 6.1"
    assert snapshot["hardware_model"] == "Pi 5"
    assert snapshot["os_release"] == {"ID": "raspbian", "VERSION": "12"}


def test_parse_tags_splits_and_trims():
    assert MODULE.parse_tags(" dev , prod ,,") == ["dev", "prod"]
    assert MODULE.parse_tags(None) == []


def test_parse_args_rejects_invalid_timeout(monkeypatch):
    monkeypatch.setenv("SUGARKUBE_TELEMETRY_TIMEOUT", "ten")
    with pytest.raises(MODULE.TelemetryError, match="--timeout"):
        MODULE.parse_args([])


def test_parse_args_rejects_blank_verifier_timeout(monkeypatch):
    monkeypatch.setenv("SUGARKUBE_TELEMETRY_VERIFIER_TIMEOUT", "   ")
    with pytest.raises(MODULE.TelemetryError, match="--verifier-timeout"):
        MODULE.parse_args([])


def test_parse_args_uses_env_defaults(monkeypatch):
    monkeypatch.setenv("SUGARKUBE_TELEMETRY_ENDPOINT", "https://example")
    monkeypatch.setenv("SUGARKUBE_TELEMETRY_TIMEOUT", "3.5")
    monkeypatch.setenv("SUGARKUBE_TELEMETRY_TAGS", "one,two")
    args = MODULE.parse_args([])
    assert args.endpoint == "https://example"
    assert args.timeout == pytest.approx(3.5)
    assert args.tags == "one,two"


def test_parse_args_defaults_to_three_minute_verifier_timeout(monkeypatch):
    monkeypatch.delenv("SUGARKUBE_TELEMETRY_VERIFIER_TIMEOUT", raising=False)
    args = MODULE.parse_args([])
    assert args.verifier_timeout == pytest.approx(180.0)


def test_discover_verifier_path_prefers_explicit(tmp_path, monkeypatch):
    executable = tmp_path / "verifier.sh"
    executable.write_text("#!/bin/sh\n", encoding="utf-8")
    executable.chmod(0o755)
    monkeypatch.delenv("SUGARKUBE_TELEMETRY_VERIFIER", raising=False)
    assert MODULE.discover_verifier_path(str(executable)) == str(executable)


def test_discover_verifier_path_uses_environment(tmp_path, monkeypatch):
    env_path = tmp_path / "from-env.sh"
    env_path.write_text("#!/bin/sh\n", encoding="utf-8")
    env_path.chmod(0o755)
    monkeypatch.setenv("SUGARKUBE_TELEMETRY_VERIFIER", str(env_path))
    assert MODULE.discover_verifier_path(None) == str(env_path)


def test_discover_verifier_path_uses_path_lookup(tmp_path, monkeypatch):
    monkeypatch.delenv("SUGARKUBE_TELEMETRY_VERIFIER", raising=False)
    binary = tmp_path / "pi_node_verifier.sh"
    binary.write_text("#!/bin/sh\n", encoding="utf-8")
    binary.chmod(0o755)
    original_is_file = MODULE.Path.is_file
    original_access = MODULE.os.access

    def fake_is_file(self):
        if str(self).endswith("pi_node_verifier.sh"):
            return False
        return original_is_file(self)

    def fake_access(path, mode):
        path_str = str(path)
        if path_str.endswith("scripts/pi_node_verifier.sh"):
            return False
        return original_access(path, mode)

    monkeypatch.setattr(MODULE.Path, "is_file", fake_is_file, raising=False)
    monkeypatch.setattr(MODULE.os, "access", fake_access)
    monkeypatch.setenv("PATH", f"{tmp_path}{os.pathsep}{os.environ.get('PATH', '')}")
    assert MODULE.discover_verifier_path(None) == str(binary)


def test_discover_verifier_path_returns_none(monkeypatch):
    monkeypatch.delenv("SUGARKUBE_TELEMETRY_VERIFIER", raising=False)
    original_is_file = MODULE.Path.is_file
    original_access = MODULE.os.access

    def fake_is_file(self):
        if str(self).endswith("pi_node_verifier.sh"):
            return False
        return original_is_file(self)

    def fake_access(path, mode):
        if str(path).endswith("pi_node_verifier.sh"):
            return False
        return original_access(path, mode)

    monkeypatch.setattr(MODULE.Path, "is_file", fake_is_file, raising=False)
    monkeypatch.setattr(MODULE.os, "access", fake_access)
    assert MODULE.discover_verifier_path("") is None


def test_discover_verifier_path_skips_falsey_candidate(monkeypatch):
    class FlakyCandidate:
        def __init__(self):
            self._first = True

        def __bool__(self):
            if self._first:
                self._first = False
                return True
            return False

        def __fspath__(self):  # noqa: D401 - path-like hook
            return ""

    monkeypatch.delenv("SUGARKUBE_TELEMETRY_VERIFIER", raising=False)
    monkeypatch.setattr(MODULE.shutil, "which", lambda value: None)
    monkeypatch.setattr(MODULE.Path, "is_file", lambda self: False, raising=False)
    monkeypatch.setattr(MODULE.os, "access", lambda path, mode: False)
    assert MODULE.discover_verifier_path(FlakyCandidate()) is None


def test_run_verifier_success(monkeypatch):
    payload = json.dumps({"checks": [{"name": "ready", "status": "pass"}]})

    class FakeResult:
        def __init__(self):
            self.stdout = payload

    monkeypatch.setattr(MODULE.subprocess, "run", lambda *a, **k: FakeResult())
    checks, errors = MODULE.run_verifier("verifier", timeout=1.0)
    assert checks[0]["name"] == "ready"
    assert errors == []


def test_run_verifier_handles_missing_file(monkeypatch):
    def boom(*a, **k):  # noqa: ANN001, ANN002
        raise FileNotFoundError

    monkeypatch.setattr(MODULE.subprocess, "run", boom)
    with pytest.raises(MODULE.TelemetryError, match="verifier not found"):
        MODULE.run_verifier("missing", timeout=1.0)


def test_run_verifier_handles_timeout(monkeypatch):
    def boom(*a, **k):  # noqa: ANN001, ANN002
        raise subprocess.TimeoutExpired(cmd=["verifier"], timeout=1.0)

    monkeypatch.setattr(MODULE.subprocess, "run", boom)
    checks, errors = MODULE.run_verifier("path", timeout=1.0)
    assert checks == []
    assert errors == ["verifier_timeout"]


def test_run_verifier_handles_called_process(monkeypatch):
    payload = json.dumps({"checks": [{"name": "ready", "status": "pass"}]})

    def boom(*a, **k):  # noqa: ANN001, ANN002
        raise subprocess.CalledProcessError(
            returncode=3,
            cmd=["verifier"],
            output=payload,
        )

    monkeypatch.setattr(MODULE.subprocess, "run", boom)
    checks, errors = MODULE.run_verifier("path", timeout=1.0)
    assert checks[0]["name"] == "ready"
    assert errors == ["verifier_exit_3"]


def test_run_verifier_handles_invalid_output(monkeypatch):
    def boom(*a, **k):  # noqa: ANN001, ANN002
        raise subprocess.CalledProcessError(
            returncode=2,
            cmd=["verifier"],
            output="not json",
        )

    monkeypatch.setattr(MODULE.subprocess, "run", boom)
    checks, errors = MODULE.run_verifier("path", timeout=1.0)
    assert checks == []
    assert errors == ["verifier_exit_2", "verifier output was not valid JSON"]


def test_run_verifier_records_parse_errors(monkeypatch):
    class FakeResult:
        stdout = "not json"

    monkeypatch.setattr(MODULE.subprocess, "run", lambda *a, **k: FakeResult())
    checks, errors = MODULE.run_verifier("verifier", timeout=1.0)
    assert checks == []
    assert errors == ["verifier output was not valid JSON"]


def test_send_payload_posts_json(monkeypatch):
    captured = {}

    class DummyResponse:
        def read(self):  # noqa: D401 - small helper
            captured["read"] = True

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):  # noqa: D401
            return False

    def fake_urlopen(request, timeout):  # noqa: ANN001, ANN002
        captured["url"] = request.full_url
        captured["headers"] = dict(request.header_items())
        captured["timeout"] = timeout
        return DummyResponse()

    monkeypatch.setattr(MODULE.urllib.request, "urlopen", fake_urlopen)
    MODULE.send_payload(
        {"hello": "world"},
        endpoint="https://example/upload",
        auth_bearer="token",
        timeout=2.0,
    )
    assert captured["url"] == "https://example/upload"
    assert captured["headers"]["Authorization"] == "Bearer token"
    assert captured["read"] is True


def test_send_payload_raises_for_http_error(monkeypatch):
    def boom(*a, **k):  # noqa: ANN001, ANN002
        raise MODULE.urllib.error.HTTPError("url", 500, "err", hdrs=None, fp=None)

    monkeypatch.setattr(MODULE.urllib.request, "urlopen", boom)
    with pytest.raises(MODULE.TelemetryError, match="HTTP 500"):
        MODULE.send_payload({}, endpoint="https://example", auth_bearer=None, timeout=1.0)


def test_send_payload_raises_for_url_error(monkeypatch):
    def boom(*a, **k):  # noqa: ANN001, ANN002
        raise MODULE.urllib.error.URLError("no route")

    monkeypatch.setattr(MODULE.urllib.request, "urlopen", boom)
    with pytest.raises(MODULE.TelemetryError, match="no route"):
        MODULE.send_payload({}, endpoint="https://example", auth_bearer=None, timeout=1.0)


def test_main_returns_when_disabled(monkeypatch):
    monkeypatch.delenv("SUGARKUBE_TELEMETRY_ENABLE", raising=False)
    called = False

    def fail(*args, **kwargs):  # noqa: ANN001, ANN002
        nonlocal called
        called = True
        raise AssertionError("should not run")

    monkeypatch.setattr(MODULE, "discover_verifier_path", fail)
    assert MODULE.main([]) == 0
    assert called is False


def test_main_errors_when_verifier_missing(monkeypatch):
    monkeypatch.setenv("SUGARKUBE_TELEMETRY_ENABLE", "true")
    monkeypatch.setattr(MODULE, "discover_verifier_path", lambda value: None)
    with pytest.raises(MODULE.TelemetryError, match="could not be located"):
        MODULE.main(["--endpoint", "https://example"])


def test_main_dry_run_prints_payload(monkeypatch, capsys):
    monkeypatch.setenv("SUGARKUBE_TELEMETRY_ENABLE", "true")
    monkeypatch.setattr(MODULE, "discover_verifier_path", lambda value: "verifier")
    monkeypatch.setattr(
        MODULE,
        "run_verifier",
        lambda path, timeout: ([{"name": "ready", "status": "pass"}], []),
    )
    monkeypatch.setattr(MODULE, "hashed_identifier", lambda **_: "id")
    monkeypatch.setattr(MODULE, "collect_environment", lambda: {"kernel": "Linux"})
    monkeypatch.setattr(MODULE, "parse_tags", lambda raw: ["tag"])
    exit_code = MODULE.main(["--endpoint", "https://example", "--dry-run"])
    assert exit_code == 0
    captured = capsys.readouterr()
    assert '"id"' in captured.out


def test_main_uploads_payload_and_prints(monkeypatch, capsys):
    monkeypatch.setenv("SUGARKUBE_TELEMETRY_ENABLE", "true")
    monkeypatch.setattr(MODULE, "discover_verifier_path", lambda value: "verifier")
    monkeypatch.setattr(
        MODULE,
        "run_verifier",
        lambda path, timeout: ([{"name": "ready", "status": "pass"}], ["warn"]),
    )
    monkeypatch.setattr(MODULE, "hashed_identifier", lambda **_: "id")
    monkeypatch.setattr(MODULE, "collect_environment", lambda: {"kernel": "Linux"})
    monkeypatch.setattr(MODULE, "parse_tags", lambda raw: ["tag"])
    sent = {}

    def fake_send(payload, *, endpoint, auth_bearer, timeout):  # noqa: ANN001, ANN002
        sent["payload"] = payload
        sent["endpoint"] = endpoint
        sent["auth"] = auth_bearer
        sent["timeout"] = timeout

    monkeypatch.setattr(MODULE, "send_payload", fake_send)
    exit_code = MODULE.main(
        [
            "--endpoint",
            "https://example",
            "--token",
            "abc",
            "--timeout",
            "5",
            "--print-payload",
        ]
    )
    assert exit_code == 0
    assert sent["endpoint"] == "https://example"
    assert sent["auth"] == "abc"
    assert sent["timeout"] == pytest.approx(5)
    assert sent["payload"]["errors"] == ["warn"]
    captured = capsys.readouterr()
    assert '"warn"' in captured.out


def test_main_requires_endpoint_when_not_dry_run(monkeypatch):
    monkeypatch.setenv("SUGARKUBE_TELEMETRY_ENABLE", "true")
    monkeypatch.setattr(MODULE, "discover_verifier_path", lambda value: "verifier")
    monkeypatch.setattr(MODULE, "run_verifier", lambda path, timeout: ([], []))
    monkeypatch.setattr(MODULE, "hashed_identifier", lambda **_: "id")
    monkeypatch.setattr(MODULE, "collect_environment", lambda: {})
    monkeypatch.setattr(MODULE, "parse_tags", lambda raw: [])
    with pytest.raises(MODULE.TelemetryError, match="endpoint not configured"):
        MODULE.main([])


def test_main_writes_markdown_snapshot(monkeypatch, tmp_path):
    monkeypatch.setenv("SUGARKUBE_TELEMETRY_ENABLE", "true")
    monkeypatch.setattr(MODULE, "discover_verifier_path", lambda value: "verifier")
    monkeypatch.setattr(
        MODULE,
        "run_verifier",
        lambda path, timeout: ([{"name": "ready", "status": "pass"}], ["warn"]),
    )
    monkeypatch.setattr(MODULE, "hashed_identifier", lambda **_: "abcdef1234567890")
    monkeypatch.setattr(
        MODULE,
        "collect_environment",
        lambda: {"kernel": "Linux 6.1", "uptime_seconds": 42, "hardware_model": "Pi 5"},
    )
    monkeypatch.setattr(MODULE, "parse_tags", lambda raw: ["lab", "pi"])
    monkeypatch.setattr(MODULE, "send_payload", lambda payload, **kwargs: None)
    exit_code = MODULE.main(["--endpoint", "https://example", "--markdown-dir", str(tmp_path)])
    assert exit_code == 0
    snapshots = list(tmp_path.glob("telemetry-*.md"))
    assert snapshots, "expected markdown snapshot file"
    content = snapshots[0].read_text(encoding="utf-8")
    assert "Sugarkube Telemetry Snapshot" in content
    assert "`lab`" in content
    assert "warn" in content
    assert "| Total | Passed | Failed" in content
