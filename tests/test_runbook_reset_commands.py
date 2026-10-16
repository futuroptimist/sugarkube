"""Exercise reset templates offline against a recorder, never K3s or sudo."""

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

RUNBOOK = Path(__file__).resolve().parents[1] / "docs" / "runbook.md"


def reset_commands():
    text = RUNBOOK.read_text().replace("\\\n", "")
    commands = [
        line for line in text.splitlines() if line.startswith("sudo ") and "--cluster-reset" in line
    ]
    assert len(commands) == 2
    # Replace only the privilege boundary; env and shell expansion remain real.
    return [command.removeprefix("sudo ") for command in commands]


@pytest.mark.parametrize("command", reset_commands())
def test_reset_environment_and_arguments(command, tmp_path):
    recorder = tmp_path / "record k3s"
    recorder.write_text(
        f"#!{sys.executable}\n"
        "import json, os, sys\n"
        "print(json.dumps({'env': dict(os.environ), 'args': sys.argv[1:]}))\n"
    )
    recorder.chmod(0o700)
    env = dict(os.environ)
    env.update(
        K3S_BINARY=str(recorder),
        RESET_CONFIG="/reviewed reset/config.yaml",
        VERIFIED_SNAPSHOT="/reviewed snapshot/local snapshot",
        K3S_CONFIG_FILE="/wrong/config.yaml",
        K3S_DATA_DIR="/wrong/data",
        K3S_URL="https://wrong.invalid:6443",
        K3S_TOKEN_FILE="/wrong/token",
        K3S_DATASTORE_ENDPOINT="https://wrong.invalid",
        K3S_ETCD_S3="true",
        K3S_DEBUG="true",
        HTTPS_PROXY="https://wrong.invalid",
    )
    env["K3S_TOKEN"] = "synthetic-test-value"
    result = subprocess.run(["/bin/bash", "-c", command], env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    recorded = json.loads(result.stdout)
    assert not any(key.startswith("K3S_") for key in recorded["env"])
    # Python may add LC_CTYPE when coercing the C locale.
    assert set(recorded["env"]) <= {"PATH", "HOME", "LANG", "LC_CTYPE"}
    assert recorded["env"]["HOME"] == "/root"
    assert recorded["env"]["LANG"] == "C"
    args = ["server", "--config", env["RESET_CONFIG"], "--cluster-reset"]
    if "--cluster-reset-restore-path" in command:
        args += ["--cluster-reset-restore-path", env["VERIFIED_SNAPSHOT"], "--etcd-s3=false"]
    assert recorded["args"] == args


@pytest.mark.parametrize("command", reset_commands())
def test_reset_requires_reviewed_inputs(command):
    for required in re.findall(r"\$\{(\w+):\?", command):
        env = {
            "K3S_BINARY": "/usr/bin/true",
            "RESET_CONFIG": "/reviewed/config.yaml",
            "VERIFIED_SNAPSHOT": "/reviewed/snapshot",
        }
        del env[required]
        result = subprocess.run(
            ["/bin/bash", "-c", command], env=env, capture_output=True, text=True
        )
        assert result.returncode != 0
        assert required in result.stderr
