"""Unit tests for the traefik-crd-doctor recipe."""

from __future__ import annotations

import os
import pathlib
import shutil
import subprocess
import textwrap
from typing import Optional

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
JUST_BIN = shutil.which("just")


def _render_doctor_script(tmp_path: pathlib.Path, apply: Optional[str] = None) -> pathlib.Path:
    args = [JUST_BIN, "--show", "traefik-crd-doctor"]
    if apply is not None:
        args.append(f"apply={apply}")

    show = subprocess.run(
        args,
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )

    script = tmp_path / "traefik-crd-doctor.sh"
    script.write_text(show.stdout, encoding="utf-8")
    script.chmod(0o755)
    return script


def _write_kubectl_stub(bin_dir: pathlib.Path) -> pathlib.Path:
    kubectl = bin_dir / "kubectl"
    kubectl.write_text(
        textwrap.dedent(
            """#!/usr/bin/env python3
import os
import sys
from pathlib import Path

args = sys.argv[1:]
state_path = os.environ.get("KUBECTL_STATE")
scenario = os.environ.get("CRD_SCENARIO", "")
log_path = os.environ.get("KUBECTL_LOG")

if log_path:
    with open(log_path, "a", encoding="utf-8") as handle:
        handle.write(" ".join(args) + "\n")

if args[:2] == ["delete", "crd"]:
    if state_path:
        Path(state_path).write_text("deleted", encoding="utf-8")
    sys.exit(0)

if args[:2] == ["get", "crd"]:
    if state_path and Path(state_path).exists():
        # Treat CRDs as removed after a delete.
        sys.exit(1)

    if scenario == "missing":
        sys.exit(1)

    if "-o" in args:
        jsonpath = args[-1]
        if "managed-by" in jsonpath:
            sys.stdout.write("Helm" if scenario == "helm" else "")
        elif "release-name" in jsonpath:
            sys.stdout.write("traefik-crd" if scenario == "helm" else "other-release")
        elif "release-namespace" in jsonpath:
            sys.stdout.write("kube-system" if scenario == "helm" else "default")
        sys.exit(0)

    sys.exit(0)

print(f"unexpected kubectl invocation: {args}", file=sys.stderr)
sys.exit(99)
"""
        ),
        encoding="utf-8",
    )
    kubectl.chmod(0o755)
    return kubectl


def _base_env(tmp_path: pathlib.Path, scenario: str, log_path: Optional[pathlib.Path] = None) -> dict[str, str]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    kubectl = _write_kubectl_stub(bin_dir)

    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}{os.pathsep}{env['PATH']}"
    env["CRD_SCENARIO"] = scenario
    env["KUBECTL_BIN"] = str(kubectl)
    env["KUBECONFIG"] = str(tmp_path / "kubeconfig")
    if log_path is not None:
        env["KUBECTL_LOG"] = str(log_path)
    state_path = tmp_path / "kubectl_state"
    env["KUBECTL_STATE"] = str(state_path)
    return env


@pytest.mark.skipif(JUST_BIN is None, reason="just is not installed in the test environment")
def test_traefik_crd_doctor_reports_missing_crds(tmp_path: pathlib.Path) -> None:
    script = _render_doctor_script(tmp_path)
    env = _base_env(tmp_path, scenario="missing")

    result = subprocess.run(
        [str(script)],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert "missing" in result.stdout
    assert "kubectl delete crd" not in result.stdout


@pytest.mark.skipif(JUST_BIN is None, reason="just is not installed in the test environment")
def test_traefik_crd_doctor_accepts_helm_owned_crds(tmp_path: pathlib.Path) -> None:
    script = _render_doctor_script(tmp_path)
    env = _base_env(tmp_path, scenario="helm")

    result = subprocess.run(
        [str(script)],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert "(OK)" in result.stdout
    assert "kubectl delete crd" not in result.stdout


@pytest.mark.skipif(JUST_BIN is None, reason="just is not installed in the test environment")
def test_traefik_crd_doctor_flags_problematic_crds(tmp_path: pathlib.Path) -> None:
    script = _render_doctor_script(tmp_path)
    env = _base_env(tmp_path, scenario="problem")

    result = subprocess.run(
        [str(script)],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0
    assert "exists but managed-by" in result.stdout
    assert "kubectl delete crd" in result.stdout
    assert "kubectl annotate crd" in result.stdout


@pytest.mark.skipif(JUST_BIN is None, reason="just is not installed in the test environment")
def test_traefik_crd_doctor_apply_deletes_after_confirmation(tmp_path: pathlib.Path) -> None:
    script = _render_doctor_script(tmp_path, apply="1")
    log_path = tmp_path / "kubectl.log"
    env = _base_env(tmp_path, scenario="problem", log_path=log_path)

    result = subprocess.run(
        [str(script)],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
        input="y\n",
    )

    assert result.returncode == 0
    assert "Planned kubectl delete command" in result.stdout
    assert "Re-ran diagnosis" in result.stdout
    assert "delete crd backendtlspolicies.gateway.networking.k8s.io" in log_path.read_text(encoding="utf-8")
