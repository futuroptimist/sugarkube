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
                "SUGARKUBE_KUBECONFIG_USER="
                + os.environ.get("SUGARKUBE_KUBECONFIG_USER", "")
                + "\\nSUGARKUBE_KUBECONFIG_HOME="
                + os.environ.get("SUGARKUBE_KUBECONFIG_HOME", "")
                + "\\nSUGARKUBE_ENV="
                + os.environ.get("SUGARKUBE_ENV", "")
                + "\\nSUGARKUBE_SERVERS="
                + os.environ.get("SUGARKUBE_SERVERS", "")
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


def test_up_normalize_env_name_strips_named_prefixes_without_just():
    lines = Path("justfile").read_text(encoding="utf-8").splitlines()
    body = _extract_recipe(lines, "up env='dev':")
    function_lines: list[str] = []
    collecting = False
    for line in body:
        stripped = line[4:] if line.startswith("    ") else line
        if stripped.startswith("normalize_env_name()"):
            collecting = True
        if collecting:
            function_lines.append(stripped)
            if stripped == "}":
                break

    assert function_lines, "normalize_env_name helper not found in the up recipe"

    script = "\n".join(
        [
            "set -Eeuo pipefail",
            *function_lines,
            "normalize_env_name staging",
            "printf '\\n'",
            "normalize_env_name env=staging",
            "printf '\\n'",
            "normalize_env_name env=env=staging",
            "printf '\\n'",
            "normalize_env_name int",
            "printf '\\n'",
        ]
    )
    result = subprocess.run(
        ["bash", "-c", script], capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == ["staging", "staging", "staging", "staging"]


def test_up_recipe_exports_only_normalized_env_to_discovery_path():
    # Regression coverage for the 2026-05-18 DSPACE outage where `env=staging` reached
    # mDNS/Avahi as `_k3s-sugar-env=staging._tcp` instead of `_k3s-sugar-staging._tcp`.
    lines = Path("justfile").read_text(encoding="utf-8").splitlines()
    body = _extract_recipe(lines, "up env='dev':")
    body_text = "\n".join(body)
    normalize_index = body_text.index('env_name="$(normalize_env_name "${env_input}")"')
    export_index = body_text.index('export SUGARKUBE_ENV="${env_name}"')
    discover_index = body_text.index("sudo -E bash scripts/k3s-discover.sh")
    assert normalize_index < export_index < discover_index
    assert 'export SUGARKUBE_ENV="${env_input}"' not in body_text


@pytest.mark.skipif(shutil.which("just") is None, reason="just is required for this test")
@pytest.mark.parametrize(
    ("command", "expected_env", "expected_servers"),
    [
        (["up", "staging"], "staging", "1"),
        (["up", "env=staging"], "staging", "1"),
        (["up", "env=env=staging"], "staging", "1"),
        (["up", "int"], "staging", "1"),
        (["up", "dev"], "dev", "1"),
        (["up", "prod"], "prod", "1"),
        (["save-logs", "staging"], "staging", "1"),
        (["save-logs", "env=staging"], "staging", "1"),
        (["ha3", "env=staging"], "staging", "3"),
    ],
)
def test_up_family_normalizes_named_env_arguments(
    tmp_path: Path, command: list[str], expected_env: str, expected_servers: str
):
    # Regression coverage for the 2026-05-18 DSPACE outage where `just up env=staging`
    # propagated the literal value into Avahi names such as `_k3s-sugar-env=staging._tcp`.
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _write_fake_sudo(bin_dir)

    capture = tmp_path / "captured.env"
    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{bin_dir}{os.pathsep}{env['PATH']}",
            "HOME": str(tmp_path / "home"),
            "TEST_CAPTURE_ENV_FILE": str(capture),
            # Keep the recipe path deterministic and avoid local sourcing / log filtering.
            "SUGARKUBE_SUMMARY_LIB": "/nonexistent/summary.sh",
            "SUGARKUBE_LOG_FILTER": "/nonexistent/filter_debug_log.py",
        }
    )

    result = subprocess.run(
        ["just", "--justfile", "justfile", *command],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    captured = capture.read_text(encoding="utf-8").splitlines()
    assert f"SUGARKUBE_ENV={expected_env}" in captured
    assert f"SUGARKUBE_SERVERS={expected_servers}" in captured
    assert "SUGARKUBE_ENV=env=staging" not in captured
    assert "SUGARKUBE_ENV=env=env=staging" not in captured
    assert "_k3s-sugar-env=staging._tcp" not in result.stdout + result.stderr
