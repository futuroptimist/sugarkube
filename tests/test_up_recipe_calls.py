from pathlib import Path
import os
import shutil
import subprocess
import textwrap

import pytest


def _extract_recipe(lines, header):
    collecting = False
    body = []
    indent = "    "
    for line in lines:
        if not collecting:
            if line.startswith(header):
                collecting = True
            continue
        if line and not line.startswith(indent):
            break
        body.append(line)
    return body


def test_up_recipe_runs_checks_and_discovery():
    lines = Path("justfile").read_text(encoding="utf-8").splitlines()
    body = _extract_recipe(lines, "up env='dev':")
    assert any("check_memory_cgroup.sh" in line for line in body)
    assert any(
        line.strip().startswith("export SUGARKUBE_KUBECONFIG_USER=") for line in body
    )
    assert any(
        line.strip().startswith("export SUGARKUBE_KUBECONFIG_HOME=") for line in body
    )
    assert any("sudo -E bash scripts/k3s-discover.sh" in line for line in body)


def _write_fake_sudo(bin_dir: Path) -> None:
    script = bin_dir / "sudo"
    script.write_text(
        textwrap.dedent(
            """#!/usr/bin/env python3
import os
import pathlib
import sys


def main() -> None:
    args = [arg for arg in sys.argv[1:] if arg != "-E"]
    if not args:
        sys.exit(1)

    if args[:2] == ["bash", "scripts/k3s-discover.sh"]:
        capture = os.environ.get("TEST_CAPTURE_ENV_FILE")
        if capture:
            path = pathlib.Path(capture)
            path.write_text(
                "SUGARKUBE_ENV="
                + os.environ.get("SUGARKUBE_ENV", "")
                + "\\nSUGARKUBE_KUBECONFIG_USER="
                + os.environ.get("SUGARKUBE_KUBECONFIG_USER", "")
                + "\\nSUGARKUBE_KUBECONFIG_HOME="
                + os.environ.get("SUGARKUBE_KUBECONFIG_HOME", "")
                + "\\n",
                encoding="utf-8",
            )
        sys.exit(0)

    # No-op for all other sudo calls in `just up`.
    sys.exit(0)


if __name__ == "__main__":
    main()
"""
        ),
        encoding="utf-8",
    )
    script.chmod(0o755)


@pytest.mark.skipif(shutil.which("just") is None, reason="just is required for this test")
def test_up_recipe_forwards_sudo_caller_kubeconfig_user_to_discovery(tmp_path: Path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _write_fake_sudo(bin_dir)

    capture = tmp_path / "captured.env"
    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{bin_dir}{os.pathsep}{env['PATH']}",
            "SUDO_USER": "alice",
            "HOME": str(tmp_path / "root-home"),
            "TEST_CAPTURE_ENV_FILE": str(capture),
            # Keep the recipe path deterministic and prevent local file sourcing.
            "SUGARKUBE_SUMMARY_LIB": "/nonexistent/summary.sh",
        }
    )

    result = subprocess.run(
        ["just", "--justfile", "justfile", "up", "env=dev"],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    captured = capture.read_text(encoding="utf-8").splitlines()
    assert "SUGARKUBE_KUBECONFIG_USER=alice" in captured
    assert "SUGARKUBE_KUBECONFIG_HOME=" in captured


@pytest.mark.skipif(shutil.which("just") is None, reason="just is required for this test")
@pytest.mark.parametrize(
    ("recipe_args", "expected_env"),
    [
        (["up", "staging"], "staging"),
        (["up", "env=staging"], "staging"),
        (["up", "env=env=staging"], "staging"),
        (["up", "int"], "staging"),
        (["up", "dev"], "dev"),
        (["up", "prod"], "prod"),
        (["save-logs", "staging"], "staging"),
        (["save-logs", "env=staging"], "staging"),
        (["ha3", "env=staging"], "staging"),
    ],
)
def test_up_recipe_normalizes_named_env_arguments(
    tmp_path: Path, recipe_args: list[str], expected_env: str
):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _write_fake_sudo(bin_dir)

    capture = tmp_path / "captured.env"
    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{bin_dir}{os.pathsep}{env['PATH']}",
            "TEST_CAPTURE_ENV_FILE": str(capture),
            "SUGARKUBE_SUMMARY_LIB": "/nonexistent/summary.sh",
            "SUGARKUBE_LOG_FILTER": "/nonexistent/filter_debug_log.py",
        }
    )

    result = subprocess.run(
        ["just", "--justfile", "justfile", *recipe_args],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    captured = capture.read_text(encoding="utf-8").splitlines()
    assert f"SUGARKUBE_ENV={expected_env}" in captured
    assert "SUGARKUBE_ENV=env=staging" not in captured
    # Regression for the DSPACE outage where `just up env=staging` previously fed
    # `_k3s-sugar-env=staging._tcp` and k3s-sugar-env=staging.service downstream.
    assert "env=env=staging" not in captured
