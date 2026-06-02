"""Stubbed just tests for generic app deploy recipes."""

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
def app_just_stub_env(tmp_path: Path, ensure_just_available: Path) -> dict[str, str]:
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
if [ "${{1:-}}" = "get" ] && [ "${{2:-}}" = "values" ]; then
  printf '{{"ingress":{{"host":"staging.example.test"}}}}\n'
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
@pytest.mark.parametrize(
    ("app", "release", "namespace", "chart", "values"),
    [
        (
            "danielsmith",
            "danielsmith",
            "danielsmith",
            "oci://ghcr.io/futuroptimist/charts/danielsmith",
            "docs/examples/danielsmith.values.dev.yaml,"
            "docs/examples/danielsmith.values.staging.yaml",
        ),
        (
            "tokenplace",
            "tokenplace",
            "tokenplace",
            "oci://ghcr.io/futuroptimist/charts/tokenplace",
            "docs/examples/tokenplace.values.dev.yaml,docs/examples/tokenplace.values.staging.yaml",
        ),
        (
            "dspace",
            "dspace",
            "dspace",
            "oci://ghcr.io/democratizedspace/charts/dspace",
            "docs/examples/dspace.values.dev.yaml,docs/examples/dspace.values.staging.yaml",
        ),
    ],
)
def test_app_deploy_uses_configured_helm_coordinates(
    app: str,
    release: str,
    namespace: str,
    chart: str,
    values: str,
    app_just_stub_env: dict[str, str],
) -> None:
    result = _run_just(
        ["app-deploy", f"app={app}", "env=staging", "tag=main-deadbee"],
        app_just_stub_env,
    )

    assert result.returncode == 0, result.stderr + result.stdout
    helm_log = Path(app_just_stub_env["HELM_LOG"]).read_text(encoding="utf-8")
    assert f"upgrade {release} {chart}" in helm_log
    assert f"--namespace {namespace}" in helm_log
    for values_file in values.split(","):
        assert f"-f {values_file}" in helm_log
    assert "--set image.tag=main-deadbee" in helm_log


@pytest.mark.usefixtures("ensure_just_available")
def test_app_deploy_rejects_mutable_tag_before_helm(app_just_stub_env: dict[str, str]) -> None:
    result = _run_just(
        ["app-deploy", "app=tokenplace", "env=staging", "tag=latest"],
        app_just_stub_env,
    )

    assert result.returncode != 0
    assert "mutable tag" in result.stderr
    helm_log_path = Path(app_just_stub_env["HELM_LOG"])
    assert not helm_log_path.exists() or helm_log_path.read_text(encoding="utf-8") == ""


@pytest.mark.usefixtures("ensure_just_available")
@pytest.mark.parametrize(
    ("recipe", "app"),
    [
        ("dspace-oci-deploy", "dspace"),
        ("tokenplace-oci-deploy", "tokenplace"),
        ("danielsmith-oci-deploy", "danielsmith"),
    ],
)
def test_app_specific_deploy_wrappers_delegate_to_generic_recipe(
    recipe: str,
    app: str,
    app_just_stub_env: dict[str, str],
) -> None:
    result = _run_just([recipe, "env=staging", "tag=tag=main-deadbee"], app_just_stub_env)

    assert result.returncode == 0, result.stderr + result.stdout
    helm_log = Path(app_just_stub_env["HELM_LOG"]).read_text(encoding="utf-8")
    assert f"upgrade {app}" in helm_log
    assert "--set image.tag=main-deadbee" in helm_log
    assert "--set image.tag=tag=main-deadbee" not in helm_log
