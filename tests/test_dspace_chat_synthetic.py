import importlib.util
import json
import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
SPEC = importlib.util.spec_from_file_location(
    "synthetic", ROOT / "scripts/dspace_chat_synthetic.py"
)
synthetic = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(synthetic)
CONFIG = ROOT / "config/dspace-chat-synthetic.json"


def config(tmp_path, **updates):
    value = json.loads(CONFIG.read_text())
    value.update(updates)
    path = tmp_path / "config.json"
    path.write_text(json.dumps(value))
    return path


def test_coordinates_and_contracts_are_explicit():
    value = synthetic.load_config(CONFIG)
    assert value["identityContract"] == "build-info-v1"
    assert value["providerConfigContract"] == "legacy-no-default-provider-v1"
    assert value["runnerRevision"] == "97ab09f13fb098de928a878bf1fe9b8d13032cb5"


@pytest.mark.parametrize("field", ["identityContract", "providerConfigContract"])
def test_contract_is_not_inferred_from_absence(tmp_path, field):
    value = json.loads(CONFIG.read_text())
    del value[field]
    path = tmp_path / "bad.json"
    path.write_text(json.dumps(value))
    with pytest.raises(synthetic.Invalid, match="explicit contract"):
        synthetic.load_config(path)


def test_legacy_contract_rejected_for_coordinate_mismatch(tmp_path):
    with pytest.raises(synthetic.Invalid, match="approved immutable"):
        synthetic.load_config(config(tmp_path, dspaceVersion="3.1.2"))


def make_repo(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", repo], check=True)
    subprocess.run(["git", "-C", repo, "config", "user.email", "test@example.invalid"], check=True)
    subprocess.run(["git", "-C", repo, "config", "user.name", "Test"], check=True)
    for name in (
        "package.json",
        "pnpm-lock.yaml",
        "pnpm-workspace.yaml",
        "frontend/package.json",
        "frontend/tests/remote-chat-smoke.spec.ts",
    ):
        path = repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(name)
    subprocess.run(["git", "-C", repo, "add", "."], check=True)
    subprocess.run(["git", "-C", repo, "commit", "-qm", "fixture"], check=True)
    revision = subprocess.check_output(["git", "-C", repo, "rev-parse", "HEAD"], text=True).strip()
    subprocess.run(
        ["git", "-C", repo, "remote", "add", "origin", "https://example.invalid/repo.git"],
        check=True,
    )
    return repo, revision


def test_git_rejects_wrong_or_missing_commit_and_dirty_state(tmp_path):
    repo, revision = make_repo(tmp_path)
    synthetic.validate_git(repo, revision, "https://example.invalid/repo.git")
    with pytest.raises(synthetic.Invalid, match="HEAD or commit"):
        synthetic.validate_git(repo, "0" * 40)
    (repo / "package.json").write_text("dirty")
    with pytest.raises(synthetic.Invalid, match="dirty"):
        synthetic.validate_git(repo, revision)


def test_git_rejects_incomplete_metadata_and_alternates(tmp_path):
    repo, revision = make_repo(tmp_path)
    (repo / ".git/objects/info/alternates").write_text("/external/objects\n")
    with pytest.raises(synthetic.Invalid, match="external Git"):
        synthetic.validate_git(repo, revision)
    shutil = __import__("shutil")
    shutil.rmtree(repo / ".git")
    with pytest.raises(synthetic.Invalid, match="complete independent"):
        synthetic.validate_git(repo, revision)


def test_runner_rejects_hash_store_shim_and_broken_link(tmp_path):
    repo, revision = make_repo(tmp_path)
    cfg = synthetic.load_config(
        config(tmp_path, runnerRevision=revision, repository="https://example.invalid/repo.git")
    )
    (repo / "sugarkube-runner-manifest.json").write_text(
        json.dumps({"revision": revision, "files": {}})
    )
    with pytest.raises(synthetic.Invalid, match="hash mismatch"):
        synthetic.validate_runner(repo, cfg)
    (repo / "sugarkube-runner-manifest.json").write_text(
        json.dumps({"revision": revision, "files": synthetic.hashes(repo)})
    )
    with pytest.raises(synthetic.Invalid, match="pnpm store"):
        synthetic.validate_runner(repo, cfg)
    (repo / "node_modules/.pnpm").mkdir(parents=True)
    shim = repo / cfg["runnerCommand"]
    shim.parent.mkdir(parents=True)
    shim.write_text("#!/bin/sh\nexit 0\n")
    shim.chmod(0o755)
    broken = repo / "frontend/node_modules/broken"
    broken.symlink_to("missing")
    with pytest.raises(synthetic.Invalid, match="broken frontend"):
        synthetic.validate_runner(repo, cfg)


def test_wrapper_argv_preserves_provider_and_redacts_output():
    source = (ROOT / "scripts/dspace_chat_synthetic.py").read_text()
    assert '"--provider",\n        config["provider"]' in source
    assert source.count("subprocess.DEVNULL") >= 4
    assert source.count("argv,") == 1 and "retry" not in source.lower()


def test_units_are_bounded_persistent_and_never_activate():
    service = (ROOT / "scripts/systemd/sugarkube-dspace-chat-synthetic.service").read_text()
    timer = (ROOT / "scripts/systemd/sugarkube-dspace-chat-synthetic.timer").read_text()
    assert "Type=oneshot" in service and "TimeoutStartSec=240" in service
    assert "Persistent=true" in timer
    combined = service + timer + (ROOT / "scripts/dspace_chat_synthetic.py").read_text()
    assert "systemctl enable" not in combined and "systemctl start" not in combined


def test_dry_run_validation_failure_is_non_mutating(tmp_path, monkeypatch):
    cfg = synthetic.load_config(CONFIG)
    marker = tmp_path / "prefix/unchanged"
    marker.parent.mkdir()
    marker.write_text("before")
    args = type(
        "Args",
        (),
        {
            "prefix": marker.parent,
            "runner": tmp_path / "missing",
            "wrapper": Path(),
            "config": CONFIG,
            "service": Path(),
            "timer": Path(),
            "apply": False,
        },
    )
    with pytest.raises(Exception):
        synthetic.install(args, cfg)
    assert marker.read_text() == "before"


def test_status_is_non_mutating_and_reports_missing_hashes(tmp_path, capsys):
    before = list(tmp_path.iterdir())
    synthetic.status(tmp_path, synthetic.load_config(CONFIG))
    report = json.loads(capsys.readouterr().out)
    assert set(report["fileSha256"].values()) == {"missing"}
    assert report["timerActive"] == "not-queried"
    assert list(tmp_path.iterdir()) == before


def test_result_lifecycle_guards_are_present():
    source = (ROOT / "scripts/dspace_chat_synthetic.py").read_text()
    for contract in (
        "INVOCATION_ID",
        "LOCK_NB",
        "result path already exists",
        "outside invocation window",
        "ownership/mode mismatch",
        "os.replace(temporary, target)",
        "shutil.rmtree(result_dir",
    ):
        assert contract in source
