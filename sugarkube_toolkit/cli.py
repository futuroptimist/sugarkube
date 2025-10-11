"""Entry points for the sugarkube CLI."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Sequence

from . import runner

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO_ROOT / "scripts"
CHECKS_SCRIPT = SCRIPTS_DIR / "checks.sh"
SUGARKUBE_DOCTOR_SCRIPT = SCRIPTS_DIR / "sugarkube_doctor.sh"
DOWNLOAD_PI_IMAGE_SCRIPT = SCRIPTS_DIR / "download_pi_image.sh"
INSTALL_PI_IMAGE_SCRIPT = SCRIPTS_DIR / "install_sugarkube_image.sh"
FLASH_PI_MEDIA_SCRIPT = SCRIPTS_DIR / "flash_pi_media.sh"
FLASH_PI_MEDIA_REPORT_SCRIPT = SCRIPTS_DIR / "flash_pi_media_report.py"
PI_SMOKE_TEST_SCRIPT = SCRIPTS_DIR / "pi_smoke_test.py"
PI_JOIN_REHEARSAL_SCRIPT = SCRIPTS_DIR / "pi_multi_node_join_rehearsal.py"
CLUSTER_BOOTSTRAP_SCRIPT = SCRIPTS_DIR / "pi_cluster_bootstrap.py"
COLLECT_SUPPORT_BUNDLE_SCRIPT = SCRIPTS_DIR / "collect_support_bundle.py"
START_HERE_DOC = REPO_ROOT / "docs" / "start-here.md"

DOC_VERIFY_COMMANDS: list[list[str]] = [
    ["pyspelling", "-c", ".spellcheck.yaml"],
    ["linkchecker", "--no-warnings", "README.md", "docs/"],
]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sugarkube",
        description="Unified helpers for Sugarkube automation workflows.",
    )
    parser.set_defaults(handler=None)

    subparsers = parser.add_subparsers(dest="section")

    doctor_parser = subparsers.add_parser(
        "doctor",
        help="Run the sugarkube doctor workflow end-to-end.",
    )
    doctor_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the helper invocation without executing it.",
    )
    doctor_parser.set_defaults(handler=_handle_doctor)

    docs_parser = subparsers.add_parser(
        "docs",
        help="Documentation workflows (spellcheck, link validation, and more).",
    )
    docs_subparsers = docs_parser.add_subparsers(dest="command")

    verify_parser = docs_subparsers.add_parser(
        "verify", help="Run pyspelling and linkchecker like the docs describe."
    )
    verify_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the commands without executing them.",
    )
    verify_parser.set_defaults(handler=_handle_docs_verify)

    simplify_parser = docs_subparsers.add_parser(
        "simplify",
        help="Install docs prerequisites and run scripts/checks.sh --docs-only.",
    )
    simplify_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the helper invocation without executing it.",
    )
    simplify_parser.set_defaults(handler=_handle_docs_simplify)

    start_here_parser = docs_subparsers.add_parser(
        "start-here",
        help="Print the Start Here handbook path or contents without leaving the CLI.",
    )
    start_here_parser.add_argument(
        "--path-only",
        action="store_true",
        help="Emit only the absolute path to docs/start-here.md.",
    )
    start_here_parser.add_argument(
        "--no-content",
        action="store_true",
        help="Deprecated alias for --path-only maintained for legacy wrappers.",
    )
    start_here_parser.set_defaults(handler=_handle_docs_start_here)

    pi_parser = subparsers.add_parser(
        "pi",
        help="Raspberry Pi image workflows (download, flashing, and validation).",
    )
    pi_subparsers = pi_parser.add_subparsers(dest="command")

    download_parser = pi_subparsers.add_parser(
        "download",
        help="Download the latest Sugarkube image via scripts/download_pi_image.sh.",
    )
    download_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the helper invocation without executing it.",
    )
    download_parser.set_defaults(handler=_handle_pi_download)

    install_parser = pi_subparsers.add_parser(
        "install",
        help="Install the Sugarkube image via scripts/install_sugarkube_image.sh.",
    )
    install_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the helper invocation without executing it.",
    )
    install_parser.set_defaults(handler=_handle_pi_install)

    flash_parser = pi_subparsers.add_parser(
        "flash",
        help="Flash the Sugarkube image via scripts/flash_pi_media.sh.",
    )
    flash_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the flashing helper invocation without executing it.",
    )
    flash_parser.set_defaults(handler=_handle_pi_flash)

    report_parser = pi_subparsers.add_parser(
        "report",
        help="Generate flash reports via scripts/flash_pi_media_report.py.",
    )
    report_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the report helper invocation without executing it.",
    )
    report_parser.set_defaults(handler=_handle_pi_report)

    smoke_parser = pi_subparsers.add_parser(
        "smoke",
        help="Exercise the Pi smoke test harness via scripts/pi_smoke_test.py.",
    )
    smoke_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the smoke test invocation without executing it.",
    )
    smoke_parser.set_defaults(handler=_handle_pi_smoke)

    rehearse_parser = pi_subparsers.add_parser(
        "rehearse",
        help="Rehearse multi-node joins via scripts/pi_multi_node_join_rehearsal.py.",
    )
    rehearse_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the rehearsal helper invocation without executing it.",
    )
    rehearse_parser.set_defaults(handler=_handle_pi_rehearse)

    support_bundle_parser = pi_subparsers.add_parser(
        "support-bundle",
        help="Collect diagnostics via scripts/collect_support_bundle.py.",
    )
    support_bundle_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the support bundle helper invocation without executing it.",
    )
    support_bundle_parser.set_defaults(handler=_handle_pi_support_bundle)

    cluster_parser = pi_subparsers.add_parser(
        "cluster",
        help="Bootstrap multi-node clusters via scripts/pi_cluster_bootstrap.py.",
    )
    cluster_parser.add_argument(
        "--config",
        required=True,
        help="Path to the cluster configuration TOML file.",
    )
    cluster_parser.add_argument(
        "--skip-download",
        action="store_true",
        help="Skip downloading the pi-image artifact before flashing media.",
    )
    cluster_parser.add_argument(
        "--skip-join",
        action="store_true",
        help="Skip running the join rehearsal/apply stage after flashing.",
    )
    cluster_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview the helper invocation without executing it.",
    )
    cluster_parser.set_defaults(handler=_handle_pi_cluster)

    return parser


def _handle_docs_verify(args: argparse.Namespace) -> int:
    try:
        runner.run_commands(DOC_VERIFY_COMMANDS, dry_run=args.dry_run, cwd=REPO_ROOT)
    except runner.CommandError as exc:
        print(exc, file=sys.stderr)
        return 1
    return 0


def _handle_docs_simplify(args: argparse.Namespace) -> int:
    script = CHECKS_SCRIPT
    if not script.exists():
        print(
            "scripts/checks.sh is missing. Run from the repository root or reinstall the tooling.",
            file=sys.stderr,
        )
        return 1

    command = [
        "bash",
        str(script),
        "--docs-only",
        *_normalize_script_args(getattr(args, "script_args", [])),
    ]
    try:
        runner.run_commands([command], dry_run=args.dry_run, cwd=REPO_ROOT)
    except runner.CommandError as exc:
        print(exc, file=sys.stderr)
        return 1
    return 0


def _handle_doctor(args: argparse.Namespace) -> int:
    script = SUGARKUBE_DOCTOR_SCRIPT
    if not script.exists():
        print(
            "scripts/sugarkube_doctor.sh is missing. "
            "Run from the repository root or reinstall the tooling.",
            file=sys.stderr,
        )
        return 1

    command = ["bash", str(script), *_normalize_script_args(getattr(args, "script_args", []))]
    try:
        runner.run_commands([command], dry_run=args.dry_run, cwd=REPO_ROOT)
    except runner.CommandError as exc:
        print(exc, file=sys.stderr)
        return 1
    return 0


def _handle_docs_start_here(args: argparse.Namespace) -> int:
    if not START_HERE_DOC.exists():
        print(
            "docs/start-here.md is missing; restore the handbook before continuing.",
            file=sys.stderr,
        )
        return 1

    if args.no_content:
        print(
            "WARNING: --no-content is deprecated; use --path-only instead.",
            file=sys.stderr,
        )

    if args.path_only or args.no_content:
        print(START_HERE_DOC)
        return 0

    print(f"Sugarkube Start Here guide: {START_HERE_DOC}")
    print()
    print(_strip_front_matter(START_HERE_DOC.read_text(encoding="utf-8")))
    return 0


def _normalize_script_args(args: Sequence[str]) -> list[str]:
    script_args = list(args)
    if script_args and script_args[0] == "--":
        return script_args[1:]
    return script_args


def _strip_front_matter(text: str) -> str:
    if text.startswith("\ufeff"):
        text = text[1:]

    if not text.lstrip().startswith("---"):
        return text

    lines = text.splitlines(keepends=True)
    if not lines or lines[0].strip() != "---":
        return text

    for idx, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            remainder_start = idx + 1
            return "".join(lines[remainder_start:])

    return text


def _forward_to_helper(
    *,
    script: Path,
    args: argparse.Namespace,
    interpreter: str,
    missing_hint: str,
    prefix: Sequence[str] | None = None,
    auto_dry_run: bool = True,
    always_execute: bool = False,
    strip_cli_dry_run: bool = False,
) -> int:
    if not script.exists():
        print(missing_hint, file=sys.stderr)
        return 1

    script_args = _normalize_script_args(getattr(args, "script_args", []))
    if strip_cli_dry_run and args.dry_run:
        script_args = [arg for arg in script_args if arg != "--dry-run"]

    combined_prefix = list(prefix or [])
    script_has_dry_run = "--dry-run" in script_args or "--dry-run" in combined_prefix

    if args.dry_run and auto_dry_run and not script_has_dry_run:
        combined_prefix.append("--dry-run")
        script_has_dry_run = True

    command = [interpreter, str(script), *combined_prefix, *script_args]

    dry_run = (
        False
        if always_execute
        else args.dry_run and (strip_cli_dry_run or not script_has_dry_run)
    )
    try:
        runner.run_commands([command], dry_run=dry_run, cwd=REPO_ROOT)
    except runner.CommandError as exc:
        print(exc, file=sys.stderr)
        return 1
    return 0


def _handle_pi_download(args: argparse.Namespace) -> int:
    return _forward_to_helper(
        script=DOWNLOAD_PI_IMAGE_SCRIPT,
        args=args,
        interpreter="bash",
        missing_hint=(
            "scripts/download_pi_image.sh is missing. "
            "Run from the repository root or reinstall the tooling."
        ),
        auto_dry_run=True,
        always_execute=False,
    )


def _handle_pi_install(args: argparse.Namespace) -> int:
    return _forward_to_helper(
        script=INSTALL_PI_IMAGE_SCRIPT,
        args=args,
        interpreter="bash",
        missing_hint=(
            "scripts/install_sugarkube_image.sh is missing. "
            "Run from the repository root or reinstall the tooling."
        ),
        auto_dry_run=True,
        always_execute=True,
    )


def _handle_pi_flash(args: argparse.Namespace) -> int:
    return _forward_to_helper(
        script=FLASH_PI_MEDIA_SCRIPT,
        args=args,
        interpreter="bash",
        missing_hint=(
            "scripts/flash_pi_media.sh is missing. "
            "Run from the repository root or reinstall the tooling."
        ),
        auto_dry_run=True,
        always_execute=False,
    )


def _handle_pi_report(args: argparse.Namespace) -> int:
    return _forward_to_helper(
        script=FLASH_PI_MEDIA_REPORT_SCRIPT,
        args=args,
        interpreter=sys.executable,
        missing_hint=(
            "scripts/flash_pi_media_report.py is missing. "
            "Run from the repository root or reinstall the tooling."
        ),
        auto_dry_run=True,
        always_execute=True,
    )


def _handle_pi_smoke(args: argparse.Namespace) -> int:
    return _forward_to_helper(
        script=PI_SMOKE_TEST_SCRIPT,
        args=args,
        interpreter=sys.executable,
        missing_hint=(
            "scripts/pi_smoke_test.py is missing. "
            "Run from the repository root or reinstall the tooling."
        ),
        auto_dry_run=False,
        always_execute=False,
    )


def _handle_pi_rehearse(args: argparse.Namespace) -> int:
    return _forward_to_helper(
        script=PI_JOIN_REHEARSAL_SCRIPT,
        args=args,
        interpreter=sys.executable,
        missing_hint=(
            "scripts/pi_multi_node_join_rehearsal.py is missing. "
            "Run from the repository root or reinstall the tooling."
        ),
        auto_dry_run=False,
        always_execute=False,
    )


def _handle_pi_support_bundle(args: argparse.Namespace) -> int:
    return _forward_to_helper(
        script=COLLECT_SUPPORT_BUNDLE_SCRIPT,
        args=args,
        interpreter=sys.executable,
        missing_hint=(
            "scripts/collect_support_bundle.py is missing. "
            "Run from the repository root or reinstall the tooling."
        ),
        auto_dry_run=True,
        always_execute=False,
        strip_cli_dry_run=True,
    )

def _handle_pi_cluster(args: argparse.Namespace) -> int:
    prefix: list[str] = []
    if args.config:
        prefix.extend(["--config", args.config])
    if args.skip_download:
        prefix.append("--skip-download")
    if args.skip_join:
        prefix.append("--skip-join")

    return _forward_to_helper(
        script=CLUSTER_BOOTSTRAP_SCRIPT,
        args=args,
        interpreter=sys.executable,
        missing_hint=(
            "scripts/pi_cluster_bootstrap.py is missing. "
            "Run from the repository root or reinstall the tooling."
        ),
        prefix=prefix,
        auto_dry_run=True,
        always_execute=True,
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    parsed_args = list(argv) if argv is not None else None
    args, extras = parser.parse_known_args(parsed_args)

    handler = getattr(args, "handler", None)
    if handler is None:
        parser.print_help()
        return 1

    if handler in {
        _handle_doctor,
        _handle_docs_simplify,
        _handle_pi_download,
        _handle_pi_install,
        _handle_pi_flash,
        _handle_pi_report,
        _handle_pi_smoke,
        _handle_pi_rehearse,
        _handle_pi_support_bundle,
        _handle_pi_cluster,
    }:
        combined = list(getattr(args, "script_args", []))
        if extras:
            combined.extend(extras)
        args.script_args = combined
    elif extras:
        parser.error("unrecognized arguments: " + " ".join(extras))

    return handler(args)
