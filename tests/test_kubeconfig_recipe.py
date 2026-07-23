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


def _write_fake_kubectl(bin_dir: Path) -> None:
    script = bin_dir / "kubectl"
    script.write_text(
        textwrap.dedent(
            """#!/usr/bin/env bash
set -euo pipefail
if [[ "$*" == *"get nodes -o json"* ]]; then
  env_label="${SUGARKUBE_STUB_NODE_ENV:-dev}"
  printf '{"items":[{"metadata":{"name":"sugarkube1","labels":{"sugarkube.env":"%s","sugarkube.cluster":"sugar"}}}]}\n' "$env_label"
  exit 0
fi
if [[ "$*" == *"config current-context"* ]]; then printf 'PLACEHOLDER-CONTEXT\n'; exit 0; fi
if [[ "$*" == *"config view"* ]]; then printf 'https://127.0.0.1:6443'; exit 0; fi
exit 1
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
    _write_fake_kubectl(bin_dir)

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

@pytest.mark.skipif(shutil.which("just") is None, reason="just is required for this test")
def test_kubeconfig_env_mismatch_does_not_persist_false_context(tmp_path: Path) -> None:
    home = tmp_path / "home"
    (home / ".kube").mkdir(parents=True)
    existing = home / ".kube" / "config"
    existing.write_text("current-context: sugar-staging\n", encoding="utf-8")
    source_config = tmp_path / "k3s.yaml"
    source_config.write_text("apiVersion: v1\nclusters: []\ncontexts: []\nusers: []\n", encoding="utf-8")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _write_fake_sudo(bin_dir)
    _write_fake_kubectl(bin_dir)
    env = os.environ.copy()
    env.update({"HOME": str(home), "PATH": f"{bin_dir}{os.pathsep}{env['PATH']}", "TEST_K3S_SOURCE": str(source_config), "TEST_SKIP_CHOWN": "1", "SUGARKUBE_STUB_NODE_ENV": "staging"})
    result = subprocess.run(["just", "--justfile", str(JUSTFILE), "kubeconfig-env", "env=prod"], env=env, capture_output=True, text=True, check=False)
    assert result.returncode != 0
    assert "requested env=prod" in result.stderr
    assert existing.read_text(encoding="utf-8") == "current-context: sugar-staging\n"


def _write_cluster_identity_recorder(bin_dir: Path, log_path: Path) -> None:
    script = bin_dir / "python3"
    script.write_text(
        textwrap.dedent(
            f"""#!/usr/bin/env bash
set -euo pipefail
if [[ "${{1:-}}" == "scripts/cluster_identity.py" && "${{2:-}}" == "assert" ]]; then
  env_value=""
  kubeconfig_value=""
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --env)
        env_value="$2"
        shift 2
        ;;
      --kubeconfig)
        kubeconfig_value="$2"
        shift 2
        ;;
      *)
        shift
        ;;
    esac
  done
  printf '%s|%s\n' "$env_value" "$kubeconfig_value" >> {str(log_path)!r}
  case "$env_value" in
    dev|staging|prod) printf '%s\n' "$env_value"; exit 0 ;;
    *) printf 'unsupported env=%s\n' "$env_value" >&2; exit 2 ;;
  esac
fi
exec /usr/bin/python3 "$@"
"""
        ),
        encoding="utf-8",
    )
    script.chmod(0o755)


@pytest.mark.skipif(shutil.which("just") is None, reason="just is required for this test")
@pytest.mark.parametrize(
    ("requested", "normalized"),
    [
        ("prod", "prod"),
        ("env=prod", "prod"),
        ("staging", "staging"),
        ("env=staging", "staging"),
        ("int", "staging"),
        ("env=int", "staging"),
    ],
)
def test_assert_cluster_env_normalizes_invocation_forms(
    tmp_path: Path, requested: str, normalized: str
) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log_path = tmp_path / "cluster_identity_calls.log"
    kubeconfig = tmp_path / "kubeconfig"
    kubeconfig.write_text("apiVersion: v1\n", encoding="utf-8")
    _write_cluster_identity_recorder(bin_dir, log_path)
    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}{os.pathsep}{env['PATH']}"

    result = subprocess.run(
        [
            "just",
            "--justfile",
            str(JUSTFILE),
            "assert-cluster-env",
            requested,
            str(kubeconfig),
        ],
        cwd=JUSTFILE.parent,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert log_path.read_text(encoding="utf-8") == f"{normalized}|{kubeconfig}\n"
    if requested.endswith("int"):
        assert 'env name "int" is deprecated' in result.stderr


@pytest.mark.skipif(shutil.which("just") is None, reason="just is required for this test")
def test_assert_cluster_env_rejects_invalid_normalized_value(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log_path = tmp_path / "cluster_identity_calls.log"
    kubeconfig = tmp_path / "kubeconfig"
    kubeconfig.write_text("apiVersion: v1\n", encoding="utf-8")
    _write_cluster_identity_recorder(bin_dir, log_path)
    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}{os.pathsep}{env['PATH']}"

    result = subprocess.run(
        [
            "just",
            "--justfile",
            str(JUSTFILE),
            "assert-cluster-env",
            "env=production",
            str(kubeconfig),
        ],
        cwd=JUSTFILE.parent,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0
    assert "unsupported env=production" in result.stderr
    assert log_path.read_text(encoding="utf-8") == f"production|{kubeconfig}\n"
