import os
import subprocess
from pathlib import Path

import pytest


SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "k3s-discover.sh"


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
            "SUGARKUBE_MDNS_DBUS": "0",
            "SUGARKUBE_SERVER_TOKEN_PATH": str(tmp_path / "server-token"),
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
    assert "token_source=env:dev" in result.stderr
    assert "token_format=legacy" in result.stderr


def test_resolver_prefers_secure_token_over_node_token(default_env, tmp_path):
    env = dict(default_env)
    env["SUGARKUBE_SERVERS"] = "3"
    env["SUGARKUBE_ALLOW_TOKEN_CREATE"] = "1"
    env["SUGARKUBE_SUDO_BIN"] = ""

    server_token_path = Path(env["SUGARKUBE_SERVER_TOKEN_PATH"])
    server_token_path.write_text("ready\n", encoding="utf-8")

    node_token_path = tmp_path / "node-token"
    node_token_path.write_text("NODETOKEN-WRONG\n", encoding="utf-8")
    env["SUGARKUBE_NODE_TOKEN_PATH"] = str(node_token_path)

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_k3s = fake_bin / "k3s"
    fake_k3s.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        "if [[ \"${1:-}\" == token && \"${2:-}\" == create ]]; then\n"
        "  echo 'K10secure::server:abc123'\n"
        "else\n"
        "  echo 'unexpected invocation' >&2\n"
        "  exit 1\n"
        "fi\n",
        encoding="utf-8",
    )
    fake_k3s.chmod(0o755)

    env["PATH"] = f"{fake_bin}:{env['PATH']}"

    result = run_discover(["--print-resolved-token"], env)

    assert result.returncode == 0
    assert result.stdout.strip() == "K10secure::server:abc123"
    assert "token-source=resolve_server_token.sh" in result.stderr
    assert "token_format=secure" in result.stderr
    assert "NODETOKEN-WRONG" not in result.stdout


def test_missing_token_allowed_for_multi_server_first_bootstrap(default_env):
    env = dict(default_env)
    env["SUGARKUBE_SERVERS"] = "3"

    result = run_discover(["--check-token-only"], env)

    assert result.returncode == 0
    assert result.stdout == ""


def test_missing_token_rejected_when_cluster_initialized(default_env):
    env = dict(default_env)
    env["SUGARKUBE_SERVERS"] = "3"
    Path(env["SUGARKUBE_SERVER_TOKEN_PATH"]).write_text("ready\n", encoding="utf-8")

    result = run_discover(["--check-token-only"], env)

    assert result.returncode == 1
    assert "SUGARKUBE_TOKEN" in result.stderr
    assert "SUGARKUBE_ALLOW_TOKEN_CREATE" in result.stderr
