from __future__ import annotations

import json
import os
import subprocess
import textwrap
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
DOCTOR_SCRIPT = REPO_ROOT / "scripts" / "traefik_crd_doctor.sh"
GATEWAY_CRDS = [
    "backendtlspolicies.gateway.networking.k8s.io",
    "gatewayclasses.gateway.networking.k8s.io",
    "gateways.gateway.networking.k8s.io",
    "grpcroutes.gateway.networking.k8s.io",
    "httproutes.gateway.networking.k8s.io",
    "referencegrants.gateway.networking.k8s.io",
]


@pytest.fixture()
def kubectl_stub(tmp_path: Path) -> dict[str, Path]:
    fixtures_dir = tmp_path / "fixtures"
    fixtures_dir.mkdir()
    log_file = tmp_path / "kubectl.log"

    stub = tmp_path / "kubectl"
    stub.write_text(
        textwrap.dedent(
            """
            #!/usr/bin/env bash
            set -euo pipefail

            fixtures_dir="${KUBECTL_FIXTURES:-}";
            log_file="${KUBECTL_STUB_LOG:-}"

            cmd="$1"
            shift

            case "${cmd}" in
              get)
                target="$1"
                shift || true
                if [[ "${target}" == crd/* ]]; then
                  crd_name="${target#crd/}"
                  fixture_path="${fixtures_dir}/${crd_name}.json"
                  if [ -f "${fixture_path}" ]; then
                    cat "${fixture_path}"
                    exit 0
                  fi
                  echo "${crd_name} not found" >&2
                  exit 1
                fi
                ;;
              delete)
                if [ "${1:-}" = "crd" ]; then
                  shift
                  for crd in "$@"; do
                    [ -n "${log_file}" ] && echo "delete crd ${crd}" >> "${log_file}"
                    rm -f "${fixtures_dir}/${crd}.json" || true
                  done
                  exit 0
                fi
                ;;
            esac

            echo "kubectl stub: unsupported invocation ${cmd} $*" >&2
            exit 1
            """
        )
    )
    stub.chmod(0o755)

    env = os.environ.copy()
    env["PATH"] = f"{tmp_path}:{env.get('PATH', '')}"
    env["KUBECTL_FIXTURES"] = str(fixtures_dir)
    env["KUBECTL_STUB_LOG"] = str(log_file)

    return {"env": env, "fixtures_dir": fixtures_dir, "log_file": log_file}


def _write_crd_fixture(fixtures_dir: Path, name: str, managed: str | None, rel: str | None, rel_ns: str | None) -> None:
    metadata: dict[str, object] = {"name": name}
    labels: dict[str, str] = {}
    annotations: dict[str, str] = {}
    if managed is not None:
        labels["app.kubernetes.io/managed-by"] = managed
    if rel is not None:
        annotations["meta.helm.sh/release-name"] = rel
    if rel_ns is not None:
        annotations["meta.helm.sh/release-namespace"] = rel_ns
    if labels:
        metadata["labels"] = labels
    if annotations:
        metadata["annotations"] = annotations

    payload = {"metadata": metadata}
    (fixtures_dir / f"{name}.json").write_text(json.dumps(payload))


def _run_doctor(env: dict[str, str], *args: str, input_text: str | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(DOCTOR_SCRIPT), *args],
        cwd=REPO_ROOT,
        env=env,
        text=True,
        capture_output=True,
        input=input_text,
    )


def test_doctor_reports_missing_crds(kubectl_stub: dict[str, Path]) -> None:
    env = dict(kubectl_stub["env"])
    result = _run_doctor(env)

    assert result.returncode == 0
    assert "No problematic Gateway API CRDs detected." in result.stdout
    assert "missing" in result.stdout
    assert "kubectl delete crd" not in result.stdout


def test_doctor_reports_healthy_crds(kubectl_stub: dict[str, Path]) -> None:
    env = dict(kubectl_stub["env"])
    fixtures_dir: Path = kubectl_stub["fixtures_dir"]

    for name in GATEWAY_CRDS:
        _write_crd_fixture(
            fixtures_dir,
            name,
            managed="Helm",
            rel="traefik-crd",
            rel_ns="kube-system",
        )

    result = _run_doctor(env)

    assert result.returncode == 0
    assert "No problematic Gateway API CRDs detected." in result.stdout
    assert "Existing CRDs are already owned by Traefik Helm releases." in result.stdout


def test_doctor_reports_problematic_crds(kubectl_stub: dict[str, Path]) -> None:
    env = dict(kubectl_stub["env"])
    fixtures_dir: Path = kubectl_stub["fixtures_dir"]

    for name in GATEWAY_CRDS:
        _write_crd_fixture(fixtures_dir, name, managed=None, rel="other", rel_ns="default")

    result = _run_doctor(env)

    assert result.returncode != 0
    assert "Detected problematic CRDs" in result.stdout
    assert "kubectl delete crd" in result.stdout
    assert "kubectl annotate crd" in result.stdout


def test_apply_mode_runs_delete_after_confirmation(kubectl_stub: dict[str, Path]) -> None:
    env = dict(kubectl_stub["env"])
    fixtures_dir: Path = kubectl_stub["fixtures_dir"]
    log_file: Path = kubectl_stub["log_file"]

    for name in GATEWAY_CRDS:
        _write_crd_fixture(fixtures_dir, name, managed=None, rel=None, rel_ns=None)

    result = _run_doctor(env, "--apply", input_text="y\n")

    assert result.returncode == 0
    assert "Executing kubectl delete" in result.stdout
    assert "CRD state is now clean." in result.stdout
    assert log_file.read_text() != ""
    assert not any((fixtures_dir / f"{name}.json").exists() for name in GATEWAY_CRDS)


def test_apply_mode_aborts_without_confirmation(kubectl_stub: dict[str, Path]) -> None:
    env = dict(kubectl_stub["env"])
    fixtures_dir: Path = kubectl_stub["fixtures_dir"]
    log_file: Path = kubectl_stub["log_file"]

    for name in GATEWAY_CRDS:
        _write_crd_fixture(fixtures_dir, name, managed=None, rel=None, rel_ns=None)

    result = _run_doctor(env, "--apply", input_text="\n")

    assert result.returncode != 0
    assert "Aborting without making changes." in result.stdout
    if log_file.exists():
        assert log_file.read_text() == ""
    else:
        assert not log_file.exists()
    assert all((fixtures_dir / f"{name}.json").exists() for name in GATEWAY_CRDS)
