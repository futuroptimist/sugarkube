"""Regression coverage for the unified Sugarkube CLI."""

from __future__ import annotations

import sys
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


def test_docs_simplify_invokes_checks_helper(monkeypatch: pytest.MonkeyPatch) -> None:
    """docs simplify should call the docs-only checks helper."""

    recorded: list[list[str]] = []

    def fake_run(
        commands: list[list[str]], *, dry_run: bool = False, env: Mapping[str, str] | None = None
    ) -> None:
        recorded.extend(commands)

    monkeypatch.setattr(runner, "run_commands", fake_run)

    exit_code = cli.main(["docs", "simplify"])

    expected_script = Path(__file__).resolve().parents[1] / "scripts" / "checks.sh"

    assert exit_code == 0
    assert recorded == [["bash", str(expected_script), "--docs-only"]]


def test_docs_simplify_supports_dry_run(capsys: pytest.CaptureFixture[str]) -> None:
    """Dry-run mode should surface the forwarded helper invocation."""

    exit_code = cli.main(["docs", "simplify", "--dry-run"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "bash" in captured.out
    assert "scripts/checks.sh --docs-only" in captured.out


def test_docs_simplify_drops_script_separator(monkeypatch: pytest.MonkeyPatch) -> None:
    """A leading `--` should be stripped before forwarding helper args."""

    recorded: list[list[str]] = []

    def fake_run(
        commands: list[list[str]], *, dry_run: bool = False, env: Mapping[str, str] | None = None
    ) -> None:
        recorded.extend(commands)

    monkeypatch.setattr(runner, "run_commands", fake_run)

    exit_code = cli.main(["docs", "simplify", "--dry-run", "--", "--skip-install"])

    expected_script = Path(__file__).resolve().parents[1] / "scripts" / "checks.sh"

    assert exit_code == 0
    assert recorded == [["bash", str(expected_script), "--docs-only", "--skip-install"]]


def test_docs_simplify_reports_missing_script(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Missing helper scripts should yield a clear error."""

    monkeypatch.setattr(cli, "CHECKS_SCRIPT", Path("/nonexistent/checks.sh"))

    exit_code = cli.main(["docs", "simplify"])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "scripts/checks.sh is missing" in captured.err


def test_docs_simplify_surfaces_failures(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Helper failures should bubble up through stderr and exit code."""

    def boom(*_args, **_kwargs):
        raise runner.CommandError(["bash", "checks.sh"], returncode=1, stderr="boom")

    monkeypatch.setattr(runner, "run_commands", boom)

    exit_code = cli.main(["docs", "simplify"])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "boom" in captured.err


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


def test_pi_install_invokes_helper(monkeypatch: pytest.MonkeyPatch) -> None:
    """pi install should wrap the installer helper script."""

    recorded: list[list[str]] = []

    def fake_run(
        commands: list[list[str]], *, dry_run: bool = False, env: Mapping[str, str] | None = None
    ) -> None:
        recorded.extend(commands)

    monkeypatch.setattr(runner, "run_commands", fake_run)

    exit_code = cli.main(["pi", "install", "--dry-run"])

    expected_script = Path(__file__).resolve().parents[1] / "scripts" / "install_sugarkube_image.sh"

    assert exit_code == 0
    assert recorded == [["bash", str(expected_script)]]


def test_pi_install_forwards_additional_args(monkeypatch: pytest.MonkeyPatch) -> None:
    """Forward CLI arguments to the install helper for docs parity."""

    recorded: list[list[str]] = []

    def fake_run(
        commands: list[list[str]], *, dry_run: bool = False, env: Mapping[str, str] | None = None
    ) -> None:
        recorded.extend(commands)

    monkeypatch.setattr(runner, "run_commands", fake_run)

    exit_code = cli.main(
        [
            "pi",
            "install",
            "--dry-run",
            "--dir",
            "~/sugarkube/images",
            "--image",
            "~/sugarkube/images/sugarkube.img",
        ]
    )

    assert exit_code == 0
    assert recorded == [
        [
            "bash",
            str(Path(__file__).resolve().parents[1] / "scripts" / "install_sugarkube_image.sh"),
            "--dir",
            "~/sugarkube/images",
            "--image",
            "~/sugarkube/images/sugarkube.img",
        ]
    ]


def test_pi_install_reports_missing_script(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Missing install helper scripts should surface an actionable error."""

    monkeypatch.setattr(
        cli, "INSTALL_PI_IMAGE_SCRIPT", Path("/nonexistent/install_sugarkube_image.sh")
    )

    exit_code = cli.main(["pi", "install", "--dry-run"])

    captured = capsys.readouterr()

    assert exit_code == 1
    assert "scripts/install_sugarkube_image.sh is missing" in captured.err


def test_pi_install_surfaces_failures(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Install handler should surface helper failures via stderr and exit code."""

    def boom(*_args, **_kwargs):
        raise runner.CommandError(
            ["bash", "install_sugarkube_image.sh"],
            returncode=1,
            stderr="boom",
        )

    monkeypatch.setattr(runner, "run_commands", boom)

    exit_code = cli.main(["pi", "install", "--dry-run"])

    captured = capsys.readouterr()

    assert exit_code == 1
    assert "boom" in captured.err


def test_pi_install_drops_script_separator(monkeypatch: pytest.MonkeyPatch) -> None:
    """A leading `--` should be stripped before forwarding install args."""

    recorded: list[list[str]] = []

    def fake_run(
        commands: list[list[str]], *, dry_run: bool = False, env: Mapping[str, str] | None = None
    ) -> None:
        recorded.extend(commands)

    monkeypatch.setattr(runner, "run_commands", fake_run)

    exit_code = cli.main(["pi", "install", "--dry-run", "--", "--dir", "~/sugarkube/images"])

    assert exit_code == 0
    assert recorded == [
        [
            "bash",
            str(Path(__file__).resolve().parents[1] / "scripts" / "install_sugarkube_image.sh"),
            "--dir",
            "~/sugarkube/images",
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


def test_pi_report_invokes_helper(monkeypatch: pytest.MonkeyPatch) -> None:
    """pi report should wrap the flash report helper script."""

    recorded: list[list[str]] = []

    def fake_run(
        commands: list[list[str]], *, dry_run: bool = False, env: Mapping[str, str] | None = None
    ) -> None:
        recorded.extend(commands)

    monkeypatch.setattr(runner, "run_commands", fake_run)

    exit_code = cli.main(["pi", "report", "--dry-run"])

    expected_script = Path(__file__).resolve().parents[1] / "scripts" / "flash_pi_media_report.py"

    assert exit_code == 0
    assert recorded == [[sys.executable, str(expected_script)]]


def test_pi_report_forwards_additional_args(monkeypatch: pytest.MonkeyPatch) -> None:
    """Forward CLI arguments to the report helper for docs parity."""

    recorded: list[list[str]] = []

    def fake_run(
        commands: list[list[str]], *, dry_run: bool = False, env: Mapping[str, str] | None = None
    ) -> None:
        recorded.extend(commands)

    monkeypatch.setattr(runner, "run_commands", fake_run)

    exit_code = cli.main(
        [
            "pi",
            "report",
            "--dry-run",
            "--image",
            "~/sugarkube/images/sugarkube.img.xz",
            "--device",
            "/dev/sdX",
        ]
    )

    assert exit_code == 0
    assert recorded == [
        [
            sys.executable,
            str(Path(__file__).resolve().parents[1] / "scripts" / "flash_pi_media_report.py"),
            "--image",
            "~/sugarkube/images/sugarkube.img.xz",
            "--device",
            "/dev/sdX",
        ]
    ]


def test_pi_report_reports_missing_script(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Missing report helper scripts should surface an actionable error."""

    monkeypatch.setattr(
        cli, "FLASH_PI_MEDIA_REPORT_SCRIPT", Path("/nonexistent/flash_pi_media_report.py")
    )

    exit_code = cli.main(["pi", "report", "--dry-run"])

    captured = capsys.readouterr()

    assert exit_code == 1
    assert "scripts/flash_pi_media_report.py is missing" in captured.err


def test_pi_report_surfaces_failures(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Report handler should surface helper failures via stderr and exit code."""

    def boom(*_args, **_kwargs):
        raise runner.CommandError(
            [sys.executable, "flash_pi_media_report.py"],
            returncode=1,
            stderr="boom",
        )

    monkeypatch.setattr(runner, "run_commands", boom)

    exit_code = cli.main(["pi", "report", "--dry-run"])

    captured = capsys.readouterr()

    assert exit_code == 1
    assert "boom" in captured.err


def test_pi_report_drops_script_separator(monkeypatch: pytest.MonkeyPatch) -> None:
    """A leading `--` should be stripped before forwarding report args."""

    recorded: list[list[str]] = []

    def fake_run(
        commands: list[list[str]], *, dry_run: bool = False, env: Mapping[str, str] | None = None
    ) -> None:
        recorded.extend(commands)

    monkeypatch.setattr(runner, "run_commands", fake_run)

    exit_code = cli.main(["pi", "report", "--dry-run", "--", "--list-devices"])

    assert exit_code == 0
    assert recorded == [
        [
            sys.executable,
            str(Path(__file__).resolve().parents[1] / "scripts" / "flash_pi_media_report.py"),
            "--list-devices",
        ]
    ]


def test_pi_smoke_invokes_helper(monkeypatch: pytest.MonkeyPatch) -> None:
    """pi smoke should wrap the smoke test helper script."""

    recorded: list[list[str]] = []

    def fake_run(
        commands: list[list[str]], *, dry_run: bool = False, env: Mapping[str, str] | None = None
    ) -> None:
        recorded.extend(commands)

    monkeypatch.setattr(runner, "run_commands", fake_run)

    exit_code = cli.main(["pi", "smoke", "--dry-run"])

    expected_script = Path(__file__).resolve().parents[1] / "scripts" / "pi_smoke_test.py"

    assert exit_code == 0
    assert recorded == [[sys.executable, str(expected_script)]]


def test_pi_smoke_forwards_additional_args(monkeypatch: pytest.MonkeyPatch) -> None:
    """Forward CLI arguments to the smoke helper for docs parity."""

    recorded: list[list[str]] = []

    def fake_run(
        commands: list[list[str]], *, dry_run: bool = False, env: Mapping[str, str] | None = None
    ) -> None:
        recorded.extend(commands)

    monkeypatch.setattr(runner, "run_commands", fake_run)

    exit_code = cli.main(
        [
            "pi",
            "smoke",
            "--dry-run",
            "--json",
            "pi-a.local",
            "pi-b.local",
        ]
    )

    assert exit_code == 0
    assert recorded == [
        [
            sys.executable,
            str(Path(__file__).resolve().parents[1] / "scripts" / "pi_smoke_test.py"),
            "--json",
            "pi-a.local",
            "pi-b.local",
        ]
    ]


def test_pi_smoke_reports_missing_script(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Missing smoke helper script should surface an actionable error."""

    monkeypatch.setattr(cli, "PI_SMOKE_TEST_SCRIPT", Path("/nonexistent/pi_smoke_test.py"))

    exit_code = cli.main(["pi", "smoke", "--dry-run"])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "scripts/pi_smoke_test.py is missing" in captured.err


def test_pi_smoke_surfaces_failures(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Smoke handler should surface helper failures via stderr and exit code."""

    def boom(*_args, **_kwargs):
        raise runner.CommandError([sys.executable, "pi_smoke_test.py"], returncode=1, stderr="boom")

    monkeypatch.setattr(runner, "run_commands", boom)

    exit_code = cli.main(["pi", "smoke", "--dry-run"])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "boom" in captured.err


def test_pi_smoke_drops_script_separator(monkeypatch: pytest.MonkeyPatch) -> None:
    """A leading `--` should be stripped before forwarding smoke args."""

    recorded: list[list[str]] = []

    def fake_run(
        commands: list[list[str]], *, dry_run: bool = False, env: Mapping[str, str] | None = None
    ) -> None:
        recorded.extend(commands)

    monkeypatch.setattr(runner, "run_commands", fake_run)

    exit_code = cli.main(["pi", "smoke", "--dry-run", "--", "--json"])

    assert exit_code == 0
    assert recorded == [
        [
            sys.executable,
            str(Path(__file__).resolve().parents[1] / "scripts" / "pi_smoke_test.py"),
            "--json",
        ]
    ]


def test_pi_rehearse_invokes_helper(monkeypatch: pytest.MonkeyPatch) -> None:
    """pi rehearse should wrap the multi-node rehearsal helper script."""

    recorded: list[list[str]] = []

    def fake_run(
        commands: list[list[str]], *, dry_run: bool = False, env: Mapping[str, str] | None = None
    ) -> None:
        recorded.extend(commands)

    monkeypatch.setattr(runner, "run_commands", fake_run)

    exit_code = cli.main(["pi", "rehearse", "--dry-run"])

    expected_script = (
        Path(__file__).resolve().parents[1] / "scripts" / "pi_multi_node_join_rehearsal.py"
    )

    assert exit_code == 0
    assert recorded == [[sys.executable, str(expected_script)]]


def test_pi_rehearse_forwards_additional_args(monkeypatch: pytest.MonkeyPatch) -> None:
    """Forward CLI arguments to the rehearsal helper for docs parity."""

    recorded: list[list[str]] = []

    def fake_run(
        commands: list[list[str]], *, dry_run: bool = False, env: Mapping[str, str] | None = None
    ) -> None:
        recorded.extend(commands)

    monkeypatch.setattr(runner, "run_commands", fake_run)

    exit_code = cli.main(
        [
            "pi",
            "rehearse",
            "--dry-run",
            "--server-url",
            "https://controller.sugarkube.lan:6443",
            "sugar-control.local",
            "--agents",
            "pi-a.local",
            "pi-b.local",
        ]
    )

    assert exit_code == 0
    assert recorded == [
        [
            sys.executable,
            str(
                Path(__file__).resolve().parents[1] / "scripts" / "pi_multi_node_join_rehearsal.py"
            ),
            "--server-url",
            "https://controller.sugarkube.lan:6443",
            "sugar-control.local",
            "--agents",
            "pi-a.local",
            "pi-b.local",
        ]
    ]


def test_pi_rehearse_reports_missing_script(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Missing rehearsal helper scripts should surface an actionable error."""

    monkeypatch.setattr(
        cli, "PI_JOIN_REHEARSAL_SCRIPT", Path("/nonexistent/pi_multi_node_join_rehearsal.py")
    )

    exit_code = cli.main(["pi", "rehearse", "--dry-run"])

    captured = capsys.readouterr()

    assert exit_code == 1
    assert "scripts/pi_multi_node_join_rehearsal.py is missing" in captured.err


def test_pi_rehearse_surfaces_failures(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Rehearsal handler should surface helper failures via stderr and exit code."""

    def boom(*_args, **_kwargs):
        raise runner.CommandError(
            [sys.executable, "pi_multi_node_join_rehearsal.py"],
            returncode=1,
            stderr="boom",
        )

    monkeypatch.setattr(runner, "run_commands", boom)

    exit_code = cli.main(["pi", "rehearse", "--dry-run"])

    captured = capsys.readouterr()

    assert exit_code == 1
    assert "boom" in captured.err


def test_pi_rehearse_drops_script_separator(monkeypatch: pytest.MonkeyPatch) -> None:
    """A leading `--` should be stripped before forwarding rehearsal args."""

    recorded: list[list[str]] = []

    def fake_run(
        commands: list[list[str]], *, dry_run: bool = False, env: Mapping[str, str] | None = None
    ) -> None:
        recorded.extend(commands)

    monkeypatch.setattr(runner, "run_commands", fake_run)

    exit_code = cli.main(["pi", "rehearse", "--dry-run", "--", "--json"])

    assert exit_code == 0
    assert recorded == [
        [
            sys.executable,
            str(
                Path(__file__).resolve().parents[1] / "scripts" / "pi_multi_node_join_rehearsal.py"
            ),
            "--json",
        ]
    ]
