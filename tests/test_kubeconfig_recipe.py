import os
import subprocess
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parent.parent
JUSTFILE = REPO_ROOT / "justfile"


K3S_SAMPLE_CONFIG = """apiVersion: v1
clusters:
- cluster:
    certificate-authority-data: FAKE
    server: https://127.0.0.1:6443
  name: default
contexts:
- context:
    cluster: default
    namespace: default
    user: default
  name: default
current-context: default
kind: Config
preferences: {}
users:
- name: default
  user:
    username: placeholder
"""


@pytest.mark.skipif(sys.platform.startswith("win"), reason="just recipes are tested on POSIX hosts")
def test_kubeconfig_recipe_rewrites_scope(tmp_path):
    home_dir = tmp_path / "home"
    home_dir.mkdir()

    fake_etc = tmp_path / "etc" / "rancher" / "k3s"
    fake_etc.mkdir(parents=True)
    source_config = fake_etc / "k3s.yaml"
    source_config.write_text(K3S_SAMPLE_CONFIG, encoding="utf-8")

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    sudo_script = fake_bin / "sudo"
    sudo_script.write_text(
        """#!/usr/bin/env bash
set -euo pipefail
if [[ "$1" == "cp" && "$2" == "/etc/rancher/k3s/k3s.yaml" ]]; then
  cp "${TEST_K3S_SOURCE:?}" "$3"
elif [[ "$1" == "chown" ]]; then
  exit 0
else
  "$@"
fi
""",
        encoding="utf-8",
    )
    sudo_script.chmod(0o755)

    env = os.environ.copy()
    env.update(
        {
            "HOME": str(home_dir),
            "PATH": f"{fake_bin}:{env.get('PATH', '')}",
            "TEST_K3S_SOURCE": str(source_config),
            "USER": env.get("USER", "tester"),
        }
    )

    result = subprocess.run(
        ["just", "--justfile", str(JUSTFILE), "kubeconfig"],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr

    kubeconfig_path = home_dir / ".kube" / "config"
    assert kubeconfig_path.exists()

    content = kubeconfig_path.read_text(encoding="utf-8")
    assert "current-context: sugar-dev" in content
    assert "name: sugar-dev" in content

