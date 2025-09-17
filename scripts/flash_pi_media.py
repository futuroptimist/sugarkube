#!/usr/bin/env python3
"""Stream Raspberry Pi images directly to removable media with verification.

The helper intentionally avoids shell pipelines so it works on Linux, macOS,
and Windows without additional tooling.  It discovers removable drives,
prompts for confirmation, streams `.img` or `.img.xz` images to the selected
device, verifies the written bytes with SHA-256, and finally ejects/offlines
the media.

Examples
--------

List candidate devices only::

    python scripts/flash_pi_media.py --list

Flash to an explicit device (non-interactive)::

    sudo python scripts/flash_pi_media.py --image ~/sugarkube/images/sugarkube.img.xz \
        --device /dev/sdX --assume-yes

Regular files are accepted as ``--device`` targets which makes automated
testing and dry-runs possible without touching real hardware.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import difflib
import hashlib
import html
import io
import json
import os
import platform
import shutil
import stat
import subprocess
import sys
import textwrap
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

BASELINE_CLOUD_INIT = Path(__file__).resolve().parent / "cloud-init" / "user-data.yaml"

CHUNK_SIZE = 4 * 1024 * 1024  # 4 MiB to balance throughput and memory usage.
PROGRESS_INTERVAL = 1.0  # seconds


def _supports_color(stream: io.TextIOBase) -> bool:
    return bool(stream.isatty()) and platform.system() != "Windows"


def _color(text: str, color_code: str) -> str:
    if not _supports_color(sys.stdout):
        return text
    return f"\033[{color_code}m{text}\033[0m"


def info(message: str) -> None:
    sys.stdout.write(f"==> {message}\n")


def warn(message: str) -> None:
    sys.stderr.write(_color(f"warning: {message}\n", "33"))


def err(message: str) -> None:
    sys.stderr.write(_color(f"error: {message}\n", "31"))


def die(message: str, code: int = 1) -> None:
    err(message)
    raise SystemExit(code)


def require(condition: bool, message: str) -> None:
    if not condition:
        die(message)


def _bytes_to_gib(size: int) -> float:
    return size / (1024**3)


def _format_size(size: int) -> str:
    if size < 1024:
        return f"{size} B"
    for unit in ["KiB", "MiB", "GiB", "TiB"]:
        size /= 1024.0
        if size < 1024:
            return f"{size:.2f} {unit}"
    return f"{size:.2f} PiB"


@dataclass
class Device:
    """A removable storage device candidate."""

    path: str
    description: str
    size: int
    is_removable: bool
    bus: Optional[str] = None
    system_id: Optional[str] = None  # disk number on Windows, identifier on macOS
    mountpoints: Sequence[str] | None = None

    @property
    def human_size(self) -> str:
        return _format_size(self.size)


def _run(cmd: Sequence[str], **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, check=False, capture_output=True, text=True, **kwargs)


def _safe_run(cmd: Sequence[str]) -> subprocess.CompletedProcess:
    try:
        return _run(cmd)
    except OSError as exc:  # pragma: no cover - defensive guard for missing binaries
        warn(f"Failed to execute {' '.join(cmd)}: {exc}")
        completed = subprocess.CompletedProcess(cmd, returncode=1, stdout="", stderr=str(exc))
        return completed


def _list_linux_devices() -> List[Device]:
    lsblk = shutil.which("lsblk")
    devices: List[Device] = []
    if lsblk:
        proc = _run(
            [
                lsblk,
                "-b",
                "-J",
                "-O",
                "-o",
                "NAME,KNAME,PATH,SIZE,MODEL,TYPE,TRAN,RM,MOUNTPOINT",
            ]
        )
        if proc.returncode == 0 and proc.stdout:
            try:
                payload = json.loads(proc.stdout)
                for entry in payload.get("blockdevices", []):
                    if entry.get("type") != "disk":
                        continue
                    path = entry.get("path") or f"/dev/{entry.get('name')}"
                    size = int(entry.get("size") or 0)
                    desc = entry.get("model") or entry.get("name") or "disk"
                    rm = bool(entry.get("rm"))
                    tran = entry.get("tran")
                    mounts: List[str] = []
                    if "children" in entry:
                        for child in entry["children"]:
                            mp = child.get("mountpoint")
                            if mp:
                                mounts.append(str(mp))
                    devices.append(
                        Device(
                            path=path,
                            description=str(desc).strip(),
                            size=size,
                            is_removable=rm or (tran in {"usb", "mmc"}),
                            bus=tran,
                            mountpoints=tuple(mounts),
                        )
                    )
                return devices
            except json.JSONDecodeError:
                warn("lsblk returned non-JSON output; falling back to /sys probing")

    sys_block = Path("/sys/block")
    if not sys_block.exists():
        return devices
    for device in sys_block.iterdir():
        if not (sys_block / device.name / "device").exists():
            continue
        path = f"/dev/{device.name}"
        size_path = sys_block / device.name / "size"
        size = int(size_path.read_text().strip()) * 512 if size_path.exists() else 0
        model_path = sys_block / device.name / "device/model"
        model = model_path.read_text().strip() if model_path.exists() else device.name
        removable_path = sys_block / device.name / "removable"
        removable = removable_path.read_text().strip() == "1" if removable_path.exists() else False
        devices.append(
            Device(
                path=path,
                description=model,
                size=size,
                is_removable=removable,
            )
        )
    return devices


def _list_macos_devices() -> List[Device]:
    proc = _run(["/usr/sbin/diskutil", "list", "-plist"])
    if proc.returncode != 0 or not proc.stdout:
        return []
    try:
        import plistlib

        data = plistlib.loads(proc.stdout.encode("utf-8"))
    except Exception as exc:  # pragma: no cover - defensive logging
        warn(f"Failed to parse diskutil output: {exc}")
        return []

    result: List[Device] = []
    for disk in data.get("AllDisksAndPartitions", []):
        identifier = disk.get("DeviceIdentifier")
        if not identifier:
            continue
        path = f"/dev/{identifier}"
        size = int(disk.get("Size", 0))
        desc = disk.get("VolumeName") or disk.get("MediaName") or identifier
        removable = bool(disk.get("RemovableMedia"))
        bus = disk.get("BusProtocol")
        mountpoints: List[str] = []
        for partition in disk.get("Partitions", []):
            mp = partition.get("MountPoint")
            if mp:
                mountpoints.append(str(mp))
        result.append(
            Device(
                path=path,
                description=str(desc).strip(),
                size=size,
                is_removable=removable or (bus and "USB" in bus.upper()),
                bus=bus,
                system_id=identifier,
                mountpoints=tuple(mountpoints),
            )
        )
    return result


def _powershell_json(command: str) -> Optional[object]:
    proc = _run(["powershell", "-NoProfile", "-Command", command])
    if proc.returncode != 0 or not proc.stdout:
        return None
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError as exc:  # pragma: no cover - defensive
        warn(f"PowerShell JSON parse failure: {exc}")
        return None


def _list_windows_devices() -> List[Device]:
    command = (
        "Get-CimInstance -Namespace root/Microsoft/Windows/Storage -ClassName MSFT_Disk "
        "| Select-Object Number,FriendlyName,Size,BusType,IsBoot,IsSystem,"
        "IsVirtual,IsOffline,IsRemovable "
        "| ConvertTo-Json -Depth 3 -Compress"
    )
    payload = _powershell_json(command)
    if payload is None:
        return []
    items: Iterable[dict]
    if isinstance(payload, list):
        items = payload
    else:
        items = [payload]

    result: List[Device] = []
    for item in items:
        try:
            number = int(item.get("Number"))
        except (TypeError, ValueError):
            continue
        path = f"\\\\.\\PhysicalDrive{number}"
        name = item.get("FriendlyName") or f"PhysicalDrive{number}"
        size = int(item.get("Size") or 0)
        bus = item.get("BusType")
        removable = bool(item.get("IsRemovable")) or (bus and bus.upper() == "USB")
        # Virtual disks or system disks should be excluded by default.
        is_system = bool(item.get("IsSystem")) or bool(item.get("IsBoot"))
        is_virtual = bool(item.get("IsVirtual"))
        result.append(
            Device(
                path=path,
                description=str(name).strip(),
                size=size,
                is_removable=removable and not is_system and not is_virtual,
                bus=bus,
                system_id=str(number),
            )
        )
    return result


def discover_devices() -> List[Device]:
    system = platform.system()
    if system == "Linux":
        return _list_linux_devices()
    if system == "Darwin":
        return _list_macos_devices()
    if system == "Windows":
        return _list_windows_devices()
    return []


def filter_candidates(devices: Sequence[Device]) -> List[Device]:
    candidates: List[Device] = []
    for dev in devices:
        if dev.is_removable:
            candidates.append(dev)
        elif dev.bus and dev.bus.lower() in {"usb", "mmc"}:
            candidates.append(dev)
    return candidates


def summarize_devices(devices: Sequence[Device]) -> None:
    if not devices:
        info("No removable drives detected. Pass --device explicitly if one is attached.")
        return
    header = f"{'#':>2}  {'Device':<20} {'Size':>10}  Description"
    info(header)
    for idx, dev in enumerate(devices, start=1):
        desc = dev.description or "(unknown)"
        line = f"{idx:>2}  {dev.path:<20} {dev.human_size:>10}  {desc}"
        if dev.mountpoints:
            mounts = ", ".join(dev.mountpoints)
            line += f"  [mounted at {mounts}]"
        print(line)


def _confirm(prompt: str, assume_yes: bool = False) -> bool:
    if assume_yes:
        return True
    reply = input(f"{prompt} [y/N]: ").strip().lower()
    return reply in {"y", "yes"}


def _device_exists(path: str) -> bool:
    try:
        os.stat(path)
        return True
    except FileNotFoundError:
        return False


def _is_block_device(path: str) -> bool:
    try:
        mode = os.stat(path).st_mode
    except FileNotFoundError:
        return False
    return stat.S_ISBLK(mode)


def _check_not_root_device(path: str) -> None:
    if platform.system() != "Linux":
        return
    if not _is_block_device(path):
        return
    try:
        root_stat = os.stat("/")
        dev_stat = os.stat(path)
    except FileNotFoundError:
        return
    if os.major(root_stat.st_dev) == os.major(dev_stat.st_rdev):
        warn(
            "The selected device shares a major number with the root filesystem. "
            "Ensure you did not select the boot drive."
        )


def _open_device(path: str, write: bool) -> io.BufferedIOBase:
    flags = os.O_RDONLY
    mode = "rb"
    if write:
        flags = os.O_WRONLY
        mode = "wb"
    if hasattr(os, "O_BINARY"):
        flags |= os.O_BINARY
    if write and hasattr(os, "O_SYNC"):
        flags |= os.O_SYNC
    fd = os.open(path, flags)
    return os.fdopen(fd, mode)


def _open_image(path: Path) -> tuple[io.BufferedReader, bool]:
    if path.suffix == ".xz":
        import lzma

        return io.BufferedReader(lzma.open(path, "rb")), True
    return io.BufferedReader(open(path, "rb")), False


def _stream_write(src: io.BufferedReader, dest: io.BufferedRandom) -> tuple[int, str]:
    sha = hashlib.sha256()
    total = 0
    last_report = time.monotonic()
    while True:
        chunk = src.read(CHUNK_SIZE)
        if not chunk:
            break
        dest.write(chunk)
        total += len(chunk)
        sha.update(chunk)
        now = time.monotonic()
        if now - last_report >= PROGRESS_INTERVAL:
            info(f"Wrote {_format_size(total)} so far")
            last_report = now
    dest.flush()
    os.fsync(dest.fileno())
    info(f"Finished writing {_format_size(total)}")
    return total, sha.hexdigest()


def _read_and_hash(device: io.BufferedRandom, size: int) -> str:
    sha = hashlib.sha256()
    remaining = size
    while remaining > 0:
        chunk = device.read(min(CHUNK_SIZE, remaining))
        if not chunk:
            break
        sha.update(chunk)
        remaining -= len(chunk)
    if remaining != 0:
        die("Device read was shorter than expected during verification")
    return sha.hexdigest()


def _auto_eject(device: Device) -> None:
    system = platform.system()
    if system == "Linux":
        path = device.path
        if shutil.which("udisksctl"):
            proc = _run(["udisksctl", "power-off", "-b", path])
            if proc.returncode == 0:
                info(f"Powered off {path}")
                return
        if shutil.which("eject"):
            proc = _run(["eject", path])
            if proc.returncode == 0:
                info(f"Ejected {path}")
                return
        warn("Unable to auto-eject. Remove the media manually once LEDs stop blinking.")
    elif system == "Darwin":
        identifier = device.system_id or device.path
        proc = _run(["/usr/sbin/diskutil", "eject", identifier])
        if proc.returncode == 0:
            info(f"Ejected {identifier}")
        else:
            warn("diskutil could not eject the media. Remove it manually when safe.")
    elif system == "Windows":
        if device.system_id and device.system_id.isdigit():
            command = (
                f"$disk = Get-Disk -Number {device.system_id} -ErrorAction SilentlyContinue; "
                "if ($disk) {"
                "  Get-Volume -DiskNumber $disk.Number -ErrorAction SilentlyContinue | "
                "    ForEach-Object { Dismount-Volume -InputObject $_ -Force -Confirm:$false }; "
                "  $disk | Set-Disk -IsOffline $true -Confirm:$false"
                "}"
            )
            proc = _run(["powershell", "-NoProfile", "-Command", command])
            if proc.returncode == 0:
                info(f"Disk {device.system_id} set offline. It is safe to remove the media.")
                return
        warn("Unable to offline the disk automatically. Use 'Safely Remove Hardware'.")


def _default_report_dir() -> Path:
    candidate = os.environ.get("SUGARKUBE_REPORT_DIR")
    if candidate:
        return Path(candidate).expanduser()
    return Path.home() / "sugarkube" / "reports"


def _resolve_report_paths(report_value: Optional[str]) -> Optional[Tuple[Path, Path]]:
    if report_value is None:
        return None

    timestamp = _dt.datetime.now(_dt.timezone.utc).strftime("%Y%m%d-%H%M%S")
    if report_value == "auto":
        base_dir = _default_report_dir()
        base_dir.mkdir(parents=True, exist_ok=True)
        base = base_dir / f"flash-{timestamp}"
        md_path = base.with_suffix(".md")
        html_path = base.with_suffix(".html")
        return md_path, html_path

    target = Path(report_value).expanduser().resolve()
    if target.is_dir():
        target.mkdir(parents=True, exist_ok=True)
        base = target / f"flash-{timestamp}"
        return base.with_suffix(".md"), base.with_suffix(".html")

    target.parent.mkdir(parents=True, exist_ok=True)
    if target.suffix:
        md_path = target.with_suffix(".md")
        html_path = target.with_suffix(".html")
    else:
        base = target
        md_path = base.with_suffix(".md")
        html_path = base.with_suffix(".html")
    return md_path, html_path


def _collect_device_metadata(device: Device) -> Dict[str, str]:
    metadata: Dict[str, str] = {
        "Device path": device.path,
        "Description": device.description or "(unknown)",
        "Bus": device.bus or "(unknown)",
        "Size": device.human_size,
        "Removable": "yes" if device.is_removable else "no",
    }
    if device.system_id:
        metadata["System identifier"] = device.system_id

    system = platform.system()
    if system == "Linux":
        proc = _safe_run(["udevadm", "info", "--query=property", "--name", device.path])
        if proc.returncode == 0 and proc.stdout:
            for line in proc.stdout.splitlines():
                if "=" not in line:
                    continue
                key, value = line.split("=", 1)
                if key in {"ID_MODEL", "ID_VENDOR", "ID_SERIAL", "ID_SERIAL_SHORT"}:
                    metadata[key.replace("ID_", "ID ")] = value
    elif system == "Darwin":  # pragma: no cover - macOS specific
        identifier = device.system_id or device.path
        proc = _safe_run(["/usr/sbin/diskutil", "info", "-plist", identifier])
        if proc.returncode == 0 and proc.stdout:
            try:
                import plistlib

                data = plistlib.loads(proc.stdout.encode("utf-8"))
            except Exception as exc:  # pragma: no cover - defensive
                warn(f"Unable to parse diskutil metadata: {exc}")
            else:
                for key in ["DeviceModel", "DeviceVendor", "DeviceSerialNumber"]:
                    value = data.get(key)
                    if value:
                        metadata[key.replace("Device", "")] = str(value)
    elif system == "Windows":  # pragma: no cover - Windows specific
        if device.system_id and device.system_id.isdigit():
            command = (
                "Get-Disk -Number "
                f"{device.system_id} | Select-Object SerialNumber,Model,Manufacturer | "
                "ConvertTo-Json -Compress"
            )
            payload = _powershell_json(command)
            if payload:
                if isinstance(payload, list) and payload:
                    payload = payload[0]
                for key in ["SerialNumber", "Model", "Manufacturer"]:
                    value = payload.get(key) if isinstance(payload, dict) else None
                    if value:
                        metadata[key] = str(value)

    return metadata


def _format_metadata_table(metadata: Dict[str, str]) -> str:
    if not metadata:
        return "_No metadata available._"
    lines = ["| Field | Value |", "| --- | --- |"]
    for key, value in metadata.items():
        escaped_value = str(value).replace("|", "\\|")
        lines.append(f"| {key} | {escaped_value} |")
    return "\n".join(lines)


def _cloud_init_diff(override: Path) -> str:
    baseline = BASELINE_CLOUD_INIT
    if not baseline.exists():
        return "Baseline user-data.yaml not found."
    if not override.exists():
        return f"Override file not found: {override}"
    base_text = baseline.read_text(encoding="utf-8").splitlines()
    override_text = override.read_text(encoding="utf-8").splitlines()
    diff = difflib.unified_diff(
        base_text,
        override_text,
        fromfile=str(baseline),
        tofile=str(override),
        lineterm="",
    )
    diff_text = "\n".join(diff)
    if not diff_text:
        return "No differences detected."
    return diff_text


def _generate_markdown_report(
    *,
    image_path: Path,
    compressed: bool,
    total_bytes: int,
    expected_hash: str,
    actual_hash: str,
    metadata: Dict[str, str],
    start_time: _dt.datetime,
    duration: float,
    cloud_init_section: Optional[str],
) -> str:
    host = platform.node()
    os_name = f"{platform.system()} {platform.release()}"
    image_desc = f"{image_path} ({'compressed' if compressed else 'raw'})"
    metadata_table = _format_metadata_table(metadata)
    diff_block = "No override provided."
    if cloud_init_section:
        diff_block = f"```diff\n{cloud_init_section}\n```"

    markdown = f"""\
# Sugarkube Flash Report

- **Generated at:** {start_time.isoformat()}
- **Host:** {host} ({os_name})
- **Image:** {image_desc}
- **Written bytes:** {total_bytes} ({_format_size(total_bytes)})
- **Expected SHA-256:** `{expected_hash}`
- **Verified SHA-256:** `{actual_hash}`
- **Duration:** {duration:.1f} seconds

## Device metadata

{metadata_table}

## Cloud-init diff

{diff_block}
"""

    return textwrap.dedent(markdown).strip() + "\n"


def _write_reports(md_path: Path, html_path: Path, markdown: str) -> None:
    md_path.write_text(markdown, encoding="utf-8")
    html_body = html.escape(markdown)
    html_content = (
        "<!DOCTYPE html>\n"
        '<html lang="en">\n<head>\n<meta charset="utf-8">\n'
        "<title>Sugarkube Flash Report</title>\n"
        "<style>body{font-family:system-ui, sans-serif; margin:2rem;}"
        "pre{white-space:pre-wrap;background:#f6f8fa;padding:1rem;border-radius:8px;}"
        "table{border-collapse:collapse;}"
        "td,th{border:1px solid #d0d7de;padding:0.5rem;text-align:left;}"
        "</style>\n</head>\n<body>\n"
        "<h1>Sugarkube Flash Report</h1>\n"
        f"<pre>{html_body}</pre>\n"
        "</body>\n</html>\n"
    )
    html_path.write_text(html_content, encoding="utf-8")


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--image",
        required=False,
        help=(
            "Path to the .img or .img.xz image. Defaults to the expanded release in "
            "~/sugarkube/images."
        ),
    )
    parser.add_argument(
        "--device",
        help=("Target device (e.g. /dev/sdX or \\.\\PhysicalDrive1). Prompts when omitted."),
    )
    parser.add_argument(
        "--assume-yes",
        action="store_true",
        help="Do not prompt for confirmation before flashing.",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="List detected removable devices and exit.",
    )
    parser.add_argument(
        "--keep-mounted",
        action="store_true",
        help="Skip automatic unmount detection. Useful for loopback files in tests.",
    )
    parser.add_argument(
        "--no-eject",
        action="store_true",
        help="Skip automatic eject/offline after flashing.",
    )
    parser.add_argument(
        "--report",
        nargs="?",
        const="auto",
        help=(
            "Write Markdown and HTML flash reports. Pass an optional path prefix "
            "or provide a custom filename."
        ),
    )
    parser.add_argument(
        "--cloud-init-override",
        help=(
            "Path to a cloud-init user-data file to diff against scripts/cloud-init/user-data.yaml."
        ),
    )
    parser.add_argument(
        "--bytes",
        type=int,
        default=0,
        help=argparse.SUPPRESS,
    )
    return parser.parse_args(argv)


def _default_image_path() -> Optional[Path]:
    candidate = Path.home() / "sugarkube" / "images" / "sugarkube.img"
    if candidate.exists():
        return candidate
    xz = candidate.with_suffix(".img.xz")
    if xz.exists():
        return xz
    return None


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    devices = discover_devices()
    candidates = filter_candidates(devices)
    start_wall = _dt.datetime.now(_dt.timezone.utc)
    start_monotonic = time.monotonic()

    if args.list:
        summarize_devices(candidates)
        return 0

    image_path: Optional[Path]
    if args.image:
        image_path = Path(args.image).expanduser().resolve()
    else:
        default = _default_image_path()
        if default is None:
            die(
                "Provide --image pointing to the sugarkube release "
                "(sugarkube.img or sugarkube.img.xz)."
            )
        image_path = default

    if not image_path.exists():
        die(f"Image not found: {image_path}")

    if not args.device:
        summarize_devices(candidates)
        if not candidates:
            die("No removable devices detected. Re-run with --device once media is attached.")
        selection = input("Enter the device number to flash: ").strip()
        try:
            index = int(selection) - 1
        except ValueError:
            die("Expected a numeric selection.")
        if index < 0 or index >= len(candidates):
            die("Selection out of range")
        target_device = candidates[index]
    else:
        target_path = args.device
        matching = [dev for dev in candidates if dev.path == target_path]
        if matching:
            target_device = matching[0]
        else:
            size_hint = 0
            if args.bytes:
                size_hint = args.bytes
            target_device = Device(
                path=target_path,
                description="(custom device)",
                size=size_hint,
                is_removable=True,
            )

    if not _device_exists(target_device.path):
        die(f"Device not found: {target_device.path}")

    _check_not_root_device(target_device.path)

    if target_device.mountpoints and not args.keep_mounted:
        mounts = ", ".join(target_device.mountpoints)
        die(
            f"{target_device.path} has mounted partitions ({mounts}). Unmount them before flashing "
            "or pass --keep-mounted to override."
        )

    allow_nonroot = os.environ.get("SUGARKUBE_FLASH_ALLOW_NONROOT") == "1"
    if hasattr(os, "geteuid"):
        if not allow_nonroot and os.geteuid() != 0:
            die("Run as root or with sudo")
    elif not allow_nonroot:
        warn(
            "Cannot determine effective user ID on this platform; "
            "ensure you have permissions to write the device."
        )

    if not _confirm(
        f"About to erase and flash {target_device.path} with {image_path.name}. Continue?",
        args.assume_yes,
    ):
        info("Aborted by user")
        return 0

    src, compressed = _open_image(image_path)
    info(f"Opening {'compressed ' if compressed else ''}image {image_path}")
    with src:
        with _open_device(target_device.path, write=True) as dest:
            total_bytes, expected_hash = _stream_write(src, dest)

    info(f"Expected SHA-256 for written bytes: {expected_hash}")

    with _open_device(target_device.path, write=False) as reader:
        actual_hash = _read_and_hash(reader, total_bytes)
    if actual_hash != expected_hash:
        die(
            "Verification failed: device SHA-256 does not match the image. "
            f"Expected {expected_hash}, got {actual_hash}."
        )
    info(f"Verified device SHA-256: {actual_hash}")

    if not args.no_eject:
        _auto_eject(target_device)

    duration = time.monotonic() - start_monotonic

    if args.report is not None:
        md_path, html_path = _resolve_report_paths(args.report)
        metadata = _collect_device_metadata(target_device)
        cloud_diff: Optional[str] = None
        if args.cloud_init_override:
            cloud_diff = _cloud_init_diff(Path(args.cloud_init_override).expanduser())
        markdown = _generate_markdown_report(
            image_path=image_path,
            compressed=compressed,
            total_bytes=total_bytes,
            expected_hash=expected_hash,
            actual_hash=actual_hash,
            metadata=metadata,
            start_time=start_wall,
            duration=duration,
            cloud_init_section=cloud_diff,
        )
        _write_reports(md_path, html_path, markdown)
        info(f"Wrote flash report: {md_path}")
        info(f"Wrote flash report: {html_path}")

    info("Flash complete")
    return 0


if __name__ == "__main__":  # pragma: no cover - manual invocation
    raise SystemExit(main())
