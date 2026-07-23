from __future__ import annotations

import json
import os
import subprocess
import textwrap
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "cluster_identity.py"


def _kubectl(bin_dir: Path) -> Path:
    path = bin_dir / "kubectl"
    path.write_text(
        textwrap.dedent(
            """#!/usr/bin/env python3
import json, os, sys
args = sys.argv[1:]
if len(args) >= 2 and args[0] == "--kubeconfig":
    args = args[2:]
if args[:2] == ["config", "current-context"]:
    print(os.environ.get("STUB_CONTEXT", "sugar-prod")); raise SystemExit(0)
if args[:2] == ["config", "view"]:
    print("https://127.0.0.1:6443", end=""); raise SystemExit(0)
if args == ["get", "nodes", "-o", "json"]:
    mode = os.environ.get("STUB_NODES", "staging")
    if mode == "fail":
        print("api down", file=sys.stderr); raise SystemExit(7)
    if mode == "empty":
        print('{"items": []}'); raise SystemExit(0)
    if mode == "missing":
        print(json.dumps({"items":[{"metadata":{"name":"sugarkube3","labels":{"sugarkube.cluster":"cube"}}}]})); raise SystemExit(0)
    if mode == "missing-cluster":
        print(json.dumps({"items":[{"metadata":{"name":"sugarkube3","labels":{"sugarkube.env":"staging"}}}]})); raise SystemExit(0)
    if mode == "mixed-cluster":
        print(json.dumps({"items":[{"metadata":{"name":"sugarkube3","labels":{"sugarkube.env":"staging","sugarkube.cluster":"cube-a"}}},{"metadata":{"name":"sugarkube4","labels":{"sugarkube.env":"staging","sugarkube.cluster":"cube-b"}}}]})); raise SystemExit(0)
    if mode == "malformed-labels":
        print(json.dumps({"items":[{"metadata":{"name":"sugarkube3","labels":[]}}]})); raise SystemExit(0)
    if mode == "mixed":
        envs = ["staging", "prod"]
    else:
        envs = [mode, mode]
    print(json.dumps({"items":[{"metadata":{"name":f"sugarkube{i+3}","labels":{"sugarkube.env":e,"sugarkube.cluster":"cube"}}} for i,e in enumerate(envs)]}))
    raise SystemExit(0)
raise SystemExit(1)
"""
        ),
        encoding="utf-8",
    )
    path.chmod(0o755)
    return path


def _run(tmp_path: Path, requested: str, mode: str) -> subprocess.CompletedProcess[str]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _kubectl(bin_dir)
    kubeconfig = tmp_path / "config"
    kubeconfig.write_text("apiVersion: v1\n", encoding="utf-8")
    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}{os.pathsep}{env['PATH']}"
    env["STUB_NODES"] = mode
    return subprocess.run(
        ["python3", str(SCRIPT), "assert", "--kubeconfig", str(kubeconfig), "--env", requested, "--cluster", "cube"],
        cwd=REPO_ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def test_cluster_identity_matching_environment_succeeds(tmp_path: Path) -> None:
    assert _run(tmp_path, "staging", "staging").returncode == 0


def test_cluster_identity_legacy_int_normalizes_to_staging(tmp_path: Path) -> None:
    result = _run(tmp_path, "staging", "int")
    assert result.returncode == 0
    assert result.stdout.strip() == "staging"


def test_cluster_identity_requested_prod_detected_staging_fails_closed(tmp_path: Path) -> None:
    result = _run(tmp_path, "prod", "staging")
    assert result.returncode != 0
    assert "requested env=prod" in result.stderr
    assert "env=staging" in result.stderr
    assert "Connected nodes: sugarkube3, sugarkube4" in result.stderr


def test_cluster_identity_requested_staging_detected_prod_fails_closed(tmp_path: Path) -> None:
    result = _run(tmp_path, "staging", "prod")
    assert result.returncode != 0
    assert "requested env=staging" in result.stderr
    assert "env=prod" in result.stderr


def test_cluster_identity_zero_nodes_fails_closed(tmp_path: Path) -> None:
    assert "zero nodes" in _run(tmp_path, "prod", "empty").stderr


def test_cluster_identity_kubectl_failure_fails_closed(tmp_path: Path) -> None:
    assert "failed to query" in _run(tmp_path, "prod", "fail").stderr


def test_cluster_identity_missing_env_label_fails_closed(tmp_path: Path) -> None:
    assert "missing sugarkube.env" in _run(tmp_path, "prod", "missing").stderr


def test_cluster_identity_mixed_env_labels_fail_closed(tmp_path: Path) -> None:
    assert "mixed or ambiguous" in _run(tmp_path, "prod", "mixed").stderr


def test_cluster_identity_missing_cluster_label_fails_closed(tmp_path: Path) -> None:
    result = _run(tmp_path, "staging", "missing-cluster")
    assert result.returncode != 0
    assert "missing sugarkube.cluster" in result.stderr


def test_cluster_identity_mixed_cluster_labels_fail_closed(tmp_path: Path) -> None:
    result = _run(tmp_path, "staging", "mixed-cluster")
    assert result.returncode != 0
    assert "mixed or ambiguous sugarkube.cluster" in result.stderr


def test_cluster_identity_unexpected_cluster_label_fails_closed(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _kubectl(bin_dir)
    kubeconfig = tmp_path / "config"
    kubeconfig.write_text("apiVersion: v1\n", encoding="utf-8")
    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}{os.pathsep}{env['PATH']}"
    env["STUB_NODES"] = "staging"
    result = subprocess.run(
        ["python3", str(SCRIPT), "assert", "--kubeconfig", str(kubeconfig), "--env", "staging", "--cluster", "other-cube"],
        cwd=REPO_ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode != 0
    assert "expected cluster=other-cube" in result.stderr
    assert "cluster=cube" in result.stderr


def test_cluster_identity_malformed_label_structure_fails_without_traceback(tmp_path: Path) -> None:
    result = _run(tmp_path, "staging", "malformed-labels")
    assert result.returncode != 0
    assert "missing sugarkube.env" in result.stderr
    assert "Traceback" not in result.stderr


def test_cluster_identity_detect_prints_details(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _kubectl(bin_dir)
    kubeconfig = tmp_path / "config"
    kubeconfig.write_text("apiVersion: v1\n", encoding="utf-8")
    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}{os.pathsep}{env['PATH']}"
    env["STUB_NODES"] = "prod"
    env["STUB_CONTEXT"] = "sugar-prod"
    result = subprocess.run(
        ["python3", str(SCRIPT), "detect", "--kubeconfig", str(kubeconfig)],
        cwd=REPO_ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0
    assert "Environment: prod" in result.stdout
    assert "Cluster: cube" in result.stdout
    assert "Nodes: sugarkube3, sugarkube4" in result.stdout
    assert "Context: sugar-prod" in result.stdout
    assert "Server: https://127.0.0.1:6443" in result.stdout


def test_cluster_identity_assert_requires_cluster(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _kubectl(bin_dir)
    kubeconfig = tmp_path / "config"
    kubeconfig.write_text("apiVersion: v1\n", encoding="utf-8")
    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}{os.pathsep}{env['PATH']}"
    result = subprocess.run(
        ["python3", str(SCRIPT), "assert", "--kubeconfig", str(kubeconfig), "--env", "staging"],
        cwd=REPO_ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode != 0
    assert "assert requires --cluster" in result.stderr


def test_cluster_identity_assert_requires_env(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _kubectl(bin_dir)
    kubeconfig = tmp_path / "config"
    kubeconfig.write_text("apiVersion: v1\n", encoding="utf-8")
    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}{os.pathsep}{env['PATH']}"
    result = subprocess.run(
        ["python3", str(SCRIPT), "assert", "--kubeconfig", str(kubeconfig)],
        cwd=REPO_ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode != 0
    assert "assert requires --env" in result.stderr
