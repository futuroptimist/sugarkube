"""Tests for the traefik-crd-doctor just recipe."""

from __future__ import annotations

import json
import os
import pathlib
import shutil
import subprocess
from typing import Dict, Tuple

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
JUST_BIN = shutil.which("just")

GATEWAY_CRDS = [
    "backendtlspolicies.gateway.networking.k8s.io",
    "gatewayclasses.gateway.networking.k8s.io",
    "gateways.gateway.networking.k8s.io",
    "grpcroutes.gateway.networking.k8s.io",
    "httproutes.gateway.networking.k8s.io",
    "referencegrants.gateway.networking.k8s.io",
]

KUBECTL_STUB = """#!/usr/bin/env python3
import json
import os
import sys
import pathlib

state_path = pathlib.Path(os.environ["KUBECTL_STATE"])
log_path = pathlib.Path(os.environ["KUBECTL_LOG"])


def load_state():
    if state_path.exists():
        return json.loads(state_path.read_text())
    return {"crds": {}}


def save_state(data):
    state_path.write_text(json.dumps(data))


def log(args):
    existing = log_path.read_text() if log_path.exists() else ""
    log_path.write_text(existing + " ".join(args) + "\n")


state = load_state()
args = sys.argv[1:]
if not args:
    sys.exit(1)

cmd = args[0]


def metadata(name: str):
    return state.get("crds", {}).get(name, {})


if cmd == "get" and len(args) >= 2 and args[1] == "crd":
    if len(args) >= 3 and args[2].startswith("crd/"):
        name = args[2].split("/", 1)[1]
        jsonpath = ""
        if "-o" in args:
            idx = args.index("-o")
            if idx + 1 < len(args):
                jsonpath = args[idx + 1]
        meta = metadata(name)
        value = ""
        if "managed-by" in jsonpath:
            value = meta.get("labels", {}).get("app.kubernetes.io/managed-by", "")
        elif "release-name" in jsonpath:
            value = meta.get("annotations", {}).get("meta.helm.sh/release-name", "")
        elif "release-namespace" in jsonpath:
            value = meta.get("annotations", {}).get("meta.helm.sh/release-namespace", "")
        sys.stdout.write(value)
        sys.exit(0 if name in state.get("crds", {}) else 1)
    else:
        names = []
        for arg in args[2:]:
            if arg.startswith("-"):
                break
            names.append(arg)
        existing = [name for name in names if name in state.get("crds", {})]
        if existing:
            sys.stdout.write("\n".join(existing) + "\n")
        sys.exit(0)
elif cmd == "delete" and len(args) >= 2 and args[1] == "crd":
    names = [a for a in args[2:] if not a.startswith("-")]
    log(sys.argv[1:])
    crds = state.get("crds", {})
    for name in names:
        crds.pop(name, None)
    state["crds"] = crds
    save_state(state)
    sys.exit(0)
elif cmd == "label" and len(args) >= 2 and args[1] == "crd":
    names = [a for a in args[2:] if not a.startswith("-") and "=" not in a]
    kv = [a for a in args[2:] if "=" in a and "managed-by" in a]
    log(sys.argv[1:])
    for name in names:
        crd = state.setdefault("crds", {}).setdefault(name, {"labels": {}, "annotations": {}})
        for entry in kv:
            key, value = entry.split("=", 1)
            if key == "app.kubernetes.io/managed-by":
                crd.setdefault("labels", {})[key] = value
    save_state(state)
    sys.exit(0)
elif cmd == "annotate" and len(args) >= 2 and args[1] == "crd":
    names = [a for a in args[2:] if not a.startswith("-") and "=" not in a]
    kv = [a for a in args[2:] if "=" in a]
    log(sys.argv[1:])
    for name in names:
        crd = state.setdefault("crds", {}).setdefault(name, {"labels": {}, "annotations": {}})
        for entry in kv:
            key, value = entry.split("=", 1)
            crd.setdefault("annotations", {})[key] = value
    save_state(state)
    sys.exit(0)
else:
    log(sys.argv[1:])
    sys.exit(0)
"""


def kubectl_stub(tmp_path: pathlib.Path) -> Tuple[pathlib.Path, pathlib.Path, pathlib.Path]:
    state_path = tmp_path / "state.json"
    log_path = tmp_path / "kubectl.log"
    kubectl_path = tmp_path / "kubectl"
    kubectl_path.write_text(KUBECTL_STUB)
    kubectl_path.chmod(0o755)
    return state_path, log_path, kubectl_path


@pytest.mark.skipif(JUST_BIN is None, reason="just is not installed in the test environment")
def test_traefik_crd_doctor_recipe_exists() -> None:
    result = subprocess.run(
        [JUST_BIN, "--list"],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )

    assert "traefik-crd-doctor" in result.stdout


@pytest.mark.skipif(JUST_BIN is None, reason="just is not installed in the test environment")
def test_traefik_crd_doctor_script_is_syntactically_valid() -> None:
    show = subprocess.run(
        [JUST_BIN, "--show", "traefik-crd-doctor"],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )

    syntax = subprocess.run(
        ["bash", "-n"],
        input=show.stdout,
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
    )

    assert syntax.returncode == 0, f"bash -n failed:\n{syntax.stderr}"


def _run_doctor(
    tmp_path: pathlib.Path, state: Dict[str, object], args: list[str] | None = None, input_text: str = ""
) -> Tuple[subprocess.CompletedProcess[str], pathlib.Path, pathlib.Path]:
    state_path, log_path, kubectl_path = kubectl_stub(tmp_path)
    state_path.write_text(json.dumps(state))

    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{kubectl_path.parent}:{env['PATH']}",
            "KUBECTL_STATE": str(state_path),
            "KUBECTL_LOG": str(log_path),
        }
    )

    cmd = [JUST_BIN, "traefik-crd-doctor"]
    if args:
        cmd.extend(args)

    result = subprocess.run(
        cmd,
        cwd=REPO_ROOT,
        env=env,
        text=True,
        input=input_text,
        capture_output=True,
    )
    return result, state_path, log_path


@pytest.mark.skipif(JUST_BIN is None, reason="just is not installed in the test environment")
def test_doctor_reports_missing_crds(tmp_path: pathlib.Path) -> None:
    result, state_path, log_path = _run_doctor(tmp_path, {"crds": {}})

    assert result.returncode == 0
    assert "missing or not present" in result.stdout
    assert "Recommended actions" not in result.stdout
    assert not log_path.exists() or log_path.read_text() == ""
    assert json.loads(state_path.read_text()) == {"crds": {}}


@pytest.mark.skipif(JUST_BIN is None, reason="just is not installed in the test environment")
def test_doctor_reports_healthy_traefik_owned_crds(tmp_path: pathlib.Path) -> None:
    healthy_state = {
        "crds": {
            name: {
                "labels": {"app.kubernetes.io/managed-by": "Helm"},
                "annotations": {
                    "meta.helm.sh/release-name": "traefik",
                    "meta.helm.sh/release-namespace": "kube-system",
                },
            }
            for name in GATEWAY_CRDS
        }
    }

    result, _, log_path = _run_doctor(tmp_path, healthy_state)

    assert result.returncode == 0
    assert "owned by release traefik" in result.stdout
    assert "Recommended actions" not in result.stdout
    assert not log_path.exists() or log_path.read_text() == ""


@pytest.mark.skipif(JUST_BIN is None, reason="just is not installed in the test environment")
def test_doctor_reports_problematic_crds(tmp_path: pathlib.Path) -> None:
    problematic_state = {
        "crds": {
            GATEWAY_CRDS[0]: {
                "labels": {"app.kubernetes.io/managed-by": "manual"},
                "annotations": {
                    "meta.helm.sh/release-name": "other-release",
                    "meta.helm.sh/release-namespace": "default",
                },
            }
        }
    }

    result, _, log_path = _run_doctor(tmp_path, problematic_state)

    assert result.returncode != 0
    assert "Recommended actions" in result.stdout
    assert "kubectl delete crd" in result.stdout
    if log_path.exists():
        assert log_path.read_text() in {"", "\n"}


@pytest.mark.skipif(JUST_BIN is None, reason="just is not installed in the test environment")
def test_doctor_allows_unmanaged_crds(tmp_path: pathlib.Path) -> None:
    unmanaged_state = {
        "crds": {
            name: {"labels": {}, "annotations": {}} for name in GATEWAY_CRDS
        }
    }

    result, state_path, log_path = _run_doctor(tmp_path, unmanaged_state)

    assert result.returncode == 0
    assert "present without Helm ownership metadata" in result.stdout
    assert "Recommended actions" not in result.stdout
    assert json.loads(state_path.read_text()) == unmanaged_state
    assert not log_path.exists() or log_path.read_text() == ""


@pytest.mark.skipif(JUST_BIN is None, reason="just is not installed in the test environment")
def test_doctor_apply_mode_runs_delete_on_confirmation(tmp_path: pathlib.Path) -> None:
    problematic_state = {
        "crds": {
            GATEWAY_CRDS[1]: {
                "labels": {},
                "annotations": {
                    "meta.helm.sh/release-name": "unowned",
                    "meta.helm.sh/release-namespace": "kube-system",
                },
            }
        }
    }

    result, state_path, log_path = _run_doctor(
        tmp_path,
        problematic_state,
        args=["apply=1"],
        input_text="y\n",
    )

    assert result.returncode == 0
    log_contents = log_path.read_text()
    assert "delete crd" in log_contents
    updated_state = json.loads(state_path.read_text())
    assert updated_state == {"crds": {}}


@pytest.mark.skipif(JUST_BIN is None, reason="just is not installed in the test environment")
def test_doctor_apply_mode_aborts_without_consent(tmp_path: pathlib.Path) -> None:
    problematic_state = {
        "crds": {
            GATEWAY_CRDS[2]: {
                "labels": {},
                "annotations": {"meta.helm.sh/release-name": "traefik"},
            }
        }
    }

    result, state_path, log_path = _run_doctor(
        tmp_path,
        problematic_state,
        args=["apply=1"],
        input_text="\n",
    )

    assert result.returncode != 0
    assert "Aborting without changes" in result.stdout
    assert json.loads(state_path.read_text()) == problematic_state
    assert not log_path.exists() or log_path.read_text() == ""
