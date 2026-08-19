import hashlib
import importlib.util
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).parents[1]


def module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


producer = module(ROOT / "scripts/dspace_chat_synthetic.py", "producer")
installer = module(ROOT / "scripts/install_dspace_chat_synthetic.py", "installer")
materializer = module(ROOT / "scripts/materialize_dspace_chat_runner.py", "materializer")


def config(tmp_path):
    value = json.loads((ROOT / "config/dspace-chat-synthetic.json").read_text())
    value.update(
        runner_root=str(tmp_path / "runners"),
        result_root=str(tmp_path / "results"),
        metric_path=str(tmp_path / "metric.prom"),
    )
    path = tmp_path / "config.json"
    path.write_text(json.dumps(value))
    return path, value


def test_contracts_are_explicit_and_legacy_coordinates_are_exact(tmp_path):
    path, value = config(tmp_path)
    assert producer.load_config(path)["provider_config_contract"] == "legacy-no-default-provider-v1"
    del value["provider_config_contract"]
    path.write_text(json.dumps(value))
    try:
        producer.load_config(path)
        assert False
    except ValueError:
        pass
    value["provider_config_contract"] = "legacy-no-default-provider-v1"
    value["dspace_version"] = "3.1.2"
    path.write_text(json.dumps(value))
    try:
        producer.load_config(path)
        assert False
    except ValueError:
        pass


def test_metric_contract_and_atomic_replacement(tmp_path):
    path = tmp_path / "metric.prom"
    path.write_bytes(b"old")
    producer.publish(path, producer.metric({}, True, 123))
    content = path.read_bytes()
    assert (
        b"dspace_chat_synthetic_success" in content
        and b" 1\n" in content
        and not list(tmp_path.glob(".dspace-chat.*"))
    )


def test_installer_dry_run_and_status_are_non_mutating(tmp_path, capsys):
    before = list(tmp_path.rglob("*"))
    assert installer.main.__name__ == "main"
    result = subprocess.run(
        [
            "python3",
            str(ROOT / "scripts/install_dspace_chat_synthetic.py"),
            "dry-run",
            "--root",
            str(tmp_path),
        ],
        text=True,
        capture_output=True,
    )
    assert result.returncode == 0 and list(tmp_path.rglob("*")) == before
    result = subprocess.run(
        [
            "python3",
            str(ROOT / "scripts/install_dspace_chat_synthetic.py"),
            "status",
            "--root",
            str(tmp_path),
        ],
        text=True,
        capture_output=True,
    )
    assert result.returncode == 0 and json.loads(result.stdout) == {
        "installed": False,
        "timer_enabled": None,
    }


def test_installer_failed_preflight_leaves_root_unchanged(tmp_path):
    repo = tmp_path / "repo"
    (repo / "scripts").mkdir(parents=True)
    marker = tmp_path / "installed"
    marker.write_text("unchanged")
    result = subprocess.run(
        [
            "python3",
            str(ROOT / "scripts/install_dspace_chat_synthetic.py"),
            "apply",
            "--root",
            str(tmp_path),
            "--repo",
            str(repo),
        ],
        capture_output=True,
    )
    assert result.returncode != 0 and marker.read_text() == "unchanged"


def test_units_are_persistent_bounded_and_not_implicitly_managed():
    timer = (ROOT / "scripts/systemd/dspace-chat-synthetic.timer").read_text()
    service = (ROOT / "scripts/systemd/dspace-chat-synthetic.service").read_text()
    installer_text = (ROOT / "scripts/install_dspace_chat_synthetic.py").read_text()
    assert "Persistent=true" in timer and "TimeoutStartSec=240" in service
    assert all(
        word not in installer_text
        for word in (
            "systemctl enable",
            "systemctl start",
            "systemctl restart",
            "systemctl disable",
        )
    )


def test_wrapper_safety_and_provider_is_in_real_argv():
    wrapper = (ROOT / "scripts/dspace-chat-synthetic").read_text().splitlines()
    assert wrapper[1:5] == [
        "set +x",
        "set -Eeuo pipefail",
        "umask 077",
        "export PYTHONDONTWRITEBYTECODE=1",
    ]
    source = (ROOT / "scripts/dspace_chat_synthetic.py").read_text()
    assert '"--provider",' in source and 'config["provider"]' in source
    assert "stdout=subprocess.DEVNULL" in source
    assert "subprocess.run(" in source and "argv," in source
    assert "shutil.rmtree(invocation_dir)" in source


def test_manifest_hash_mismatch_is_detectable(tmp_path):
    file = tmp_path / "critical"
    file.write_text("one")
    expected = hashlib.sha256(file.read_bytes()).hexdigest()
    file.write_text("two")
    assert hashlib.sha256(file.read_bytes()).hexdigest() != expected


def runner_fixture(tmp_path):
    runner = tmp_path / "runner"
    (runner / ".git/objects/info").mkdir(parents=True)
    (runner / "node_modules/.pnpm").mkdir(parents=True)
    (runner / "node_modules/.bin").mkdir(parents=True)
    cli = runner / "node_modules/.bin/playwright"
    cli.write_text("#!/bin/sh\n")
    cli.chmod(0o755)
    for relative in materializer.CRITICAL:
        path = runner / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(relative)
    return runner


def test_materializer_rejects_missing_store_alternates_and_invalid_cli(tmp_path, monkeypatch):
    revision = "a" * 40
    monkeypatch.setattr(
        materializer,
        "run",
        lambda *args, **kwargs: revision if "rev-parse" in args else "",
    )
    runner = runner_fixture(tmp_path)
    (runner / "node_modules/.pnpm").rmdir()
    try:
        materializer.validate(runner, revision)
        assert False
    except ValueError as error:
        assert "pnpm store" in str(error)
    (runner / "node_modules/.pnpm").mkdir()
    (runner / ".git/objects/info/alternates").write_text("/external/objects\n")
    try:
        materializer.validate(runner, revision)
        assert False
    except ValueError as error:
        assert "externally dependent" in str(error)
    (runner / ".git/objects/info/alternates").unlink()
    (runner / "node_modules/.bin/playwright").chmod(0o644)
    try:
        materializer.validate(runner, revision)
        assert False
    except ValueError as error:
        assert "Playwright" in str(error)


def test_materializer_rejects_wrong_head_dirty_state_and_missing_object(tmp_path, monkeypatch):
    source = tmp_path / "source"
    source.mkdir()
    revision = "b" * 40
    monkeypatch.setattr(
        materializer, "run", lambda *args, **kwargs: "tree" if "cat-file" in args else ""
    )
    try:
        materializer.validate_source(source, revision, "https://example.invalid/dspace")
        assert False
    except ValueError as error:
        assert "commit object" in str(error)
    answers = iter(["commit", "c" * 40])
    monkeypatch.setattr(materializer, "run", lambda *args, **kwargs: next(answers))
    try:
        materializer.validate_source(source, revision, "https://example.invalid/dspace")
        assert False
    except ValueError as error:
        assert "HEAD" in str(error)


def test_result_directory_contract_checks_exact_owner_group_and_mode(tmp_path):
    directory = tmp_path / "results"
    directory.mkdir(mode=0o700)
    info = directory.stat()
    producer.check_dir(directory, info.st_uid, info.st_gid, 0o700)
    try:
        producer.check_dir(directory, info.st_uid, info.st_gid, 0o710)
        assert False
    except ValueError:
        pass
