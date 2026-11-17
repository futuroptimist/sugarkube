"""Unprivileged safeguards for the separately approved disposable guest harness."""

import hashlib
import importlib.util
import json
from pathlib import Path, PureWindowsPath
import subprocess
import sys
import zipfile

import pytest

DIRECTORY = Path(__file__).resolve().parents[1] / "scripts/qualification"


def load(name):
    spec = importlib.util.spec_from_file_location(name, DIRECTORY / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("name", ["resolver_lifecycle", "resolver_offline_prepare"])
def test_optimized_python_refused_before_operational_entrypoint(name):
    result = subprocess.run(
        [sys.executable, "-O", str(DIRECTORY / f"{name}.py"), "--help"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode != 0 and "requires assertions enabled" in result.stderr


@pytest.mark.parametrize("error", [OSError("gone"), ValueError("unrelated")])
def test_unrelated_refusal_does_not_count_as_qualification(error):
    module = load("resolver_lifecycle")
    records = []

    def fail():
        raise error

    with pytest.raises((OSError, AssertionError)):
        module.refused(fail, "K3s resolver directory mount drifted", records)
    assert records == []


@pytest.mark.parametrize("failure", ["hash", "traversal", "installer"])
def test_invalid_offline_wheel_does_not_create_dependency_directory(tmp_path, failure):
    module = load("resolver_offline_prepare")
    wheels = tmp_path / "wheels"
    wheels.mkdir()
    wheel = wheels / "fixture.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr("fixture.dist-info/WHEEL", "Root-Is-Purelib: true\n")
        if failure == "traversal":
            archive.writestr("../escape", "wrong")
        if failure == "installer":
            archive.writestr("fixture.data/scripts/run", "wrong")
    digest = hashlib.sha256(wheel.read_bytes()).hexdigest()
    (tmp_path / "python-dependencies.json").write_text(
        json.dumps(
            {
                "packages": [
                    {
                        "file": "wheels/fixture.whl",
                        "sha256": "0" * 64 if failure == "hash" else digest,
                    }
                ]
            }
        )
    )
    destination = tmp_path / "deps"
    with pytest.raises(AssertionError):
        module.prepare(tmp_path, destination)
    assert not destination.exists()
    assert not (tmp_path / "escape").exists()


def test_early_pytest_failure_persists_result_and_runs_cleanup(tmp_path, monkeypatch):
    from types import SimpleNamespace

    module = load("resolver_lifecycle")
    # Model the approved guest, independently of CI's floating host interpreter.
    # Replace only this module's reference; do not mutate the process-wide sys module.
    monkeypatch.setattr(
        module, "sys", SimpleNamespace(version_info=(3, 12, 0), executable=sys.executable)
    )
    monkeypatch.setattr(module, "ROOT", tmp_path / "fixture")
    monkeypatch.setattr(module.os, "geteuid", lambda: 0)
    monkeypatch.setattr(module.os, "readlink", lambda _: "../run/systemd/resolve/stub-resolv.conf")
    monkeypatch.setattr(module.socket, "gethostname", lambda: "sugarkube-lifecycle-proof-v1")
    monkeypatch.setattr(module.shutil, "which", lambda _: "/usr/bin/real-tool")
    monkeypatch.setattr(module, "run", lambda *args: "LoadState=not-found")
    monkeypatch.setattr(module, "baseline", lambda: {"links": [{"ifname": "lo"}]})
    monkeypatch.setattr(module, "module", lambda: SimpleNamespace())
    for key, value in module.FLAGS.items():
        monkeypatch.setenv(key, value)

    def failed_pytest(*args, **kwargs):
        assert "timeout" not in kwargs  # One-shot session deadline owns descendants.
        raise subprocess.CalledProcessError(2, args[0])

    monkeypatch.setattr(module.subprocess, "run", failed_pytest)
    output = tmp_path / "result.json"
    with pytest.raises(subprocess.CalledProcessError):
        module.qualify(output)
    result = json.loads(output.read_text())
    assert result["passed"] is False and result["cleanup_passed"] is True
    assert result["namespace_cases"] == 0 and "CalledProcessError" in result["error"]


@pytest.mark.parametrize("version", [(3, 11, 5), (3, 13, 0), (3, 14, 8)])
def test_guest_version_gate_refuses_other_interpreters_before_work(tmp_path, monkeypatch, version):
    from types import SimpleNamespace

    module = load("resolver_lifecycle")
    monkeypatch.setattr(module, "sys", SimpleNamespace(version_info=version))
    monkeypatch.setattr(
        module.os, "readlink", lambda *args: pytest.fail("version gate reached host resolver")
    )
    monkeypatch.setattr(module, "run", lambda *args: pytest.fail("version gate reached a command"))
    monkeypatch.setattr(module, "baseline", lambda: pytest.fail("version gate reached baseline"))
    output = tmp_path / "result.json"
    with pytest.raises(AssertionError):
        module.qualify(output)
    assert not output.exists()


@pytest.mark.parametrize("mismatch", ["sid", "start_ticks"])
def test_ambiguous_group_identity_refuses_signaling(monkeypatch, mismatch):
    monkeypatch.syspath_prepend(str(DIRECTORY))
    module = load("resolver_oneshot")
    record = {"pid": 100, "pgid": 100, "sid": 100, "start_ticks": 500}
    record[mismatch] += 1
    with pytest.raises(RuntimeError, match="do not signal"):
        module.owned([record], 100, 500)


def test_already_removed_units_are_clean_only_with_verified_properties(monkeypatch):
    monkeypatch.syspath_prepend(str(DIRECTORY))
    module = load("resolver_oneshot")
    properties = "LoadState=not-found\nMainPID=0\nActiveState=inactive"
    assert module.already_cleaned(properties)
    assert not module.already_cleaned(properties.replace("MainPID=0", "MainPID=123"))
    assert not module.already_cleaned(properties.replace("inactive", "deactivating"))


def test_windows_preparation_names_are_linux_paths():
    module = load("build_resolver_bundle")
    root = PureWindowsPath(r"C:\Users\owner\bundle")
    path = root / "source" / "scripts" / "resolver.py"
    digest = "a" * 64
    assert module.checksum_record(path, root, digest) == (digest + "  source/scripts/resolver.py\n")
    assert module.relative_name(path, root.parent) == "bundle/source/scripts/resolver.py"


def test_generated_manifest_explicitly_uses_utf8_and_lf(tmp_path):
    module = load("build_resolver_bundle")
    calls = []

    class RecordingPath:
        def write_text(self, text, **kwargs):
            calls.append((text, kwargs))

    text = '{"note":"café"}\n'
    module.write_utf8(RecordingPath(), text)
    assert calls == [(text, {"encoding": "utf-8", "newline": "\n"})]
    target = tmp_path / "manifest.json"
    module.write_utf8(target, text)
    assert target.read_bytes() == text.encode("utf-8")


def test_preparation_sources_parse_as_python_311():
    import ast

    for name in ("build_resolver_bundle", "resolver_offline_prepare"):
        ast.parse((DIRECTORY / f"{name}.py").read_text(encoding="utf-8"), feature_version=(3, 11))


def test_builder_rejects_older_python_before_reading_repository(tmp_path, monkeypatch):
    module = load("build_resolver_bundle")
    monkeypatch.setattr(module.sys, "version_info", (3, 10, 0))
    with pytest.raises(RuntimeError, match="Python 3.11"):
        module.build(tmp_path, "a" * 40, tmp_path / "bundle.tar.gz")
