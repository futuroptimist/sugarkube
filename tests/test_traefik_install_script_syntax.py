"""Ensure the traefik-install just recipe expands to valid shell."""

from __future__ import annotations

import pathlib
import shutil
import subprocess

import pytest


REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
JUST_BIN = shutil.which("just")


@pytest.mark.skipif(JUST_BIN is None, reason="just is not installed in the test environment")
def test_traefik_install_recipe_exists() -> None:
    result = subprocess.run(
        [JUST_BIN, "--list"],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )

    assert "traefik-install" in result.stdout


@pytest.mark.skipif(JUST_BIN is None, reason="just is not installed in the test environment")
def test_traefik_install_script_is_syntactically_valid() -> None:
    show = subprocess.run(
        [JUST_BIN, "--show", "traefik-install"],
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
