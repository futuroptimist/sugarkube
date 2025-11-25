"""Tests for the traefik-crd-doctor just recipe."""

from __future__ import annotations

import os
import pathlib
import shutil
import subprocess
import tempfile

import pytest


REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
JUST_BIN = shutil.which("just")
FIXTURES = REPO_ROOT / "tests" / "fixtures"


def _prepare_env(
    tmp_path: pathlib.Path,
    state_fixture: pathlib.Path,
    *,
    log_calls: bool = False,
) -> dict[str, str]:
    env = os.environ.copy()

    kubectl_dir = tmp_path / "bin"
    kubectl_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy(FIXTURES / "kubectl_gateway_crd_stub.sh", kubectl_dir / "kubectl")

    state_copy = tmp_path / "state.txt"
    shutil.copy(state_fixture, state_copy)

    home = tmp_path / "home"
    kube_dir = home / ".kube"
    kube_dir.mkdir(parents=True, exist_ok=True)
    (kube_dir / "config").touch()

    env.update(
        PATH=f"{kubectl_dir}:{env['PATH']}",
        CRD_STATE_FILE=str(state_copy),
        HOME=str(home),
    )

    if log_calls:
        log_path = tmp_path / "kubectl_calls.log"
        if log_path.exists():
            log_path.unlink()
        env["KUBECTL_CALL_LOG"] = str(log_path)

    return env


def _run_doctor(
    state_fixture: pathlib.Path,
    *,
    apply: bool = False,
    input_text: str | None = None,
    log_calls: bool = False,
) -> tuple[subprocess.CompletedProcess[str], pathlib.Path]:
    tmp_path = pathlib.Path(tempfile.mkdtemp(prefix="traefik_crd_doctor_"))
    env = _prepare_env(tmp_path, state_fixture, log_calls=log_calls)

    args: list[str] = [JUST_BIN, "traefik-crd-doctor"]
    if apply:
        args.append("apply=1")

    return (
        subprocess.run(
            args,
            cwd=REPO_ROOT,
            env=env,
            input=input_text,
            text=True,
            capture_output=True,
        ),
        tmp_path,
    )


@pytest.mark.skipif(JUST_BIN is None, reason="just is not installed in the test environment")
def test_doctor_reports_missing_crds_exit_success() -> None:
    result, _ = _run_doctor(FIXTURES / "gateway_crd_state_none.txt")

    assert result.returncode == 0
    assert "No problematic Gateway API CRDs detected." in result.stdout
    assert "Suggested commands" not in result.stdout


@pytest.mark.skipif(JUST_BIN is None, reason="just is not installed in the test environment")
def test_doctor_reports_helm_owned_crds_exit_success() -> None:
    result, _ = _run_doctor(FIXTURES / "gateway_crd_state_all_helm.txt")

    assert result.returncode == 0
    assert "✅ CRD gatewayclasses.gateway.networking.k8s.io" in result.stdout
    assert "Suggested commands" not in result.stdout


@pytest.mark.skipif(JUST_BIN is None, reason="just is not installed in the test environment")
def test_doctor_flags_problematic_crds() -> None:
    result, _ = _run_doctor(FIXTURES / "gateway_crd_state_problematic.txt")

    assert result.returncode != 0
    assert "Suggested commands" in result.stdout
    assert "kubectl delete crd backendtlspolicies.gateway.networking.k8s.io" in result.stdout


@pytest.mark.skipif(JUST_BIN is None, reason="just is not installed in the test environment")
def test_doctor_apply_executes_delete_after_confirmation() -> None:
    state_fixture = FIXTURES / "gateway_crd_state_problematic.txt"
    result, tmp_path = _run_doctor(state_fixture, apply=True, input_text="y\n", log_calls=True)

    assert result.returncode == 0
    assert "Executing: kubectl delete crd" in result.stdout
    assert "Re-running CRD report after apply" in result.stdout

    call_log = tmp_path / "kubectl_calls.log"
    assert call_log.read_text().strip() == (
        "delete crd "
        "backendtlspolicies.gateway.networking.k8s.io "
        "gatewayclasses.gateway.networking.k8s.io "
        "gateways.gateway.networking.k8s.io "
        "grpcroutes.gateway.networking.k8s.io "
        "httproutes.gateway.networking.k8s.io "
        "referencegrants.gateway.networking.k8s.io"
    )


@pytest.mark.skipif(JUST_BIN is None, reason="just is not installed in the test environment")
def test_doctor_apply_aborts_without_confirmation() -> None:
    state_fixture = FIXTURES / "gateway_crd_state_problematic.txt"
    result, tmp_path = _run_doctor(state_fixture, apply=True, input_text="\n", log_calls=True)

    assert result.returncode != 0
    assert "Aborting apply; no changes were made." in result.stdout

    call_log = tmp_path / "kubectl_calls.log"
    assert not call_log.exists() or call_log.read_text().strip() == ""
