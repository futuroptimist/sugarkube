#!/usr/bin/env python3
"""Interactive macOS setup wizard for Sugarkube contributors.

The wizard keeps macOS hosts aligned with the tooling expectations described in the Pi image
quickstart. It inspects Homebrew, required formulas, and workspace directories, then applies or
prints a step-by-step remediation plan.
"""

from __future__ import annotations

import argparse
import os
import platform
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, List, Sequence

# Homebrew packages we expect on contributor laptops.
REQUIRED_FORMULAE = {
    "coreutils": "GNU userland used by flashing and verifier scripts.",
    "just": "Runs repository automation recipes mirroring the Makefile targets.",
    "pipx": "Installs Python CLIs in isolated environments for repeatable runs.",
    "qemu": "Boots Pi images locally for smoke tests without extra hardware.",
    "xz": "Decompresses release artifacts and installer bundles.",
}

TAP_NAME = "sugarkube/sugarkube"
CONFIG_FILE = Path("sugarkube/config/sugarkube.env")
DIRECTORIES = [
    Path("sugarkube/cache"),
    Path("sugarkube/images"),
    Path("sugarkube/reports"),
]

CONFIG_TEMPLATE = """# Sugarkube macOS defaults
# Keep these directories in sync with the docs quickstart and automation scripts.
SUGARKUBE_IMAGES_DIR="{home}/sugarkube/images"
SUGARKUBE_REPORTS_DIR="{home}/sugarkube/reports"
SUGARKUBE_CACHE_DIR="{home}/sugarkube/cache"
# Always aim for 100% patch coverage on the first pytest run.
"""


class SetupError(RuntimeError):
    """Raised when the setup wizard cannot continue."""


@dataclass
class Task:
    """Single actionable task discovered by the wizard."""

    description: str
    detail: str | None = None
    action: Callable[[], None] | None = None


class SystemContext:
    """Facade around OS interactions so tests can stub behaviours."""

    def __init__(
        self,
        *,
        runner: Callable[..., subprocess.CompletedProcess[str]] | None = None,
        home: Path | None = None,
    ) -> None:
        self._runner = runner or subprocess.run
        self.home = home or Path.home()

    # ---- platform helpers -------------------------------------------------
    def platform(self) -> str:
        return platform.system().lower()

    def has_command(self, name: str) -> bool:
        return shutil.which(name) is not None

    # ---- Homebrew helpers --------------------------------------------------
    def brew_taps(self) -> set[str]:
        output = self._run_text(["brew", "tap"])
        return {line.strip() for line in output.splitlines() if line.strip()}

    def brew_packages(self) -> set[str]:
        output = self._run_text(["brew", "list", "--formula"])
        return {line.strip() for line in output.splitlines() if line.strip()}

    def run(self, command: Sequence[str]) -> None:
        try:
            self._runner(command, check=True)
        except FileNotFoundError as exc:  # pragma: no cover - exercised via tests
            raise SetupError(f"Command not found: {command[0]}") from exc
        except subprocess.CalledProcessError as exc:  # pragma: no cover - tests cover via stub
            stderr = (exc.stderr or "").strip()
            detail = f": {stderr}" if stderr else ""
            raise SetupError(
                f"Command {' '.join(command)} failed with exit code {exc.returncode}{detail}"
            ) from exc

    # ---- filesystem helpers -----------------------------------------------
    def path_exists(self, relative: Path) -> bool:
        return (self.home / relative).exists()

    def ensure_directory(self, relative: Path) -> Path:
        target = self.home / relative
        try:
            target.mkdir(parents=True, exist_ok=True)
        except OSError as exc:  # pragma: no cover - tested via monkeypatch
            raise SetupError(f"Failed to create {target}: {exc}") from exc
        return target

    def write_config_file(self, relative: Path, content: str) -> bool:
        target = self.home / relative
        if target.exists():
            return False
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)
        os.chmod(target, 0o600)
        return True

    # ---- private helpers ---------------------------------------------------
    def _run_text(self, command: Sequence[str]) -> str:
        try:
            result = self._runner(
                command,
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
        except FileNotFoundError as exc:
            raise SetupError("Homebrew is required but not installed (missing 'brew').") from exc
        except subprocess.CalledProcessError as exc:
            stderr = (exc.stderr or "").strip()
            raise SetupError(f"brew command failed: {stderr or exc}") from exc
        return result.stdout


class SetupWizard:
    """Compute and execute the macOS setup plan."""

    def __init__(self, system: SystemContext, stream) -> None:
        self.system = system
        self.stream = stream

    def build_plan(self, *, force: bool) -> List[Task]:
        if self.system.platform() != "darwin" and not force:
            raise SetupError(
                "This wizard only targets macOS. Re-run with --force to bypass the platform check."
            )
        if not self.system.has_command("brew"):
            raise SetupError("Install Homebrew from https://brew.sh/ before running this wizard.")

        plan: List[Task] = []
        taps = self.system.brew_taps()
        packages = self.system.brew_packages()

        if TAP_NAME not in taps:
            plan.append(
                Task(
                    description=f"Add the {TAP_NAME} Homebrew tap",
                    detail="Enables `brew install sugarkube` for future updates.",
                    action=lambda: self.system.run(["brew", "tap", TAP_NAME]),
                )
            )

        for name, note in sorted(REQUIRED_FORMULAE.items()):
            if name not in packages:
                plan.append(
                    Task(
                        description=f"Install {name} via Homebrew",
                        detail=note,
                        action=lambda pkg=name: self.system.run(["brew", "install", pkg]),
                    )
                )

        if "sugarkube" not in packages:
            plan.append(
                Task(
                    description="Install the sugarkube formula",
                    detail="Provides the `sugarkube-setup` CLI and future helpers.",
                    action=lambda: self.system.run(["brew", "install", "sugarkube"]),
                )
            )

        for relative in DIRECTORIES:
            if not self.system.path_exists(relative):
                plan.append(
                    Task(
                        description=f"Create {self.system.home / relative}",
                        action=lambda rel=relative: self.system.ensure_directory(rel),
                    )
                )

        home_str = str(self.system.home)
        rendered = CONFIG_TEMPLATE.format(home=home_str)
        if self.system.write_config_file(CONFIG_FILE, rendered):
            plan.append(
                Task(
                    description=f"Seed {self.system.home / CONFIG_FILE}",
                    detail="Configures default cache/image/report directories for automation.",
                )
            )

        plan.append(
            Task(
                description="Review docs/pi_image_quickstart.md and run `make doctor` after setup",
                detail="Keeps macOS hosts aligned with CI and patch coverage expectations.",
            )
        )
        return plan

    def render_plan(self, plan: Iterable[Task]) -> None:
        tasks = list(plan)
        if not tasks:
            self.stream.write("All Sugarkube macOS prerequisites are already satisfied.\n")
            return
        self.stream.write("Sugarkube macOS setup plan:\n")
        for index, task in enumerate(tasks, start=1):
            self.stream.write(f"  {index}. {task.description}\n")
            if task.detail:
                self.stream.write(f"       {task.detail}\n")

    def apply(self, plan: Iterable[Task]) -> None:
        for task in plan:
            if task.action is None:
                continue
            task.action()

    def run(self, *, force: bool, apply: bool) -> int:
        plan = self.build_plan(force=force)
        self.render_plan(plan)
        if plan and apply:
            self.stream.write("\nApplying macOS setup actions...\n")
            self.apply(plan)
            self.stream.write("\nmacOS setup complete.\n")
        elif plan:
            self.stream.write("\nRe-run with --apply to execute these steps automatically.\n")
        else:
            self.stream.write("macOS setup complete.\n")
        return 0


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Execute the proposed brew and filesystem changes instead of printing the plan.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Bypass the macOS platform check (useful for CI coverage and documentation builds).",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None, *, system: SystemContext | None = None) -> int:
    args = parse_args(argv)
    context = system or SystemContext()
    wizard = SetupWizard(context, stream=sys.stdout)
    try:
        return wizard.run(force=args.force, apply=args.apply)
    except SetupError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":  # pragma: no cover - exercise via tests calling main directly
    sys.exit(main())
