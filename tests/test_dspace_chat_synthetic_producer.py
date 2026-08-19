"""Deterministic, host-isolated tests for the repository-owned synthetic producer."""

from __future__ import annotations

import copy
import json
import os
import subprocess
from pathlib import Path

import pytest

from scripts import dspace_chat_synthetic_runtime as runtime
from scripts import install_dspace_chat_synthetic as installer
from scripts import materialize_dspace_chat_runner as materializer

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config/dspace-chat-synthetic.json"


def config(tmp_path: Path) -> dict:
    value = json.loads(CONFIG.read_text(encoding="utf-8"))
    value.update(
        runnerRoot=str(tmp_path / "runners"),
        resultRoot=str(tmp_path / "results"),
        metricPath=str(tmp_path / "metric.prom"),
        metricsConsumer=str(tmp_path / "consumer.py"),
    )
    return value


def git(*args: str, cwd: Path) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True
    ).stdout.strip()


def source_repo(tmp_path: Path) -> tuple[Path, str]:
    source = tmp_path / "source"
    source.mkdir()
    git("init", cwd=source)
    git("config", "user.email", "tests@example.invalid", cwd=source)
    git("config", "user.name", "Tests", cwd=source)
    git("remote", "add", "origin", "https://github.com/democratizedspace/dspace.git", cwd=source)
    (source / "package.json").write_text("{}\n")
    git("add", "package.json", cwd=source)
    git("commit", "-m", "fixture", cwd=source)
    return source, git("rev-parse", "HEAD", cwd=source)


def test_configuration_selects_contracts_and_exact_legacy_coordinate(tmp_path: Path) -> None:
    path = tmp_path / "config.json"
    value = config(tmp_path)
    path.write_text(json.dumps(value))
    assert runtime.load_config(path)["providerConfigContract"] == "legacy-no-default-provider-v1"
    for key in ("identityContract", "providerConfigContract"):
        broken = copy.deepcopy(value)
        broken.pop(key)
        path.write_text(json.dumps(broken))
        with pytest.raises(runtime.Invalid):
            runtime.load_config(path)
    broken = copy.deepcopy(value)
    broken["dspaceVersion"] = "3.1.2"
    path.write_text(json.dumps(broken))
    with pytest.raises(runtime.Invalid, match="coordinate"):
        runtime.load_config(path)
    broken = copy.deepcopy(value)
    broken["schemaVersion"] = 2
    path.write_text(json.dumps(broken))
    with pytest.raises(runtime.Invalid, match="schema"):
        runtime.load_config(path)


def test_wrapper_safety_and_provider_is_in_actual_argv() -> None:
    wrapper = (ROOT / "scripts/dspace_chat_synthetic_wrapper.sh").read_text()
    assert "set +x\nset -Eeuo pipefail\numask 077\nexport PYTHONDONTWRITEBYTECODE=1" in wrapper
    source = (ROOT / "scripts/dspace_chat_synthetic_runtime.py").read_text()
    assert '"--provider",' in source and 'config["provider"],' in source
    assert 'subprocess.run(\n            ["runuser"' in source
    assert source.count("subprocess.DEVNULL") >= 4


@pytest.mark.parametrize("condition", ["wrong-head", "dirty", "missing-object", "identity"])
def test_source_verification_rejects_invalid_git_state(tmp_path: Path, condition: str) -> None:
    source, revision = source_repo(tmp_path)
    identity = "https://github.com/democratizedspace/dspace.git"
    if condition == "wrong-head":
        wanted = "0" * 40
    elif condition == "missing-object":
        wanted = "1" * 40
    elif condition == "dirty":
        (source / "package.json").write_text('{"dirty":true}\n')
        wanted = revision
    else:
        identity = "https://example.invalid/wrong.git"
        wanted = revision
    with pytest.raises((ValueError, subprocess.SubprocessError)):
        materializer.verify_source(source, wanted, identity)


def test_source_verification_rejects_incomplete_metadata(tmp_path: Path) -> None:
    source = tmp_path / "export"
    source.mkdir()
    with pytest.raises(ValueError, match="metadata"):
        materializer.verify_source(source, "0" * 40, "identity")


def snapshot(tmp_path: Path) -> tuple[Path, str]:
    source, revision = source_repo(tmp_path)
    target = tmp_path / "snapshot"
    git("clone", "--local", "--no-hardlinks", str(source), str(target), cwd=tmp_path)
    (target / "node_modules/.pnpm").mkdir(parents=True)
    cli = target / "node_modules/.bin/playwright"
    cli.parent.mkdir(parents=True)
    cli.write_text("#!/bin/sh\nexit 0\n")
    cli.chmod(0o755)
    (target / "frontend/node_modules").mkdir(parents=True)
    return target, revision


@pytest.mark.parametrize("fault", ["alternates", "store", "cli", "broken-link"])
def test_snapshot_validation_rejects_external_or_incomplete_dependencies(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fault: str
) -> None:
    target, revision = snapshot(tmp_path)
    monkeypatch.setattr(
        materializer, "command", lambda *a, **k: revision if "rev-parse" in a else ""
    )
    if fault == "alternates":
        path = target / ".git/objects/info/alternates"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("/external/objects\n")
    elif fault == "store":
        (target / "node_modules/.pnpm").rmdir()
    elif fault == "cli":
        (target / "node_modules/.bin/playwright").chmod(0o644)
    else:
        (target / "frontend/node_modules/broken").symlink_to("/absent")
    with pytest.raises(ValueError):
        materializer.validate(target, revision)


def test_runner_validation_rejects_coordinate_and_hash_mismatch(tmp_path: Path) -> None:
    value = config(tmp_path)
    runner = Path(value["runnerRoot"]) / value["runnerRevision"]
    runner.mkdir(parents=True)
    (runner / "sugarkube-runner-manifest.json").write_text(json.dumps({"runnerRevision": "0" * 40}))
    with pytest.raises(runtime.Invalid, match="coordinate"):
        runtime.validate_runner(value)


@pytest.mark.parametrize("files", [{}, {"../outside": "0" * 64}, {"package.json": "bad"}])
def test_runner_validation_rejects_invalid_manifest_files(tmp_path: Path, files: dict) -> None:
    value = config(tmp_path)
    runner = Path(value["runnerRoot"]) / value["runnerRevision"]
    runner.mkdir(parents=True)
    manifest = {
        "schemaVersion": 1,
        "runnerRevision": value["runnerRevision"],
        "repositoryIdentity": value["repositoryIdentity"],
        "files": files,
    }
    (runner / "sugarkube-runner-manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(runtime.Invalid, match="manifest|coordinate"):
        runtime.validate_runner(value)


def test_directory_mode_ownership_checks(tmp_path: Path) -> None:
    path = tmp_path / "results"
    path.mkdir(mode=0o710)
    info = path.stat()
    runtime.validate_dir(path, info.st_uid, info.st_gid, 0o710)
    path.chmod(0o770)
    with pytest.raises(runtime.Invalid, match="ownership or mode"):
        runtime.validate_dir(path, info.st_uid, info.st_gid, 0o710)


def test_metrics_consumer_success_failure_malformed_and_atomic_preservation(tmp_path: Path) -> None:
    from scripts.dspace_chat_synthetic_metrics import main as consumer_main

    revision = "9" * 40
    result, output = tmp_path / "result.json", tmp_path / "metric.prom"
    output.write_bytes(b"prior-metric-byte-for-byte\n")
    base = {
        "schemaVersion": 1,
        "journey": "/chat",
        "executedAt": int(__import__("time").time()),
        "runnerRevision": revision,
        "transport": "intercepted",
        "mutationEnabled": False,
    }
    import sys

    for passed, expected in ((True, " 1\n"), (False, " 0\n")):
        result.write_text(json.dumps({**base, "passed": passed}))
        monkey = [
            "consumer",
            "--result",
            str(result),
            "--output",
            str(output),
            "--runner-revision",
            revision,
        ]
        old, sys.argv = sys.argv, monkey
        try:
            assert consumer_main() == 0
        finally:
            sys.argv = old
        assert expected in output.read_text()
        assert not list(tmp_path.glob(".dspace-chat.*"))
    previous = output.read_bytes()
    result.write_text('{"rawSecret":"do-not-print"}')
    old, sys.argv = sys.argv, [
        "consumer",
        "--result",
        str(result),
        "--output",
        str(output),
        "--runner-revision",
        revision,
    ]
    try:
        with pytest.raises(SystemExit):
            consumer_main()
    finally:
        sys.argv = old
    assert output.read_bytes() == previous


def test_installer_dry_run_status_apply_and_exact_rollback(tmp_path: Path, capsys) -> None:
    before = set(tmp_path.rglob("*"))
    with __import__("tempfile").TemporaryDirectory() as temporary:
        staged = Path(temporary)
        installer.render(staged)
        installer.validate(staged)
    assert set(tmp_path.rglob("*")) == before
    assert installer.status(tmp_path) == 0
    assert "sha256=missing" in capsys.readouterr().out
    with __import__("tempfile").TemporaryDirectory() as temporary:
        staged = Path(temporary)
        installer.render(staged)
        installer.install(staged, tmp_path, "a" * 40)
    current = tmp_path / "var/lib/sugarkube/dspace-chat-installations/current"
    assert os.readlink(current) == "a" * 40
    retained = current.parent / ("a" * 40)
    installer.activate(retained, tmp_path, "a" * 40)
    with pytest.raises((OSError, ValueError)):
        installer.activate(current.parent / ("b" * 40), tmp_path, "b" * 40)
    with pytest.raises(ValueError, match="40-character"):
        installer.activate(retained, tmp_path, "../escape")


def test_failed_installer_preflight_leaves_installation_unchanged(tmp_path: Path) -> None:
    marker = tmp_path / "installed"
    marker.write_bytes(b"unchanged")
    staged = tmp_path / "bad-stage"
    staged.mkdir()
    (staged / "manifest.json").write_text("{}")
    with pytest.raises(ValueError):
        installer.install(staged, tmp_path, "c" * 40)
    assert marker.read_bytes() == b"unchanged"


def test_units_are_bounded_persistent_hardened_and_never_implicitly_activated() -> None:
    service = (ROOT / "scripts/systemd/dspace-chat-synthetic.service").read_text()
    timer = (ROOT / "scripts/systemd/dspace-chat-synthetic.timer").read_text()
    install = (ROOT / "scripts/install_dspace_chat_synthetic.py").read_text()
    assert "Type=oneshot" in service and "TimeoutStartSec=300" in service
    assert "RuntimeDirectory=sugarkube/dspace-chat-synthetic" in service
    assert "RuntimeDirectoryMode=0710" in service and "Group=pi" in service
    assert "ProtectSystem=strict" in service and "Persistent=true" in timer
    for mutation in (
        "systemctl enable",
        "systemctl start",
        "systemctl stop",
        "systemctl restart",
        "systemctl disable",
    ):
        assert mutation not in install


def test_lifecycle_is_single_shot_owner_scoped_bounded_and_redacted() -> None:
    source = (ROOT / "scripts/dspace_chat_synthetic_runtime.py").read_text()
    assert "LOCK_NB" in source and "INVOCATION_ID" in source
    assert 'f"uid-{account.pw_uid}-{invocation}"' in source
    assert 'timeout=config["timeoutSeconds"]' in source
    assert "result.unlink()" in source and "invocation_dir.rmdir()" in source
    assert "glob(" not in source and "rmtree" not in source
    for forbidden in ("retry", "systemctl", "rollback", "restart"):
        assert forbidden not in source.lower()
