from __future__ import annotations

import json
import os
import subprocess
from argparse import Namespace
from datetime import datetime, timezone
from pathlib import Path

import pytest
from pytest import CaptureFixture, MonkeyPatch

from scripts import collect_support_bundle


def test_default_specs_cover_required_commands() -> None:
    specs = {
        spec.output_path.as_posix(): spec.remote_command
        for spec in collect_support_bundle.default_specs()
    }
    required = {
        "kubernetes/events.txt": "kubectl get events",
        "helm/releases.txt": "helm list -A",
        "systemd/systemd-analyze-blame.txt": "systemd-analyze blame",
        "compose/docker-compose-logs.txt": "docker compose",
        "journals/journalctl-boot.txt": "journalctl -b",
    }
    for path, snippet in required.items():
        assert path in specs, f"expected {path} in default specs"
        assert snippet in specs[path]


@pytest.mark.parametrize(
    "entry, expected_path",
    [
        ("extra/foo.txt:echo hi:Extra command", Path("extra/foo.txt")),
    ],
)
def test_parse_extra_specs(entry: str, expected_path: Path) -> None:
    spec = collect_support_bundle.parse_extra_specs([entry])[0]
    assert spec.output_path == expected_path
    assert spec.remote_command == "echo hi"
    assert spec.description == "Extra command"


def test_parse_args_includes_target_flag() -> None:
    args = collect_support_bundle.parse_args(["pi.local"])
    assert hasattr(args, "target")
    assert args.target == []


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("", "root"),
        ("///", "root"),
        ("!!!", "target"),
        ("var/log", "var_log"),
    ],
)
def test_sanitize_target_name_variants(raw: str, expected: str) -> None:
    assert collect_support_bundle._sanitize_target_name(raw) == expected


def test_build_bundle_dir_sanitises_host(tmp_path: Path) -> None:
    ts = datetime(2024, 1, 2, 3, 4, 5, tzinfo=timezone.utc)
    bundle = collect_support_bundle.build_bundle_dir(tmp_path, "pi.local:2222", ts)
    assert bundle.exists()
    assert bundle.name.startswith("pi.local_2222-20240102T030405Z")


def test_parse_args_defaults() -> None:
    args = collect_support_bundle.parse_args(["pi.local"])
    assert args.host == "pi.local"
    assert args.user == collect_support_bundle.DEFAULT_USER
    assert args.output_dir == collect_support_bundle.DEFAULT_OUTPUT_DIR
    assert args.command_timeout == collect_support_bundle.DEFAULT_COMMAND_TIMEOUT
    assert args.connect_timeout == collect_support_bundle.DEFAULT_CONNECT_TIMEOUT
    assert args.spec == []
    assert args.target == []


def test_parse_extra_specs_invalid_format() -> None:
    with pytest.raises(ValueError, match="Invalid --spec entry"):
        collect_support_bundle.parse_extra_specs(["only-two:parts"])


def test_parse_extra_specs_rejects_absolute_paths() -> None:
    with pytest.raises(ValueError, match="must be relative"):
        collect_support_bundle.parse_extra_specs(["/abs/path:echo hi:desc"])


def test_build_ssh_command_includes_identity_and_options() -> None:
    args = Namespace(
        user="pi",
        host="pi.local",
        identity="/tmp/id_rsa",
        port=2022,
        connect_timeout=5,
        ssh_option=["LogLevel=ERROR", "Compression=yes"],
        target=[],
    )
    cmd = collect_support_bundle.build_ssh_command(args, "echo hi")
    assert cmd[:2] == ["ssh", "-o"]
    assert "-i" in cmd and cmd[cmd.index("-i") + 1] == "/tmp/id_rsa"
    assert "-p" in cmd and cmd[cmd.index("-p") + 1] == "2022"
    assert cmd.count("-o") >= 5  # includes defaults and custom -o entries
    assert cmd[-3:] == ["bash", "-lc", "set -o pipefail; echo hi"]


def test_write_command_output_creates_parent_dirs(tmp_path: Path) -> None:
    target = tmp_path / "nested" / "output.txt"
    collect_support_bundle.write_command_output(target, "payload")
    assert target.read_text() == "payload"


def test_copy_targets_captures_paths(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    commands: list[list[str]] = []

    class DummyCompleted:
        def __init__(self, returncode: int, stdout: str = "", stderr: str = "") -> None:
            self.returncode = returncode
            self.stdout = stdout
            self.stderr = stderr

    responses = [
        DummyCompleted(0, stdout="ok"),
        DummyCompleted(5, stderr="denied"),
    ]

    def fake_run(cmd: list[str], **_kwargs):
        commands.append(cmd)
        return responses.pop(0)

    monkeypatch.setattr(collect_support_bundle.subprocess, "run", fake_run)

    args = Namespace(
        user="pi",
        host="pi.local",
        identity="/tmp/id_ed25519",
        port=2222,
        connect_timeout=7,
        ssh_option=["LogLevel=ERROR"],
        command_timeout=30,
        target=["/boot/first-boot-report", "/var/log/syslog"],
    )

    results = collect_support_bundle.copy_targets(args, tmp_path)

    assert len(results) == 2
    assert results[0]["status"] == "success"
    assert results[0]["path"] == "/boot/first-boot-report"
    assert "local_path" in results[0]
    assert results[1]["status"] == "failed"
    assert results[1]["path"] == "/var/log/syslog"
    assert results[1]["exit_code"] == 5
    assert commands and commands[0][0] == "scp"


def test_copy_targets_handles_timeout_and_duplicate_names(
    tmp_path: Path, monkeypatch: MonkeyPatch, capsys: CaptureFixture[str]
) -> None:
    class DummyCompleted:
        def __init__(self, returncode: int) -> None:
            self.returncode = returncode
            self.stdout = ""
            self.stderr = ""

    call_count = 0

    def fake_run(cmd: list[str], **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise collect_support_bundle.subprocess.TimeoutExpired(
                cmd=cmd, timeout=kwargs.get("timeout", 0)
            )
        return DummyCompleted(0)

    monkeypatch.setattr(collect_support_bundle.subprocess, "run", fake_run)

    args = Namespace(
        user="pi",
        host="pi.local",
        identity=None,
        port=22,
        connect_timeout=10,
        ssh_option=[],
        command_timeout=12,
        target=["   ", "/var/log/", "etc/config", "etc/config"],
    )

    results = collect_support_bundle.copy_targets(args, tmp_path)

    captured = capsys.readouterr()
    assert "timed out" in captured.err

    assert len(results) == 3
    assert [item["status"] for item in results] == ["timeout", "success", "success"]
    assert results[0]["local_path"].endswith("targets/var_log")
    assert results[1]["local_path"].endswith("targets/etc_config")
    assert results[2]["local_path"].endswith("targets/etc_config-2")


def test_shell_wrapper_exposes_python_cli() -> None:
    script = Path(__file__).resolve().parents[1] / "scripts" / "collect_support_bundle.sh"
    assert script.exists(), "collect_support_bundle.sh wrapper should ship alongside the docs"
    assert os.access(script, os.X_OK), "collect_support_bundle.sh must be executable"
    result = subprocess.run(
        [str(script), "--help"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert "collect_support_bundle.py" in result.stdout


def test_execute_specs_writes_logs(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    calls: list[list[str]] = []

    class DummyCompleted:
        def __init__(self, stdout: str, stderr: str, returncode: int) -> None:
            self.stdout = stdout
            self.stderr = stderr
            self.returncode = returncode

    responses = [
        DummyCompleted("ok", "warning", 0),
        DummyCompleted("", "", 5),
    ]

    def fake_run(cmd: list[str], **kwargs):
        calls.append(cmd)
        return responses.pop(0)

    monkeypatch.setattr(collect_support_bundle.subprocess, "run", fake_run)
    args = Namespace(
        user="pi",
        host="pi.local",
        identity=None,
        port=22,
        connect_timeout=10,
        ssh_option=[],
        command_timeout=30,
        target=[],
    )
    specs = [
        collect_support_bundle.CommandSpec(Path("foo.txt"), "echo foo", "first"),
        collect_support_bundle.CommandSpec(Path("bar.txt"), "echo bar", "second"),
    ]
    bundle_dir = tmp_path
    results = collect_support_bundle.execute_specs(args, specs, bundle_dir)

    assert len(results) == 2
    assert results[0]["status"] == "success"
    assert results[1]["status"] == "failed"
    assert (bundle_dir / "foo.txt").read_text().startswith("# first\n")
    assert "(no output)" in (bundle_dir / "bar.txt").read_text()
    assert calls and calls[0][0] == "ssh"


def test_execute_specs_handles_timeout(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    def fake_run(*_args, **_kwargs):
        raise collect_support_bundle.subprocess.TimeoutExpired(cmd="ssh", timeout=10)

    monkeypatch.setattr(collect_support_bundle.subprocess, "run", fake_run)
    args = Namespace(
        user="pi",
        host="pi.local",
        identity=None,
        port=22,
        connect_timeout=10,
        ssh_option=[],
        command_timeout=10,
        target=[],
    )
    spec = collect_support_bundle.CommandSpec(Path("foo.txt"), "echo foo", "desc")
    results = collect_support_bundle.execute_specs(args, [spec], tmp_path)

    assert results[0]["status"] == "timeout"
    assert "Timed out" in (tmp_path / "foo.txt").read_text()


def test_archive_bundle_creates_tar(tmp_path: Path) -> None:
    bundle_dir = tmp_path / "bundle"
    bundle_dir.mkdir()
    (bundle_dir / "file.txt").write_text("content")
    tar_path = collect_support_bundle.archive_bundle(bundle_dir)
    assert tar_path.exists()


def test_main_invalid_spec_returns_error(tmp_path: Path, capsys: CaptureFixture[str]) -> None:
    exit_code = collect_support_bundle.main(
        ["pi.local", "--output-dir", str(tmp_path), "--spec", "bad-format"]
    )
    captured = capsys.readouterr()
    assert exit_code == 2
    assert "error:" in captured.err


def test_main_success_with_archive(
    tmp_path: Path, monkeypatch: MonkeyPatch, capsys: CaptureFixture[str]
) -> None:
    monkeypatch.setattr(collect_support_bundle, "default_specs", lambda: [])

    def fake_execute(args, specs, bundle_dir):
        (bundle_dir / "artifact.txt").write_text("data")
        return [
            {"command": {"description": "ok"}, "exit_code": 0, "status": "success"},
            {"command": {"description": "bad"}, "exit_code": 1, "status": "failed"},
        ]

    monkeypatch.setattr(collect_support_bundle, "execute_specs", fake_execute)

    exit_code = collect_support_bundle.main(["pi.local", "--output-dir", str(tmp_path)])
    captured = capsys.readouterr()
    assert exit_code == 0
    assert "Support bundle saved to" in captured.out
    assert "warning: 1 command(s) failed" in captured.err

    bundle_dirs = [p for p in tmp_path.iterdir() if p.is_dir()]
    assert bundle_dirs, "expected bundle directory to be created"
    summary_path = bundle_dirs[0] / "summary.json"
    assert summary_path.exists()
    summary = json.loads(summary_path.read_text())
    assert summary["results"][0]["status"] == "success"

    tar_files = list(tmp_path.glob("*.tar.gz"))
    assert tar_files, "expected archive to be created"


def test_main_all_failures_return_nonzero(
    tmp_path: Path, monkeypatch: MonkeyPatch, capsys: CaptureFixture[str]
) -> None:
    monkeypatch.setattr(collect_support_bundle, "default_specs", lambda: [])

    def fake_execute(args, specs, bundle_dir):
        (bundle_dir / "artifact.txt").write_text("data")
        return [
            {"command": {"description": "bad"}, "exit_code": 1, "status": "failed"},
        ]

    monkeypatch.setattr(collect_support_bundle, "execute_specs", fake_execute)

    exit_code = collect_support_bundle.main(
        ["pi.local", "--output-dir", str(tmp_path), "--no-archive"]
    )
    captured = capsys.readouterr()
    assert exit_code == 1
    assert "warning: no commands succeeded" in captured.err
    assert "Support bundle saved to" in captured.out


def test_main_includes_target_results(
    tmp_path: Path, monkeypatch: MonkeyPatch, capsys: CaptureFixture[str]
) -> None:
    monkeypatch.setattr(collect_support_bundle, "default_specs", lambda: [])

    def fake_execute(args, specs, bundle_dir):
        (bundle_dir / "artifact.txt").write_text("data")
        return [{"command": {"description": "ok"}, "exit_code": 0, "status": "success"}]

    def fake_copy_targets(args, bundle_dir):
        return [{"path": "log.txt", "status": "success"}]

    monkeypatch.setattr(collect_support_bundle, "execute_specs", fake_execute)
    monkeypatch.setattr(collect_support_bundle, "copy_targets", fake_copy_targets)

    exit_code = collect_support_bundle.main(
        ["pi.local", "--output-dir", str(tmp_path), "--no-archive"]
    )
    captured = capsys.readouterr()
    assert exit_code == 0
    assert "Support bundle saved to" in captured.out

    bundle_dirs = [p for p in tmp_path.iterdir() if p.is_dir()]
    assert bundle_dirs
    summary_path = bundle_dirs[0] / "summary.json"
    summary = json.loads(summary_path.read_text())
    assert summary["targets"] == [{"path": "log.txt", "status": "success"}]
