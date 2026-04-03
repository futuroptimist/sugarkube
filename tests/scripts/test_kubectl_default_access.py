"""Regression tests for rootless kubectl defaults on Pi nodes."""

from __future__ import annotations

from pathlib import Path

K3S_DISCOVER = Path(__file__).resolve().parents[2] / "scripts" / "k3s-discover.sh"
KUBECONFIG_LIB = Path(__file__).resolve().parents[2] / "scripts" / "lib" / "kubeconfig.sh"
JUSTFILE = Path(__file__).resolve().parents[2] / "justfile"


def test_k3s_install_sets_world_readable_kubeconfig_mode() -> None:
    script = K3S_DISCOVER.read_text(encoding="utf-8")

    assert '"K3S_KUBECONFIG_MODE=${SUGARKUBE_K3S_KUBECONFIG_MODE:-644}"' in script


def test_ensure_user_kubeconfig_persists_env_in_profile_and_bashrc() -> None:
    script = KUBECONFIG_LIB.read_text(encoding="utf-8")

    assert 'for shell_init_path in "${target_home%/}/.bashrc" "${target_home%/}/.profile"' in script
    assert "export KUBECONFIG=$HOME/.kube/config" in script


def test_status_recipe_uses_user_kubectl_without_sudo() -> None:
    justfile = JUSTFILE.read_text(encoding="utf-8")

    assert "scripts/ensure_user_kubeconfig.sh || true" in justfile
    assert "kubectl get nodes -o wide" in justfile
