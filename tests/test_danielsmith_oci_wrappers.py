"""Regression coverage for Danielsmith OCI just wrapper argument normalization."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]


def _write_executable(path: Path, contents: str) -> None:
    path.write_text(contents, encoding="utf-8")
    path.chmod(0o755)


@pytest.fixture()
def wrapper_stubs(tmp_path: Path) -> tuple[Path, Path]:
    """Place harmless just/kubectl stubs before PATH for inner recipe calls."""

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    just_log = tmp_path / "inner-just.log"
    _write_executable(
        bin_dir / "just",
        """#!/usr/bin/env bash
set -eu
printf '%s\n' "$*" >> "${SUGARKUBE_JUST_LOG}"
""",
    )
    _write_executable(
        bin_dir / "kubectl",
        """#!/usr/bin/env bash
exit 0
""",
    )
    return bin_dir, just_log


@pytest.mark.usefixtures("ensure_just_available")
@pytest.mark.parametrize(
    ("recipe", "args", "expected_helper"),
    [
        ("danielsmith-oci-deploy", ["env=staging", "tag=tag=main-deadbee"], "helm-oci-install"),
        ("danielsmith-oci-deploy", ["staging", "main-deadbee"], "helm-oci-install"),
        ("danielsmith-oci-redeploy", ["env=staging", "tag=tag=main-deadbee"], "helm-oci-upgrade"),
    ],
)
def test_danielsmith_oci_wrappers_pass_immutable_tags_to_helm_helpers(
    wrapper_stubs: tuple[Path, Path], recipe: str, args: list[str], expected_helper: str
) -> None:
    """Named-style and positional tags should reach the Helm wrapper as immutable tags."""

    bin_dir, just_log = wrapper_stubs
    just_bin = shutil.which("just")
    assert just_bin, "just should be installed by the ensure_just_available fixture"

    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}{os.pathsep}{env.get('PATH', '')}"
    env["SUGARKUBE_JUST_LOG"] = str(just_log)

    result = subprocess.run(
        [just_bin, recipe, *args],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    log = just_log.read_text(encoding="utf-8")
    assert expected_helper in log
    assert "tag=main-deadbee" in log
    assert "tag=tag=main-deadbee" not in log


@pytest.mark.usefixtures("ensure_just_available")
@pytest.mark.parametrize("mutable_tag", ["tag=main-latest", "tag=latest", "tag=main"])
def test_danielsmith_oci_deploy_rejects_named_mutable_tags(
    wrapper_stubs: tuple[Path, Path], mutable_tag: str
) -> None:
    """Mutable tag rejection should run after named-style tag normalization."""

    bin_dir, just_log = wrapper_stubs
    just_bin = shutil.which("just")
    assert just_bin, "just should be installed by the ensure_just_available fixture"

    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}{os.pathsep}{env.get('PATH', '')}"
    env["SUGARKUBE_JUST_LOG"] = str(just_log)

    result = subprocess.run(
        [just_bin, "danielsmith-oci-deploy", "env=staging", mutable_tag],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0
    assert "mutable tag" in result.stderr
    assert not just_log.exists(), "invalid tags should fail before invoking helper recipes"
