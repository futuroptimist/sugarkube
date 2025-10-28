import os
import subprocess
from pathlib import Path

import pytest

SCRIPT = str(Path(__file__).resolve().parents[2] / "scripts" / "k3s-discover.sh")


@pytest.fixture()
def fake_k3s(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()

    k3s_bin = bin_dir / "k3s"
    k3s_bin.write_text(
        "#!/usr/bin/env bash\n"
        "if [ \"$1\" = \"token\" ] && [ \"$2\" = \"create\" ]; then\n"
        "  echo 'K10-test-secure-token'\n"
        "  exit 0\n"
        "fi\n"
        "echo 'unexpected invocation' >&2\n"
        "exit 1\n",
        encoding="utf-8",
    )
    k3s_bin.chmod(0o755)

    return bin_dir


def test_server_join_prefers_secure_token(tmp_path, fake_k3s):
    server_token_path = tmp_path / "var" / "lib" / "rancher" / "k3s" / "server" / "token"
    server_token_path.parent.mkdir(parents=True)
    server_token_path.write_text("dummy", encoding="utf-8")

    node_token_path = tmp_path / "insecure-node-token"
    node_token_path.write_text("NODETOKEN123", encoding="utf-8")

    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{fake_k3s}:{env['PATH']}",
            "SUGARKUBE_CLUSTER": "sugar",
            "SUGARKUBE_ENV": "dev",
            "SUGARKUBE_SERVERS": "2",
            "SUGARKUBE_ALLOW_TOKEN_CREATE": "1",
            "SUGARKUBE_SUDO_BIN": "",
            "SUGARKUBE_K3S_SERVER_TOKEN_PATH": str(server_token_path),
            "SUGARKUBE_NODE_TOKEN_PATH": str(node_token_path),
        }
    )

    result = subprocess.run(
        ["bash", SCRIPT, "--print-resolved-token"],
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0
    assert result.stdout.strip() == "K10-test-secure-token"
    assert "NODETOKEN123" not in result.stdout
    assert "token-source" in result.stderr


def test_server_join_without_token_fails(tmp_path):
    server_token_path = tmp_path / "var" / "lib" / "rancher" / "k3s" / "server" / "token"
    server_token_path.parent.mkdir(parents=True)
    server_token_path.write_text("exists", encoding="utf-8")

    env = {
        "PATH": os.environ["PATH"],
        "SUGARKUBE_CLUSTER": "sugar",
        "SUGARKUBE_ENV": "dev",
        "SUGARKUBE_SERVERS": "2",
        "SUGARKUBE_ALLOW_TOKEN_CREATE": "0",
        "SUGARKUBE_K3S_SERVER_TOKEN_PATH": str(server_token_path),
    }

    result = subprocess.run(
        ["bash", SCRIPT, "--check-token-only"],
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 1
    assert "failed to resolve secure k3s server join token" in result.stderr
