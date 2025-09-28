#!/usr/bin/env python3
"""Flash Raspberry Pi media and emit Markdown/HTML reports."""

from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import difflib
import hashlib
import html
import io
import json
import lzma
import os
import platform
import re
import sys
import tempfile
import textwrap
import time
from pathlib import Path
from typing import Iterable, Sequence, Tuple

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

CHUNK_SIZE = 4 * 1024 * 1024
DEFAULT_REPORT_DIR = Path.home() / "sugarkube" / "reports"
DEFAULT_BASE_CLOUD_INIT = SCRIPT_DIR / "cloud-init" / "user-data.yaml"

import flash_pi_media as flash  # noqa: E402


class FlashReportError(Exception):
    """Raised when the flash and report workflow cannot complete."""


def _format_bytes(size: int) -> str:
    for unit in ["B", "KiB", "MiB", "GiB", "TiB"]:
        if size < 1024 or unit == "TiB":
            return f"{size:.2f} {unit}" if unit != "B" else f"{size} {unit}"
        size /= 1024
    return f"{size:.2f} PiB"


def _sha256_file(path: Path) -> str:
    sha = hashlib.sha256()
    with path.open("rb") as src:
        for chunk in iter(lambda: src.read(CHUNK_SIZE), b""):
            sha.update(chunk)
    return sha.hexdigest()


def _expand_image(
    image_path: Path,
) -> Tuple[Path, bool, int, float, str, tempfile.TemporaryDirectory[str] | None]:
    start = time.time()
    if image_path.suffix != ".xz":
        size = image_path.stat().st_size
        digest = _sha256_file(image_path)
        return image_path, False, size, time.time() - start, digest, None

    tempdir = tempfile.TemporaryDirectory(prefix="sugarkube-flash-")
    expanded = Path(tempdir.name) / image_path.stem
    sha = hashlib.sha256()
    total = 0
    with lzma.open(image_path, "rb") as src, expanded.open("wb") as dest:
        while True:
            chunk = src.read(CHUNK_SIZE)
            if not chunk:
                break
            dest.write(chunk)
            sha.update(chunk)
            total += len(chunk)
    duration = time.time() - start
    digest = sha.hexdigest()
    return expanded, True, total, duration, digest, tempdir


def _select_device(args: argparse.Namespace, devices: Sequence[flash.Device]) -> flash.Device:
    if args.device:
        for dev in devices:
            if dev.path == args.device:
                return dev
        size_hint = args.bytes if args.bytes else 0
        return flash.Device(
            path=args.device,
            description="(custom device)",
            size=size_hint,
            is_removable=True,
        )

    flash.summarize_devices(devices)
    if not devices:
        raise FlashReportError(
            "No removable devices detected. Attach media or pass --device explicitly."
        )

    selection = input("Enter the device number to flash: ").strip()
    try:
        index = int(selection) - 1
    except ValueError as exc:  # pragma: no cover - interactive guard
        raise FlashReportError("Expected a numeric selection.") from exc
    if index < 0 or index >= len(devices):
        raise FlashReportError("Selection out of range.")
    return devices[index]


def _ensure_device_ready(device: flash.Device, *, keep_mounted: bool, dry_run: bool) -> None:
    if not dry_run and not flash._device_exists(device.path):  # type: ignore[attr-defined]
        raise FlashReportError(f"Device not found: {device.path}")
    if not dry_run:
        flash._check_not_root_device(device.path)  # type: ignore[attr-defined]
    if device.mountpoints and not keep_mounted and not dry_run:
        mounts = ", ".join(device.mountpoints)
        raise FlashReportError(
            f"{device.path} has mounted partitions ({mounts}). Unmount them or pass --keep-mounted."
        )


def _run_flash(
    expanded_path: Path, args: argparse.Namespace, device: flash.Device
) -> tuple[str, str, str, str]:
    argv = [
        "--image",
        str(expanded_path),
        "--device",
        device.path,
        "--assume-yes",
    ]
    if args.no_eject:
        argv.append("--no-eject")
    if args.keep_mounted:
        argv.append("--keep-mounted")
    if args.dry_run:
        argv.append("--dry-run")
    if not device.path:
        raise FlashReportError("Device path is required for flashing.")
    stdout_buffer = io.StringIO()
    stderr_buffer = io.StringIO()
    exit_code = 0
    with contextlib.redirect_stdout(stdout_buffer), contextlib.redirect_stderr(stderr_buffer):
        try:
            exit_code = flash.main(argv)
        except SystemExit as exc:  # pragma: no cover - propagate CLI exits
            exit_code = exc.code if isinstance(exc.code, int) else 1
    stdout = stdout_buffer.getvalue()
    stderr = stderr_buffer.getvalue()
    if exit_code:
        message = textwrap.dedent(
            f"""
            Flash helper failed (exit code {exit_code}).
            STDOUT:
            {stdout}
            STDERR:
            {stderr}
            """
        ).strip()
        raise FlashReportError(message)
    expected = _extract_hash(stdout, r"Expected SHA-256 for written bytes: (\w+)")
    verified = _extract_hash(stdout, r"Verified device SHA-256: (\w+)")
    return stdout, stderr, expected, verified


def _extract_hash(payload: str, pattern: str) -> str:
    match = re.search(pattern, payload)
    return match.group(1) if match else ""


def _cloud_init_diff(args: argparse.Namespace) -> tuple[str, str]:
    if not args.cloud_init:
        return "No cloud-init override supplied; nothing to diff.", ""
    override = Path(args.cloud_init).expanduser().resolve()
    if not override.exists():
        return f"Cloud-init override not found: {override}", ""

    base_path = (
        Path(args.base_cloud_init).expanduser().resolve()
        if args.base_cloud_init
        else DEFAULT_BASE_CLOUD_INIT.resolve()
    )
    base_lines: Iterable[str]
    base_label: str
    if base_path.exists():
        base_lines = base_path.read_text().splitlines()
        base_label = str(base_path)
    else:
        base_lines = []
        base_label = "(empty baseline)"

    override_lines = override.read_text().splitlines()
    diff_lines = list(
        difflib.unified_diff(
            list(base_lines),
            override_lines,
            fromfile=base_label,
            tofile=str(override),
            lineterm="",
        )
    )
    if not diff_lines:
        return "Cloud-init override matches the baseline.", ""
    diff_text = "\n".join(diff_lines)
    return "See diff below.", diff_text


def _build_markdown(metadata: dict) -> str:
    diff_intro = metadata["cloud_init"]["summary"]
    diff_block = metadata["cloud_init"].get("diff")
    log_output = metadata["flash_log"]
    stderr_output = metadata["flash_stderr"]
    diff_section = ""
    if diff_block:
        diff_section = f"````diff\n{diff_block}\n````"
    summary_lines = "\n".join(
        [
            f"- **Timestamp:** {metadata['timestamp']}",
            f"- **Host:** {metadata['host']}",
            f"- **Image:** `{metadata['image']['source']}`",
            f"- **Expanded Image:** `{metadata['image']['expanded']}`",
            f"- **Expanded Size:** {_format_bytes(metadata['image']['bytes'])}",
            f"- **Expanded SHA-256:** `{metadata['image']['sha256']}`",
            f"- **Expand Duration:** {metadata['image']['expanded_duration']:.1f}s",
            f"- **Flash Duration:** {metadata['flash_duration']:.1f}s",
            f"- **Report Directory:** `{metadata['report_dir']}`",
        ]
    )
    md = textwrap.dedent(
        f"""
        # Sugarkube Flash Report

        {summary_lines}

        ## Device

        | Field | Value |
        | --- | --- |
        | Path | `{metadata['device']['path']}` |
        | Description | {metadata['device']['description']} |
        | Size | {_format_bytes(metadata['device']['size'])} |
        | Bus | {metadata['device'].get('bus', 'n/a')} |
        | System ID | {metadata['device'].get('system_id', 'n/a')} |

        ## Verification

        - Expected SHA-256: `{metadata['verification']['expected']}`
        - Verified SHA-256: `{metadata['verification']['verified']}`

        ## Cloud-init

        {diff_intro}

        {diff_section}

        ## Flash Logs

        ```
        {log_output.strip()}
        ```
        ```
        {stderr_output.strip() or 'No stderr output.'}
        ```
        """
    ).strip()
    return md


def _build_html(metadata: dict, markdown_body: str) -> str:
    diff_block = metadata["cloud_init"].get("diff")
    diff_html = ""
    if diff_block:
        diff_html = f"<pre><code>{html.escape(diff_block)}</code></pre>"
    device_rows = "".join(
        f"<tr><th>{html.escape(key)}</th><td>{html.escape(value)}</td></tr>"
        for key, value in [
            ("Path", metadata["device"]["path"]),
            ("Description", metadata["device"]["description"]),
            ("Size", _format_bytes(metadata["device"]["size"])),
            ("Bus", metadata["device"].get("bus", "n/a") or "n/a"),
            ("System ID", metadata["device"].get("system_id", "n/a") or "n/a"),
        ]
    )
    verification_html = "".join(
        f"<li><code>{html.escape(label)}</code>: <code>{html.escape(value)}</code></li>"
        for label, value in [
            ("Expected SHA-256", metadata["verification"]["expected"]),
            ("Verified SHA-256", metadata["verification"]["verified"]),
        ]
    )
    escaped_stdout = html.escape(metadata["flash_log"].strip())
    escaped_stderr = html.escape(metadata["flash_stderr"].strip() or "No stderr output.")
    escaped_timestamp = html.escape(metadata["timestamp"])
    escaped_host = html.escape(metadata["host"])
    escaped_image_source = html.escape(metadata["image"]["source"])
    escaped_expanded_image = html.escape(metadata["image"]["expanded"])
    escaped_image_sha = html.escape(metadata["image"]["sha256"])
    escaped_report_dir = html.escape(metadata["report_dir"])
    cloud_summary = html.escape(metadata["cloud_init"]["summary"])
    return textwrap.dedent(
        f"""
        <!DOCTYPE html>
        <html lang="en">
        <head>
          <meta charset="utf-8" />
          <title>Sugarkube Flash Report</title>
          <style>
            body {{ font-family: system-ui, sans-serif; margin: 2rem; line-height: 1.5; }}
            table {{ border-collapse: collapse; width: 100%; max-width: 40rem; }}
            th, td {{ border: 1px solid #ccc; padding: 0.5rem; text-align: left; }}
            pre {{ background: #f5f5f5; padding: 1rem; overflow-x: auto; }}
            code {{
              font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas,
                           'Liberation Mono', 'Courier New', monospace;
            }}
          </style>
        </head>
        <body>
          <h1>Sugarkube Flash Report</h1>
          <p><strong>Timestamp:</strong> {escaped_timestamp}<br />
          <strong>Host:</strong> {escaped_host}<br />
          <strong>Image:</strong> <code>{escaped_image_source}</code><br />
          <strong>Expanded Image:</strong>
          <code>{escaped_expanded_image}</code><br />
          <strong>Expanded Size:</strong> {_format_bytes(metadata['image']['bytes'])}<br />
          <strong>Expanded SHA-256:</strong>
          <code>{escaped_image_sha}</code><br />
          <strong>Expand Duration:</strong> {metadata['image']['expanded_duration']:.1f}s<br />
          <strong>Flash Duration:</strong> {metadata['flash_duration']:.1f}s<br />
          <strong>Report Directory:</strong> <code>{escaped_report_dir}</code></p>
          <h2>Device</h2>
          <table>
            {device_rows}
          </table>
          <h2>Verification</h2>
          <ul>
            {verification_html}
          </ul>
          <h2>Cloud-init</h2>
          <p>{cloud_summary}</p>
          {diff_html}
          <h2>Flash Logs</h2>
          <h3>stdout</h3>
          <pre><code>{escaped_stdout}</code></pre>
          <h3>stderr</h3>
          <pre><code>{escaped_stderr}</code></pre>
        </body>
        </html>
        """
    ).strip()


def _write_report(metadata: dict, report_dir: Path) -> None:
    report_dir.mkdir(parents=True, exist_ok=True)
    markdown_body = _build_markdown(metadata)
    html_body = _build_html(metadata, markdown_body)
    (report_dir / "flash-report.md").write_text(markdown_body)
    (report_dir / "flash-report.html").write_text(html_body)
    (report_dir / "flash-report.json").write_text(json.dumps(metadata, indent=2))
    (report_dir / "flash.log").write_text(metadata["flash_log"])
    (report_dir / "flash.stderr").write_text(metadata["flash_stderr"])


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", help="Path to the compressed or expanded image.")
    parser.add_argument("--device", help="Device path to flash (e.g. /dev/sdX).")
    parser.add_argument(
        "--assume-yes",
        action="store_true",
        help="Skip confirmation prompts. Requires --device for non-interactive runs.",
    )
    parser.add_argument(
        "--no-eject", action="store_true", help="Skip auto-eject/offline after flashing."
    )
    parser.add_argument(
        "--keep-mounted",
        action="store_true",
        help="Allow flashing even when partitions remain mounted.",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Validate inputs without writing the device."
    )
    parser.add_argument(
        "--cloud-init",
        help="Optional path to a cloud-init override to diff against the baseline.",
    )
    parser.add_argument(
        "--base-cloud-init",
        help=(
            "Path to the baseline cloud-init file "
            "(defaults to scripts/cloud-init/user-data.yaml)."
        ),
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_REPORT_DIR,
        help="Directory where reports will be stored (defaults to ~/sugarkube/reports).",
    )
    parser.add_argument(
        "--keep-expanded",
        action="store_true",
        help="Keep the expanded .img when flashing from .xz archives.",
    )
    parser.add_argument(
        "--list-devices", action="store_true", help="List removable devices and exit."
    )
    parser.add_argument("--bytes", type=int, default=0, help=argparse.SUPPRESS)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    devices = flash.filter_candidates(flash.discover_devices())

    if args.list_devices:
        flash.summarize_devices(devices)
        return 0

    if not args.image:
        raise FlashReportError(
            "Provide --image pointing to the sugarkube release (sugarkube.img or .img.xz)."
        )

    source_image = Path(args.image).expanduser().resolve()
    if not source_image.exists():
        raise FlashReportError(f"Image not found: {source_image}")

    # Regression coverage:
    # tests/flash_pi_media_report_test.py::test_list_devices_without_image_exits_cleanly
    device = _select_device(args, devices)
    _ensure_device_ready(device, keep_mounted=args.keep_mounted, dry_run=args.dry_run)

    if not args.assume_yes:
        reply = (
            input(f"About to expand {source_image.name} and flash {device.path}. Continue? [y/N]: ")
            .strip()
            .lower()
        )
        if reply not in {"y", "yes"}:
            print("Aborted by user.")
            return 0

    expanded_path, was_compressed, expanded_bytes, expand_duration, expanded_sha, tempdir = (
        _expand_image(source_image)
    )

    report_dir = args.output_dir.expanduser().resolve()
    now = dt.datetime.now(dt.timezone.utc).astimezone()
    timestamp = now.isoformat()
    slug = device.path.replace("/", "-").replace("\\", "-").strip("-") or "device"
    report_path = report_dir / f"flash-{now.strftime('%Y%m%d-%H%M%S')}-{slug}"

    try:
        flash_start = time.time()
        stdout, stderr, expected_hash, verified_hash = _run_flash(expanded_path, args, device)
        flash_duration = time.time() - flash_start
    finally:
        if tempdir and not args.keep_expanded:
            tempdir.cleanup()

    report_path.mkdir(parents=True, exist_ok=True)

    if args.keep_expanded and was_compressed:
        destination = report_path / expanded_path.name
        if destination.exists():
            destination.unlink()
        os.replace(expanded_path, destination)
        expanded_display = str(destination)
        if tempdir:
            tempdir.cleanup()
            tempdir = None
    else:
        expanded_display = str(expanded_path)
        if was_compressed and not args.keep_expanded:
            expanded_display += " (removed after flash)"

    cloud_summary, cloud_diff = _cloud_init_diff(args)

    metadata = {
        "timestamp": timestamp,
        "host": f"{platform.node()} ({platform.system()} {platform.release()})",
        "report_dir": str(report_path),
        "image": {
            "source": str(source_image),
            "expanded": expanded_display,
            "bytes": expanded_bytes,
            "sha256": expanded_sha,
            "expanded_duration": expand_duration,
        },
        "device": {
            "path": device.path,
            "description": device.description or "(unknown)",
            "size": device.size,
            "bus": device.bus,
            "system_id": device.system_id,
        },
        "flash_duration": flash_duration,
        "verification": {
            "expected": expected_hash,
            "verified": verified_hash,
        },
        "cloud_init": {
            "summary": cloud_summary,
        },
        "flash_log": stdout,
        "flash_stderr": stderr,
    }
    if cloud_diff:
        metadata["cloud_init"]["diff"] = cloud_diff

    _write_report(metadata, report_path)
    print(f"Flash report written to {report_path}")
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entrypoint
    try:
        raise SystemExit(main())
    except FlashReportError as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1)
