import hashlib
import json
import os
import subprocess
from pathlib import Path

import pytest

from scripts import dspace_chat_synthetic as producer

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config/dspace-chat-synthetic/staging.json"
INSTALLER = ROOT / "scripts/install_dspace_chat_synthetic.py"


def test_config_explicitly_binds_approved_coordinates():
    value = producer.load_config(CONFIG)
    assert value["identityContract"] == "build-info-v1"
    assert value["providerConfigContract"] == "legacy-no-default-provider-v1"
    assert value["runnerRevision"] == "97ab09f13fb098de928a878bf1fe9b8d13032cb5"
    assert value["dspaceSourceRevision"] == "22f506e07e0b5abfd0cf756e9c5827c0458fb4b2"


def test_contract_is_not_inferred_from_absence(tmp_path):
    value = json.loads(CONFIG.read_text())
    del value["providerConfigContract"]
    path = tmp_path / "config.json"
    path.write_text(json.dumps(value))
    with pytest.raises(producer.SyntheticError, match="exact schema"):
        producer.load_config(path)


def test_legacy_contract_rejected_for_coordinate_drift(tmp_path):
    value = json.loads(CONFIG.read_text())
    value["dspaceVersion"] = "3.1.2"
    path = tmp_path / "config.json"
    path.write_text(json.dumps(value))
    with pytest.raises(producer.SyntheticError, match="not approved"):
        producer.load_config(path)


def test_valid_result_binds_invocation_window_owner_and_mode(tmp_path):
    config = json.loads(CONFIG.read_text())
    invocation = "a" * 32
    path = tmp_path / "result.json"
    value = {
        "schemaVersion": 1,
        "journey": "/chat",
        "passed": True,
        "executedAt": 100,
        "completedAt": 101,
        "invocationId": invocation,
        "runnerRevision": config["runnerRevision"],
        "transport": "intercepted",
        "mutationEnabled": False,
    }
    path.write_text(json.dumps(value))
    path.chmod(0o600)
    assert producer.valid_result(path, config, invocation, 99, 102, os.getuid(), os.getgid())
    for field, replacement in (
        ("invocationId", "b" * 32),
        ("executedAt", 98),
        ("completedAt", 103),
        ("passed", "true"),
    ):
        changed = dict(value)
        changed[field] = replacement
        path.write_text(json.dumps(changed))
        path.chmod(0o600)
        assert not producer.valid_result(
            path, config, invocation, 99, 102, os.getuid(), os.getgid()
        )
    path.write_text(json.dumps(value))
    path.chmod(0o644)
    assert not producer.valid_result(path, config, invocation, 99, 102, os.getuid(), os.getgid())


def test_metric_publication_is_atomic_and_preservation_is_callers_default(tmp_path, monkeypatch):
    output = tmp_path / "metric.prom"
    output.write_bytes(b"previous\n")
    before = output.read_bytes()
    assert before == b"previous\n"
    replaced = []
    original = producer.os.replace
    monkeypatch.setattr(
        producer.os,
        "replace",
        lambda source, target: (replaced.append((source, target)), original(source, target))[1],
    )
    producer.publish_metric(output, True, 123)
    assert replaced and output.read_text().endswith(" 123\n")
    assert "dspace_chat_synthetic_success" in output.read_text()


def test_wrapper_safety_provider_argv_and_units():
    wrapper = (ROOT / "scripts/dspace_chat_synthetic").read_text()
    assert wrapper.splitlines()[1:5] == [
        "set +x",
        "set -Eeuo pipefail",
        "umask 077",
        "export PYTHONDONTWRITEBYTECODE=1",
    ]
    source = (ROOT / "scripts/dspace_chat_synthetic.py").read_text()
    assert '"--provider"' in source and 'config["provider"]' in source
    assert "shutil.rmtree(result_dir)" in source
    assert "glob-based cleanup" not in source
    service = (ROOT / "scripts/systemd/sugarkube-dspace-chat-synthetic.service").read_text()
    timer = (ROOT / "scripts/systemd/sugarkube-dspace-chat-synthetic.timer").read_text()
    assert "Type=oneshot" in service and "TimeoutStartSec=330s" in service
    assert "Persistent=true" in timer
    assert "systemctl" not in service + timer


def test_installer_dry_run_and_status_are_non_mutating(tmp_path):
    before = hashlib.sha256(str(sorted(tmp_path.rglob("*"))).encode()).hexdigest()
    result = subprocess.run(
        [str(INSTALLER), "install", "--root", str(tmp_path)],
        text=True,
        capture_output=True,
        check=False,
        cwd=ROOT,
    )
    assert result.returncode == 0, result.stderr
    assert "no files or units changed" in result.stdout
    assert not list(tmp_path.rglob("*"))
    status = subprocess.run(
        [str(INSTALLER), "status", "--root", str(tmp_path)],
        text=True,
        capture_output=True,
        check=False,
        cwd=ROOT,
    )
    assert status.returncode == 0 and "timerActivation=absent" in status.stdout
    assert before == hashlib.sha256(str(sorted(tmp_path.rglob("*"))).encode()).hexdigest()


@pytest.mark.parametrize("revision", ["", "abc", "g" * 40, "1" * 39])
def test_rollback_requires_exact_retained_revision(tmp_path, revision):
    result = subprocess.run(
        [str(INSTALLER), "rollback", "--root", str(tmp_path), "--revision", revision],
        text=True,
        capture_output=True,
        check=False,
        cwd=ROOT,
    )
    assert result.returncode != 0
    assert not list(tmp_path.rglob("*"))
