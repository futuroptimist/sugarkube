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
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

STATE_DIR = Path("/var/log/sugarkube")
STATE_FILE = STATE_DIR / "ssd-clone.state.json"
DONE_FILE = STATE_DIR / "ssd-clone.done"
MOUNT_ROOT = Path("/mnt/ssd-clone")
ENV_TARGET = "SUGARKUBE_SSD_CLONE_TARGET"
ENV_EXTRA_ARGS = "SUGARKUBE_SSD_CLONE_EXTRA_ARGS"


class CommandError(RuntimeError):
    """Raised when an external command fails."""


@dataclass
class CloneContext:
    """Context shared across clone steps."""

    target_disk: str
    dry_run: bool
    verbose: bool
    resume: bool
    state_file: Path = STATE_FILE
    state: Dict[str, object] = field(default_factory=dict)
    source_root: Optional[str] = None
    source_boot: Optional[str] = None
    target_root: Optional[str] = None
    target_boot: Optional[str] = None
    mount_root: Optional[Path] = None

    def log(self, message: str) -> None:
        prefix = "[DRY-RUN] " if self.dry_run else ""
        print(f"{prefix}{message}")


@dataclass
class Step:
    """Represent a clone step with a unique identifier."""

    name: str
    description: str

    def run(self, ctx: CloneContext, func) -> None:
        if ctx.state.get("completed", {}).get(self.name):
            ctx.log(f"Skipping {self.name} (already completed).")
            return
        ctx.log(f"==> {self.description}")
        func(ctx)
        if not ctx.dry_run:
            completed = ctx.state.setdefault("completed", {})
            completed[self.name] = True
            save_state(ctx)


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


def _env_extra_args() -> List[str]:
    raw = os.environ.get(ENV_EXTRA_ARGS, "").strip()
    if not raw:
        return []
    try:
        return shlex.split(raw)
    except ValueError as error:
        raise SystemExit(f"Invalid {ENV_EXTRA_ARGS}: {error}") from error


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
        "--verbose",
        action="store_true",
        help="Show stdout/stderr from helper commands.",
    )
    env_args = _env_extra_args()
    cli_args = list(argv) if argv is not None else sys.argv[1:]
    return parser.parse_args([*env_args, *cli_args])


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


def auto_select_target() -> str:
    env_target = resolve_env_target()
    if env_target:
        return env_target
    source_disk = os.path.realpath(parent_disk(resolve_mount_device("/")))
    source_size = device_size_bytes(source_disk)
    data = lsblk_json(["NAME", "KNAME", "TYPE", "TRAN", "HOTPLUG", "SIZE", "MODEL"])
    blockdevices = data.get("blockdevices", [])
    if not isinstance(blockdevices, list):
        raise SystemExit("Unexpected lsblk JSON structure; expected a list of block devices.")
    best: Optional[Tuple[int, int, str, Dict[str, object]]] = None
    for entry in blockdevices:
        if str(entry.get("type")) != "disk":
            continue
        name = entry.get("kname") or entry.get("name")
        if not name:
            continue
        device = f"/dev/{name}"
        real = os.path.realpath(device)
        if real == source_disk:
            continue
        size = int(entry.get("size") or 0)
        if size < source_size:
            # Skip disks that cannot hold the source contents.
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
        # Prefer larger disks to leave headroom.
        score += min(size // (1024**3), 100)
        candidate = (score, size, device, entry)
        if best is None or candidate > best:
            best = candidate
    if not best:
        raise SystemExit(
            "Unable to automatically determine a target disk. "
            "Attach an SSD and retry or set SUGARKUBE_SSD_CLONE_TARGET."
        )
    device = best[2]
    print(
        "Auto-selected clone target:",
        device,
        f"(model={best[3].get('model', 'unknown')}, size={best[1]} bytes)",
    )
    return device


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


def unmount_partition(ctx: CloneContext, mountpoint: Path) -> None:
    run_command(ctx, ["umount", str(mountpoint)])


def replicate_partition_table(ctx: CloneContext) -> None:
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
    boot_partition = compose_partition(ctx.target_disk, ctx.state["partition_suffix_boot"])
    root_partition = compose_partition(ctx.target_disk, ctx.state["partition_suffix_root"])
    if boot_fs not in {"vfat", "fat32", "fat"}:
        raise SystemExit(f"Unsupported boot filesystem {boot_fs}")
    if root_fs not in {"ext4", "ext3", "ext2"}:
        raise SystemExit(f"Unsupported root filesystem {root_fs}")
    run_command(ctx, ["mkfs.vfat", "-F", "32", "-n", "SUGARKUBE_BOOT", boot_partition])
    run_command(ctx, ["mkfs.ext4", "-F", "-L", "sugarkube-root", root_partition])
    ctx.target_boot = boot_partition
    ctx.target_root = root_partition


def sync_boot(ctx: CloneContext) -> None:
    boot_partition = ctx.target_boot or compose_partition(
        ctx.target_disk, ctx.state["partition_suffix_boot"]
    )
    target_mount = ctx.mount_root / "boot"
    ensure_mount_point(target_mount)
    mount_partition(ctx, boot_partition, target_mount)
    try:
        rsync_args = [
            "rsync",
            "-aHAX",
            "--numeric-ids",
            "--partial",
            "--delete",
            "--info=progress2",
            "/boot/",
            f"{target_mount}/",
        ]
        if ctx.dry_run:
            rsync_args.insert(1, "--dry-run")
        run_command(ctx, rsync_args)
    finally:
        unmount_partition(ctx, target_mount)


def sync_root(ctx: CloneContext) -> None:
    root_partition = ctx.target_root or compose_partition(
        ctx.target_disk, ctx.state["partition_suffix_root"]
    )
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
    boot_partition = compose_partition(ctx.target_disk, ctx.state["partition_suffix_boot"])
    root_partition = compose_partition(ctx.target_disk, ctx.state["partition_suffix_root"])
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


def gather_source_metadata(ctx: CloneContext) -> None:
    source_root = resolve_mount_device("/")
    source_boot = resolve_mount_device("/boot")
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
        }
    )
    if not ctx.dry_run:
        save_state(ctx)


def main() -> None:
    ensure_root()
    args = parse_args()
    if args.auto_target:
        target_disk = auto_select_target()
    else:
        target_disk = args.target
    ctx = CloneContext(
        target_disk=os.path.realpath(target_disk),
        dry_run=args.dry_run,
        verbose=args.verbose,
        resume=args.resume,
        state_file=args.state_file,
    )
    ctx.mount_root = args.mount_root
    ensure_mount_point(ctx.mount_root)
    if not Path(ctx.target_disk).exists():
        raise SystemExit(f"Target device {ctx.target_disk} does not exist.")
    ensure_state_ready(ctx)
    gather_source_metadata(ctx)
    steps = {
        "partition": replicate_partition_table,
        "format": format_partitions,
        "sync_boot": sync_boot,
        "sync_root": sync_root,
        "update_configs": update_configs,
        "finalize": finalize,
    }
    for step in [
        Step("partition", "Replicating partition table"),
        Step("format", "Formatting target partitions"),
        Step("sync_boot", "Synchronizing boot partition"),
        Step("sync_root", "Synchronizing root filesystem"),
        Step("update_configs", "Updating cmdline.txt and fstab"),
        Step("finalize", "Writing completion marker"),
    ]:
        step.run(ctx, steps[step.name])
    ctx.log("All steps complete. Reboot once validation succeeds.")


if __name__ == "__main__":
    try:
        main()
    except CommandError as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(1)
