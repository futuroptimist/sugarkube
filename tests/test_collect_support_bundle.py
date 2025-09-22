from __future__ import annotations

import json
import subprocess
import tarfile
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


def test_parse_extra_specs_rejects_invalid_entries() -> None:
    with pytest.raises(ValueError):
        collect_support_bundle.parse_extra_specs(["missing parts"])
    with pytest.raises(ValueError):
        collect_support_bundle.parse_extra_specs(["/abs/path:cmd:desc"])


def test_build_ssh_command_includes_identity_port_and_options(tmp_path: Path) -> None:
    args = collect_support_bundle.parse_args(
        [
            "pi.local",
            "--user",
            "root",
            "--identity",
            str(tmp_path / "id_ed25519"),
            "--port",
            "2222",
            "--ssh-option",
            "StrictHostKeyChecking=yes",
        ]
    )
    cmd = collect_support_bundle.build_ssh_command(args, "echo hello")
    assert "-i" in cmd
    assert str(tmp_path / "id_ed25519") in cmd
    assert "-p" in cmd
    assert "2222" in cmd
    assert "StrictHostKeyChecking=yes" in cmd
    assert cmd[-3:] == ["bash", "-lc", "set -o pipefail; echo hello"]


def test_execute_specs_covers_success_failure_timeout_and_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    args = collect_support_bundle.parse_args(["pi.local", "--output-dir", str(tmp_path)])
    specs = [
        collect_support_bundle.CommandSpec(Path("ok.txt"), "echo ok", "success"),
        collect_support_bundle.CommandSpec(Path("fail.txt"), "exit 1", "failure"),
        collect_support_bundle.CommandSpec(Path("slow.txt"), "sleep", "timeout"),
        collect_support_bundle.CommandSpec(Path("error.txt"), "boom", "error"),
    ]

    responses = [
        subprocess.CompletedProcess(args=[], returncode=0, stdout="ok\n", stderr=""),
        subprocess.CompletedProcess(args=[], returncode=3, stdout="bad", stderr="sad"),
        subprocess.TimeoutExpired(cmd="sleep", timeout=args.command_timeout),
        RuntimeError("boom"),
    ]

    def fake_run(*_args, **_kwargs):
        resp = responses.pop(0)
        if isinstance(resp, Exception):
            raise resp
        return resp

    monkeypatch.setattr(collect_support_bundle.subprocess, "run", fake_run)

    bundle_dir = tmp_path / "bundle"
    bundle_dir.mkdir()
    results = collect_support_bundle.execute_specs(args, specs, bundle_dir)

    statuses = [item["status"] for item in results]
    assert statuses == ["success", "failed", "timeout", "error"]

    success_output = (bundle_dir / "ok.txt").read_text(encoding="utf-8")
    assert "Exit status: 0" in success_output

    failure_output = (bundle_dir / "fail.txt").read_text(encoding="utf-8")
    assert "sad" in failure_output
    assert "Exit status: 3" in failure_output

    timeout_output = (bundle_dir / "slow.txt").read_text(encoding="utf-8")
    assert "Timed out" in timeout_output

    error_output = (bundle_dir / "error.txt").read_text(encoding="utf-8")
    assert "Error: boom" in error_output


def test_archive_bundle_creates_tar(tmp_path: Path) -> None:
    bundle_dir = tmp_path / "bundle"
    bundle_dir.mkdir()
    (bundle_dir / "file.txt").write_text("data", encoding="utf-8")
    tar_path = collect_support_bundle.archive_bundle(bundle_dir)
    assert tar_path.exists()
    with tarfile.open(tar_path, "r:gz") as tar:
        names = tar.getnames()
    assert bundle_dir.name + "/file.txt" in names


def test_main_creates_bundle_and_archive(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    fake_specs = [collect_support_bundle.CommandSpec(Path("ok.txt"), "cmd", "desc")]

    monkeypatch.setattr(
        collect_support_bundle,
        "default_specs",
        lambda: fake_specs,
    )

    def fake_execute(args, specs, bundle_dir):
        assert specs == fake_specs
        (bundle_dir / "ok.txt").write_text("payload", encoding="utf-8")
        return [
            {"command": specs[0].to_dict(), "exit_code": 0, "status": "success"},
            {"command": specs[0].to_dict(), "exit_code": 2, "status": "failed"},
        ]

    monkeypatch.setattr(collect_support_bundle, "execute_specs", fake_execute)

    exit_code = collect_support_bundle.main(
        ["pi.local", "--output-dir", str(tmp_path), "--command-timeout", "5"]
    )

    assert exit_code == 0

    bundle_dirs = [p for p in tmp_path.iterdir() if p.is_dir()]
    assert len(bundle_dirs) == 1
    bundle_dir = bundle_dirs[0]
    summary = json.loads((bundle_dir / "summary.json").read_text(encoding="utf-8"))
    assert summary["host"] == "pi.local"
    assert any(item["status"] == "success" for item in summary["results"])

    tarball = bundle_dir.with_suffix(".tar.gz")
    assert tarball.exists()

    out = capsys.readouterr()
    assert "warning: 1 command(s) failed" in out.err


def test_main_returns_error_when_no_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(collect_support_bundle, "default_specs", lambda: [])
    monkeypatch.setattr(
        collect_support_bundle,
        "execute_specs",
        lambda args, specs, bundle_dir: [{"command": {}, "exit_code": None, "status": "timeout"}],
    )

    exit_code = collect_support_bundle.main(
        ["pi.local", "--no-archive", "--output-dir", str(tmp_path)]
    )
    assert exit_code == 1


def test_main_rejects_invalid_spec(capsys: pytest.CaptureFixture[str]) -> None:
    exit_code = collect_support_bundle.main(["pi.local", "--spec", "bad-entry"])
    err = capsys.readouterr().err
    assert exit_code == 2
    assert "Invalid --spec" in err
