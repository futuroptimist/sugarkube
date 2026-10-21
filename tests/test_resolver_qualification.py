"""Unprivileged safeguards for the separately approved disposable guest harness."""

import hashlib
import importlib.util
import json
from pathlib import Path
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
