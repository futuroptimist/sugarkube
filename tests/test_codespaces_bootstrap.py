"""Ensure codespaces bootstrap installs documented prerequisites."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]


def _extract_makefile_target(target: str) -> list[str]:
    text = (REPO_ROOT / "Makefile").read_text(encoding="utf-8")
    pattern = rf"^{target}:\n((?:\t.+\n)+)"
    match = re.search(pattern, text, flags=re.MULTILINE)
    if not match:
        pytest.fail(f"{target} target missing from Makefile")
    return [line.strip() for line in match.group(1).strip().splitlines()]


def _extract_justfile_recipe(target: str) -> list[str]:
    text = (REPO_ROOT / "justfile").read_text(encoding="utf-8")
    pattern = rf"^{target}:\n((?:\s{{4,}}.+\n)+)"
    match = re.search(pattern, text, flags=re.MULTILINE)
    if not match:
        pytest.fail(f"{target} recipe missing from justfile")
    return [line.strip() for line in match.group(1).strip().splitlines()]


def test_codespaces_bootstrap_installs_doc_prereqs() -> None:
    make_cmds = _extract_makefile_target("codespaces-bootstrap")
    just_cmds = _extract_justfile_recipe("codespaces-bootstrap")

    apt_packages = {"aspell", "aspell-en", "python3", "python3-pip", "python3-venv"}
    pip_packages = {"pre-commit", "pyspelling", "linkchecker"}

    def collect_apt_packages(commands: list[str]) -> set[str]:
        for idx, cmd in enumerate(commands):
            if cmd.startswith("sudo apt-get install"):
                tokens: list[str] = []
                remainder = cmd.split("sudo apt-get install", 1)[1]
                tokens.extend(remainder.replace("-y", "").replace("\\", " ").split())
                next_idx = idx + 1
                while next_idx < len(commands):
                    part = commands[next_idx]
                    tokens.extend(part.replace("\\", " ").split())
                    if not part.endswith("\\"):
                        break
                    next_idx += 1
                return {token for token in tokens if token}
        pytest.fail("apt-get install command missing")

    make_apt_packages = collect_apt_packages(make_cmds)
    just_apt_packages = collect_apt_packages(just_cmds)

    for package in apt_packages:
        assert package in make_apt_packages, f"{package} missing from Makefile apt install"
        assert package in just_apt_packages, f"{package} missing from justfile apt install"

    make_pip = next((cmd for cmd in make_cmds if "pip install" in cmd), None)
    just_pip = next((cmd for cmd in just_cmds if "pip install" in cmd), None)
    assert make_pip and just_pip, "codespaces bootstrap must install Python tooling via pip"

    for package in pip_packages:
        assert package in make_pip, f"{package} missing from Makefile pip install"
        assert package in just_pip, f"{package} missing from justfile pip install"
