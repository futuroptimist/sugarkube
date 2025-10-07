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
