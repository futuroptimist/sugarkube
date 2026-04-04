from __future__ import annotations

import os
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
JUSTFILE = REPO_ROOT / "justfile"


def test_helm_oci_deploy_recipe_enables_wait_flags() -> None:
    justfile_text = JUSTFILE.read_text(encoding="utf-8")
    assert "helm_args+=(--wait --wait-for-jobs --timeout 180s)" in justfile_text
    assert 'Running Helm deploy with rollout wait (timeout: 180s)...' in justfile_text


def _write_fake_helm(bin_dir: Path) -> None:
    script = bin_dir / "helm"
    script.write_text(
        textwrap.dedent(
            """#!/usr/bin/env python3
import os
import sys
from pathlib import Path


def fail(msg: str) -> None:
    print(msg, file=sys.stderr)
    sys.exit(1)


args = sys.argv[1:]
if not args or args[0] != "upgrade":
    fail(f"expected helm upgrade call, got: {' '.join(args)}")

required_flags = {"--install", "--create-namespace", "--wait", "--wait-for-jobs"}
missing = sorted(flag for flag in required_flags if flag not in args)
if missing:
    fail(f"missing required flags: {', '.join(missing)}")

if "--timeout" not in args:
    fail("--timeout flag is required")

timeout_value = args[args.index("--timeout") + 1]
if timeout_value != "180s":
    fail(f"expected timeout 180s, got {timeout_value}")

release = args[1]
chart = args[2]
if release != "dspace":
    fail(f"expected release=dspace, got {release}")
if chart != "oci://fake.registry/charts/dspace":
    fail(f"unexpected chart {chart}")

if "--version" not in args:
    fail("expected --version when version_file is provided")

version = args[args.index("--version") + 1]
registry_root = Path(os.environ["FAKE_OCI_REGISTRY"])
artifact = registry_root / "charts" / "dspace" / f"{version}.tgz"
if not artifact.exists():
    fail(f"missing fake OCI artifact: {artifact}")

Path(os.environ["HELM_INVOCATION_LOG"]).write_text(" ".join(args), encoding="utf-8")
print("fake helm deploy successful")
"""
        ),
        encoding="utf-8",
    )
    script.chmod(0o755)


@pytest.mark.skipif(shutil.which("just") is None, reason="just is required for this test")
def test_helm_oci_install_waits_for_readiness_with_oci_chart(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _write_fake_helm(bin_dir)

    registry = tmp_path / "fake_oci_registry"
    artifact = registry / "charts" / "dspace" / "1.2.3.tgz"
    artifact.parent.mkdir(parents=True)
    artifact.write_text("fake chart artifact", encoding="utf-8")

    version_file = tmp_path / "dspace.version"
    version_file.write_text("1.2.3\n", encoding="utf-8")

    kubeconfig = tmp_path / "kubeconfig"
    kubeconfig.write_text("apiVersion: v1\n", encoding="utf-8")

    helm_log = tmp_path / "helm.log"

    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{bin_dir}{os.pathsep}{env['PATH']}",
            "KUBECONFIG": str(kubeconfig),
            "FAKE_OCI_REGISTRY": str(registry),
            "HELM_INVOCATION_LOG": str(helm_log),
        }
    )

    result = subprocess.run(
        [
            "just",
            "--justfile",
            str(JUSTFILE),
            "helm-oci-install",
            "release=dspace",
            "namespace=dspace",
            "chart=oci://fake.registry/charts/dspace",
            f"version_file={version_file}",
        ],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "rollout wait" in result.stdout
    invocation = helm_log.read_text(encoding="utf-8")
    assert "--wait" in invocation
    assert "--wait-for-jobs" in invocation
    assert "--timeout 180s" in invocation
