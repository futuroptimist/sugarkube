"""Regression tests for Danielsmith OCI wrapper argument normalization."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]


def _write_executable(path: Path, body: str) -> None:
    path.write_text(body, encoding="utf-8")
    path.chmod(0o755)


@pytest.fixture()
def danielsmith_oci_stub_env(tmp_path: Path, ensure_just_available: Path) -> dict[str, str]:
    """Return an environment with Kubernetes/Helm side effects stubbed out."""

    assert ensure_just_available.exists()

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log_path = tmp_path / "helm.log"

    _write_executable(
        bin_dir / "sudo",
        """#!/usr/bin/env bash
set -euo pipefail
if [ "${1:-}" = "cp" ]; then
  mkdir -p "$(dirname "${3}")"
  printf 'stub kubeconfig\n' > "${3}"
fi
exit 0
""",
    )
    _write_executable(
        bin_dir / "kubectl",
        """#!/usr/bin/env bash
set -euo pipefail
if [[ "$*" == *"config current-context"* ]]; then printf 'sugar-${SUGARKUBE_STUB_CONTEXT_ENV:-staging}\n'; exit 0; fi
if [[ "$*" == *"config view"* ]]; then printf 'https://127.0.0.1:6443\n'; exit 0; fi
if [[ "$*" == *"get"*"nodes"* && "$*" == *"-o"*"json"* ]]; then
  env_label="${SUGARKUBE_STUB_NODE_ENV:-${SUGARKUBE_ENV:-staging}}"
  printf '{"items":[{"metadata":{"name":"sugarkube3","labels":{"sugarkube.cluster":"sugar","sugarkube.env":"%s"}}}]}\n' "$env_label"
  exit 0
fi
exit 0
""",
    )
    _write_executable(
        bin_dir / "helm",
        f"""#!/usr/bin/env bash
set -euo pipefail
printf '%s\n' "$*" >> {str(log_path)!r}
if [ "${{1:-}}" = "-n" ] && [ "${{3:-}}" = "status" ]; then
  printf 'STATUS: deployed\n'
fi
exit 0
""",
    )

    env = os.environ.copy()
    env["HOME"] = str(tmp_path / "home")
    env["PATH"] = f"{bin_dir}{os.pathsep}{env.get('PATH', '')}"
    env["SUGARKUBE_HELM_ROLLOUT_TIMEOUT"] = "1s"
    env["HELM_LOG"] = str(log_path)
    return env


def _run_just(args: list[str], env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["just", *args],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.mark.usefixtures("ensure_just_available")
@pytest.mark.parametrize("tag_arg", ["tag=main-deadbee", "tag=tag=main-deadbee"])
def test_danielsmith_oci_deploy_normalizes_named_tag(
    tag_arg: str,
    danielsmith_oci_stub_env: dict[str, str],
) -> None:
    result = _run_just(
        ["danielsmith-oci-deploy", "env=staging", tag_arg],
        danielsmith_oci_stub_env,
    )

    assert result.returncode == 0, result.stderr + result.stdout
    helm_log = Path(danielsmith_oci_stub_env["HELM_LOG"]).read_text(encoding="utf-8")
    assert "--set image.tag=main-deadbee" in helm_log
    assert "--set image.tag=tag=main-deadbee" not in helm_log


@pytest.mark.usefixtures("ensure_just_available")
def test_danielsmith_oci_deploy_keeps_positional_tag_working(
    danielsmith_oci_stub_env: dict[str, str],
) -> None:
    result = _run_just(
        ["danielsmith-oci-deploy", "staging", "main-deadbee"],
        danielsmith_oci_stub_env,
    )

    assert result.returncode == 0, result.stderr + result.stdout
    helm_log = Path(danielsmith_oci_stub_env["HELM_LOG"]).read_text(encoding="utf-8")
    assert "--set image.tag=main-deadbee" in helm_log


@pytest.mark.usefixtures("ensure_just_available")
def test_danielsmith_oci_redeploy_normalizes_named_tag(
    danielsmith_oci_stub_env: dict[str, str],
) -> None:
    result = _run_just(
        ["danielsmith-oci-redeploy", "env=staging", "tag=main-deadbee"],
        danielsmith_oci_stub_env,
    )

    assert result.returncode == 0, result.stderr + result.stdout
    helm_log = Path(danielsmith_oci_stub_env["HELM_LOG"]).read_text(encoding="utf-8")
    assert "--set image.tag=main-deadbee" in helm_log
    assert "--set image.tag=tag=main-deadbee" not in helm_log


@pytest.mark.usefixtures("ensure_just_available")
def test_danielsmith_oci_promote_prod_normalizes_repeated_named_tag(
    danielsmith_oci_stub_env: dict[str, str],
) -> None:
    result = _run_just(
        ["danielsmith-oci-promote-prod", "tag=tag=main-deadbee"],
        danielsmith_oci_stub_env,
    )

    assert result.returncode == 0, result.stderr + result.stdout
    helm_log = Path(danielsmith_oci_stub_env["HELM_LOG"]).read_text(encoding="utf-8")
    assert "--set image.tag=main-deadbee" in helm_log
    assert "--set image.tag=tag=main-deadbee" not in helm_log


@pytest.mark.usefixtures("ensure_just_available")
@pytest.mark.parametrize("mutable_tag", ["tag=main-latest", "tag=latest", "tag=main"])
def test_danielsmith_oci_deploy_rejects_mutable_named_tags(
    mutable_tag: str,
    danielsmith_oci_stub_env: dict[str, str],
) -> None:
    result = _run_just(
        ["danielsmith-oci-deploy", "env=staging", mutable_tag],
        danielsmith_oci_stub_env,
    )

    assert result.returncode != 0
    assert "mutable tag" in result.stderr
    helm_log_path = Path(danielsmith_oci_stub_env["HELM_LOG"])
    assert not helm_log_path.exists() or helm_log_path.read_text(encoding="utf-8") == ""


@pytest.mark.usefixtures("ensure_just_available")
def test_danielsmith_compat_wrapper_cannot_bypass_cluster_guard(
    danielsmith_oci_stub_env: dict[str, str],
) -> None:
    env = danielsmith_oci_stub_env.copy()
    env["SUGARKUBE_STUB_NODE_ENV"] = "staging"
    result = _run_just(["danielsmith-oci-promote-prod", "tag=main-deadbee"], env)
    assert result.returncode != 0
    assert "requested env=prod" in result.stderr
    helm_log_path = Path(env["HELM_LOG"])
    assert not helm_log_path.exists() or "upgrade danielsmith" not in helm_log_path.read_text(encoding="utf-8")
