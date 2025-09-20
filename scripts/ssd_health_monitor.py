#!/usr/bin/env python3
"""Collect SMART health metrics for Sugarkube SSDs."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

DEFAULT_REPORT_DIR = Path.home() / "sugarkube" / "reports" / "ssd-health"
DEFAULT_TAG = "ssd-health"
SMARTCTL_EXIT_OK = {0, 2}
DEFAULT_WARN_PERCENT_USED = 80
DEFAULT_WARN_TEMPERATURE = 70


class MonitorError(RuntimeError):
    """Raised when health monitoring cannot proceed."""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Inspect an SSD or NVMe device with smartctl, store structured reports, and "
            "surface warnings when wear or temperature crosses configured thresholds."
        )
    )
    parser.add_argument(
        "--device",
        help=(
            "Block device to inspect (e.g. /dev/sda). If omitted, the script attempts to "
            "discover the root filesystem device."
        ),
    )
    parser.add_argument(
        "--report-dir",
        type=Path,
        default=DEFAULT_REPORT_DIR,
        help="Directory where JSON/Markdown reports are written (default: %(default)s)",
    )
    parser.add_argument(
        "--tag",
        default=DEFAULT_TAG,
        help="Prefix for generated report files (default: %(default)s)",
    )
    parser.add_argument(
        "--warn-percentage",
        type=int,
        default=DEFAULT_WARN_PERCENT_USED,
        help=(
            "Warn when percentage used is greater than or equal to this value. "
            "Only applies when wear metrics are reported (default: %(default)s)."
        ),
    )
    parser.add_argument(
        "--warn-temperature",
        type=int,
        default=DEFAULT_WARN_TEMPERATURE,
        help=(
            "Warn when the drive temperature in °C is greater than or equal to this "
            "value (default: %(default)s)."
        ),
    )
    parser.add_argument(
        "--fail-on-warn",
        action="store_true",
        help="Exit with status 2 if warnings are detected.",
    )
    parser.add_argument(
        "--no-markdown",
        action="store_true",
        help="Skip generating a Markdown report alongside JSON output.",
    )
    parser.add_argument(
        "--no-json",
        action="store_true",
        help="Skip generating a JSON report and only print to stdout/Markdown.",
    )
    parser.add_argument(
        "--print-json",
        action="store_true",
        help="Also print the JSON report to stdout after writing it to disk.",
    )
    return parser.parse_args()


def run_command(command: List[str]) -> subprocess.CompletedProcess[str]:
    """Run a command and capture stdout/stderr."""

    return subprocess.run(command, check=False, capture_output=True, text=True)


def find_mount_source(mountpoint: Path) -> Optional[str]:
    """Return the source device for a mountpoint."""

    result = run_command(["findmnt", "-no", "SOURCE", str(mountpoint)])
    if result.returncode == 0:
        source = result.stdout.strip()
        if source:
            return source

    try:
        with open("/proc/self/mounts", "r", encoding="utf-8") as handle:
            for line in handle:
                parts = line.split()
                if len(parts) >= 2 and parts[1] == str(mountpoint):
                    return parts[0]
    except OSError:
        return None
    return None


def resolve_block_device(specifier: str) -> Optional[str]:
    """Resolve a mount specifier or partition path to a base block device."""

    if specifier.startswith("PARTUUID=") or specifier.startswith("UUID="):
        result = run_command(["blkid", "-t", specifier, "-o", "device"])
        if result.returncode == 0:
            device = result.stdout.strip().splitlines()
            if device:
                return resolve_block_device(device[0])
        return None

    if specifier.startswith("/dev/"):
        real_path = os.path.realpath(specifier)
        lsblk = run_command(["lsblk", "-no", "PKNAME", real_path])
        if lsblk.returncode == 0:
            parent = lsblk.stdout.strip()
            if parent:
                return f"/dev/{parent}"
        return real_path

    return None


def detect_root_device() -> Optional[str]:
    """Best-effort detection of the primary root filesystem device."""

    source = find_mount_source(Path("/"))
    if not source:
        return None
    return resolve_block_device(source)


def ensure_smartctl_available() -> None:
    """Ensure smartctl is installed before continuing."""

    if not shutil.which("smartctl"):
        raise MonitorError(
            "smartctl is required but was not found in PATH. Install smartmontools first."
        )


def collect_smart_data(device: str) -> Tuple[Dict[str, Any], List[str]]:
    """Run smartctl in JSON mode and return parsed data plus warnings."""

    process = run_command(["smartctl", "-a", "-j", device])
    if process.returncode not in SMARTCTL_EXIT_OK:
        message = process.stderr.strip() or process.stdout.strip() or "smartctl failed"
        raise MonitorError(message)

    try:
        data = json.loads(process.stdout)
    except json.JSONDecodeError as exc:  # pragma: no cover - defensive coding
        raise MonitorError(f"Failed to parse smartctl JSON output: {exc}") from exc

    warnings: List[str] = []
    smart_status = data.get("smart_status", {})
    if smart_status.get("passed") is False:
        warnings.append("SMART overall-health self-assessment reported a failure.")

    return data, warnings


def _attribute_value(attribute: Dict[str, Any]) -> Optional[float]:
    raw = attribute.get("raw")
    if isinstance(raw, dict):
        if "value" in raw:
            try:
                return float(raw["value"])
            except (TypeError, ValueError):
                return None
        if "string" in raw:
            try:
                return float(raw["string"].strip())
            except (TypeError, ValueError):
                return None
    if isinstance(raw, (int, float)):
        return float(raw)
    return None


def _find_attribute(
    data: Dict[str, Any],
    *,
    names: Iterable[str] = (),
    ids: Iterable[int] = (),
) -> Optional[Dict[str, Any]]:
    table = data.get("ata_smart_attributes", {}).get("table", [])
    for entry in table:
        if entry.get("name") in names or entry.get("id") in ids:
            return entry
    return None


def summarise_metrics(data: Dict[str, Any]) -> Dict[str, Any]:
    """Extract useful metrics from smartctl JSON output."""

    device_info = data.get("device", {})
    nvme_log = data.get("nvme_smart_health_information_log", {})
    temperature = data.get("temperature", {})
    power_on = data.get("power_on_time", {})

    metrics: Dict[str, Any] = {
        "model_name": device_info.get("model_name") or device_info.get("name"),
        "serial_number": device_info.get("serial_number"),
        "firmware_version": device_info.get("firmware_version"),
    }

    if "hours" in power_on:
        metrics["power_on_hours"] = power_on["hours"]
    else:
        attr = _find_attribute(data, names=["Power_On_Hours"], ids=[9])
        value = _attribute_value(attr) if attr else None
        if value is not None:
            metrics["power_on_hours"] = int(value)

    if "current" in temperature:
        metrics["temperature_celsius"] = temperature["current"]
    elif nvme_log.get("temperature") is not None:
        metrics["temperature_celsius"] = nvme_log["temperature"]

    if nvme_log.get("percentage_used") is not None:
        metrics["percentage_used"] = nvme_log["percentage_used"]
    else:
        wear_attr = _find_attribute(
            data,
            names=[
                "Media_Wearout_Indicator",
                "Remaining_Lifetime_Perc",
                "Wear_Leveling_Count",
                "Percent_Lifetime_Remain",
            ],
        )
        wear_value = _attribute_value(wear_attr) if wear_attr else None
        if wear_value is not None:
            if wear_attr and wear_attr.get("name") in {
                "Percent_Lifetime_Remain",
                "Remaining_Lifetime_Perc",
            }:
                metrics["percentage_used"] = max(0, min(100, 100 - wear_value))
            elif wear_attr and wear_attr.get("name") == "Wear_Leveling_Count":
                metrics["wear_leveling_count"] = wear_value
            else:
                metrics["percentage_used"] = max(0, min(100, 100 - wear_value))

    smart_status = data.get("smart_status", {})
    if "passed" in smart_status:
        metrics["smart_passed"] = smart_status["passed"]
    if "self_test" in smart_status:
        metrics["self_test"] = smart_status["self_test"]

    return metrics


def format_markdown(
    *,
    device: str,
    timestamp: dt.datetime,
    metrics: Dict[str, Any],
    warnings: List[str],
    report_path: Path,
) -> str:
    """Render a Markdown report string."""

    table_rows = ["| Field | Value |", "| --- | --- |"]
    for field, label in (
        ("model_name", "Model"),
        ("serial_number", "Serial"),
        ("firmware_version", "Firmware"),
        ("power_on_hours", "Power-On Hours"),
        ("temperature_celsius", "Temperature (°C)"),
        ("percentage_used", "Percentage Used"),
        ("wear_leveling_count", "Wear Level Count"),
        ("smart_passed", "SMART Passed"),
    ):
        value = metrics.get(field)
        if value is None:
            continue
        table_rows.append(f"| {label} | {value} |")

    warning_section = (
        "\n".join(f"- ⚠️ {item}" for item in warnings) if warnings else "- ✅ No warnings"
    )

    lines = [
        f"# SSD Health Report for `{device}`",
        "",
        f"Generated: {timestamp.isoformat()} UTC",
        f"Report path: `{report_path}`",
        "",
        "## Summary",
        "",
        *table_rows,
        "",
        "## Warnings",
        "",
        warning_section,
        "",
        "## smartctl Command",
        "",
        "```bash",
        f"smartctl -a -j {device}",
        "```",
    ]
    return "\n".join(lines) + "\n"


def build_report(
    *,
    device: str,
    data: Dict[str, Any],
    metrics: Dict[str, Any],
    warnings: List[str],
    report_dir: Path,
    tag: str,
    generate_json: bool,
    generate_markdown: bool,
    print_json: bool,
) -> Tuple[Optional[Path], Optional[Path], Dict[str, Any]]:
    """Persist reports to disk and optionally return their paths."""

    timestamp = dt.datetime.utcnow()
    report_dir.mkdir(parents=True, exist_ok=True)
    stem = f"{tag}-{timestamp.strftime('%Y%m%dT%H%M%SZ')}"

    payload = {
        "device": device,
        "timestamp": timestamp.isoformat() + "Z",
        "metrics": metrics,
        "warnings": warnings,
        "smartctl": data,
    }

    json_path: Optional[Path] = None
    if generate_json:
        json_path = report_dir / f"{stem}.json"
        json_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        if print_json:
            json.dump(payload, sys.stdout, indent=2, sort_keys=True)
            sys.stdout.write("\n")

    markdown_path: Optional[Path] = None
    if generate_markdown:
        markdown_path = report_dir / f"{stem}.md"
        markdown_content = format_markdown(
            device=device,
            timestamp=timestamp,
            metrics=metrics,
            warnings=warnings,
            report_path=json_path or markdown_path,
        )
        markdown_path.write_text(markdown_content, encoding="utf-8")

    return json_path, markdown_path, payload


def evaluate_thresholds(
    *,
    metrics: Dict[str, Any],
    warnings: List[str],
    warn_percentage: int,
    warn_temperature: int,
) -> None:
    """Append warnings based on configured thresholds."""

    percentage = metrics.get("percentage_used")
    if isinstance(percentage, (int, float)) and percentage >= warn_percentage:
        warnings.append(
            (
                f"Drive wear is at {percentage:.0f}% which meets or exceeds "
                f"the {warn_percentage}% threshold."
            )
        )

    temperature = metrics.get("temperature_celsius")
    if isinstance(temperature, (int, float)) and temperature >= warn_temperature:
        warnings.append(
            f"Drive temperature is {temperature:.0f}°C which meets or exceeds the "
            f"{warn_temperature}°C threshold."
        )


def main() -> int:
    args = parse_args()

    try:
        ensure_smartctl_available()
        device = args.device or detect_root_device()
        if not device:
            raise MonitorError(
                "Unable to determine the block device. Specify one with --device (e.g. /dev/sda)."
            )

        data, warnings = collect_smart_data(device)
        metrics = summarise_metrics(data)
        metrics["device_path"] = device
        evaluate_thresholds(
            metrics=metrics,
            warnings=warnings,
            warn_percentage=args.warn_percentage,
            warn_temperature=args.warn_temperature,
        )
        json_path, markdown_path, _ = build_report(
            device=device,
            data=data,
            metrics=metrics,
            warnings=warnings,
            report_dir=args.report_dir,
            tag=args.tag,
            generate_json=not args.no_json,
            generate_markdown=not args.no_markdown,
            print_json=args.print_json,
        )
    except MonitorError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    summary_lines = [
        f"Device: {device}",
        f"Model: {metrics.get('model_name', 'unknown')}",
    ]
    if "temperature_celsius" in metrics:
        summary_lines.append(f"Temperature: {metrics['temperature_celsius']}°C")
    if "percentage_used" in metrics:
        summary_lines.append(f"Wear used: {metrics['percentage_used']:.0f}%")
    if warnings:
        summary_lines.append("Warnings:")
        summary_lines.extend(f"  - {item}" for item in warnings)
    else:
        summary_lines.append("Warnings: none")

    print("\n".join(summary_lines))
    if json_path:
        print(f"JSON report: {json_path}")
    if markdown_path:
        print(f"Markdown report: {markdown_path}")

    if warnings and args.fail_on_warn:
        return 2

    return 0


if __name__ == "__main__":
    sys.exit(main())
