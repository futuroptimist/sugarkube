from __future__ import annotations

import os
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest


JUSTFILE = Path(__file__).resolve().parent.parent / "justfile"


def _write_fake_sudo(bin_dir: Path) -> None:
    script = bin_dir / "sudo"
    script.write_text(
        textwrap.dedent(
            """#!/usr/bin/env python3
import os
import subprocess
import sys


def main() -> None:
    args = sys.argv[1:]
    if not args:
        sys.exit(1)

    source = os.environ.get("TEST_K3S_SOURCE")
    if args[0] == "cp" and source and args[1] == "/etc/rancher/k3s/k3s.yaml":
        args = ["cp", source, *args[2:]]
    elif args[0] == "chown" and os.environ.get("TEST_SKIP_CHOWN") == "1":
        sys.exit(0)

    result = subprocess.run(args, env=os.environ)
    sys.exit(result.returncode)


if __name__ == "__main__":
    main()
"""
        ),
        encoding="utf-8",
    )
    script.chmod(0o755)


@pytest.mark.skipif(shutil.which("just") is None, reason="just is required for this test")
def test_kubeconfig_recipe_scopes_context(tmp_path: Path) -> None:
    home = tmp_path / "home"
    kube_dir = home / ".kube"
    kube_dir.mkdir(parents=True)

    source_config = tmp_path / "k3s.yaml"
    source_config.write_text(
        textwrap.dedent(
            """apiVersion: v1
clusters:
- cluster:
    server: https://127.0.0.1:6443
  name: PLACEHOLDER-CLUSTER
contexts:
- context:
    cluster: PLACEHOLDER-CLUSTER
    user: PLACEHOLDER-USER
  name: PLACEHOLDER-CONTEXT
current-context: PLACEHOLDER-CONTEXT
users:
- name: PLACEHOLDER-USER
  user:
    client-certificate-data: ZmFrZS1jZXJ0
    client-key-data: ZmFrZS1rZXk=
"""
        ),
        encoding="utf-8",
    )

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _write_fake_sudo(bin_dir)

    env = os.environ.copy()
    env.update(
        {
            "HOME": str(home),
            "PATH": f"{bin_dir}{os.pathsep}{env['PATH']}",
            "TEST_K3S_SOURCE": str(source_config),
            # GitHub's macOS runners use BSD sed (different flags) and mount the
            # workspace with special permissions, so chown/chmod behave oddly.
            # The shim skips chown to keep the recipe portable across CI.
            "TEST_SKIP_CHOWN": "1",
        }
    )

    result = subprocess.run(
        ["just", "--justfile", str(JUSTFILE), "kubeconfig", "env=dev"],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr

    config_path = kube_dir / "config"
    assert config_path.exists()

    contents = config_path.read_text(encoding="utf-8")
    assert "sugar-dev" in contents
    assert "current-context: sugar-dev" in contents
    assert "PLACEHOLDER" not in contents
