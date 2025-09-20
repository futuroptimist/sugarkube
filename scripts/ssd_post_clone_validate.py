#!/usr/bin/env python3
"""Validate SSD clone configuration and run basic health checks."""

from __future__ import annotations

import argparse
import contextlib
import dataclasses
import datetime as dt
import json
import os
import re
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path
from typing import Dict, Iterable, List, Optional

DEFAULT_REPORT_DIR = Path.home() / "sugarkube" / "reports"
DEFAULT_BOOT_MOUNT = Path("/boot")
DEFAULT_CMDLINE = DEFAULT_BOOT_MOUNT / "cmdline.txt"
DEFAULT_FSTAB = Path("/etc/fstab")
DEFAULT_STRESS_PATH = Path("/var/log/sugarkube")
DEFAULT_STRESS_MB = 128


class ValidationStatus:
    """Possible validation result states."""

    PASS = "pass"
    WARN = "warn"
    FAIL = "fail"
    SKIP = "skip"


STATUS_EMOJI = {
    ValidationStatus.PASS: "✅",
    ValidationStatus.WARN: "⚠️",
    ValidationStatus.FAIL: "❌",
    ValidationStatus.SKIP: "⏭️",
}


@dataclasses.dataclass
class CheckResult:
    """Record the outcome of an individual validation step."""

    name: str
    status: str
    details: str
    data: Dict[str, object]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Validate a cloned SSD before switching the Raspberry Pi to boot from it. "
            "The script checks /boot/cmdline.txt, /etc/fstab, EEPROM boot order, and "
            "performs a configurable read/write stress test."
        )
    )
    parser.add_argument(
        "--report-dir",
        type=Path,
        default=DEFAULT_REPORT_DIR,
        help="Directory where timestamped reports are stored (default: %(default)s)",
    )
    parser.add_argument(
        "--boot-mount",
        type=Path,
        default=DEFAULT_BOOT_MOUNT,
        help="Path where the boot partition is mounted (default: %(default)s)",
    )
    parser.add_argument(
        "--cmdline",
        type=Path,
        default=DEFAULT_CMDLINE,
        help="Path to cmdline.txt (default: %(default)s)",
    )
    parser.add_argument(
        "--fstab",
        type=Path,
        default=DEFAULT_FSTAB,
        help="Path to fstab for validation (default: %(default)s)",
    )
    parser.add_argument(
        "--stress-path",
        type=Path,
        default=DEFAULT_STRESS_PATH,
        help="Directory used for temporary stress-test files (default: %(default)s)",
    )
    parser.add_argument(
        "--stress-mb",
        type=int,
        default=DEFAULT_STRESS_MB,
        help="Megabytes written/read during the stress test (default: %(default)s)",
    )
    parser.add_argument(
        "--skip-stress",
        action="store_true",
        help="Skip the read/write stress test and only validate configuration",
    )
    parser.add_argument(
        "--report-prefix",
        default="ssd-validation",
        help="Subdirectory prefix inside --report-dir (default: %(default)s)",
    )
    return parser.parse_args()


def run_command(command: List[str]) -> subprocess.CompletedProcess[str]:
    """Run a command and return the completed process."""

    return subprocess.run(command, check=False, capture_output=True, text=True)


def find_mount_source(mountpoint: Path) -> Optional[str]:
    """Return the source device for a mountpoint."""

    result = run_command(["findmnt", "-no", "SOURCE", str(mountpoint)])
    if result.returncode == 0:
        output = result.stdout.strip()
        if output:
            return output

    try:
        with open("/proc/self/mounts", "r", encoding="utf-8") as handle:
            for line in handle:
                parts = line.split()
                if len(parts) >= 2 and parts[1] == str(mountpoint):
                    return parts[0]
    except OSError:
        return None
    return None


def resolve_partuuid(source: Optional[str]) -> Optional[str]:
    """Extract the PARTUUID from a mount source or device."""

    if not source:
        return None
    if source.startswith("PARTUUID="):
        return source.split("=", 1)[1]
    if source.startswith("/dev/"):
        real_source = os.path.realpath(source)
        if real_source != source:
            return resolve_partuuid(real_source)
        result = run_command(["blkid", "-s", "PARTUUID", "-o", "value", source])
        if result.returncode == 0:
            value = result.stdout.strip()
            return value or None
    return None


def load_fstab(path: Path) -> Dict[str, str]:
    """Parse fstab and return a mapping of mountpoints to specifiers."""

    mapping: Dict[str, str] = {}
    try:
        content = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return mapping
    for line in content.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        parts = stripped.split()
        if len(parts) < 2:
            continue
        spec, mountpoint = parts[0], parts[1]
        mapping[mountpoint] = spec
    return mapping


def extract_cmdline_root(path: Path) -> Optional[str]:
    """Read cmdline.txt and return the root PARTUUID if present."""

    try:
        content = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    match = re.search(r"root=PARTUUID=(\S+)", content)
    if match:
        return match.group(1)
    return None


def parse_boot_order(output: str) -> Optional[str]:
    """Extract the boot order string from EEPROM command output."""

    match = re.search(r"BOOT_ORDER\s*=\s*(0x[0-9a-fA-F]+|[0-9a-fA-F]+)", output)
    if not match:
        return None
    value = match.group(1).strip()
    if value.lower().startswith("0x"):
        return value[2:].lower()
    return value.lower()


def evaluate_boot_order(order: str) -> Dict[str, object]:
    """Assess whether USB boot precedes SD boot in the EEPROM order."""

    # Raspberry Pi firmware evaluates BOOT_ORDER from the least significant nibble, meaning
    # the right-most character is attempted first. Reverse the string so index zero aligns with
    # the highest priority boot mode before comparing the positions of USB (4/6) vs SD (0/1).
    digits = list(reversed(order))
    usb_indices = [i for i, digit in enumerate(digits) if digit in {"4", "6"}]
    sd_indices = [i for i, digit in enumerate(digits) if digit in {"0", "1"}]
    if not usb_indices:
        status = ValidationStatus.WARN
        detail = "Boot order does not reference USB mass storage (4 or 6)."
    elif not sd_indices:
        status = ValidationStatus.PASS
        detail = "USB mass storage is present and SD is absent in the boot order."
    else:
        if min(usb_indices) < min(sd_indices):
            status = ValidationStatus.PASS
            detail = "USB mass storage precedes SD card in the boot order."
        else:
            status = ValidationStatus.WARN
            detail = "SD card precedes USB mass storage; consider reordering."
    return {
        "status": status,
        "order": order,
        "details": detail,
    }


def ensure_space(target: Path, required_mb: int) -> bool:
    """Return True when the target path has enough available space."""

    try:
        stats = os.statvfs(target)
    except FileNotFoundError:
        target.mkdir(parents=True, exist_ok=True)
        stats = os.statvfs(target)
    available_bytes = stats.f_bavail * stats.f_frsize
    return available_bytes >= required_mb * 1024 * 1024


def stress_test(target: Path, size_mb: int) -> Dict[str, object]:
    """Write and read a temporary file to verify SSD responsiveness."""

    target.mkdir(parents=True, exist_ok=True)
    if not ensure_space(target, size_mb + 8):
        return {
            "status": ValidationStatus.WARN,
            "details": "Insufficient free space for stress test.",
        }

    chunk_size = 1 * 1024 * 1024
    chunk = b"\0" * chunk_size
    iterations = max(1, size_mb)
    test_file = target / f"ssd-validation-{os.getpid()}-{int(dt.datetime.now().timestamp())}.bin"
    try:
        write_start = dt.datetime.now(dt.timezone.utc)
        with open(test_file, "wb", buffering=chunk_size) as handle:
            for _ in range(iterations):
                handle.write(chunk)
            handle.flush()
            os.fsync(handle.fileno())
        write_end = dt.datetime.now(dt.timezone.utc)

        read_start = dt.datetime.now(dt.timezone.utc)
        with open(test_file, "rb", buffering=chunk_size) as handle:
            while handle.read(chunk_size):
                pass
        read_end = dt.datetime.now(dt.timezone.utc)
    except OSError as exc:
        return {
            "status": ValidationStatus.FAIL,
            "details": f"Stress test failed: {exc}",
        }
    finally:
        with contextlib.suppress(FileNotFoundError):
            test_file.unlink()

    write_seconds = (write_end - write_start).total_seconds()
    read_seconds = (read_end - read_start).total_seconds()
    total_mb = iterations * (chunk_size / (1024 * 1024))
    write_speed = total_mb / write_seconds if write_seconds > 0 else None
    read_speed = total_mb / read_seconds if read_seconds > 0 else None
    if write_speed is None or read_speed is None:
        return {
            "status": ValidationStatus.WARN,
            "details": "Unable to compute throughput during stress test.",
        }
    return {
        "status": ValidationStatus.PASS,
        "details": "Stress test completed successfully.",
        "size_mb": total_mb,
        "write_seconds": write_seconds,
        "read_seconds": read_seconds,
        "write_mb_s": write_speed,
        "read_mb_s": read_speed,
    }


def collect_checks(args: argparse.Namespace) -> List[CheckResult]:
    """Gather validation checks for reporting."""

    checks: List[CheckResult] = []

    root_source = find_mount_source(Path("/"))
    boot_source = find_mount_source(args.boot_mount)
    root_partuuid = resolve_partuuid(root_source)
    boot_partuuid = resolve_partuuid(boot_source)

    checks.append(
        CheckResult(
            name="Root filesystem source",
            status=ValidationStatus.PASS if root_source else ValidationStatus.FAIL,
            details=(f"Root filesystem is mounted from {root_source or 'an unknown source'}."),
            data={
                "mountpoint": "/",
                "source": root_source,
                "partuuid": root_partuuid,
            },
        )
    )
    checks.append(
        CheckResult(
            name="Boot filesystem source",
            status=ValidationStatus.PASS if boot_source else ValidationStatus.WARN,
            details=(f"Boot filesystem is mounted from {boot_source or 'an unknown source'}."),
            data={
                "mountpoint": str(args.boot_mount),
                "source": boot_source,
                "partuuid": boot_partuuid,
            },
        )
    )

    fstab_entries = load_fstab(args.fstab)
    root_fstab = resolve_partuuid(fstab_entries.get("/"))
    boot_fstab = resolve_partuuid(fstab_entries.get(str(args.boot_mount)))

    root_status = ValidationStatus.PASS
    root_detail = "Root PARTUUID matches /etc/fstab entry."
    if not root_partuuid or not root_fstab:
        root_status = ValidationStatus.FAIL
        root_detail = "Unable to resolve root PARTUUID from mount or fstab."
    elif root_partuuid != root_fstab:
        root_status = ValidationStatus.FAIL
        root_detail = f"Root PARTUUID mismatch: mount {root_partuuid} vs fstab {root_fstab}."
    checks.append(
        CheckResult(
            name="Root fstab entry",
            status=root_status,
            details=root_detail,
            data={
                "mount_partuuid": root_partuuid,
                "fstab_partuuid": root_fstab,
                "fstab_spec": fstab_entries.get("/"),
            },
        )
    )

    boot_status = ValidationStatus.PASS
    boot_detail = "Boot PARTUUID matches /etc/fstab entry."
    if not boot_partuuid or not boot_fstab:
        boot_status = ValidationStatus.WARN
        boot_detail = "Unable to resolve boot PARTUUID from mount or fstab."
    elif boot_partuuid != boot_fstab:
        boot_status = ValidationStatus.FAIL
        boot_detail = f"Boot PARTUUID mismatch: mount {boot_partuuid} vs fstab {boot_fstab}."
    checks.append(
        CheckResult(
            name="Boot fstab entry",
            status=boot_status,
            details=boot_detail,
            data={
                "mount_partuuid": boot_partuuid,
                "fstab_partuuid": boot_fstab,
                "fstab_spec": fstab_entries.get(str(args.boot_mount)),
            },
        )
    )

    cmdline_partuuid = extract_cmdline_root(args.cmdline)
    cmdline_status = ValidationStatus.PASS
    cmdline_detail = "cmdline.txt root PARTUUID matches the mounted filesystem."
    if not cmdline_partuuid:
        cmdline_status = ValidationStatus.FAIL
        cmdline_detail = "cmdline.txt does not contain a root=PARTUUID entry."
    elif not root_partuuid:
        cmdline_status = ValidationStatus.FAIL
        cmdline_detail = "Unable to compare cmdline.txt with the mounted root."
    elif cmdline_partuuid != root_partuuid:
        cmdline_status = ValidationStatus.FAIL
        cmdline_detail = (
            f"cmdline.txt root PARTUUID {cmdline_partuuid} does not match mounted {root_partuuid}."
        )
    checks.append(
        CheckResult(
            name="cmdline.txt root",
            status=cmdline_status,
            details=cmdline_detail,
            data={
                "cmdline_partuuid": cmdline_partuuid,
                "root_partuuid": root_partuuid,
                "cmdline_path": str(args.cmdline),
            },
        )
    )

    if shutil.which("rpi-eeprom-config") is None:
        checks.append(
            CheckResult(
                name="EEPROM boot order",
                status=ValidationStatus.WARN,
                details="rpi-eeprom-config unavailable; skipping boot order validation.",
                data={
                    "returncode": None,
                    "stdout": "",
                    "stderr": "",
                },
            )
        )
    else:
        eeprom = run_command(["rpi-eeprom-config", "--summary"])
        if eeprom.returncode != 0:
            checks.append(
                CheckResult(
                    name="EEPROM boot order",
                    status=ValidationStatus.WARN,
                    details="rpi-eeprom-config returned a non-zero status; see stderr for details.",
                    data={
                        "returncode": eeprom.returncode,
                        "stdout": eeprom.stdout,
                        "stderr": eeprom.stderr,
                    },
                )
            )
        else:
            order = parse_boot_order(eeprom.stdout)
            if order is None:
                checks.append(
                    CheckResult(
                        name="EEPROM boot order",
                        status=ValidationStatus.WARN,
                        details="Unable to parse BOOT_ORDER from rpi-eeprom-config output.",
                        data={
                            "stdout": eeprom.stdout,
                            "stderr": eeprom.stderr,
                        },
                    )
                )
            else:
                boot_eval = evaluate_boot_order(order)
                checks.append(
                    CheckResult(
                        name="EEPROM boot order",
                        status=boot_eval["status"],
                        details=boot_eval["details"],
                        data={
                            "order": order,
                            "stdout": eeprom.stdout,
                            "stderr": eeprom.stderr,
                        },
                    )
                )

    if args.skip_stress:
        checks.append(
            CheckResult(
                name="SSD stress test",
                status=ValidationStatus.SKIP,
                details="Stress test skipped by request.",
                data={
                    "size_mb": args.stress_mb,
                    "path": str(args.stress_path),
                },
            )
        )
    else:
        stress = stress_test(args.stress_path.expanduser(), args.stress_mb)
        checks.append(
            CheckResult(
                name="SSD stress test",
                status=stress.get("status", ValidationStatus.WARN),
                details=stress.get("details", ""),
                data=stress,
            )
        )

    return checks


def build_markdown(timestamp: str, checks: Iterable[CheckResult]) -> str:
    """Render a Markdown report summarizing the validation."""

    lines: List[str] = ["# Sugarkube SSD Post-Clone Validation", ""]
    lines.append(f"- Generated: {timestamp}")
    lines.append(f"- Hostname: {os.uname().nodename}")
    lines.append("")
    lines.append("## Results")
    lines.append("")
    for check in checks:
        emoji = STATUS_EMOJI.get(check.status, "•")
        lines.append(f"- {emoji} **{check.name}** — {check.details}")
    lines.append("")
    lines.append("## Detailed Data")
    lines.append("")
    for check in checks:
        lines.append(f"### {check.name}")
        lines.append("")
        lines.append(f"Status: {STATUS_EMOJI.get(check.status, '•')} {check.status}")
        lines.append("")
        if check.data:
            lines.append("```json")
            lines.append(json.dumps(check.data, indent=2, sort_keys=True))
            lines.append("```")
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def summarize_console(checks: Iterable[CheckResult]) -> None:
    """Print a concise summary to stdout."""

    print("SSD post-clone validation results:\n")
    for check in checks:
        emoji = STATUS_EMOJI.get(check.status, "•")
        print(f"{emoji} {check.name}: {check.details}")
    print("")


def write_reports(
    report_dir: Path, prefix: str, markdown: str, checks: Iterable[CheckResult]
) -> Path:
    """Persist Markdown and JSON reports to disk."""

    timestamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    report_root = report_dir / prefix / timestamp
    report_root.mkdir(parents=True, exist_ok=True)
    markdown_path = report_root / "report.md"
    markdown_path.write_text(markdown, encoding="utf-8")
    json_path = report_root / "report.json"
    payload = {
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "checks": [
            {
                "name": check.name,
                "status": check.status,
                "details": check.details,
                "data": check.data,
            }
            for check in checks
        ],
    }
    json_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return report_root


def exit_code(checks: Iterable[CheckResult]) -> int:
    """Return 0 if no failures were encountered, otherwise 1."""

    for check in checks:
        if check.status == ValidationStatus.FAIL:
            return 1
    return 0


def main() -> int:
    args = parse_args()
    if args.stress_mb < 1:
        print("--stress-mb must be at least 1", file=sys.stderr)
        return 2
    checks = collect_checks(args)
    timestamp = dt.datetime.now(dt.timezone.utc).isoformat()
    markdown = build_markdown(timestamp, checks)
    summarize_console(checks)
    prefix = args.report_prefix.strip().strip("/") or "ssd-validation"
    report_root = write_reports(args.report_dir.expanduser(), prefix, markdown, checks)
    print(
        textwrap.dedent(
            f"""
        Reports saved to: {report_root}
          - Markdown: {report_root / 'report.md'}
          - JSON: {report_root / 'report.json'}
        """
        ).strip()
    )
    return exit_code(checks)


if __name__ == "__main__":  # pragma: no cover - manual execution script
    sys.exit(main())
