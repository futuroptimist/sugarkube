from __future__ import annotations

import argparse
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import pytest

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


def test_build_bundle_dir_sanitises_host(tmp_path: Path) -> None:
    ts = datetime(2024, 1, 2, 3, 4, 5, tzinfo=timezone.utc)
    bundle = collect_support_bundle.build_bundle_dir(tmp_path, "pi.local:2222", ts)
    assert bundle.exists()
    assert bundle.name.startswith("pi.local_2222-20240102T030405Z")


def test_parse_extra_specs_invalid_format() -> None:
    with pytest.raises(ValueError, match="Invalid --spec entry"):
        collect_support_bundle.parse_extra_specs(["missing:description"])


def test_parse_extra_specs_rejects_absolute_path() -> None:
    with pytest.raises(ValueError, match="relative"):
        collect_support_bundle.parse_extra_specs(["/abs/path:echo hi:desc"])


def test_parse_args_supports_all_flags(tmp_path: Path) -> None:
    args = collect_support_bundle.parse_args(
        [
            "--user",
            "admin",
            "--identity",
            str(tmp_path / "id_ed25519"),
            "--port",
            "2222",
            "--output-dir",
            str(tmp_path / "bundles"),
            "--command-timeout",
            "45",
            "--connect-timeout",
            "8",
            "--ssh-option",
            "StrictHostKeyChecking=yes",
            "--ssh-option",
            "LogLevel=DEBUG",
            "--no-archive",
            "--spec",
            "extra/out.txt:echo hi:Extra",
            "pi.local",
        ]
    )
    assert args.user == "admin"
    assert args.identity.endswith("id_ed25519")
    assert args.port == 2222
    assert args.output_dir.endswith("bundles")
    assert args.command_timeout == 45
    assert args.connect_timeout == 8
    assert args.ssh_option == ["StrictHostKeyChecking=yes", "LogLevel=DEBUG"]
    assert args.no_archive is True
    assert args.spec == ["extra/out.txt:echo hi:Extra"]
    assert args.host == "pi.local"


def test_build_ssh_command_includes_customisations(tmp_path: Path) -> None:
    args = argparse.Namespace(
        user="admin",
        host="pi.local",
        connect_timeout=7,
        identity=str(tmp_path / "id"),
        port=2022,
        ssh_option=["StrictHostKeyChecking=yes", "LogLevel=DEBUG"],
    )
    cmd = collect_support_bundle.build_ssh_command(args, "echo hi")
    assert cmd[:6] == [
        "ssh",
        "-o",
        "ConnectTimeout=7",
        "-o",
        "BatchMode=yes",
        "-o",
    ]
    assert "-i" in cmd and args.identity in cmd
    assert "-p" in cmd and "2022" in cmd
    assert cmd.count("-o") >= 5  # base options + custom ones
    assert cmd[-3:] == ["bash", "-lc", "set -o pipefail; echo hi"]


def test_write_command_output_creates_parents(tmp_path: Path) -> None:
    target = tmp_path / "nested" / "out.txt"
    collect_support_bundle.write_command_output(target, "payload")
    assert target.read_text(encoding="utf-8") == "payload"


def test_execute_specs_handles_success_failure_timeout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    args = argparse.Namespace(
        user="pi",
        host="pi.local",
        command_timeout=5,
        identity=None,
        port=22,
        ssh_option=[],
        connect_timeout=3,
    )
    specs = [
        collect_support_bundle.CommandSpec(Path("ok.txt"), "echo ok", "Success"),
        collect_support_bundle.CommandSpec(Path("fail.txt"), "echo fail", "Failure"),
        collect_support_bundle.CommandSpec(Path("slow.txt"), "echo slow", "Slow"),
    ]
    bundle_dir = tmp_path / "bundle"
    bundle_dir.mkdir()

    outcomes = iter(
        [
            dict(returncode=0, stdout="ok output\n", stderr=""),
            dict(returncode=5, stdout="", stderr="boom\n"),
            "timeout",
        ]
    )

    class DummyCompleted:
        def __init__(self, returncode: int, stdout: str, stderr: str) -> None:
            self.returncode = returncode
            self.stdout = stdout
            self.stderr = stderr

    def fake_run(cmd: list[str], **kwargs: object) -> DummyCompleted:
        outcome = next(outcomes)
        if outcome == "timeout":
            raise subprocess.TimeoutExpired(cmd, kwargs.get("timeout"))
        assert kwargs["text"] is True
        assert kwargs["capture_output"] is True
        return DummyCompleted(**outcome)

    monkeypatch.setattr(collect_support_bundle.subprocess, "run", fake_run)

    results = collect_support_bundle.execute_specs(args, specs, bundle_dir)

    statuses = [item["status"] for item in results]
    assert statuses == ["success", "failed", "timeout"]

    ok_content = (bundle_dir / "ok.txt").read_text(encoding="utf-8")
    assert "Success" in ok_content and "ok output" in ok_content

    fail_content = (bundle_dir / "fail.txt").read_text(encoding="utf-8")
    assert "Failure" in fail_content
    assert "(no output)" in fail_content
    assert "boom" in fail_content

    timeout_content = (bundle_dir / "slow.txt").read_text(encoding="utf-8")
    assert "Timed out after 5 seconds" in timeout_content


def test_main_handles_bad_spec(capsys: pytest.CaptureFixture[str]) -> None:
    code = collect_support_bundle.main(["--spec", "bad", "pi.local"])
    captured = capsys.readouterr()
    assert code == 2
    assert "error:" in captured.err


def test_main_success_creates_tar(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    summary_dir = tmp_path / "bundles"

    monkeypatch.setattr(collect_support_bundle, "default_specs", lambda: [])

    def fake_execute(args: argparse.Namespace, specs, bundle_dir: Path):
        collect_support_bundle.write_command_output(bundle_dir / "extra.txt", "data")
        return [
            {"command": {}, "status": "success", "exit_code": 0},
            {"command": {}, "status": "failed", "exit_code": 1},
        ]

    monkeypatch.setattr(collect_support_bundle, "execute_specs", fake_execute)

    code = collect_support_bundle.main(["--output-dir", str(summary_dir), "pi.local"])
    captured = capsys.readouterr()

    assert code == 0
    assert "Support bundle saved to" in captured.out
    assert "failed;" in captured.err

    bundles = list(summary_dir.iterdir())
    assert len(bundles) == 2  # directory + archive
    directory = [p for p in bundles if p.is_dir()][0]
    tarball = [p for p in bundles if p.suffixes == [".tar", ".gz"]][0]

    summary = json.loads((directory / "summary.json").read_text(encoding="utf-8"))
    assert summary["results"][0]["status"] == "success"
    assert tarball.exists()


def test_main_returns_failure_when_no_command_success(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(collect_support_bundle, "default_specs", lambda: [])
    monkeypatch.setattr(collect_support_bundle, "execute_specs", lambda *a, **k: [])

    code = collect_support_bundle.main(["--output-dir", str(tmp_path), "--no-archive", "pi.local"])
    captured = capsys.readouterr()

    assert code == 1
    assert "warning: no commands succeeded" in captured.err
    bundle_dirs = [p for p in tmp_path.iterdir() if p.is_dir()]
    assert len(bundle_dirs) == 1
