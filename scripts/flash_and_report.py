#!/usr/bin/env python3
"""Flash sugarkube images and emit Markdown/HTML/JSON reports.

The wrapper builds on ``flash_pi_media.py`` and makes the flashing pipeline
self-documenting.  It expands compressed images, flashes the selected device,
verifies SHA-256 sums, records hardware attributes, and optionally compares the
cloud-init configuration that will apply on first boot.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import difflib
import hashlib
import html
import json
import os
import platform
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Dict, Optional, Sequence, Tuple

SCRIPT_DIR = Path(__file__).resolve().parent
FLASH_SCRIPT = SCRIPT_DIR / "flash_pi_media.py"

if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

try:  # pragma: no cover - import failure handled gracefully below
    import flash_pi_media
except Exception:  # pragma: no cover
    flash_pi_media = None

CHUNK_SIZE = 4 * 1024 * 1024


class FlashError(RuntimeError):
    """Raised when flashing fails."""


def _sha256_path(path: Path) -> Tuple[str, int]:
    hasher = hashlib.sha256()
    size = 0
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(CHUNK_SIZE)
            if not chunk:
                break
            hasher.update(chunk)
            size += len(chunk)
    return hasher.hexdigest(), size


def _decompress_image(image: Path, workdir: Path) -> Tuple[Path, Dict[str, object]]:
    metadata: Dict[str, object] = {
        "source_path": str(image),
    }
    source_hash, source_bytes = _sha256_path(image)
    metadata["source_sha256"] = source_hash
    metadata["source_bytes"] = source_bytes

    if image.suffix != ".xz":
        metadata["expanded_path"] = str(image)
        metadata["expanded_sha256"] = source_hash
        metadata["expanded_bytes"] = source_bytes
        return image, metadata

    import lzma

    expanded = workdir / image.stem
    hasher = hashlib.sha256()
    total = 0
    with lzma.open(image, "rb") as src, expanded.open("wb") as dest:
        while True:
            chunk = src.read(CHUNK_SIZE)
            if not chunk:
                break
            dest.write(chunk)
            hasher.update(chunk)
            total += len(chunk)
    metadata["expanded_path"] = str(expanded)
    metadata["expanded_sha256"] = hasher.hexdigest()
    metadata["expanded_bytes"] = total
    return expanded, metadata


def _hash_device(path: str, expected_bytes: int) -> Tuple[str, int]:
    hasher = hashlib.sha256()
    read_bytes = 0
    with open(path, "rb", buffering=0) as handle:
        while read_bytes < expected_bytes:
            chunk = handle.read(min(CHUNK_SIZE, expected_bytes - read_bytes))
            if not chunk:
                break
            hasher.update(chunk)
            read_bytes += len(chunk)
    if read_bytes != expected_bytes:
        raise FlashError(f"Device read returned {read_bytes} bytes, expected {expected_bytes}.")
    return hasher.hexdigest(), read_bytes


def _describe_device(path: str) -> Dict[str, object]:
    info: Dict[str, object] = {"path": path}
    try:
        stat = os.stat(path)
        info["mode"] = stat.st_mode
        info["size"] = getattr(stat, "st_size", 0)
    except FileNotFoundError:
        info["missing"] = True
        return info

    if flash_pi_media is None:
        return info

    try:
        devices = flash_pi_media.discover_devices()
    except Exception:  # pragma: no cover - discovery issues shouldn't abort reports
        return info

    for device in devices:
        if device.path == path:
            info.update(
                {
                    "description": device.description,
                    "is_removable": device.is_removable,
                    "human_size": getattr(device, "human_size", None),
                    "bus": device.bus,
                    "mountpoints": list(device.mountpoints or []),
                }
            )
            break
    return info


def _load_text(path: Optional[str]) -> Optional[str]:
    if not path:
        return None
    data_path = Path(path)
    if not data_path.exists():
        raise FlashError(f"cloud-init file not found: {path}")
    return data_path.read_text(encoding="utf-8")


def _compute_diff(expected: str, observed: str, expected_label: str, observed_label: str) -> str:
    return "\n".join(
        difflib.unified_diff(
            expected.splitlines(),
            observed.splitlines(),
            fromfile=expected_label,
            tofile=observed_label,
            lineterm="",
        )
    )


def _build_html(markdown_text: str) -> str:
    escaped = html.escape(markdown_text)
    style = (
        "body{font-family:monospace;background:#101418;color:#e7f5ff;padding:1.5rem;}"
        "pre{white-space:pre-wrap;word-break:break-word;}"
        "a{color:#9cdcfe;}"
    )
    return (
        "<!doctype html>\n"
        '<html lang="en">\n'
        "  <head>\n"
        '    <meta charset="utf-8">\n'
        "    <title>Sugarkube Flash Report</title>\n"
        f"    <style>{style}</style>\n"
        "  </head>\n"
        "  <body>\n"
        f"    <pre>{escaped}</pre>\n"
        "  </body>\n"
        "</html>\n"
    )


def _is_regular_file(path: str) -> bool:
    try:
        return Path(path).is_file()
    except OSError:
        return False


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", required=True, help="Path to the .img or .img.xz file")
    parser.add_argument("--device", required=True, help="Device path or regular file target")
    parser.add_argument(
        "--report-dir",
        default="./flash-reports",
        help="Directory to store Markdown, HTML, and JSON reports (default: ./flash-reports)",
    )
    parser.add_argument(
        "--cloud-init-expected",
        help="Optional preset or template to diff against the observed cloud-init payload",
    )
    parser.add_argument(
        "--cloud-init-observed",
        help="Optional cloud-init file that will be copied to the boot volume",
    )
    parser.add_argument(
        "--cloud-init-log",
        help="Optional cloud-init status log to embed in the report",
    )
    parser.add_argument(
        "--no-eject",
        action="store_true",
        help="Skip automatic eject/offline after flashing (passed through to flash_pi_media)",
    )
    parser.add_argument(
        "--skip-device-hash",
        action="store_true",
        help="Skip hashing the flashed device (useful for very large disks when time is critical)",
    )
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    image_path = Path(args.image).expanduser().resolve()
    if not image_path.exists():
        raise FlashError(f"Image not found: {image_path}")

    device_path = args.device
    report_dir = Path(args.report_dir).expanduser().resolve()
    report_dir.mkdir(parents=True, exist_ok=True)

    timestamp = _dt.datetime.now(_dt.UTC).strftime("%Y%m%d-%H%M%S")
    report_base = report_dir / f"flash-report-{timestamp}"

    with tempfile.TemporaryDirectory(prefix="sugarkube-flash-") as tmpdir:
        workdir = Path(tmpdir)
        expanded_path, image_meta = _decompress_image(image_path, workdir)

        if not FLASH_SCRIPT.exists():
            raise FlashError(f"flash script missing: {FLASH_SCRIPT}")

        should_hash = not args.skip_device_hash
        forced_no_eject = False

        cmd = [
            sys.executable,
            str(FLASH_SCRIPT),
            "--image",
            str(expanded_path),
            "--device",
            device_path,
            "--assume-yes",
        ]
        if should_hash and not args.no_eject:
            forced_no_eject = True

        if args.no_eject or forced_no_eject:
            cmd.append("--no-eject")
        if _is_regular_file(device_path):
            cmd.append("--keep-mounted")

        env = os.environ.copy()
        if _is_regular_file(device_path):
            env.setdefault("SUGARKUBE_FLASH_ALLOW_NONROOT", "1")

        result = subprocess.run(cmd, capture_output=True, text=True, env=env)
        if result.returncode != 0:
            raise FlashError(
                "flash_pi_media.py failed" f" (exit {result.returncode}): {result.stderr.strip()}"
            )

        device_meta = _describe_device(device_path)
        device_meta["bytes_expected"] = image_meta["expanded_bytes"]
        device_meta["command"] = cmd
        device_meta["forced_no_eject"] = forced_no_eject

        if args.skip_device_hash:
            device_meta["sha256"] = None
            device_meta["bytes_observed"] = None
            device_meta["verification"] = "skipped"
        else:
            digest, written = _hash_device(device_path, int(image_meta["expanded_bytes"]))
            device_meta["sha256"] = digest
            device_meta["bytes_observed"] = written
            device_meta["verification"] = (
                "match" if digest == image_meta["expanded_sha256"] else "mismatch"
            )
            if device_meta["verification"] != "match":
                raise FlashError("SHA-256 mismatch between expanded image and flashed media.")

        if forced_no_eject and not _is_regular_file(device_path):
            device_meta["post_hash_eject"] = "not_attempted"
            if flash_pi_media is not None and hasattr(flash_pi_media, "Device"):
                try:
                    eject_device = flash_pi_media.Device(
                        path=device_path,
                        description=str(device_meta.get("description") or device_path),
                        size=int(device_meta.get("size") or image_meta["expanded_bytes"]),
                        is_removable=bool(device_meta.get("is_removable", True)),
                        bus=device_meta.get("bus"),
                        system_id=device_meta.get("system_id"),
                        mountpoints=tuple(device_meta.get("mountpoints") or ()),
                    )
                    if hasattr(flash_pi_media, "_auto_eject"):
                        flash_pi_media._auto_eject(eject_device)
                        device_meta["post_hash_eject"] = "attempted"
                except Exception:
                    device_meta["post_hash_eject"] = "failed"

    expected_text = _load_text(args.cloud_init_expected)
    observed_text = _load_text(args.cloud_init_observed)
    log_text = _load_text(args.cloud_init_log)
    diff_text = None
    if expected_text and observed_text:
        diff_text = _compute_diff(
            expected_text,
            observed_text,
            args.cloud_init_expected,
            args.cloud_init_observed,
        )

    markdown_lines = [
        "# Sugarkube Flash Report",
        "",
        f"- Timestamp: {timestamp} UTC",
        f"- Host: {platform.node()} ({platform.platform()})",
        f"- Source image: {image_meta['source_path']}",
        f"- Expanded image: {image_meta['expanded_path']}",
        f"- Target device: {device_path}",
        "",
        "## Checksum summary",
        f"- Source SHA-256: {image_meta['source_sha256']}",
        f"- Expanded SHA-256: {image_meta['expanded_sha256']}",
    ]

    if not args.skip_device_hash:
        markdown_lines.append(f"- Device SHA-256: {device_meta['sha256']}")
    else:
        markdown_lines.append("- Device SHA-256: (skipped)")

    markdown_lines.extend(
        [
            "",
            "## Device details",
            json.dumps(device_meta, indent=2),
            "",
            "## Flash log",
            "```",
            result.stdout.strip(),
            "```",
        ]
    )

    if result.stderr.strip():
        markdown_lines.extend(["", "### stderr", "```", result.stderr.strip(), "```"])

    if diff_text:
        markdown_lines.extend(["", "## cloud-init diff", "```", diff_text, "```"])

    if log_text:
        markdown_lines.extend(["", "## cloud-init log", "```", log_text.strip(), "```"])

    markdown_content = "\n".join(markdown_lines) + "\n"
    html_content = _build_html(markdown_content)

    summary = {
        "timestamp": timestamp,
        "host": {
            "hostname": platform.node(),
            "platform": platform.platform(),
        },
        "image": image_meta,
        "device": device_meta,
        "cloud_init": {
            "expected": args.cloud_init_expected,
            "observed": args.cloud_init_observed,
            "diff": diff_text,
            "log": args.cloud_init_log,
        },
        "flash_log": {
            "stdout": result.stdout,
            "stderr": result.stderr,
        },
    }

    report_base_md = report_base.with_suffix(".md")
    report_base_html = report_base.with_suffix(".html")
    report_base_json = report_base.with_suffix(".json")

    report_base_md.write_text(markdown_content, encoding="utf-8")
    report_base_html.write_text(html_content, encoding="utf-8")
    report_base_json.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    print(f"Report written to {report_base_md}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    try:
        raise SystemExit(main())
    except FlashError as exc:  # pragma: no cover - ensures friendly CLI failure
        sys.stderr.write(f"error: {exc}\n")
        raise SystemExit(1)
