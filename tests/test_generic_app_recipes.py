"""Stubbed tests for generic app deployment recipes and compatibility wrappers."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]


def _write_executable(path: Path, body: str) -> None:
    path.write_text(body, encoding="utf-8")
    path.chmod(0o755)


@pytest.fixture()
def generic_app_stub_env(tmp_path: Path, ensure_just_available: Path) -> dict[str, str]:
    assert ensure_just_available.exists()
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    helm_log = tmp_path / "helm.log"
    kubectl_log = tmp_path / "kubectl.log"

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
        bin_dir / "python3",
        f"""#!/usr/bin/env bash
set -euo pipefail
case "${{1:-}}" in
  */scripts/app_config.py|scripts/app_config.py)
    exec {sys.executable!r} "$@"
    ;;
  *update_kubeconfig_scope.py)
    exit 0
    ;;
esac
exec {sys.executable!r} "$@"
""",
    )
    _write_executable(
        bin_dir / "kubectl",
        f"""#!/usr/bin/env bash
set -euo pipefail
printf '%s\n' "$*" >> {str(kubectl_log)!r}
if [ "${{3:-}}" = "get" ] && [ "${{4:-}}" = "deploy,statefulset,daemonset" ]; then
  exit 0
fi
if [ "${{3:-}}" = "get" ] && [ "${{4:-}}" = "deploy" ]; then
  exit 1
fi
exit 0
""",
    )
    _write_executable(
        bin_dir / "helm",
        f"""#!/usr/bin/env bash
set -euo pipefail
printf '%s\n' "$*" >> {str(helm_log)!r}
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
    env["HELM_LOG"] = str(helm_log)
    env["KUBECTL_LOG"] = str(kubectl_log)
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
def test_generic_danielsmith_deploy_passes_image_tag(generic_app_stub_env: dict[str, str]) -> None:
    result = _run_just(
        ["app-deploy", "app=danielsmith", "env=staging", "tag=main-deadbee"],
        generic_app_stub_env,
    )

    assert result.returncode == 0, result.stderr + result.stdout
    helm_log = Path(generic_app_stub_env["HELM_LOG"]).read_text(encoding="utf-8")
    assert "--set image.tag=main-deadbee" in helm_log


@pytest.mark.usefixtures("ensure_just_available")
@pytest.mark.parametrize(
    ("app", "chart", "namespace", "values"),
    [
        (
            "tokenplace",
            "oci://ghcr.io/futuroptimist/charts/tokenplace",
            "tokenplace",
            "-f docs/examples/tokenplace.values.dev.yaml -f docs/examples/tokenplace.values.staging.yaml",
        ),
        (
            "dspace",
            "oci://ghcr.io/democratizedspace/charts/dspace",
            "dspace",
            "-f docs/examples/dspace.values.dev.yaml -f docs/examples/dspace.values.staging.yaml",
        ),
    ],
)
def test_generic_deploy_uses_app_config_coordinates(
    app: str,
    chart: str,
    namespace: str,
    values: str,
    generic_app_stub_env: dict[str, str],
) -> None:
    result = _run_just(
        ["app-deploy", f"app={app}", "env=staging", "tag=main-deadbee"],
        generic_app_stub_env,
    )

    assert result.returncode == 0, result.stderr + result.stdout
    helm_log = Path(generic_app_stub_env["HELM_LOG"]).read_text(encoding="utf-8")
    assert f"upgrade {namespace} {chart} --namespace {namespace}" in helm_log
    assert values in helm_log
    assert "--set image.tag=main-deadbee" in helm_log


@pytest.mark.usefixtures("ensure_just_available")
def test_mutable_tag_rejected_before_helm(generic_app_stub_env: dict[str, str]) -> None:
    result = _run_just(
        ["app-deploy", "app=tokenplace", "env=staging", "tag=latest"],
        generic_app_stub_env,
    )

    assert result.returncode != 0
    assert "mutable tag" in result.stderr
    helm_log_path = Path(generic_app_stub_env["HELM_LOG"])
    assert not helm_log_path.exists() or helm_log_path.read_text(encoding="utf-8") == ""


@pytest.mark.usefixtures("ensure_just_available")
@pytest.mark.parametrize(
    ("recipe", "app"),
    [
        ("danielsmith-oci-deploy", "danielsmith"),
        ("tokenplace-oci-deploy", "tokenplace"),
        ("dspace-oci-deploy", "dspace"),
    ],
)
def test_compatibility_deploy_wrappers_call_generic_flow(
    recipe: str,
    app: str,
    generic_app_stub_env: dict[str, str],
) -> None:
    result = _run_just([recipe, "env=staging", "tag=tag=main-deadbee"], generic_app_stub_env)

    assert result.returncode == 0, result.stderr + result.stdout
    helm_log = Path(generic_app_stub_env["HELM_LOG"]).read_text(encoding="utf-8")
    assert f"upgrade {app if app != 'danielsmith' else 'danielsmith'}" in helm_log
    assert "--set image.tag=main-deadbee" in helm_log
    assert "--set image.tag=tag=main-deadbee" not in helm_log
