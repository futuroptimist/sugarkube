"""Utility helpers for running subprocesses consistently."""

from __future__ import annotations

import os
import shlex
import subprocess
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass


@dataclass(slots=True)
class CommandError(RuntimeError):
    """Raised when a subprocess exits with a non-zero status."""

    command: Sequence[str]
    returncode: int
    stderr: str | None = None

    def __str__(self) -> str:
        message = f"{format_command(self.command)} exited with status {self.returncode}"
        if self.stderr:
            stderr = self.stderr.strip()
            if stderr:
                message = f"{message}\n{stderr}"
        return message


def format_command(command: Sequence[str]) -> str:
    """Render a subprocess command for display or logging."""

    return " ".join(shlex.quote(part) for part in command)


def _merge_env(env: Mapping[str, str] | None) -> Mapping[str, str] | None:
    if env is None:
        return None
    merged = os.environ.copy()
    merged.update(env)
    return merged


def run_commands(
    commands: Iterable[Sequence[str]],
    *,
    dry_run: bool = False,
    env: Mapping[str, str] | None = None,
    cwd: os.PathLike[str] | str | None = None,
) -> None:
    """Run each command, stopping at the first failure.

    When ``dry_run`` is ``True`` the commands are only printed.
    """

    process_env = _merge_env(env)

    for command in commands:
        printable = format_command(command)
        print(f"$ {printable}", flush=True)
        if dry_run:
            continue
        result = subprocess.run(
            command,
            env=process_env,
            check=False,
            text=True,
            stderr=subprocess.PIPE,
            cwd=str(cwd) if cwd is not None else None,
        )
        if result.returncode != 0:
            raise CommandError(command, result.returncode, stderr=result.stderr)
