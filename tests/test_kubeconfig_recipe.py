import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.mark.skipif(shutil.which("just") is None, reason="just command is required")
@pytest.mark.skipif(sys.platform.startswith("win"), reason="just recipes require POSIX paths")
def test_kubeconfig_recipe(tmp_path):
    home = tmp_path / "home"
    home.mkdir()

    source_config = tmp_path / "k3s.yaml"
    source_config.write_text(
        """apiVersion: v1
clusters:
- cluster:
    certificate-authority-data: ZHVtbXk=
    server: https://127.0.0.1:6443
  name: default
contexts:
- context:
    cluster: default
    user: default
  name: default
current-context: default
kind: Config
preferences: {}
users:
- name: default
  user:
    token: DUMMY
""",
        encoding="utf-8",
    )

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    sudo_stub = bin_dir / "sudo"
    sudo_stub.write_text(
        """#!/bin/sh
set -eu
if [ "$#" -eq 0 ]; then
  exit 0
fi
cmd="$1"
shift
if [ "$cmd" = "cp" ]; then
  src="$1"
  shift
  dest="$1"
  shift || true
  if [ "$src" = "/etc/rancher/k3s/k3s.yaml" ]; then
    /bin/cp "$SUGARKUBE_TEST_K3S_YAML" "$dest"
    exit $?
  fi
  exec /bin/cp "$src" "$dest" "$@"
fi
if [ "$cmd" = "chown" ]; then
  exit 0
fi
exec "$cmd" "$@"
""",
        encoding="utf-8",
    )
    sudo_stub.chmod(0o755)

    env = os.environ.copy()
    env.update(
        {
            "HOME": str(home),
            "USER": "sugarkube",
            "PATH": f"{bin_dir}:{env.get('PATH', '')}",
            "SUGARKUBE_TEST_K3S_YAML": str(source_config),
        }
    )

    result = subprocess.run(
        ["just", "--justfile", str(REPO_ROOT / "justfile"), "kubeconfig", "dev"],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr

    kubeconfig_path = home / ".kube" / "config"
    assert kubeconfig_path.exists(), kubeconfig_path

    if hasattr(os, "getuid"):
        assert kubeconfig_path.stat().st_uid == os.getuid()

    kubeconfig_contents = kubeconfig_path.read_text(encoding="utf-8")
    assert "current-context: sugar-dev" in kubeconfig_contents
    assert "name: sugar-dev" in kubeconfig_contents
