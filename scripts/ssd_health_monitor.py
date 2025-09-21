#!/usr/bin/env python3
"""Collect SMART metrics and wear indicators for sugarkube SSDs."""

from __future__ import annotations

import argparse
import dataclasses
import datetime as dt
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

DEFAULT_REPORT_DIR = Path.home() / "sugarkube" / "reports"
DEFAULT_REPORT_PREFIX = "ssd-health"


class MonitorStatus:
    """Possible outcomes for monitor checks."""

    PASS = "pass"
    WARN = "warn"
    FAIL = "fail"


STATUS_EMOJI = {
    MonitorStatus.PASS: "✅",
    MonitorStatus.WARN: "⚠️",
    MonitorStatus.FAIL: "❌",
}


@dataclasses.dataclass
class MonitorCheck:
    """Record the outcome of a monitoring step."""

    name: str
    status: str
    summary: str
    data: Dict[str, Any]


@dataclasses.dataclass
class SmartctlResult:
    """Capture smartctl JSON payload and exit information."""

    payload: Optional[Dict[str, Any]]
    return_code: int
    stdout: str
    stderr: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Collect SMART health information for the active sugarkube SSD. "
            "The helper auto-detects the root disk, records wear indicators, "
            "and writes Markdown/JSON reports under ~/sugarkube/reports/"
            "ssd-health/<timestamp>/."
        )
    )
    parser.add_argument(
        "--device",
        help=(
            "Block device (e.g. /dev/sda) or partition to inspect. Defaults to the"
            " root filesystem's parent device."
        ),
    )
    parser.add_argument(
        "--report-dir",
        type=Path,
        default=DEFAULT_REPORT_DIR,
        help="Directory where timestamped reports are stored (default: %(default)s)",
    )
    parser.add_argument(
        "--report-prefix",
        default=DEFAULT_REPORT_PREFIX,
        help="Subdirectory name under --report-dir (default: %(default)s)",
    )
    parser.add_argument(
        "--tag",
        help="Optional tag appended to the report directory name for easier grouping.",
    )
    parser.add_argument(
        "--skip-markdown",
        action="store_true",
        help="Skip writing Markdown reports; JSON remains available.",
    )
    parser.add_argument(
        "--skip-json",
        action="store_true",
        help="Skip writing JSON summaries; Markdown remains available.",
    )
    parser.add_argument(
        "--warn-temperature",
        type=float,
        default=70.0,
        help="Warn when the reported temperature is at or above this value (°C).",
    )
    parser.add_argument(
        "--warn-percentage-used",
        type=float,
        default=80.0,
        help="Warn when NVMe percentage used meets or exceeds this value (default: %(default)s).",
    )
    parser.add_argument(
        "--fail-percentage-used",
        type=float,
        default=95.0,
        help="Fail when NVMe percentage used meets or exceeds this value (default: %(default)s).",
    )
    parser.add_argument(
        "--warn-life-left",
        type=float,
        default=20.0,
        help=(
            "Warn when ATA Percent_Lifetime_Remain (or similar) drops below this value"
            " (default: %(default)s)."
        ),
    )
    parser.add_argument(
        "--fail-life-left",
        type=float,
        default=10.0,
        help=(
            "Fail when ATA Percent_Lifetime_Remain (or similar) drops below this value"
            " (default: %(default)s)."
        ),
    )
    return parser.parse_args()


def run_command(command: List[str]) -> subprocess.CompletedProcess[str]:
    """Run a command and return the completed process."""

    return subprocess.run(command, capture_output=True, check=False, text=True)


def detect_root_partition() -> Optional[str]:
    """Return the block device backing the root filesystem."""

    result = run_command(["findmnt", "-no", "SOURCE", "/"])
    if result.returncode != 0:
        return None
    source = result.stdout.strip()
    if not source:
        return None
    if source.startswith("PARTUUID="):
        uuid = source.split("=", 1)[1]
        uuid_result = run_command(["blkid", "-t", f"PARTUUID={uuid}", "-o", "device"])
        if uuid_result.returncode == 0:
            device = uuid_result.stdout.strip().splitlines()[0:1]
            if device:
                return device[0]
        return None
    if source.startswith("/dev/"):
        return source
    return None


def strip_partition_suffix(device: str) -> str:
    """Strip partition suffixes from a block device path."""

    if not device.startswith("/dev/"):
        return device
    # Handle NVMe and MMC style names (nvme0n1p2, mmcblk0p2).
    if re.match(r"^/dev/(nvme\d+n\d+|mmcblk\d+|loop\d+)", device):
        if "p" in device:
            return device[: device.rfind("p")]
        return device
    # Generic USB/SATA devices (sda2, sdb1, etc.).
    stripped = device.rstrip("0123456789")
    if stripped.endswith("p"):
        stripped = stripped[:-1]
    return stripped or device


def resolve_parent_device(device: str) -> str:
    """Attempt to resolve the parent block device for a partition."""

    pkname = run_command(["lsblk", "-no", "PKNAME", device])
    if pkname.returncode == 0:
        entry = pkname.stdout.strip().splitlines()[0:1]
        if entry:
            parent = entry[0]
            if parent:
                return f"/dev/{parent}"
    stripped = strip_partition_suffix(device)
    if os.path.exists(stripped):
        return stripped
    return device


def resolve_device(user_device: Optional[str]) -> Tuple[MonitorCheck, Optional[str]]:
    """Return a MonitorCheck describing device detection and the resolved device."""

    if user_device:
        resolved = str(Path(user_device).expanduser())
        if not os.path.exists(resolved):
            message = f"{resolved} does not exist."
            return (
                MonitorCheck(
                    name="Detect SSD device",
                    status=MonitorStatus.FAIL,
                    summary=message,
                    data={"requested": resolved},
                ),
                None,
            )
        parent = resolve_parent_device(resolved)
        summary = f"Using user-specified device {resolved}."
        status = MonitorStatus.PASS
        data = {"device": parent, "requested": resolved, "source": "user"}
        if parent != resolved:
            summary = f"Using {parent} (resolved from {resolved})."
            data["resolved_from"] = resolved
        return (
            MonitorCheck(
                name="Detect SSD device",
                status=status,
                summary=summary,
                data=data,
            ),
            parent,
        )

    partition = detect_root_partition()
    if not partition:
        return (
            MonitorCheck(
                name="Detect SSD device",
                status=MonitorStatus.FAIL,
                summary="Unable to resolve the root filesystem device.",
                data={},
            ),
            None,
        )
    parent = resolve_parent_device(partition)
    summary = f"Detected root partition {partition}; monitoring {parent}."
    data = {"partition": partition, "device": parent, "source": "auto"}
    status = MonitorStatus.PASS
    if parent == partition:
        summary = f"Using {parent} for SMART queries; unable to determine distinct parent device."
        data["warning"] = "Parent device fallback"
        status = MonitorStatus.WARN
    return (
        MonitorCheck(
            name="Detect SSD device",
            status=status,
            summary=summary,
            data=data,
        ),
        parent,
    )


def run_smartctl(device: str) -> SmartctlResult:
    """Invoke smartctl and capture JSON output."""

    smartctl = shutil.which("smartctl")
    if not smartctl:
        return SmartctlResult(payload=None, return_code=127, stdout="", stderr="smartctl not found")
    command = [smartctl, "-a", "-j", device]
    result = run_command(command)
    payload: Optional[Dict[str, Any]] = None
    if result.stdout:
        try:
            payload = json.loads(result.stdout)
        except json.JSONDecodeError:
            payload = None
    return SmartctlResult(
        payload=payload,
        return_code=result.returncode,
        stdout=result.stdout,
        stderr=result.stderr,
    )


def summarize_smartctl(device: str, result: SmartctlResult) -> MonitorCheck:
    """Summarize smartctl execution."""

    if result.payload is None:
        stderr = result.stderr.strip()
        summary = "smartctl output could not be parsed."
        if stderr:
            summary += f" stderr: {stderr}"
        data = {
            "device": device,
            "return_code": result.return_code,
            "stderr": stderr,
            "stdout_present": bool(result.stdout),
        }
        return MonitorCheck(
            name="Run smartctl",
            status=MonitorStatus.FAIL,
            summary=summary,
            data=data,
        )
    status = MonitorStatus.PASS
    summary = f"Collected SMART data from {device}."
    if result.return_code != 0 and result.return_code not in (0, 2):
        status = MonitorStatus.WARN
        summary = f"smartctl reported exit code {result.return_code}; check payload for warnings."
    return MonitorCheck(
        name="Run smartctl",
        status=status,
        summary=summary,
        data={"device": device, "return_code": result.return_code},
    )


def extract_temperature(payload: Dict[str, Any]) -> Optional[float]:
    """Extract the current temperature in Celsius when available."""

    temp_section = payload.get("temperature")
    if isinstance(temp_section, dict):
        current = temp_section.get("current")
        if isinstance(current, (int, float)):
            return float(current)
    # NVMe devices report under nvme_smart_health_information_log.
    nvme = payload.get("nvme_smart_health_information_log")
    if isinstance(nvme, dict):
        current = nvme.get("temperature")
        if isinstance(current, (int, float)):
            return float(current)
    return None


def extract_wear_entries(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Return a list of wear-related SMART attributes."""

    entries: List[Dict[str, Any]] = []
    nvme = payload.get("nvme_smart_health_information_log")
    if isinstance(nvme, dict):
        for key in (
            "percentage_used",
            "available_spare",
            "available_spare_threshold",
            "critical_warning",
            "data_units_written",
            "host_reads_32mib",
            "host_writes_32mib",
        ):
            if key in nvme:
                entries.append({"name": key, "value": nvme[key]})
    ata = payload.get("ata_smart_attributes", {})
    table = ata.get("table") if isinstance(ata, dict) else None
    if isinstance(table, list):
        for row in table:
            name = row.get("name")
            if not isinstance(name, str):
                continue
            lower = name.lower()
            if any(token in lower for token in ("wear", "life", "percent", "spare")):
                value = row.get("value")
                raw = row.get("raw", {})
                if isinstance(raw, dict):
                    raw_value = raw.get("value")
                    raw_string = raw.get("string")
                else:
                    raw_value = None
                    raw_string = None
                entries.append(
                    {
                        "name": name,
                        "value": value,
                        "raw_value": raw_value,
                        "raw_string": raw_string,
                    }
                )
    return entries


def evaluate_health(
    payload: Dict[str, Any],
    args: argparse.Namespace,
) -> Tuple[List[MonitorCheck], Dict[str, Any]]:
    """Evaluate SMART payload and produce checks plus summary data."""

    checks: List[MonitorCheck] = []
    summary: Dict[str, Any] = {}
    smart_status = payload.get("smart_status")
    passed: Optional[bool] = None
    if isinstance(smart_status, dict):
        raw_passed = smart_status.get("passed")
        if isinstance(raw_passed, bool):
            passed = raw_passed
    summary["smart_passed"] = passed
    if passed is False:
        checks.append(
            MonitorCheck(
                name="SMART overall health",
                status=MonitorStatus.FAIL,
                summary="smartctl reports a failing health status.",
                data={"smart_passed": passed},
            )
        )
    elif passed is True:
        checks.append(
            MonitorCheck(
                name="SMART overall health",
                status=MonitorStatus.PASS,
                summary="SMART overall health passed.",
                data={"smart_passed": passed},
            )
        )
    else:
        checks.append(
            MonitorCheck(
                name="SMART overall health",
                status=MonitorStatus.WARN,
                summary="SMART health flag unavailable in smartctl output.",
                data={},
            )
        )

    temperature = extract_temperature(payload)
    summary["temperature_c"] = temperature
    if temperature is None:
        checks.append(
            MonitorCheck(
                name="Temperature",
                status=MonitorStatus.WARN,
                summary="Temperature not reported by smartctl.",
                data={},
            )
        )
    else:
        temp_status = MonitorStatus.PASS
        summary_msg = f"Current temperature: {temperature:.1f} °C."
        if temperature >= args.warn_temperature:
            temp_status = MonitorStatus.WARN
            summary_msg = (
                f"Temperature {temperature:.1f} °C meets or exceeds "
                f"warn threshold {args.warn_temperature:.1f} °C."
            )
        checks.append(
            MonitorCheck(
                name="Temperature",
                status=temp_status,
                summary=summary_msg,
                data={"temperature_c": temperature, "warn_threshold": args.warn_temperature},
            )
        )

    wear_entries = extract_wear_entries(payload)
    summary["wear_entries"] = wear_entries
    wear_status = MonitorStatus.PASS
    wear_summary = "Collected wear indicators."
    fail_reasons: List[str] = []
    warn_reasons: List[str] = []

    for entry in wear_entries:
        name = entry.get("name", "").lower()
        value = entry.get("value")
        if name == "percentage_used" and isinstance(value, (int, float)):
            if value >= args.fail_percentage_used:
                fail_reasons.append(
                    f"percentage_used {value} ≥ fail threshold {args.fail_percentage_used}"
                )
            elif value >= args.warn_percentage_used:
                warn_reasons.append(
                    f"percentage_used {value} ≥ warn threshold {args.warn_percentage_used}"
                )
        if "percent" in name and "remain" in name and isinstance(value, (int, float)):
            if value <= args.fail_life_left:
                fail_reasons.append(
                    f"{entry['name']} {value} ≤ fail threshold {args.fail_life_left}"
                )
            elif value <= args.warn_life_left:
                warn_reasons.append(
                    f"{entry['name']} {value} ≤ warn threshold {args.warn_life_left}"
                )
    if fail_reasons:
        wear_status = MonitorStatus.FAIL
        wear_summary = "; ".join(fail_reasons)
    elif warn_reasons:
        wear_status = MonitorStatus.WARN
        wear_summary = "; ".join(warn_reasons)
    checks.append(
        MonitorCheck(
            name="Wear indicators",
            status=wear_status,
            summary=wear_summary,
            data={
                "warn_reasons": warn_reasons,
                "fail_reasons": fail_reasons,
                "entries": wear_entries,
            },
        )
    )
    return checks, summary


def build_markdown(
    timestamp: str,
    device: str,
    checks: Iterable[MonitorCheck],
    payload: Optional[Dict[str, Any]],
) -> str:
    """Render a Markdown report summarizing the checks."""

    lines = ["# SSD Health Report", ""]
    lines.append(f"- Generated at: {timestamp}")
    lines.append(f"- Device: `{device}`")
    if payload:
        model = payload.get("model_name") or payload.get("serial_number")
        if model:
            lines.append(f"- Model/Serial: {model}")
    lines.append("")
    lines.append("## Checks")
    lines.append("")
    lines.append("| Status | Check | Details |")
    lines.append("| --- | --- | --- |")
    for check in checks:
        emoji = STATUS_EMOJI.get(check.status, "•")
        lines.append(f"| {emoji} | {check.name} | {check.summary} |")
    lines.append("")

    if payload:
        wear_entries = extract_wear_entries(payload)
        if wear_entries:
            lines.append("## Wear Indicators")
            lines.append("")
            lines.append("| Name | Value | Raw Value | Raw String |")
            lines.append("| --- | --- | --- | --- |")
            for entry in wear_entries:
                raw_value = entry.get("raw_value")
                raw_string = entry.get("raw_string")
                lines.append(
                    "| {name} | {value} | {raw_value} | {raw_string} |".format(
                        name=entry.get("name", ""),
                        value=entry.get("value", ""),
                        raw_value=raw_value if raw_value is not None else "",
                        raw_string=raw_string if raw_string else "",
                    )
                )
            lines.append("")
    return "\n".join(lines).strip() + "\n"


def write_reports(
    report_dir: Path,
    prefix: str,
    tag: Optional[str],
    markdown: Optional[str],
    payload: Optional[Dict[str, Any]],
    checks: Iterable[MonitorCheck],
    device: str,
    write_summary: bool,
) -> Path:
    """Persist reports to disk and return the directory path."""

    timestamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    pieces = [prefix.strip().strip("/") or DEFAULT_REPORT_PREFIX, timestamp]
    if tag:
        pieces.insert(1, re.sub(r"[^A-Za-z0-9._-]", "-", tag.strip()))
    report_root = report_dir.expanduser()
    report_path = report_root.joinpath(*pieces)
    report_path.mkdir(parents=True, exist_ok=True)
    if markdown:
        (report_path / "report.md").write_text(markdown, encoding="utf-8")
    if payload is not None:
        (report_path / "smartctl.json").write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    if write_summary:
        summary_payload = {
            "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
            "device": device,
            "checks": [
                {
                    "name": check.name,
                    "status": check.status,
                    "summary": check.summary,
                    "data": check.data,
                }
                for check in checks
            ],
        }
        (report_path / "summary.json").write_text(
            json.dumps(summary_payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    return report_path


def summarize_console(checks: Iterable[MonitorCheck]) -> None:
    """Print a human-readable summary to stdout."""

    print("SSD health monitor results:\n")
    for check in checks:
        emoji = STATUS_EMOJI.get(check.status, "•")
        print(f"{emoji} {check.name}: {check.summary}")
    print("")


def exit_code(checks: Iterable[MonitorCheck]) -> int:
    """Return exit code 1 when any check fails."""

    for check in checks:
        if check.status == MonitorStatus.FAIL:
            return 1
    return 0


def main() -> int:
    args = parse_args()
    detection_check, device = resolve_device(args.device)
    checks: List[MonitorCheck] = [detection_check]
    if not device:
        summarize_console(checks)
        return exit_code(checks)

    smart_result = run_smartctl(device)
    smart_check = summarize_smartctl(device, smart_result)
    checks.append(smart_check)
    payload = smart_result.payload
    if payload is not None:
        eval_checks, _ = evaluate_health(payload, args)
        checks.extend(eval_checks)
    summarize_console(checks)

    markdown: Optional[str] = None
    if not args.skip_markdown and payload is not None:
        timestamp = dt.datetime.now(dt.timezone.utc).isoformat()
        markdown = build_markdown(timestamp, device, checks, payload)
    elif not args.skip_markdown:
        timestamp = dt.datetime.now(dt.timezone.utc).isoformat()
        markdown = build_markdown(timestamp, device, checks, payload or {})

    if args.skip_json and args.skip_markdown:
        return exit_code(checks)

    prefix = args.report_prefix.strip().strip("/") or DEFAULT_REPORT_PREFIX
    report_path = write_reports(
        args.report_dir,
        prefix,
        args.tag,
        markdown if not args.skip_markdown else None,
        payload,
        checks,
        device,
        write_summary=not args.skip_json,
    )
    print("\nReports saved to: {directory}".format(directory=report_path))
    if not args.skip_markdown:
        print(f"  - Markdown: {report_path / 'report.md'}")
    if not args.skip_json:
        print(f"  - JSON: {report_path / 'summary.json'}")
    if payload is not None:
        print(f"  - smartctl JSON: {report_path / 'smartctl.json'}")
    return exit_code(checks)


if __name__ == "__main__":  # pragma: no cover - manual script execution
    sys.exit(main())
