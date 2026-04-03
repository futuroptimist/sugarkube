from __future__ import annotations

import os
import subprocess
import textwrap
from pathlib import Path


def _write_fake_id(bin_dir: Path) -> None:
    script = bin_dir / "id"
    script.write_text(
        textwrap.dedent(
            """#!/usr/bin/env python3
import sys

USERS = {"tester": ("1000", "1000"), "pi": ("1001", "1001")}

args = sys.argv[1:]
if args == ["-un"]:
    print("tester")
    sys.exit(0)
if len(args) == 2 and args[0] == "-u" and args[1] in USERS:
    print(USERS[args[1]][0])
    sys.exit(0)
if len(args) == 2 and args[0] == "-g" and args[1] in USERS:
    print(USERS[args[1]][1])
    sys.exit(0)
sys.exit(1)
"""
        ),
        encoding="utf-8",
    )
    script.chmod(0o755)


def _write_fake_getent(bin_dir: Path, tester_home: Path, pi_home: Path) -> None:
    script = bin_dir / "getent"
    script.write_text(
        textwrap.dedent(
            f"""#!/usr/bin/env python3
import sys

if len(sys.argv) == 3 and sys.argv[1] == "passwd":
    if sys.argv[2] == "tester":
        print("tester:x:1000:1000::" + {str(tester_home)!r} + ":/bin/bash")
        sys.exit(0)
    if sys.argv[2] == "pi":
        print("pi:x:1001:1001::" + {str(pi_home)!r} + ":/bin/bash")
        sys.exit(0)
sys.exit(2)
"""
        ),
        encoding="utf-8",
    )
    script.chmod(0o755)


def _write_fake_sudo(bin_dir: Path) -> None:
    script = bin_dir / "sudo"
    script.write_text(
        textwrap.dedent(
            """#!/usr/bin/env python3
import os
import subprocess
import sys

args = sys.argv[1:]
if not args:
    sys.exit(1)

if args[0] == "chown":
    sys.exit(0)

source = os.environ.get("TEST_K3S_SOURCE")
if source:
    remapped = []
    for item in args:
        if item == "/etc/rancher/k3s/k3s.yaml":
            remapped.append(source)
        else:
            remapped.append(item)
    args = remapped

result = subprocess.run(args, env=os.environ)
sys.exit(result.returncode)
"""
        ),
        encoding="utf-8",
    )
    script.chmod(0o755)


def test_kubeconfig_syncs_additional_pi_user(tmp_path: Path) -> None:
    tester_home = tmp_path / "tester-home"
    pi_home = tmp_path / "pi-home"
    tester_home.mkdir()
    pi_home.mkdir()

    source_config = tmp_path / "k3s.yaml"
    source_config.write_text(
        textwrap.dedent(
            """apiVersion: v1
clusters:
- name: sugar
  cluster:
    server: https://127.0.0.1:6443
"""
        ),
        encoding="utf-8",
    )

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _write_fake_id(bin_dir)
    _write_fake_getent(bin_dir, tester_home, pi_home)
    _write_fake_sudo(bin_dir)

    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{bin_dir}{os.pathsep}{env['PATH']}",
            "HOME": str(tester_home),
            "TEST_K3S_SOURCE": str(source_config),
            "SUGARKUBE_KUBECONFIG_USER": "tester",
            "SUGARKUBE_KUBECONFIG_HOME": str(tester_home),
            "SUGARKUBE_KUBECONFIG_ADDITIONAL_USERS": "pi",
        }
    )

    result = subprocess.run(
        [
            "bash",
            "-lc",
            "source scripts/lib/kubeconfig.sh && kubeconfig::ensure_user_kubeconfig",
        ],
        cwd=Path(__file__).resolve().parent.parent,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr

    tester_cfg = tester_home / ".kube" / "config"
    pi_cfg = pi_home / ".kube" / "config"
    assert tester_cfg.exists()
    assert pi_cfg.exists()
    assert tester_cfg.read_text(encoding="utf-8") == source_config.read_text(encoding="utf-8")
    assert pi_cfg.read_text(encoding="utf-8") == source_config.read_text(encoding="utf-8")

    assert "export KUBECONFIG=$HOME/.kube/config" in (tester_home / ".bashrc").read_text(
        encoding="utf-8"
    )
    assert "export KUBECONFIG=$HOME/.kube/config" in (pi_home / ".bashrc").read_text(
        encoding="utf-8"
    )
