import importlib.util
import json
import sys
from pathlib import Path

import pytest

TEAM_MODULE_PATH = Path(__file__).resolve().parent.parent / "scripts" / "sugarkube_teams.py"
if "sugarkube_teams" not in sys.modules:
    TEAM_SPEC = importlib.util.spec_from_file_location("scripts.sugarkube_teams", TEAM_MODULE_PATH)
    TEAM_MODULE = importlib.util.module_from_spec(TEAM_SPEC)
    sys.modules.setdefault("scripts.sugarkube_teams", TEAM_MODULE)
    sys.modules.setdefault("sugarkube_teams", TEAM_MODULE)
    TEAM_SPEC.loader.exec_module(TEAM_MODULE)  # type: ignore[arg-type]

MODULE_PATH = Path(__file__).resolve().parent.parent / "scripts" / "first_boot_service.py"
SPEC = importlib.util.spec_from_file_location("scripts.first_boot_service", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)  # type: ignore[arg-type]


class DummyNotifier:
    should_enable = True
    notifications = []

    def __init__(self):
        self.enabled = type(self).should_enable

    @classmethod
    def from_env(cls):
        return cls()

    def notify(self, *, event, status, lines, fields):
        type(self).notifications.append((event, status, tuple(lines), dict(fields)))


@pytest.fixture(autouse=True)
def _patch_notifier(monkeypatch):
    DummyNotifier.notifications.clear()
    DummyNotifier.should_enable = True
    monkeypatch.setattr(MODULE, "TeamsNotifier", DummyNotifier)
    monkeypatch.setattr(MODULE, "TeamsNotificationError", RuntimeError)


def _configure_env(monkeypatch, tmp_path):
    report_dir = tmp_path / "report"
    log_path = tmp_path / "first-boot.log"
    state_dir = tmp_path / "state"
    verifier = tmp_path / "pi_node_verifier.sh"
    verifier.write_text("#!/bin/sh\n")
    verifier.chmod(0o755)

    ok_marker = state_dir / "first-boot.ok"
    fail_marker = state_dir / "first-boot.failed"
    expand_marker = state_dir / "rootfs-expanded"

    monkeypatch.setenv("FIRST_BOOT_REPORT_DIR", str(report_dir))
    monkeypatch.setenv("FIRST_BOOT_LOG_PATH", str(log_path))
    monkeypatch.setenv("FIRST_BOOT_STATE_DIR", str(state_dir))
    monkeypatch.setenv("FIRST_BOOT_VERIFIER", str(verifier))
    monkeypatch.setenv("FIRST_BOOT_ATTEMPTS", "2")
    monkeypatch.setenv("FIRST_BOOT_RETRY_DELAY", "0")
    monkeypatch.setenv("FIRST_BOOT_SKIP_LOG", "0")
    monkeypatch.setenv("FIRST_BOOT_CLOUD_INIT_TIMEOUT", "5")
    monkeypatch.setenv("FIRST_BOOT_OK_MARKER", str(ok_marker))
    monkeypatch.setenv("FIRST_BOOT_FAIL_MARKER", str(fail_marker))
    monkeypatch.setenv("FIRST_BOOT_EXPAND_MARKER", str(expand_marker))

    return report_dir, log_path, state_dir, verifier, ok_marker, fail_marker, expand_marker


def test_first_boot_service_success(monkeypatch, tmp_path):
    (
        report_dir,
        log_path,
        state_dir,
        verifier,
        ok_marker,
        fail_marker,
        expand_marker,
    ) = _configure_env(monkeypatch, tmp_path)

    state_dir.mkdir(parents=True)
    monkeypatch.setattr(MODULE.time, "sleep", lambda _secs: None)

    raspi_config_path = tmp_path / "raspi-config"
    cloud_init_path = tmp_path / "cloud-init"

    real_which = MODULE.shutil.which

    def fake_which(cmd):
        if cmd == "raspi-config":
            return str(raspi_config_path)
        if cmd == "cloud-init":
            return str(cloud_init_path)
        return real_which(cmd)

    monkeypatch.setattr(MODULE.shutil, "which", fake_which)

    json_attempts = {"count": 0}

    def fake_run(args, capture_output, text, check, timeout=None):  # noqa: ARG001
        if args[0] == str(raspi_config_path):
            return MODULE.subprocess.CompletedProcess(args, 0, "", "")
        if args[0] == str(cloud_init_path):
            return MODULE.subprocess.CompletedProcess(args, 0, "status: done", "")
        if args[0] == str(verifier):
            if "--json" in args:
                json_attempts["count"] += 1
                if json_attempts["count"] == 1:
                    return MODULE.subprocess.CompletedProcess(
                        args,
                        1,
                        json.dumps(
                            {
                                "checks": [
                                    {"name": "cloud_init", "status": "pass"},
                                    {"name": "k3s_node_ready", "status": "pass"},
                                ]
                            }
                        ),
                        "initial failure",
                    )
                return MODULE.subprocess.CompletedProcess(
                    args,
                    0,
                    json.dumps(
                        {
                            "checks": [
                                {"name": "cloud_init", "status": "pass"},
                                {"name": "k3s_node_ready", "status": "pass"},
                                {"name": "projects_compose_active", "status": "pass"},
                                {"name": "token_place_http", "status": "pass"},
                                {"name": "dspace_http", "status": "pass"},
                            ]
                        }
                    ),
                    "",
                )
            if "--log" in args:
                Path(args[-1]).write_text("legacy log\n")
                return MODULE.subprocess.CompletedProcess(args, 0, "", "log stderr")
        raise AssertionError(f"Unexpected command: {args}")

    monkeypatch.setattr(MODULE.subprocess, "run", fake_run)

    assert MODULE.main() == 0

    summary = json.loads((report_dir / "summary.json").read_text())
    assert summary["overall"] == "pass"
    assert summary["summary"]["k3s"] == "pass"
    assert (report_dir / "summary.md").exists()
    assert (report_dir / "summary.html").exists()
    assert (report_dir / "cloud-init.log").read_text().startswith("status: done")
    assert ok_marker.read_text().strip() == "ok"
    assert not fail_marker.exists()
    assert expand_marker.exists()
    assert log_path.exists()
    events = [(event, status) for event, status, *_ in DummyNotifier.notifications]
    assert events == [("first-boot", "starting"), ("first-boot", "success")]


def test_first_boot_service_failure(monkeypatch, tmp_path):
    (
        report_dir,
        _log_path,
        state_dir,
        verifier,
        ok_marker,
        fail_marker,
        expand_marker,
    ) = _configure_env(monkeypatch, tmp_path)

    monkeypatch.setenv("FIRST_BOOT_ATTEMPTS", "1")
    monkeypatch.setenv("FIRST_BOOT_SKIP_LOG", "1")
    state_dir.mkdir(parents=True)
    monkeypatch.setattr(MODULE.time, "sleep", lambda _secs: None)

    real_which = MODULE.shutil.which

    def fake_which(cmd):
        if cmd in {"raspi-config", "cloud-init"}:
            return None
        return real_which(cmd)

    monkeypatch.setattr(MODULE.shutil, "which", fake_which)

    def fake_run(args, capture_output, text, check, timeout=None):  # noqa: ARG001
        if args[0] == str(verifier):
            return MODULE.subprocess.CompletedProcess(
                args,
                2,
                json.dumps(
                    {
                        "checks": [
                            {"name": "cloud_init", "status": "fail"},
                            {"name": "k3s_node_ready", "status": "pass"},
                        ]
                    }
                ),
                "verifier failed",
            )
        raise AssertionError(f"Unexpected command: {args}")

    monkeypatch.setattr(MODULE.subprocess, "run", fake_run)

    result = MODULE.main()
    assert result == 2

    summary = json.loads((report_dir / "summary.json").read_text())
    assert summary["overall"] == "fail"
    assert "cloud_init" in summary["summary"]
    assert not (report_dir / "cloud-init.log").exists()
    assert not expand_marker.exists()
    assert fail_marker.exists()
    assert "verifier exit code 2" in fail_marker.read_text()
    events = [(event, status) for event, status, *_ in DummyNotifier.notifications]
    assert events[-1] == ("first-boot", "failed")


def test_first_boot_service_skips_when_already_ok(monkeypatch, tmp_path):
    (
        _report_dir,
        _log_path,
        state_dir,
        _verifier,
        ok_marker,
        fail_marker,
        _expand_marker,
    ) = _configure_env(monkeypatch, tmp_path)

    state_dir.mkdir(parents=True)
    ok_marker.parent.mkdir(parents=True, exist_ok=True)
    ok_marker.write_text("ok\n")
    if fail_marker.exists():
        fail_marker.unlink()

    assert MODULE.main() == 0
    assert DummyNotifier.notifications == []


def test_notify_teams_no_notifier(monkeypatch):
    monkeypatch.setattr(MODULE, "TeamsNotifier", None)
    MODULE._notify_teams("first-boot", "info", ["line"], {})


def test_notify_teams_handles_setup_error(monkeypatch):
    messages = []
    monkeypatch.setattr(MODULE, "_warn", messages.append)

    class FailingNotifier:
        @classmethod
        def from_env(cls):  # noqa: ANN101, ANN201 - simple stub
            raise MODULE.TeamsNotificationError("bad config")

    monkeypatch.setattr(MODULE, "TeamsNotifier", FailingNotifier)
    MODULE._notify_teams("first-boot", "info", ["line"], {})
    assert any("bad config" in message for message in messages)


def test_run_verifier_requires_attempts():
    with pytest.raises(ValueError):
        MODULE._run_verifier(Path("/tmp/verifier"), 0, 1)  # noqa: SLF001


def test_notify_teams_disabled(monkeypatch):
    DummyNotifier.should_enable = False
    MODULE._notify_teams("first-boot", "info", ["line"], {})
    assert DummyNotifier.notifications == []


def test_expand_rootfs_when_marker_exists(monkeypatch, tmp_path):
    marker = tmp_path / "expanded"
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.touch()
    logs = []
    monkeypatch.setattr(MODULE, "_log", logs.append)
    MODULE._expand_rootfs(marker)
    assert any("already expanded" in entry for entry in logs)


def test_expand_rootfs_failure(monkeypatch, tmp_path):
    marker = tmp_path / "expanded"
    raspi = tmp_path / "raspi-config"
    raspi.write_text("#!/bin/sh\nexit 1\n")
    raspi.chmod(0o755)

    def fake_which(cmd):
        if cmd == "raspi-config":
            return str(raspi)
        return None

    monkeypatch.setattr(MODULE.shutil, "which", fake_which)

    class FakeCompleted:
        returncode = 1
        stderr = "oops"

    monkeypatch.setattr(MODULE.subprocess, "run", lambda *args, **kwargs: FakeCompleted())

    with pytest.raises(RuntimeError):
        MODULE._expand_rootfs(marker)


def test_gather_cloud_init_timeout(monkeypatch):
    def fake_which(cmd):
        return "cloud-init" if cmd == "cloud-init" else None

    monkeypatch.setattr(MODULE.shutil, "which", fake_which)

    def fake_run(*_args, **_kwargs):
        raise MODULE.subprocess.TimeoutExpired(cmd="cloud-init", timeout=5)

    monkeypatch.setattr(MODULE.subprocess, "run", fake_run)
    stdout, code = MODULE._gather_cloud_init(5)
    assert stdout == ""
    assert code is None


def test_gather_cloud_init_empty_output(monkeypatch):
    def fake_which(cmd):
        return "cloud-init" if cmd == "cloud-init" else None

    monkeypatch.setattr(MODULE.shutil, "which", fake_which)

    class FakeResult:
        stdout = "   "
        returncode = 0

    monkeypatch.setattr(MODULE.subprocess, "run", lambda *args, **kwargs: FakeResult())
    stdout, code = MODULE._gather_cloud_init(5)
    assert stdout == "cloud-init did not produce status output"
    assert code == 0


def test_run_verifier_invalid_json(monkeypatch, tmp_path):
    verifier = tmp_path / "verifier"
    verifier.write_text("#!/bin/sh\n")
    verifier.chmod(0o755)

    attempts = {"count": 0}

    def fake_run(args, capture_output, text, check):  # noqa: ARG001
        attempts["count"] += 1
        stdout = "{" if attempts["count"] == 1 else "{}"
        return MODULE.subprocess.CompletedProcess(
            args,
            0 if attempts["count"] > 1 else 1,
            stdout,
            "",
        )

    monkeypatch.setattr(MODULE.subprocess, "run", fake_run)
    monkeypatch.setattr(MODULE.time, "sleep", lambda _secs: None)
    MODULE._run_verifier(verifier, 2, 0)


def test_run_verifier_no_json(monkeypatch, tmp_path):
    verifier = tmp_path / "verifier"
    verifier.write_text("#!/bin/sh\n")
    verifier.chmod(0o755)

    def fake_run(args, capture_output, text, check):  # noqa: ARG001
        return MODULE.subprocess.CompletedProcess(args, 1, "", "")

    monkeypatch.setattr(MODULE.subprocess, "run", fake_run)
    with pytest.raises(RuntimeError):
        MODULE._run_verifier(verifier, 1, 0)


def test_render_summary_mixed_status(tmp_path):
    result = MODULE.VerifierResult(
        data={
            "checks": [
                {"name": "cloud_init", "status": "pass"},
                {"name": "k3s_node_ready", "status": "unknown"},
            ]
        },
        exit_code=0,
        stdout="",
        stderr="",
        attempts=1,
    )
    payload = MODULE._render_summary(result, {}, None)
    assert payload["overall"] == "mixed"


def test_write_verifier_stderr_removes_empty(tmp_path):
    path = tmp_path / "stderr.log"
    path.write_text("old\n")
    MODULE._write_verifier_stderr(path, "")
    assert not path.exists()


def test_import_fallback_when_sugarkube_teams_missing(monkeypatch):
    import builtins

    module_name = "scripts.first_boot_service_missing"
    spec = importlib.util.spec_from_file_location(module_name, MODULE_PATH)
    module = importlib.util.module_from_spec(spec)

    original_import = builtins.__import__

    def fake_import(name, globals=None, locals=None, fromlist=(), level=0):  # noqa: ANN001,B009
        if name == "sugarkube_teams":
            raise ImportError("boom")
        return original_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)  # type: ignore[arg-type]
    assert module.TeamsNotifier is None
    assert module.TeamsNotificationError is RuntimeError


def test_failure_path_clears_ok_marker(monkeypatch, tmp_path):
    (
        report_dir,
        _log_path,
        state_dir,
        verifier,
        ok_marker,
        fail_marker,
        expand_marker,
    ) = _configure_env(monkeypatch, tmp_path)

    state_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(MODULE, "_notify_teams", lambda *args, **kwargs: None)
    monkeypatch.setattr(MODULE, "_expand_rootfs", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(MODULE, "_gather_cloud_init", lambda _timeout: (None, None))
    monkeypatch.setattr(MODULE, "_invoke_verifier_log", lambda *args, **kwargs: 0)
    monkeypatch.setattr(MODULE, "_write_verifier_stderr", lambda *args, **kwargs: None)
    monkeypatch.setattr(MODULE, "_write_json", lambda *args, **kwargs: None)
    monkeypatch.setattr(MODULE, "_write_markdown", lambda *args, **kwargs: None)
    monkeypatch.setattr(MODULE, "_write_html", lambda *args, **kwargs: None)

    def fake_run_verifier(_verifier, attempts, delay):  # noqa: ARG001
        ok_marker.parent.mkdir(parents=True, exist_ok=True)
        ok_marker.write_text("ok\n")
        return MODULE.VerifierResult({"checks": []}, 2, "", "", 1)

    monkeypatch.setattr(MODULE, "_run_verifier", fake_run_verifier)
    monkeypatch.setenv("FIRST_BOOT_ATTEMPTS", "1")
    monkeypatch.setenv("FIRST_BOOT_SKIP_LOG", "1")

    result = MODULE.main()
    assert result == 2
    assert not ok_marker.exists()
    assert fail_marker.exists()


def test_success_path_removes_fail_marker(monkeypatch, tmp_path):
    (
        report_dir,
        log_path,
        state_dir,
        verifier,
        ok_marker,
        fail_marker,
        expand_marker,
    ) = _configure_env(monkeypatch, tmp_path)

    fail_marker.parent.mkdir(parents=True, exist_ok=True)
    fail_marker.write_text("old failure\n")

    state_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(MODULE.time, "sleep", lambda _secs: None)

    raspi_config_path = tmp_path / "raspi-config"
    cloud_init_path = tmp_path / "cloud-init"

    real_which = MODULE.shutil.which

    def fake_which(cmd):
        if cmd == "raspi-config":
            return str(raspi_config_path)
        if cmd == "cloud-init":
            return str(cloud_init_path)
        return real_which(cmd)

    monkeypatch.setattr(MODULE.shutil, "which", fake_which)

    def fake_run(args, capture_output, text, check, timeout=None):  # noqa: ARG001
        if args[0] == str(raspi_config_path):
            return MODULE.subprocess.CompletedProcess(args, 0, "", "")
        if args[0] == str(cloud_init_path):
            return MODULE.subprocess.CompletedProcess(args, 0, "status", "")
        if args[0] == str(verifier):
            if "--json" in args:
                return MODULE.subprocess.CompletedProcess(
                    args,
                    0,
                    json.dumps(
                        {
                            "checks": [
                                {"name": "cloud_init", "status": "pass"},
                                {"name": "k3s_node_ready", "status": "pass"},
                            ]
                        }
                    ),
                    "",
                )
            if "--log" in args:
                Path(args[-1]).write_text("log\n")
                return MODULE.subprocess.CompletedProcess(args, 0, "", "")
        raise AssertionError(f"Unexpected command: {args}")

    monkeypatch.setattr(MODULE.subprocess, "run", fake_run)

    assert MODULE.main() == 0
    assert not fail_marker.exists()
