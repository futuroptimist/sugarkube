"""Regression coverage for the unified Sugarkube CLI."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

import pytest

from sugarkube_toolkit import cli, runner


def test_docs_verify_invokes_doc_checks(monkeypatch: pytest.MonkeyPatch) -> None:
    """docs verify should chain the documented lint commands."""

    recorded: list[list[str]] = []

    def fake_run(
        commands: list[list[str]], *, dry_run: bool = False, env: Mapping[str, str] | None = None
    ) -> None:
        recorded.extend(commands)

    monkeypatch.setattr(runner, "run_commands", fake_run)

    exit_code = cli.main(["docs", "verify"])

    assert exit_code == 0
    assert recorded == [
        ["pyspelling", "-c", ".spellcheck.yaml"],
        ["linkchecker", "--no-warnings", "README.md", "docs/"],
    ]


def test_docs_verify_supports_dry_run(capsys: pytest.CaptureFixture[str]) -> None:
    """Dry-run mode should print the commands without executing them."""

    exit_code = cli.main(["docs", "verify", "--dry-run"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "pyspelling -c .spellcheck.yaml" in captured.out
    assert "linkchecker --no-warnings README.md docs/" in captured.out


def test_docs_verify_surfaces_failures(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Command failures should surface an actionable error message."""

    def boom(*_args, **_kwargs):
        raise runner.CommandError(["pyspelling"], returncode=3, stderr="missing dictionary")

    monkeypatch.setattr(runner, "run_commands", boom)

    exit_code = cli.main(["docs", "verify"])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "missing dictionary" in captured.err


def test_pi_download_invokes_helper(monkeypatch: pytest.MonkeyPatch) -> None:
    """pi download should wrap the documented helper script."""

    recorded: list[list[str]] = []

    def fake_run(
        commands: list[list[str]], *, dry_run: bool = False, env: Mapping[str, str] | None = None
    ) -> None:
        recorded.extend(commands)

    monkeypatch.setattr(runner, "run_commands", fake_run)

    exit_code = cli.main(["pi", "download", "--dry-run"])

    expected_script = Path(__file__).resolve().parents[1] / "scripts" / "download_pi_image.sh"

    assert exit_code == 0
    assert recorded == [["bash", str(expected_script)]]


def test_pi_download_forwards_additional_args(monkeypatch: pytest.MonkeyPatch) -> None:
    """Forward CLI arguments to the helper script for parity with docs."""

    recorded: list[list[str]] = []

    def fake_run(
        commands: list[list[str]], *, dry_run: bool = False, env: Mapping[str, str] | None = None
    ) -> None:
        recorded.extend(commands)

    monkeypatch.setattr(runner, "run_commands", fake_run)

    exit_code = cli.main(
        [
            "pi",
            "download",
            "--dry-run",
            "--dir",
            "~/sugarkube/images",
            "--output",
            "~/sugarkube/images/custom.img.xz",
        ]
    )

    assert exit_code == 0
    assert recorded == [
        [
            "bash",
            str(Path(__file__).resolve().parents[1] / "scripts" / "download_pi_image.sh"),
            "--dir",
            "~/sugarkube/images",
            "--output",
            "~/sugarkube/images/custom.img.xz",
        ]
    ]


def test_pi_download_reports_missing_script(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Missing helper scripts should surface an actionable error."""

    monkeypatch.setattr(cli, "DOWNLOAD_PI_IMAGE_SCRIPT", Path("/nonexistent/download_pi_image.sh"))

    exit_code = cli.main(["pi", "download", "--dry-run"])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "scripts/download_pi_image.sh is missing" in captured.err


def test_pi_download_surfaces_failures(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Handler should surface helper failures via stderr and exit code."""

    def boom(*_args, **_kwargs):
        raise runner.CommandError(["bash", "download_pi_image.sh"], returncode=1, stderr="boom")

    monkeypatch.setattr(runner, "run_commands", boom)

    exit_code = cli.main(["pi", "download", "--dry-run"])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "boom" in captured.err


def test_pi_download_drops_script_separator(monkeypatch: pytest.MonkeyPatch) -> None:
    """A leading `--` should be stripped before forwarding script arguments."""

    recorded: list[list[str]] = []

    def fake_run(
        commands: list[list[str]], *, dry_run: bool = False, env: Mapping[str, str] | None = None
    ) -> None:
        recorded.extend(commands)

    monkeypatch.setattr(runner, "run_commands", fake_run)

    exit_code = cli.main(["pi", "download", "--dry-run", "--", "--flag", "value"])

    assert exit_code == 0
    assert recorded == [
        [
            "bash",
            str(Path(__file__).resolve().parents[1] / "scripts" / "download_pi_image.sh"),
            "--flag",
            "value",
        ]
    ]


def test_pi_flash_invokes_helper(monkeypatch: pytest.MonkeyPatch) -> None:
    """pi flash should wrap the flashing helper script."""

    recorded: list[list[str]] = []

    def fake_run(
        commands: list[list[str]], *, dry_run: bool = False, env: Mapping[str, str] | None = None
    ) -> None:
        recorded.extend(commands)

    monkeypatch.setattr(runner, "run_commands", fake_run)

    exit_code = cli.main(["pi", "flash", "--dry-run"])

    expected_script = Path(__file__).resolve().parents[1] / "scripts" / "flash_pi_media.sh"

    assert exit_code == 0
    assert recorded == [["bash", str(expected_script)]]


def test_pi_flash_forwards_additional_args(monkeypatch: pytest.MonkeyPatch) -> None:
    """Forward CLI arguments to the flash helper for docs parity."""

    recorded: list[list[str]] = []

    def fake_run(
        commands: list[list[str]], *, dry_run: bool = False, env: Mapping[str, str] | None = None
    ) -> None:
        recorded.extend(commands)

    monkeypatch.setattr(runner, "run_commands", fake_run)

    exit_code = cli.main(
        [
            "pi",
            "flash",
            "--dry-run",
            "--image",
            "~/sugarkube/images/sugarkube.img",
            "--device",
            "/dev/sdX",
        ]
    )

    assert exit_code == 0
    assert recorded == [
        [
            "bash",
            str(Path(__file__).resolve().parents[1] / "scripts" / "flash_pi_media.sh"),
            "--image",
            "~/sugarkube/images/sugarkube.img",
            "--device",
            "/dev/sdX",
        ]
    ]


def test_pi_flash_reports_missing_script(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Missing flash helper scripts should surface an actionable error."""

    monkeypatch.setattr(cli, "FLASH_PI_MEDIA_SCRIPT", Path("/nonexistent/flash_pi_media.sh"))

    exit_code = cli.main(["pi", "flash", "--dry-run"])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "scripts/flash_pi_media.sh is missing" in captured.err


def test_pi_flash_surfaces_failures(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Flash handler should surface helper failures via stderr and exit code."""

    def boom(*_args, **_kwargs):
        raise runner.CommandError(["bash", "flash_pi_media.sh"], returncode=1, stderr="boom")

    monkeypatch.setattr(runner, "run_commands", boom)

    exit_code = cli.main(["pi", "flash", "--dry-run"])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "boom" in captured.err


def test_pi_flash_drops_script_separator(monkeypatch: pytest.MonkeyPatch) -> None:
    """A leading `--` should be stripped before forwarding flash args."""

    recorded: list[list[str]] = []

    def fake_run(
        commands: list[list[str]], *, dry_run: bool = False, env: Mapping[str, str] | None = None
    ) -> None:
        recorded.extend(commands)

    monkeypatch.setattr(runner, "run_commands", fake_run)

    exit_code = cli.main(["pi", "flash", "--dry-run", "--", "--assume-yes"])

    assert exit_code == 0
    assert recorded == [
        [
            "bash",
            str(Path(__file__).resolve().parents[1] / "scripts" / "flash_pi_media.sh"),
            "--assume-yes",
        ]
    ]
