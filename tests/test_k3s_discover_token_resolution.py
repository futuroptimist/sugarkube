import os
import subprocess
from pathlib import Path

import pytest


SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "k3s-discover.sh"


@pytest.fixture()
def default_env(tmp_path):
    env = os.environ.copy()
    for key in list(env):
        if key.startswith("SUGARKUBE_TOKEN"):
            env.pop(key, None)
    env.update(
        {
            "SUGARKUBE_ENV": "dev",
            "SUGARKUBE_SERVERS": "1",
            "SUGARKUBE_NODE_TOKEN_PATH": str(tmp_path / "node-token"),
            "SUGARKUBE_BOOT_TOKEN_PATH": str(tmp_path / "boot-token"),
        }
    )
    return env


def run_discover(args, env):
    result = subprocess.run(
        ["bash", str(SCRIPT), *args],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    return result


def test_prefers_env_specific_token(default_env):
    env = dict(default_env)
    env["SUGARKUBE_TOKEN_DEV"] = "dev-specific-token"

    result = run_discover(["--print-resolved-token"], env)

    assert result.returncode == 0
    assert result.stdout.strip() == "dev-specific-token"


def test_reads_node_token_file(default_env, tmp_path):
    node_token_path = tmp_path / "node-token"
    node_token_path.write_text("K10node::server:abc123\n", encoding="utf-8")

    env = dict(default_env)
    env["SUGARKUBE_NODE_TOKEN_PATH"] = str(node_token_path)

    result = run_discover(["--print-resolved-token"], env)

    assert result.returncode == 0
    assert result.stdout.strip() == "K10node::server:abc123"


def test_reads_boot_token_file(default_env, tmp_path):
    boot_token_path = tmp_path / "boot-token"
    boot_token_path.write_text(
        "# header\nNODE_TOKEN=K10boot::server:def456\n", encoding="utf-8"
    )

    env = dict(default_env)
    env["SUGARKUBE_NODE_TOKEN_PATH"] = str(tmp_path / "missing-node-token")
    env["SUGARKUBE_BOOT_TOKEN_PATH"] = str(boot_token_path)

    result = run_discover(["--print-resolved-token"], env)

    assert result.returncode == 0
    assert result.stdout.strip() == "K10boot::server:def456"


def test_missing_token_allowed_for_single_server(default_env):
    result = run_discover(["--check-token-only"], default_env)

    assert result.returncode == 0
    assert result.stdout == ""


def test_missing_token_rejected_for_multi_server(default_env):
    env = dict(default_env)
    env["SUGARKUBE_SERVERS"] = "3"

    result = run_discover(["--check-token-only"], env)

    assert result.returncode == 1
    assert "SUGARKUBE_TOKEN" in result.stderr
