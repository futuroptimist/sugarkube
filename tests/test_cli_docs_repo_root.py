"""Ensure the CLI runs helpers from the repository root as documented."""

from __future__ import annotations

from pathlib import Path
from typing import Mapping, Sequence

import pytest

from sugarkube_toolkit import cli, runner


@pytest.mark.parametrize(
    "argv, expected_forwarded",
    [
        (["docs", "verify"], 2),
        (["docs", "simplify"], 1),
    ],
)
def test_cli_invocations_pin_repo_root(
    argv: list[str],
    expected_forwarded: int,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """CLI commands must execute from repo root even when run inside subdirectories."""

    nested = tmp_path / "nested" / "dir"
    nested.mkdir(parents=True)
    monkeypatch.chdir(nested)

    recorded_cwds: list[Path | None] = []
    forwarded_commands: list[Sequence[Sequence[str]]] = []

    def fake_run(
        commands: Sequence[Sequence[str]],
        *,
        dry_run: bool = False,
        env: Mapping[str, str] | None = None,
        cwd: Path | None = None,
    ) -> None:
        recorded_cwds.append(Path(cwd) if cwd is not None else None)
        forwarded_commands.append(commands)

    monkeypatch.setattr(runner, "run_commands", fake_run)

    exit_code = cli.main(argv)

    assert exit_code == 0
    assert recorded_cwds == [cli.REPO_ROOT]
    assert len(forwarded_commands) == 1
    assert len(forwarded_commands[0]) == expected_forwarded


def test_readme_calls_out_repo_root_execution() -> None:
    """The README should mention the enforced repository-root working directory."""

    readme_text = Path("README.md").read_text(encoding="utf-8")

    assert "repository root" in readme_text and "CLI" in readme_text


def test_contributor_map_calls_out_repo_root_execution() -> None:
    """The contributor script map should reiterate the repository-root requirement."""

    doc_text = Path("docs/contributor_script_map.md").read_text(encoding="utf-8")

    assert "repository root" in doc_text and "CLI" in doc_text


def test_readme_points_to_sugarkube_wrapper_for_nested_usage() -> None:
    """Readers should learn to use scripts/sugarkube when not at repo root."""

    readme_text = Path("README.md").read_text(encoding="utf-8")

    assert "scripts/sugarkube" in readme_text, "README should mention the wrapper for nested usage"
