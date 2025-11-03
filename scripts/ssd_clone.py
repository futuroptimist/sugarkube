#!/usr/bin/env python3
"""Clone the active SD card to an SSD with dry-run and resume support."""

from __future__ import annotations

import argparse
import json
import os
import re
import secrets
import shlex
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence, Set, Tuple

STATE_DIR = Path("/var/log/sugarkube")
STATE_FILE = STATE_DIR / "ssd-clone.state.json"
DONE_FILE = STATE_DIR / "ssd-clone.done"
ERROR_LOG = STATE_DIR / "ssd-clone.error.log"
MOUNT_ROOT = Path("/mnt/ssd-clone")
ENV_TARGET = "SUGARKUBE_SSD_CLONE_TARGET"
ENV_WAIT = "SUGARKUBE_SSD_CLONE_WAIT_SECS"
ENV_POLL = "SUGARKUBE_SSD_CLONE_POLL_SECS"
ENV_EXTRA_ARGS = "SUGARKUBE_SSD_CLONE_EXTRA_ARGS"
ENV_BOOT_MOUNT = "SUGARKUBE_BOOT_MOUNT"
DEFAULT_WAIT_SECS = 900
DEFAULT_POLL_SECS = 10
FAT_LABEL_MAX = 11
EXT_LABEL_MAX = 16

STEP_ORDER = [
    "partition",
    "format",
    "sync_boot",
    "sync_root",
    "update_configs",
    "finalize",
]


class CommandError(RuntimeError):
    """Raised when an external command fails."""


@dataclass
class CloneContext:
    """Context shared across clone steps."""

    target_disk: str
    dry_run: bool = False
    verbose: bool = False
    resume: bool = False
    assume_yes: bool = False
    skip_partition: bool = False
    skip_format: bool = False
    skip_to: Optional[str] = None
    preserve_labels: bool = False
    refresh_uuid: bool = False
    boot_label: Optional[str] = None
    root_label: Optional[str] = None
    boot_mount: str = "/boot"
    state_file: Path = STATE_FILE
    state: Dict[str, object] = field(default_factory=dict)
    source_root: Optional[str] = None
    source_boot: Optional[str] = None
    target_root: Optional[str] = None
    target_boot: Optional[str] = None
    mount_root: Optional[Path] = None
    mounted_paths: List[Path] = field(default_factory=list)
    start_time: float = field(default_factory=time.monotonic)

    def log(self, message: str) -> None:
        prefix = "[DRY-RUN] " if self.dry_run else ""
        print(f"{prefix}{message}")

    def is_step_completed(self, name: str) -> bool:
        completed = self.state.get("completed", {})
        return bool(completed.get(name))

    def mark_step_completed(self, name: str) -> None:
        if self.dry_run:
            return
        completed = self.state.setdefault("completed", {})
        completed[name] = True
        save_state(self)

    def register_mount(self, mountpoint: Path) -> None:
        if self.dry_run:
            return
        if mountpoint not in self.mounted_paths:
            self.mounted_paths.append(mountpoint)

    def unregister_mount(self, mountpoint: Path) -> None:
        if self.dry_run:
            return
        try:
            self.mounted_paths.remove(mountpoint)
        except ValueError:
            pass


@dataclass
class Step:
    """Represent a clone step with a unique identifier."""

    name: str
    description: str
    validator: Optional[Callable[[CloneContext], bool]] = None

    def run(self, ctx: CloneContext, func) -> None:
        if should_skip_step(ctx, self.name):
            ctx.log(f"Skipping {self.name} (requested).")
            return
        if ctx.is_step_completed(self.name):
            if self.validator and not self.validator(ctx):
                ctx.log(
                    f"State indicates {self.name} completed but verification failed; re-running."
                )
            else:
                ctx.log(f"Skipping {self.name} (already completed).")
                return
        ctx.log(f"==> {self.description}")
        func(ctx)
        ctx.mark_step_completed(self.name)


def normalize_skip_to(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    mapping = {
        "sync": "sync_boot",
        "update": "update_configs",
    }
    normalized = mapping.get(value, value)
    if normalized not in STEP_ORDER:
        raise SystemExit(f"Unsupported --skip-to value: {value}")
    return normalized


def should_skip_step(ctx: CloneContext, step_name: str) -> bool:
    if step_name == "partition" and ctx.skip_partition:
        return True
    if step_name == "format" and ctx.skip_format:
        return True
    if ctx.skip_to is None:
        return False
    try:
        start_index = STEP_ORDER.index(ctx.skip_to)
        step_index = STEP_ORDER.index(step_name)
    except ValueError:
        return False
    return step_index < start_index


def run_command(
    ctx: CloneContext, command: List[str], *, input_text: Optional[str] = None
) -> subprocess.CompletedProcess[str]:
    """Run an external command unless dry-run is active."""

    ctx.log("Executing: " + shlex.join(command))
    if ctx.dry_run:
        return subprocess.CompletedProcess(command, 0, "", "")
    result = subprocess.run(
        command,
        check=False,
        text=True,
        capture_output=True,
        input=input_text,
    )
    if result.returncode != 0:
        raise CommandError(
            f"Command failed ({result.returncode}): {shlex.join(command)}\n"
            f"stdout: {result.stdout}\n"
            f"stderr: {result.stderr}"
        )
    if ctx.verbose and result.stdout:
        sys.stdout.write(result.stdout)
    if ctx.verbose and result.stderr:
        sys.stderr.write(result.stderr)
    return result


def ensure_root() -> None:
    if os.geteuid() != 0:
        raise SystemExit("This script must be run as root to access block devices.")


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Clone the active SD card to a target SSD. Preview actions with --dry-run and "
            "resume partially completed clones with --resume."
        )
    )
    target_group = parser.add_mutually_exclusive_group(required=True)
    target_group.add_argument(
        "--target",
        help="Target block device (e.g., /dev/sda)",
    )
    target_group.add_argument(
        "--auto-target",
        action="store_true",
        help="Automatically select a target disk (prefers hotplug USB/NVMe devices).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print actions without modifying the target disk.",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Resume a previous clone using the saved state file.",
    )
    parser.add_argument(
        "--state-file",
        type=Path,
        default=STATE_FILE,
        help="Override the clone state file path (default: %(default)s)",
    )
    parser.add_argument(
        "--mount-root",
        type=Path,
        default=MOUNT_ROOT,
        help="Directory used to mount target partitions during sync (default: %(default)s)",
    )
    parser.add_argument(
        "--boot-mount",
        help=(
            "Source boot mountpoint. Overrides auto-detection and " f"{ENV_BOOT_MOUNT} if supplied."
        ),
    )
    parser.add_argument(
        "--boot-label",
        help="Label applied to the FAT boot partition (defaults to derived value).",
    )
    parser.add_argument(
        "--root-label",
        help="Label applied to the root filesystem (defaults to source label).",
    )
    parser.add_argument(
        "--skip-format",
        action="store_true",
        help="Skip formatting target partitions (expects existing filesystems).",
    )
    parser.add_argument(
        "--skip-partition",
        action="store_true",
        help="Skip partition table replication and use the current target layout.",
    )
    parser.add_argument(
        "--skip-to",
        choices=["partition", "format", "sync", "sync_boot", "sync_root", "update", "finalize"],
        help="Skip all steps prior to the chosen phase ('sync' starts at boot sync).",
    )
    parser.add_argument(
        "--preserve-labels",
        action="store_true",
        help="Avoid rewriting filesystem labels when the target already matches.",
    )
    parser.add_argument(
        "--refresh-uuid",
        action="store_true",
        help="Generate new disk identifiers and PARTUUIDs on the target device.",
    )
    parser.add_argument(
        "--assume-yes",
        action="store_true",
        help="Bypass the destructive action confirmation prompt.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Show stdout/stderr from helper commands.",
    )
    arg_list = list(argv if argv is not None else sys.argv[1:])
    extra_args = os.environ.get(ENV_EXTRA_ARGS)
    if extra_args:
        try:
            arg_list.extend(shlex.split(extra_args))
        except ValueError as error:
            raise SystemExit(f"{ENV_EXTRA_ARGS} contains invalid shell syntax: {error}") from error
    return parser.parse_args(arg_list)


def lsblk_json(fields: List[str]) -> Dict[str, object]:
    result = subprocess.run(
        ["lsblk", "--json", "-b", "-o", ",".join(fields)],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise SystemExit("lsblk --json failed; cannot enumerate block devices.")
    try:
        return json.loads(result.stdout or "{}")
    except json.JSONDecodeError as error:
        raise SystemExit(f"Unable to parse lsblk output: {error}") from error


def device_size_bytes(device: str) -> int:
    result = subprocess.run(
        ["lsblk", "-b", "-ndo", "SIZE", device],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0 or not result.stdout.strip():
        raise SystemExit(f"Unable to determine size for {device}")
    return int(result.stdout.strip())


def _read_wait_seconds(value: Optional[int]) -> int:
    if value is not None:
        wait = value
    else:
        raw = os.environ.get(ENV_WAIT)
        if raw in (None, ""):
            wait = DEFAULT_WAIT_SECS
        else:
            try:
                wait = int(raw)
            except ValueError as error:
                raise SystemExit(f"{ENV_WAIT} must be an integer (received {raw!r}).") from error
    if wait < 0:
        raise SystemExit(f"{ENV_WAIT} must be non-negative (received {wait}).")
    return wait


def _read_poll_seconds(value: Optional[int]) -> int:
    if value is not None:
        poll = value
    else:
        raw = os.environ.get(ENV_POLL)
        if raw in (None, ""):
            poll = DEFAULT_POLL_SECS
        else:
            try:
                poll = int(raw)
            except ValueError as error:
                raise SystemExit(f"{ENV_POLL} must be an integer (received {raw!r}).") from error
    if poll <= 0:
        raise SystemExit(f"{ENV_POLL} must be greater than zero (received {poll}).")
    return poll


def resolve_env_target() -> Optional[str]:
    target = os.environ.get(ENV_TARGET)
    if not target:
        return None
    path = Path(target)
    if not path.exists():
        raise SystemExit(f"{ENV_TARGET}={target} is set but the device does not exist.")
    real = os.path.realpath(target)
    source_disk = os.path.realpath(parent_disk(resolve_mount_device("/")))
    if real == source_disk:
        raise SystemExit(
            f"{ENV_TARGET} points at the source disk ({source_disk}); choose another device."
        )
    return target


def determine_boot_mount(cli_value: Optional[str]) -> str:
    if cli_value:
        return cli_value
    env_value = os.environ.get(ENV_BOOT_MOUNT)
    if env_value:
        return env_value
    candidates = ["/boot/firmware", "/boot"]
    for candidate in candidates:
        result = subprocess.run(
            ["findmnt", "-no", "TARGET", candidate],
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
        if os.path.ismount(candidate):
            return candidate
    raise SystemExit(
        "Unable to determine the boot mountpoint. Specify --boot-mount or set " f"{ENV_BOOT_MOUNT}."
    )


def _pick_best_candidate(
    source_disk: str, source_size: int
) -> Optional[tuple[int, int, str, dict[str, object]]]:
    data = lsblk_json(["NAME", "KNAME", "TYPE", "TRAN", "HOTPLUG", "SIZE", "MODEL"])
    blockdevices = data.get("blockdevices", [])
    if not isinstance(blockdevices, list):
        raise SystemExit("Unexpected lsblk JSON structure: blockdevices should be a list.")
    best: Optional[tuple[int, int, str, dict[str, object]]] = None
    for entry in blockdevices:
        if not isinstance(entry, dict):
            continue
        if str(entry.get("type")) != "disk":
            continue
        name = entry.get("kname") or entry.get("name")
        if not isinstance(name, str) or not name:
            continue
        device = f"/dev/{name}"
        real = os.path.realpath(device)
        if real == source_disk:
            continue
        size = int(entry.get("size") or 0)
        if size < source_size:
            continue
        hotplug = int(entry.get("hotplug") or 0)
        tran = str(entry.get("tran") or "").lower()
        score = 0
        if hotplug:
            score += 100
        if tran in {"usb", "sata", "nvme"}:
            score += 40
        if "ssd" in str(entry.get("model") or "").lower():
            score += 5
        score += min(size // (1024**3), 100)
        candidate = (score, size, device, entry)
        if best is None or candidate > best:
            best = candidate
    return best


def auto_select_target(*, wait_secs: Optional[int] = None, poll_secs: Optional[int] = None) -> str:
    env_target = resolve_env_target()
    if env_target:
        return env_target
    wait = _read_wait_seconds(wait_secs)
    poll = _read_poll_seconds(poll_secs)
    source_disk = os.path.realpath(parent_disk(resolve_mount_device("/")))
    source_size = device_size_bytes(source_disk)
    failure_message = (
        "Unable to automatically determine a target disk. "
        "Attach an SSD and retry or set SUGARKUBE_SSD_CLONE_TARGET."
    )
    deadline = None if wait == 0 else time.monotonic() + wait
    waiting_announced = False
    while True:
        best = _pick_best_candidate(source_disk, source_size)
        if best:
            device = best[2]
            print(
                "Auto-selected clone target:",
                device,
                f"(model={best[3].get('model', 'unknown')}, size={best[1]} bytes)",
            )
            return device
        if wait == 0:
            raise SystemExit(failure_message)
        if deadline is not None and time.monotonic() >= deadline:
            raise SystemExit(failure_message)
        if not waiting_announced:
            print(
                "Waiting for an SSD to appear before cloning. "
                f"Polling every {poll} seconds (timeout {wait} seconds)."
            )
            waiting_announced = True
        time.sleep(poll)


def load_state(ctx: CloneContext) -> None:
    if not ctx.state_file.exists():
        ctx.state = {}
        return
    with ctx.state_file.open("r", encoding="utf-8") as handle:
        ctx.state = json.load(handle)


def save_state(ctx: CloneContext) -> None:
    if ctx.dry_run:
        return
    ctx.state.setdefault("target", ctx.target_disk)
    ctx.state.setdefault("completed", {})
    ctx.state_file.parent.mkdir(parents=True, exist_ok=True)
    with ctx.state_file.open("w", encoding="utf-8") as handle:
        json.dump(ctx.state, handle, indent=2, sort_keys=True)
        handle.write("\n")


def ensure_state_ready(ctx: CloneContext) -> None:
    if ctx.resume:
        if not ctx.state_file.exists():
            print("Warning: resume unavailable (state file missing); continuing fresh.")
            ctx.state = {}
            return
        load_state(ctx)
        recorded_target = ctx.state.get("target")
        if recorded_target and recorded_target != ctx.target_disk:
            raise SystemExit(
                f"State file references {recorded_target} but --target is {ctx.target_disk}."
            )
    else:
        if ctx.state_file.exists() and not ctx.dry_run:
            raise SystemExit(
                "A previous clone state exists. Use --resume to continue or remove the state file."
            )
        ctx.state = {}
        if not ctx.dry_run:
            save_state(ctx)


def resolve_mount_device(mountpoint: str) -> str:
    result = subprocess.run(
        ["findmnt", "-no", "SOURCE", mountpoint],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0 or not result.stdout.strip():
        raise SystemExit(f"Unable to determine device for mount {mountpoint}")
    source = result.stdout.strip()
    if source.startswith("PARTUUID="):
        partuuid = source.split("=", 1)[1]
        lookup = subprocess.run(
            ["blkid", "-t", f"PARTUUID={partuuid}", "-o", "device"],
            check=False,
            capture_output=True,
            text=True,
        )
        if lookup.returncode != 0 or not lookup.stdout.strip():
            raise SystemExit(f"Unable to resolve PARTUUID {partuuid} to a device")
        return lookup.stdout.strip()
    return source


def parent_disk(device: str) -> str:
    result = subprocess.run(
        ["lsblk", "-no", "PKNAME", device],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode == 0 and result.stdout.strip():
        return f"/dev/{result.stdout.strip()}"
    match = re.match(r"(/dev/\D+?)(p?\d+)$", device)
    if not match:
        raise SystemExit(f"Unable to determine parent disk for {device}")
    return match.group(1)


def partition_suffix(device: str) -> str:
    match = re.search(r"(p?)(\d+)$", device)
    if not match:
        raise SystemExit(f"Unable to determine partition suffix for {device}")
    return match.group(2)


def compose_partition(disk: str, number: str) -> str:
    if disk.endswith(tuple("0123456789")):
        return f"{disk}p{number}"
    return f"{disk}{number}"


def _parse_lsblk_pairs(line: str) -> Dict[str, str]:
    info: Dict[str, str] = {}
    for token in shlex.split(line):
        if "=" not in token:
            continue
        key, value = token.split("=", 1)
        info[key] = value.strip('"')
    return info


def _enumerate_partitions(disk: str) -> List[Dict[str, str]]:
    result = subprocess.run(
        ["lsblk", "-nrpo", "NAME,TYPE,FSTYPE,LABEL", "-P", disk],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise SystemExit(f"Unable to list partitions on {disk}")
    partitions: List[Dict[str, str]] = []
    for line in result.stdout.splitlines():
        info = _parse_lsblk_pairs(line)
        if info.get("TYPE") == "part":
            partitions.append(info)
    return partitions


def _collect_label_candidates(*labels: Optional[str]) -> Tuple[Set[str], List[str]]:
    display: List[str] = []
    normalized: Set[str] = set()
    for label in labels:
        if not label:
            continue
        lowered = label.casefold()
        if lowered in normalized:
            continue
        normalized.add(lowered)
        display.append(label)
    return normalized, display


def _select_partition(
    ctx: CloneContext,
    partitions: List[Dict[str, str]],
    *,
    expected_device: str,
    expected_fs: str,
    label_candidates: Set[str],
    label_display: List[str],
    kind: str,
) -> str:
    normalized_fs = canonical_fs(expected_fs)
    expected_info = next((p for p in partitions if p.get("NAME") == expected_device), None)
    if label_candidates:
        label_matches = [
            part for part in partitions if (part.get("LABEL") or "").casefold() in label_candidates
        ]
        if len(label_matches) == 1:
            return label_matches[0]["NAME"]
        if len(label_matches) > 1:
            found = ", ".join(
                sorted(
                    f"{part.get('NAME')} (LABEL={part.get('LABEL') or '""'})"
                    for part in label_matches
                )
            )
            labels = ", ".join(label_display)
            raise SystemExit(
                f"Multiple {kind} partitions on {ctx.target_disk} match labels {labels}: {found}. "
                "Provide unique labels or align numbering before using --skip-partition."
            )
    if expected_info:
        actual_fs = canonical_fs(expected_info.get("FSTYPE", ""))
        if actual_fs == normalized_fs or not expected_info.get("FSTYPE"):
            return expected_device
    fs_matches = [
        part for part in partitions if canonical_fs(part.get("FSTYPE", "")) == normalized_fs
    ]
    if len(fs_matches) == 1:
        return fs_matches[0]["NAME"]
    if len(fs_matches) > 1:
        found = ", ".join(sorted(part.get("NAME", "") for part in fs_matches))
        raise SystemExit(
            f"Multiple partitions on {ctx.target_disk} use filesystem {expected_fs}: {found}. "
            "Label the desired partition or align numbering before using --skip-partition."
        )
    if expected_info:
        actual_fs = expected_info.get("FSTYPE") or "unknown"
        raise SystemExit(
            (
                f"Target {kind} partition {expected_device} has filesystem {actual_fs}, "
                f"expected {expected_fs}. "
                "Do not use --skip-partition unless the target numbering matches the source."
            )
        )
    raise SystemExit(
        (
            "Unable to locate a "
            f"{kind} partition on {ctx.target_disk} matching filesystem {expected_fs}. "
            "Ensure the target layout matches the source or label the partition "
            "before using --skip-partition."
        )
    )


def resolve_target_partitions(ctx: CloneContext) -> (str, str):
    if ctx.target_boot and ctx.target_root:
        return ctx.target_boot, ctx.target_root
    boot_suffix = ctx.state.get("partition_suffix_boot")
    root_suffix = ctx.state.get("partition_suffix_root")
    if boot_suffix is None or root_suffix is None:
        raise SystemExit(
            "Missing partition suffix metadata; gather_source_metadata must run first."
        )
    boot_partition = compose_partition(ctx.target_disk, str(boot_suffix))
    root_partition = compose_partition(ctx.target_disk, str(root_suffix))
    if ctx.skip_partition:
        partitions = _enumerate_partitions(ctx.target_disk)
        if not partitions:
            raise SystemExit(
                f"No partitions detected on {ctx.target_disk}; cannot honor --skip-partition."
            )
        boot_labels, boot_display = _collect_label_candidates(
            ctx.state.get("target_boot_label"),
            ctx.state.get("source_boot_label"),
            ctx.boot_label,
        )
        root_labels, root_display = _collect_label_candidates(
            ctx.state.get("target_root_label"),
            ctx.state.get("source_root_label"),
            ctx.root_label,
        )
        boot_selected = _select_partition(
            ctx,
            partitions,
            expected_device=boot_partition,
            expected_fs=ctx.state["source_boot_fs"],
            label_candidates=boot_labels,
            label_display=boot_display,
            kind="boot",
        )
        root_selected = _select_partition(
            ctx,
            partitions,
            expected_device=root_partition,
            expected_fs=ctx.state["source_root_fs"],
            label_candidates=root_labels,
            label_display=root_display,
            kind="root",
        )
        changed = False
        if boot_selected != boot_partition:
            ctx.log(
                (
                    "Target boot partition numbering differs; using "
                    f"{boot_selected} instead of {boot_partition}."
                )
            )
            ctx.state["partition_suffix_boot"] = partition_suffix(boot_selected)
            boot_partition = boot_selected
            changed = True
        if root_selected != root_partition:
            ctx.log(
                (
                    "Target root partition numbering differs; using "
                    f"{root_selected} instead of {root_partition}."
                )
            )
            ctx.state["partition_suffix_root"] = partition_suffix(root_selected)
            root_partition = root_selected
            changed = True
        if changed:
            save_state(ctx)
    ctx.target_boot = boot_partition
    ctx.target_root = root_partition
    return boot_partition, root_partition


def detect_filesystem(device: str) -> str:
    result = subprocess.run(
        ["lsblk", "-no", "FSTYPE", device],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0 or not result.stdout.strip():
        raise SystemExit(f"Unable to detect filesystem for {device}")
    return result.stdout.strip()


def ensure_mount_point(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def mount_partition(ctx: CloneContext, device: str, mountpoint: Path) -> None:
    ensure_mount_point(mountpoint)
    run_command(ctx, ["mount", device, str(mountpoint)])
    ctx.register_mount(mountpoint)


def unmount_partition(ctx: CloneContext, mountpoint: Path) -> None:
    try:
        run_command(ctx, ["umount", str(mountpoint)])
    finally:
        ctx.unregister_mount(mountpoint)


def cleanup_mounts(ctx: Optional[CloneContext]) -> None:
    if ctx is None:
        return
    for mountpoint in reversed(list(ctx.mounted_paths)):
        subprocess.run(["umount", str(mountpoint)], check=False, capture_output=True)
        ctx.unregister_mount(mountpoint)


def partition_exists(device: str) -> bool:
    return Path(device).exists()


def canonical_fs(value: str) -> str:
    normalized = value.lower()
    if normalized in {"fat", "fat32"}:
        return "vfat"
    return normalized


def filesystem_matches(device: str, expected_fs: str) -> bool:
    if not partition_exists(device):
        return False
    result = subprocess.run(
        ["lsblk", "-no", "FSTYPE", device],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return False
    actual = (result.stdout or "").strip()
    if not actual:
        return False
    return canonical_fs(actual) == canonical_fs(expected_fs)


def read_label(device: str) -> Optional[str]:
    if not partition_exists(device):
        return None
    result = subprocess.run(
        ["blkid", "-s", "LABEL", "-o", "value", device],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return None
    label = (result.stdout or "").strip()
    return label or None


def labels_match(device: str, expected: Optional[str], *, allow_missing: bool = False) -> bool:
    if expected is None:
        return True
    actual = read_label(device)
    if actual is None:
        return allow_missing
    return actual == expected


def sanitize_fat_label(label: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9 _-]", "_", label or "")
    cleaned = cleaned.upper().strip()
    if len(cleaned) > FAT_LABEL_MAX:
        cleaned = cleaned[:FAT_LABEL_MAX]
    return cleaned or "SUGARKUBE"


def clamp_ext_label(label: str) -> str:
    if not label:
        return "sugarkube-root"
    if len(label) > EXT_LABEL_MAX:
        return label[:EXT_LABEL_MAX]
    return label


def replicate_partition_table(ctx: CloneContext) -> None:
    if ctx.skip_partition:
        ctx.log("Partition replication skipped via --skip-partition.")
        return
    source_disk = ctx.state["source_disk"]
    dump = subprocess.run(
        ["sfdisk", "--dump", source_disk],
        check=False,
        capture_output=True,
        text=True,
    )
    if dump.returncode != 0:
        raise SystemExit(f"Failed to dump partition table for {source_disk}")
    ctx.log(f"Replicating partition table from {source_disk} to {ctx.target_disk}")
    run_command(ctx, ["sgdisk", "--zap-all", ctx.target_disk])
    run_command(ctx, ["sfdisk", ctx.target_disk], input_text=dump.stdout)
    if ctx.refresh_uuid:
        randomize_disk_identifiers(ctx)
    run_command(ctx, ["partprobe", ctx.target_disk])


def randomize_disk_identifiers(ctx: CloneContext) -> None:
    """Ensure the target disk has unique GUIDs/IDs."""

    try:
        run_command(ctx, ["sgdisk", "-G", ctx.target_disk])
        return
    except CommandError:
        ctx.log("sgdisk -G failed; falling back to updating the DOS disk identifier.")
    disk_id = f"0x{secrets.randbits(32):08x}"
    run_command(ctx, ["sfdisk", "--disk-id", ctx.target_disk, disk_id])


def format_partitions(ctx: CloneContext) -> None:
    boot_fs = ctx.state["source_boot_fs"].lower()
    root_fs = ctx.state["source_root_fs"].lower()
    boot_partition, root_partition = resolve_target_partitions(ctx)
    if ctx.skip_format:
        ctx.log("Formatting skipped via --skip-format.")
        return
    if boot_fs not in {"vfat", "fat32", "fat"}:
        raise SystemExit(f"Unsupported boot filesystem {boot_fs}")
    if root_fs not in {"ext4", "ext3", "ext2"}:
        raise SystemExit(f"Unsupported root filesystem {root_fs}")
    existing_boot_label = read_label(boot_partition)
    boot_ready = filesystem_matches(boot_partition, "vfat") and (
        ctx.preserve_labels
        or labels_match(
            boot_partition,
            ctx.boot_label or ctx.state.get("source_boot_label"),
            allow_missing=True,
        )
    )
    if boot_ready:
        ctx.log("Boot partition already formatted with compatible filesystem; skipping mkfs.")
        if existing_boot_label:
            ctx.state["target_boot_label"] = existing_boot_label
    else:
        label = sanitize_fat_label(
            ctx.boot_label or ctx.state.get("source_boot_label") or "SUGARKUBE"
        )
        if ctx.preserve_labels:
            run_command(ctx, ["mkfs.vfat", "-F", "32", boot_partition])
        else:
            run_command(ctx, ["mkfs.vfat", "-F", "32", "-n", label, boot_partition])
        ctx.state["target_boot_label"] = label
    existing_root_label = read_label(root_partition)
    target_root_label = clamp_ext_label(
        ctx.root_label or ctx.state.get("source_root_label") or "sugarkube-root"
    )
    root_ready = filesystem_matches(root_partition, root_fs) and (
        ctx.preserve_labels or labels_match(root_partition, target_root_label, allow_missing=True)
    )
    if root_ready:
        ctx.log("Root partition already formatted with compatible filesystem; skipping mkfs.")
        if existing_root_label:
            ctx.state["target_root_label"] = existing_root_label
        return
    run_command(ctx, ["mkfs.ext4", "-F", "-L", target_root_label, root_partition])
    ctx.state["target_root_label"] = target_root_label


def sync_boot(ctx: CloneContext) -> None:
    boot_partition, _ = resolve_target_partitions(ctx)
    target_mount = ctx.mount_root / "boot"
    ensure_mount_point(target_mount)
    mount_partition(ctx, boot_partition, target_mount)
    try:
        source_boot = os.path.abspath(ctx.boot_mount)
        if not source_boot.endswith("/"):
            source_boot = f"{source_boot}/"
        rsync_args = [
            "rsync",
            "-aHAX",
            "--numeric-ids",
            "--partial",
            "--delete",
            "--info=progress2",
            source_boot,
            f"{target_mount}/",
        ]
        if ctx.dry_run:
            rsync_args.insert(1, "--dry-run")
        run_command(ctx, rsync_args)
    finally:
        unmount_partition(ctx, target_mount)


def sync_root(ctx: CloneContext) -> None:
    _, root_partition = resolve_target_partitions(ctx)
    target_mount = ctx.mount_root / "root"
    ensure_mount_point(target_mount)
    mount_partition(ctx, root_partition, target_mount)
    try:
        rsync_args = [
            "rsync",
            "-aHAX",
            "--numeric-ids",
            "--partial",
            "--inplace",
            "--delete",
            "--info=progress2",
            "--exclude",
            "dev/*",
            "--exclude",
            "proc/*",
            "--exclude",
            "sys/*",
            "--exclude",
            "tmp/*",
            "--exclude",
            "var/tmp/*",
            "--exclude",
            "run/*",
            "--exclude",
            "mnt/ssd-clone/*",
            "/",
            f"{target_mount}/",
        ]
        if ctx.dry_run:
            rsync_args.insert(1, "--dry-run")
        run_command(ctx, rsync_args)
    finally:
        unmount_partition(ctx, target_mount)


def update_configs(ctx: CloneContext) -> None:
    if ctx.dry_run:
        ctx.log("Would update cmdline.txt and fstab with the new PARTUUIDs once cloning completes.")
        return
    boot_partition, root_partition = resolve_target_partitions(ctx)
    boot_uuid = get_partuuid(boot_partition)
    root_uuid = get_partuuid(root_partition)
    boot_mount = ctx.mount_root / "boot-config"
    root_mount = ctx.mount_root / "root-config"
    ensure_mount_point(boot_mount)
    ensure_mount_point(root_mount)
    mount_partition(ctx, boot_partition, boot_mount)
    mount_partition(ctx, root_partition, root_mount)
    try:
        cmdline_path = boot_mount / "cmdline.txt"
        if cmdline_path.exists() and not ctx.dry_run:
            content = cmdline_path.read_text(encoding="utf-8")
            content = re.sub(r"root=PARTUUID=[^\s]+", f"root=PARTUUID={root_uuid}", content)
            cmdline_path.write_text(content, encoding="utf-8")
        fstab_path = root_mount / "etc" / "fstab"
        if fstab_path.exists() and not ctx.dry_run:
            content = fstab_path.read_text(encoding="utf-8")
            content = content.replace(ctx.state["source_root_partuuid"], root_uuid)
            if ctx.state.get("source_boot_partuuid"):
                content = content.replace(ctx.state["source_boot_partuuid"], boot_uuid)
            fstab_path.write_text(content, encoding="utf-8")
    finally:
        unmount_partition(ctx, root_mount)
        unmount_partition(ctx, boot_mount)


def get_partuuid(device: str) -> str:
    result = subprocess.run(
        ["blkid", "-s", "PARTUUID", "-o", "value", device],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0 or not result.stdout.strip():
        raise SystemExit(f"Unable to resolve PARTUUID for {device}")
    return result.stdout.strip()


def finalize(ctx: CloneContext) -> None:
    ctx.log("Clone completed successfully. Remember to run ssd_post_clone_validate.py.")
    if ctx.dry_run:
        return
    DONE_FILE.parent.mkdir(parents=True, exist_ok=True)
    DONE_FILE.write_text("Clone completed\n", encoding="utf-8")
    ctx.state.setdefault("completed", {})
    ctx.state["completed"]["finalize"] = True
    save_state(ctx)
    emit_summary(ctx)


def gather_source_metadata(ctx: CloneContext) -> None:
    source_root = resolve_mount_device("/")
    source_boot = resolve_mount_device(ctx.boot_mount)
    ctx.source_root = source_root
    ctx.source_boot = source_boot
    source_disk = os.path.realpath(parent_disk(source_root))
    target_disk = os.path.realpath(ctx.target_disk)
    if source_disk == target_disk:
        raise SystemExit("Target disk matches the source disk; choose a different device.")
    ctx.state.update(
        {
            "source_disk": source_disk,
            "partition_suffix_boot": partition_suffix(source_boot),
            "partition_suffix_root": partition_suffix(source_root),
            "source_root_partuuid": get_partuuid(source_root),
            "source_boot_partuuid": get_partuuid(source_boot),
            "source_boot_fs": detect_filesystem(source_boot),
            "source_root_fs": detect_filesystem(source_root),
            "source_boot_label": read_label(source_boot),
            "source_root_label": read_label(source_root),
            "source_size_bytes": device_size_bytes(source_disk),
        }
    )
    if not ctx.dry_run:
        save_state(ctx)


def prepare_labels(ctx: CloneContext) -> None:
    desired_boot = ctx.boot_label or ctx.state.get("source_boot_label") or "SUGARKUBE"
    sanitized_boot = sanitize_fat_label(desired_boot)
    if sanitized_boot != desired_boot:
        ctx.log(f"Boot label adjusted to {sanitized_boot} (from {desired_boot}).")
    ctx.boot_label = sanitized_boot
    desired_root = ctx.root_label or ctx.state.get("source_root_label") or "sugarkube-root"
    clamped_root = clamp_ext_label(desired_root)
    if clamped_root != desired_root:
        ctx.log(f"Root label adjusted to {clamped_root} (from {desired_root}).")
    ctx.root_label = clamped_root


def confirm_destruction(ctx: CloneContext) -> None:
    if ctx.dry_run:
        return
    if ctx.assume_yes:
        ctx.log("Assuming confirmation due to --assume-yes.")
        return
    prompt = (
        f"About to clone from {ctx.state.get('source_disk')} to {ctx.target_disk}. "
        "All data on the target will be erased. Continue? [y/N]: "
    )
    try:
        response = input(prompt)
    except EOFError:
        raise SystemExit("Clone aborted (no confirmation input).") from None
    if response.strip().lower() not in {"y", "yes"}:
        raise SystemExit("Clone aborted by user.")


def validate_partitions_present(ctx: CloneContext) -> bool:
    boot_partition, root_partition = resolve_target_partitions(ctx)
    return partition_exists(boot_partition) and partition_exists(root_partition)


def validate_format_matches(ctx: CloneContext) -> bool:
    boot_partition, root_partition = resolve_target_partitions(ctx)
    if not filesystem_matches(boot_partition, ctx.state["source_boot_fs"]):
        return False
    if not filesystem_matches(root_partition, ctx.state["source_root_fs"]):
        return False
    if ctx.preserve_labels:
        return True
    if not labels_match(boot_partition, ctx.boot_label, allow_missing=True):
        return False
    if not labels_match(root_partition, ctx.root_label, allow_missing=True):
        return False
    return True


def emit_summary(ctx: CloneContext) -> None:
    elapsed = time.monotonic() - ctx.start_time
    size_bytes = ctx.state.get("source_size_bytes")
    if size_bytes:
        size_str = f"{size_bytes} bytes ({size_bytes / (1024**3):.2f} GiB)"
    else:
        size_str = "unknown"
    ctx.log("Clone summary:")
    ctx.log(f"  Source disk: {ctx.state.get('source_disk', 'unknown')}")
    ctx.log(f"  Target disk: {ctx.target_disk}")
    ctx.log(f"  Boot mount: {ctx.boot_mount}")
    ctx.log(f"  Target mount root: {ctx.mount_root}")
    ctx.log(f"  Copied size: {size_str}")
    ctx.log(f"  Elapsed time: {elapsed:.1f} seconds")
    boot_uuid = ctx.state.get("target_boot_partuuid")
    root_uuid = ctx.state.get("target_root_partuuid")
    if boot_uuid:
        ctx.log(f"  Boot PARTUUID: {boot_uuid}")
    if root_uuid:
        ctx.log(f"  Root PARTUUID: {root_uuid}")
    boot_label = ctx.state.get("target_boot_label") or ctx.boot_label
    root_label = ctx.state.get("target_root_label") or ctx.root_label
    if boot_label:
        ctx.log(f"  Boot label: {boot_label}")
    if root_label:
        ctx.log(f"  Root label: {root_label}")


def handle_failure(ctx: Optional[CloneContext], error: BaseException) -> None:
    cleanup_mounts(ctx)
    if ctx is None or ctx.dry_run:
        return
    if ctx.state_file.exists():
        ctx.state_file.unlink(missing_ok=True)
    if DONE_FILE.exists():
        DONE_FILE.unlink(missing_ok=True)
    ERROR_LOG.parent.mkdir(parents=True, exist_ok=True)
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S%z", time.localtime())
    with ERROR_LOG.open("a", encoding="utf-8") as handle:
        handle.write(f"[{timestamp}] Clone failure: {error}\n")
        handle.write(
            "Hint: ensure target partitions are unmounted, then rerun with --resume or remove the "
            "state file.\n"
        )


def main() -> None:
    ensure_root()
    args = parse_args()
    if args.auto_target:
        target_disk = auto_select_target()
    else:
        target_disk = args.target
    boot_mount = determine_boot_mount(args.boot_mount)
    ctx = CloneContext(
        target_disk=os.path.realpath(target_disk),
        dry_run=args.dry_run,
        verbose=args.verbose,
        resume=args.resume,
        assume_yes=args.assume_yes,
        skip_partition=args.skip_partition,
        skip_format=args.skip_format,
        skip_to=normalize_skip_to(args.skip_to),
        preserve_labels=args.preserve_labels,
        refresh_uuid=args.refresh_uuid,
        boot_label=args.boot_label,
        root_label=args.root_label,
        boot_mount=boot_mount,
        state_file=args.state_file,
    )
    ctx.mount_root = args.mount_root
    ensure_mount_point(ctx.mount_root)
    if not Path(ctx.target_disk).exists():
        raise SystemExit(f"Target device {ctx.target_disk} does not exist.")
    ensure_state_ready(ctx)
    gather_source_metadata(ctx)
    prepare_labels(ctx)
    confirm_destruction(ctx)
    validators = {
        "partition": validate_partitions_present,
        "format": validate_format_matches,
    }
    steps = {
        "partition": replicate_partition_table,
        "format": format_partitions,
        "sync_boot": sync_boot,
        "sync_root": sync_root,
        "update_configs": update_configs,
        "finalize": finalize,
    }
    try:
        for step in [
            Step("partition", "Replicating partition table", validators.get("partition")),
            Step("format", "Formatting target partitions", validators.get("format")),
            Step("sync_boot", "Synchronizing boot partition"),
            Step("sync_root", "Synchronizing root filesystem"),
            Step("update_configs", "Updating cmdline.txt and fstab"),
            Step("finalize", "Writing completion marker"),
        ]:
            step.run(ctx, steps[step.name])
        ctx.log("All steps complete. Reboot once validation succeeds.")
    except Exception as error:
        handle_failure(ctx, error)
        raise


if __name__ == "__main__":
    try:
        main()
    except CommandError as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(1)
    except Exception as error:  # pragma: no cover - defensive cleanup
        print(str(error), file=sys.stderr)
        raise SystemExit(1)
