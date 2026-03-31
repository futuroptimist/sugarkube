from __future__ import annotations

import os
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
JUSTFILE = REPO_ROOT / "justfile"


@pytest.mark.skipif(shutil.which("just") is None, reason="just is required for this test")
def test_helm_oci_install_waits_for_rollout_with_fake_oci_registry(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()

    helm_log = tmp_path / "helm.log"
    kubectl_log = tmp_path / "kubectl.log"

    (tmp_path / "kubeconfig").write_text("apiVersion: v1\nkind: Config\n", encoding="utf-8")

    (bin_dir / "helm").write_text(
        textwrap.dedent(
            """#!/usr/bin/env bash
set -euo pipefail

echo "$*" >> "${HELM_TEST_LOG}"
if [[ "$*" != *"oci://registry.test.local:5000/charts/demo"* ]]; then
  echo "expected fake OCI registry chart URL" >&2
  exit 1
fi
"""
        ),
        encoding="utf-8",
    )
    (bin_dir / "helm").chmod(0o755)

    (bin_dir / "kubectl").write_text(
        textwrap.dedent(
            """#!/usr/bin/env bash
set -euo pipefail

echo "$*" >> "${KUBECTL_TEST_LOG}"
if [[ "$1" == "-n" && "$3" == "get" ]]; then
  if [[ "$6" == "app.kubernetes.io/instance=demo" ]]; then
    printf 'deployment.apps/demo\nstatefulset.apps/demo-worker\n'
    exit 0
  fi
  exit 0
fi
if [[ "$1" == "-n" && "$3" == "rollout" && "$4" == "status" ]]; then
  echo "rollout complete for $5"
  exit 0
fi
"""
        ),
        encoding="utf-8",
    )
    (bin_dir / "kubectl").chmod(0o755)

    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{bin_dir}{os.pathsep}{env['PATH']}",
            "HELM_TEST_LOG": str(helm_log),
            "KUBECTL_TEST_LOG": str(kubectl_log),
            "KUBECONFIG": str(tmp_path / "kubeconfig"),
        }
    )

    result = subprocess.run(
        [
            "just",
            "--justfile",
            str(JUSTFILE),
            "helm-oci-install",
            "release=demo",
            "namespace=demo",
            "chart=oci://registry.test.local:5000/charts/demo",
            "values=docs/examples/dspace.values.dev.yaml",
            "version=1.2.3",
            "default_tag=v3-latest",
        ],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "Waiting for rollout completion" in result.stdout
    assert "deployment.apps/demo" in result.stdout
    assert "statefulset.apps/demo-worker" in result.stdout

    kubectl_calls = kubectl_log.read_text(encoding="utf-8")
    assert "rollout status deployment.apps/demo --timeout=300s" in kubectl_calls
    assert "rollout status statefulset.apps/demo-worker --timeout=300s" in kubectl_calls
