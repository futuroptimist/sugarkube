import argparse
import importlib.util
import subprocess
import sys
import types
from pathlib import Path

import pytest

MODULE_PATH = Path(__file__).resolve().parent.parent / "scripts" / "workflow_artifact_notifier.py"
SPEC = importlib.util.spec_from_file_location("scripts.workflow_artifact_notifier", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules.setdefault("scripts.workflow_artifact_notifier", MODULE)
SPEC.loader.exec_module(MODULE)  # type: ignore[arg-type]


def test_parse_run_url_success():
    reference = MODULE._parse_run_url("https://github.com/foo/bar/actions/runs/12345")
    assert reference.repo == "foo/bar"
    assert reference.run_id == 12345


def test_parse_run_url_invalid():
    with pytest.raises(MODULE.WorkflowNotifierError):
        MODULE._parse_run_url("https://github.com/foo/bar")


def test_resolve_reference_defaults():
    args = argparse.Namespace(run_url=None, repo=None, run_id="42", default_repo="foo/bar")
    reference = MODULE._resolve_reference(args)
    assert reference.repo == "foo/bar"
    assert reference.run_id == 42


def test_resolve_reference_from_url():
    args = argparse.Namespace(
        run_url="https://github.com/futuroptimist/sugarkube/actions/runs/123",
        repo=None,
        run_id=None,
        default_repo=None,
    )
    reference = MODULE._resolve_reference(args)
    assert reference.repo == "futuroptimist/sugarkube"
    assert reference.run_id == 123


def test_resolve_reference_missing_repo():
    args = argparse.Namespace(run_url=None, repo=None, run_id=None, default_repo=None)
    with pytest.raises(MODULE.WorkflowNotifierError):
        MODULE._resolve_reference(args)


def test_detect_platform(monkeypatch):
    monkeypatch.setattr(MODULE, "sys", types.SimpleNamespace(platform="darwin"))
    assert MODULE._detect_platform() == "macos"
    monkeypatch.setattr(MODULE, "sys", types.SimpleNamespace(platform="win32"))
    assert MODULE._detect_platform() == "windows"
    monkeypatch.setattr(MODULE, "sys", types.SimpleNamespace(platform="linux"))
    assert MODULE._detect_platform() == "linux"


def test_system_notifier_linux_command():
    captured = {}

    def fake_runner(command):
        captured["command"] = list(command)

    notifier = MODULE.SystemNotifier(platform="linux", runner=fake_runner)
    notifier.notify(title="Done", body="Artifacts ready", url="https://example")
    command = captured["command"]
    assert command[0] == "notify-send"
    assert command[-1].endswith("https://example")


def test_system_notifier_macos_command():
    captured = {}

    def fake_runner(command):
        captured["command"] = list(command)

    notifier = MODULE.SystemNotifier(platform="macos", runner=fake_runner)
    notifier.notify(title="Ready", body="Artifacts", url=None)
    command = captured["command"]
    assert command[:2] == ["osascript", "-e"]
    assert "display notification" in command[2]


def test_system_notifier_windows_command():
    captured = {}

    def fake_runner(command):
        captured["command"] = list(command)

    notifier = MODULE.SystemNotifier(platform="windows", runner=fake_runner)
    notifier.notify(title="Ready", body="Artifacts' note", url=None)
    command = captured["command"]
    assert command[0] == "powershell"
    assert "ConvertFrom-Json" in command[-1]


def test_system_notifier_missing_backend():
    def failing_runner(_command):
        raise FileNotFoundError

    notifier = MODULE.SystemNotifier(platform="linux", runner=failing_runner)
    with pytest.raises(MODULE.NotificationUnavailableError):
        notifier.notify(title="X", body="Y", url=None)


@pytest.mark.parametrize(
    "size,expected",
    [
        (None, "unknown"),
        (1024, "1.0 KiB"),
        (5 * 1024 * 1024, "5.0 MiB"),
    ],
)
def test_format_size(size, expected):
    assert MODULE._format_size(size) == expected


def test_summarize_artifacts_empty():
    assert MODULE._summarize_artifacts([]) == ["Artifacts: none available"]


def test_workflow_watcher_waits(monkeypatch):
    runs = iter(
        [
            {"status": "in_progress"},
            {
                "status": "completed",
                "run_number": 22,
                "conclusion": "success",
                "html_url": "https://example",
            },
        ]
    )

    class DummyClient:
        def fetch_run(self, reference):
            assert reference.run_id == 99
            return next(runs)

        def fetch_artifacts(self, reference):
            assert reference.repo == "foo/bar"
            return [{"name": "bundle", "size_in_bytes": 1024, "expired": False}]

    monkeypatch.setattr(MODULE.time, "sleep", lambda _seconds: None)
    watcher = MODULE.WorkflowWatcher(
        DummyClient(),
        MODULE.WorkflowReference(repo="foo/bar", run_id=99),
        poll_interval=0.1,
        timeout=5.0,
    )
    run, artifacts = watcher.wait_for_artifacts()
    assert run["run_number"] == 22
    assert len(artifacts) == 1


def test_workflow_watcher_timeout(monkeypatch):
    class DummyClient:
        def fetch_run(self, _reference):
            return {"status": "in_progress"}

        def fetch_artifacts(self, _reference):
            return []

    class FakeTime:
        def __init__(self):
            self.current = 0.0

        def monotonic(self):
            value = self.current
            self.current += 1.0
            return value

        def sleep(self, _seconds):
            self.current += 1.0

    fake_time = FakeTime()
    monkeypatch.setattr(MODULE.time, "monotonic", fake_time.monotonic)
    monkeypatch.setattr(MODULE.time, "sleep", fake_time.sleep)
    watcher = MODULE.WorkflowWatcher(
        DummyClient(),
        MODULE.WorkflowReference(repo="foo/bar", run_id=50),
        poll_interval=0.1,
        timeout=2.0,
    )
    with pytest.raises(MODULE.WorkflowNotifierError):
        watcher.wait_for_artifacts()


def test_build_message_summary():
    run = {
        "run_number": 7,
        "conclusion": "success",
        "head_branch": "main",
        "event": "workflow_dispatch",
    }
    artifacts = [
        {"name": "image", "size_in_bytes": 2048, "expired": False},
        {"name": "old", "size_in_bytes": 5 * 1024 * 1024, "expired": True},
    ]
    title, body = MODULE._build_message(run, artifacts)
    assert "#7" in title
    assert "Conclusion: success" in body
    assert "main" in body
    assert "Artifacts:" in body
    assert "old" in body


def test_parse_arguments_timeout_disable(monkeypatch):
    monkeypatch.setenv("GITHUB_REPOSITORY", "foo/bar")
    args = MODULE._parse_arguments(["--run-id", "1", "--timeout", "0"])
    assert args.timeout is None
    assert args.default_repo == "foo/bar"


def test_cli_print_only(monkeypatch, capsys):
    class DummyWatcher:
        def __init__(self, client, reference, *, poll_interval, timeout):
            assert reference.repo == "foo/bar"
            assert poll_interval == 30.0
            assert timeout == 900.0

        def wait_for_artifacts(self):
            run = {
                "run_number": 10,
                "conclusion": "success",
                "html_url": "https://example/run/10",
                "head_branch": "main",
                "event": "workflow_dispatch",
            }
            artifacts = [{"name": "img", "size_in_bytes": 4096, "expired": False}]
            return run, artifacts

    class DummyClient:
        def __init__(self, executable):
            assert executable == "gh"

    monkeypatch.setattr(MODULE, "WorkflowWatcher", DummyWatcher)
    monkeypatch.setattr(MODULE, "GhClient", DummyClient)

    MODULE.main(
        [
            "--run-url",
            "https://github.com/foo/bar/actions/runs/10",
            "--gh",
            "gh",
            "--print-only",
        ]
    )
    out, err = capsys.readouterr()
    assert "workflow #10" in out.lower()
    assert "Artifacts" in out
    assert err == ""


def test_cli_system_notifier_fallback(monkeypatch, capsys):
    class DummyWatcher:
        def __init__(self, client, reference, *, poll_interval, timeout):
            pass

        def wait_for_artifacts(self):
            run = {
                "run_number": 3,
                "conclusion": "failure",
                "html_url": "https://example/run/3",
            }
            artifacts = []
            return run, artifacts

    class DummyClient:
        def __init__(self, executable):
            assert executable == "gh"

    class DummySystemNotifier:
        def __init__(self, platform=None):
            self.platform = platform

        def notify(self, *, title, body, url):
            raise MODULE.NotificationUnavailableError("missing backend")

    class RecorderConsoleNotifier:
        called = {}

        def notify(self, *, title, body, url):
            RecorderConsoleNotifier.called = {
                "title": title,
                "body": body,
                "url": url,
            }

    monkeypatch.setattr(MODULE, "WorkflowWatcher", DummyWatcher)
    monkeypatch.setattr(MODULE, "GhClient", DummyClient)
    monkeypatch.setattr(MODULE, "SystemNotifier", DummySystemNotifier)
    monkeypatch.setattr(MODULE, "ConsoleNotifier", RecorderConsoleNotifier)

    MODULE.main(
        [
            "--run-url",
            "https://github.com/foo/bar/actions/runs/3",
            "--gh",
            "gh",
        ]
    )
    out, err = capsys.readouterr()
    assert "conclusion: failure" in RecorderConsoleNotifier.called["body"].lower()
    assert "warning" in err.lower()
    assert "run/3" in RecorderConsoleNotifier.called["url"]


def test_gh_client_missing_binary(monkeypatch):
    monkeypatch.setattr(
        MODULE.subprocess,
        "run",
        lambda *args, **kwargs: (_ for _ in ()).throw(FileNotFoundError()),
    )
    client = MODULE.GhClient("gh-missing")
    with pytest.raises(MODULE.WorkflowNotifierError):
        client.fetch_run(MODULE.WorkflowReference(repo="foo/bar", run_id=1))


def test_gh_client_called_process_error(monkeypatch):
    def failing_run(*_args, **_kwargs):
        raise subprocess.CalledProcessError(1, "gh", stderr="boom")

    monkeypatch.setattr(MODULE.subprocess, "run", failing_run)
    client = MODULE.GhClient("gh")
    with pytest.raises(MODULE.WorkflowNotifierError):
        client.fetch_artifacts(MODULE.WorkflowReference(repo="foo/bar", run_id=2))
