from __future__ import annotations

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
        collect_support_bundle.parse_extra_specs(["just-one-part"])


def test_parse_extra_specs_rejects_absolute_paths() -> None:
    with pytest.raises(ValueError, match="relative"):
        collect_support_bundle.parse_extra_specs(["/abs/path:cmd:desc"])


def test_build_ssh_command_includes_identity_port_and_options() -> None:
    args = collect_support_bundle.parse_args(
        [
            "--user",
            "root",
            "--identity",
            "/tmp/id_ed25519",
            "--port",
            "2222",
            "--ssh-option",
            "StrictHostKeyChecking=accept-new",
            "--ssh-option",
            "LogLevel=ERROR",
            "pi.local",
        ]
    )
    command = collect_support_bundle.build_ssh_command(args, "echo hi")

    assert command[0] == "ssh"
    assert "-i" in command and "/tmp/id_ed25519" in command
    assert "-p" in command and "2222" in command
    assert command.count("-o") >= 4  # ConnectTimeout + BatchMode + StrictHostKeyChecking + custom
    assert any(part == "root@pi.local" for part in command)
    assert command[-3:] == ["bash", "-lc", "set -o pipefail; echo hi"]


def test_execute_specs_records_success_failure_and_timeout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    args = collect_support_bundle.parse_args(["--output-dir", str(tmp_path), "pi.local"])
    bundle_dir = tmp_path / "bundle"
    bundle_dir.mkdir()

    specs = [
        collect_support_bundle.CommandSpec(Path("success.txt"), "echo success", "Success command"),
        collect_support_bundle.CommandSpec(
            Path("failure.txt"), "echo fail 1>&2; exit 3", "Failure command"
        ),
        collect_support_bundle.CommandSpec(Path("timeout.txt"), "sleep 5", "Timeout command"),
    ]

    def fake_run(cmd, check, text, capture_output, timeout):  # type: ignore[override]
        remote = cmd[-1].split(";", 1)[-1].strip()
        if "success" in remote:
            return subprocess.CompletedProcess(cmd, 0, stdout="all good\n", stderr="")
        if "fail" in remote:
            return subprocess.CompletedProcess(cmd, 3, stdout="", stderr="oh no\n")
        raise subprocess.TimeoutExpired(cmd=cmd, timeout=timeout)

    monkeypatch.setattr(collect_support_bundle.subprocess, "run", fake_run)

    results = collect_support_bundle.execute_specs(args, specs, bundle_dir)

    assert [item["status"] for item in results] == ["success", "failed", "timeout"]

    success_payload = (bundle_dir / "success.txt").read_text()
    assert "all good" in success_payload

    failure_payload = (bundle_dir / "failure.txt").read_text()
    assert "(no output)" in failure_payload
    assert "# stderr" in failure_payload

    timeout_payload = (bundle_dir / "timeout.txt").read_text()
    assert "Timed out" in timeout_payload


def test_main_creates_archive_and_reports_partial_failures(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    spec = collect_support_bundle.CommandSpec(Path("default.txt"), "ignored", "Default command")
    monkeypatch.setattr(collect_support_bundle, "default_specs", lambda: [spec])

    def fake_execute(args, specs, bundle_dir):
        assert len(specs) == 2
        (bundle_dir / "default.txt").write_text("payload")
        return [
            {"command": specs[0].to_dict(), "exit_code": 0, "status": "success"},
            {
                "command": specs[0].to_dict(),
                "exit_code": 1,
                "status": "failed",
            },
        ]

    monkeypatch.setattr(collect_support_bundle, "execute_specs", fake_execute)

    exit_code = collect_support_bundle.main(
        [
            "--output-dir",
            str(tmp_path),
            "--spec",
            "extras/info.txt:echo hi:Extra info",
            "pi.local",
        ]
    )
    captured = capsys.readouterr()

    assert exit_code == 0
    assert "Support bundle saved to" in captured.out
    assert "tar.gz" in captured.out
    assert "warning: 1 command(s) failed" in captured.err

    bundles = sorted(tmp_path.glob("*.tar.gz"))
    assert bundles, "expected an archive to be created"

    bundle_dirs = [path for path in tmp_path.iterdir() if path.is_dir()]
    assert bundle_dirs, "expected bundle directory to remain on disk"
    summary_path = bundle_dirs[0] / "summary.json"
    assert summary_path.exists()
    summary = json.loads(summary_path.read_text())
    assert summary["results"][0]["status"] == "success"


def test_main_warns_when_all_commands_fail(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    spec = collect_support_bundle.CommandSpec(Path("default.txt"), "ignored", "Default command")
    monkeypatch.setattr(collect_support_bundle, "default_specs", lambda: [spec])

    def fake_execute(args, specs, bundle_dir):
        assert specs
        return [
            {
                "command": specs[0].to_dict(),
                "exit_code": None,
                "status": "timeout",
            }
        ]

    monkeypatch.setattr(collect_support_bundle, "execute_specs", fake_execute)

    exit_code = collect_support_bundle.main(
        [
            "--no-archive",
            "--output-dir",
            str(tmp_path),
            "pi.local",
        ]
    )
    captured = capsys.readouterr()

    assert exit_code == 1
    assert "Support bundle saved to" in captured.out
    assert "warning: no commands succeeded" in captured.err

    bundle_dirs = list(tmp_path.iterdir())
    assert bundle_dirs, "expected bundle directory to exist"
    summary_path = bundle_dirs[0] / "summary.json"
    assert summary_path.exists()
