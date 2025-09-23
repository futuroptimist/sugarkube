#!/usr/bin/env python3
"""Boot freshly built Sugarkube images inside QEMU for a smoke test."""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import lzma
import shutil
import subprocess
import sys
import tempfile
import textwrap
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, Sequence


class SmokeTestError(RuntimeError):
    """Raised when the QEMU smoke test cannot complete successfully."""


STUB_VERIFIER_PATH = Path("/opt/smoketest/pi_node_verifier_stub.sh")
DROPIN_NAME = "zz-smoketest.conf"
SERIAL_SUCCESS_MARKERS = (
    "[first-boot] first-boot already completed successfully",
    "[first-boot] appending verifier report",
    "[first-boot] summary.json",
)


@dataclass(slots=True)
class PreparedImage:
    image_path: Path
    kernel: Path
    dtb: Path
    cmdline: str


def _run(
    command: Sequence[str],
    *,
    sudo: bool = False,
    check: bool = True,
    capture_output: bool = False,
    text: bool = True,
    **kwargs,
) -> subprocess.CompletedProcess[str]:
    full_cmd: list[str] = list(command)
    if sudo:
        full_cmd = ["sudo", "-n", *full_cmd]
    return subprocess.run(  # noqa: PLW1510 - deliberate pass-through
        full_cmd,
        check=check,
        capture_output=capture_output,
        text=text,
        **kwargs,
    )


def decompress_image(source: Path, work_dir: Path) -> Path:
    """Return the raw image path, expanding `.xz` archives when necessary."""

    if source.suffix == ".xz":
        dest = work_dir / source.with_suffix("").name
        with lzma.open(source, "rb") as src, dest.open("wb") as dst:
            shutil.copyfileobj(src, dst)
        return dest

    dest = work_dir / source.name
    if dest == source:
        return dest
    shutil.copy2(source, dest)
    return dest


@contextlib.contextmanager
def attach_loop(image: Path) -> Iterator[str]:
    result = _run(
        ["losetup", "--find", "--show", "-P", str(image)],
        sudo=True,
        capture_output=True,
    )
    loop_device = result.stdout.strip()
    if not loop_device:
        raise SmokeTestError("losetup did not return a loop device path")
    try:
        yield loop_device
    finally:
        _run(["losetup", "-d", loop_device], sudo=True, check=False)


@contextlib.contextmanager
def mount_partition(device: str, mount_point: Path) -> Iterator[Path]:
    mount_point.mkdir(parents=True, exist_ok=True)
    _run(["mount", "-o", "rw", device, str(mount_point)], sudo=True)
    try:
        yield mount_point
    finally:
        _run(["umount", str(mount_point)], sudo=True, check=False)


def _normalise_cmdline(text: str) -> str:
    tokens = text.split()
    updated: list[str] = []
    has_console = False
    for entry in tokens:
        if entry.startswith("root="):
            entry = "root=/dev/mmcblk0p2"
        if entry.startswith("console=ttyAMA0"):
            has_console = True
        updated.append(entry)
    if not has_console:
        updated.append("console=ttyAMA0,115200")
    if "sugarkube.smoketest=1" not in updated:
        updated.append("sugarkube.smoketest=1")
    return " ".join(updated)


def _find_dtb(boot_dir: Path) -> Path:
    config = boot_dir / "config.txt"
    if config.exists():
        for raw_line in config.read_text().splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("device_tree="):
                dtb_name = line.split("=", 1)[1].strip()
                candidate = boot_dir / dtb_name
                if candidate.exists():
                    return candidate

    for candidate_name in (
        "bcm2712-rpi-5-b.dtb",
        "bcm2711-rpi-4-b.dtb",
        "bcm2710-rpi-3-b-plus.dtb",
    ):
        candidate = boot_dir / candidate_name
        if candidate.exists():
            return candidate
    raise SmokeTestError("Unable to locate a Raspberry Pi device tree blob")


def _install_stub(root_dir: Path) -> None:
    target = root_dir / STUB_VERIFIER_PATH.relative_to("/")
    target.parent.mkdir(parents=True, exist_ok=True)
    script = textwrap.dedent(
        """
        #!/usr/bin/env bash
        set -euo pipefail

        json=false
        enable_log=true
        report_path=""

        while [[ $# -gt 0 ]]; do
          case "$1" in
            --json)
              json=true
              ;;
            --log)
              if [[ $# -lt 2 ]]; then
                echo "--log requires a path" >&2
                exit 1
              fi
              report_path="$2"
              shift
              ;;
            --log=*)
              report_path="${1#*=}"
              ;;
            --no-log)
              enable_log=false
              ;;
            --help)
              cat <<'USAGE'
        Usage: pi_node_verifier_stub.sh [--json] [--log PATH] [--no-log]
        USAGE
              exit 0
              ;;
          esac
          shift
        done

        read -r -d '' payload <<'JSON' || true
{"checks":[
  {"name":"cloud_init","status":"pass"},
  {"name":"k3s_node_ready","status":"skip"},
  {"name":"projects_compose_active","status":"skip"},
  {"name":"token_place_http","status":"skip"},
  {"name":"dspace_http","status":"skip"}
]}
JSON

        if $json; then
          printf '%s\n' "$payload"
        else
          printf 'Sugarkube smoke verifier: all checks passed\\n'
        fi

        if $enable_log && [[ -n "$report_path" ]]; then
          mkdir -p "$(dirname "$report_path")"
          {
            printf '# Sugarkube Smoke Test\\n'
            printf '\nAll checks passed in QEMU smoke mode.\\n'
          } >>"$report_path"
        fi
        """
    ).strip()
    target.write_text(script + "\n")
    target.chmod(0o755)


def _install_dropin(root_dir: Path) -> None:
    dropin_dir = root_dir / "etc/systemd/system/first-boot.service.d"
    dropin_dir.mkdir(parents=True, exist_ok=True)
    dropin = dropin_dir / DROPIN_NAME
    content = textwrap.dedent(
        f"""
        [Service]
        Environment=FIRST_BOOT_VERIFIER={STUB_VERIFIER_PATH}
        Environment=FIRST_BOOT_SKIP_LOG=1
        Environment=FIRST_BOOT_ATTEMPTS=1
        Environment=FIRST_BOOT_RETRY_DELAY=5
        Environment=FIRST_BOOT_CLOUD_INIT_TIMEOUT=180
        Environment=TOKEN_PLACE_HEALTH_URL=skip
        Environment=DSPACE_HEALTH_URL=skip
        """
    ).strip()
    dropin.write_text(content + "\n")


def prepare_image(image: Path, work_dir: Path) -> PreparedImage:
    with attach_loop(image) as loop:
        boot_device = f"{loop}p1"
        root_device = f"{loop}p2"
        boot_mount = work_dir / "mnt-boot"
        root_mount = work_dir / "mnt-root"

        with mount_partition(boot_device, boot_mount) as boot_dir:
            kernel = boot_dir / "kernel8.img"
            if not kernel.exists():
                raise SmokeTestError("kernel8.img missing from boot partition")
            kernel_dest = work_dir / kernel.name
            shutil.copy2(kernel, kernel_dest)

            dtb_source = _find_dtb(boot_dir)
            dtb_dest = work_dir / dtb_source.name
            shutil.copy2(dtb_source, dtb_dest)

            cmdline_path = boot_dir / "cmdline.txt"
            if not cmdline_path.exists():
                raise SmokeTestError("cmdline.txt missing from boot partition")
            cmdline = _normalise_cmdline(cmdline_path.read_text().strip())

        with mount_partition(root_device, root_mount) as root_dir:
            _install_stub(root_dir)
            _install_dropin(root_dir)
            expand_marker = root_dir / "var/log/sugarkube/rootfs-expanded"
            expand_marker.parent.mkdir(parents=True, exist_ok=True)
            expand_marker.write_text("qemu-smoke\n")

    return PreparedImage(image, kernel_dest, dtb_dest, cmdline)


def _stream_qemu_output(process: subprocess.Popen[str], log_file: io.TextIOBase) -> Iterator[str]:
    assert process.stdout is not None
    for line in process.stdout:
        log_file.write(line)
        log_file.flush()
        yield line


def run_qemu(
    prepared: PreparedImage,
    *,
    timeout: int,
    qemu_binary: str = "qemu-system-aarch64",
    log_path: Path,
) -> None:
    command = [
        qemu_binary,
        "-M",
        "raspi4",
        "-smp",
        "4",
        "-m",
        "2048",
        "-kernel",
        str(prepared.kernel),
        "-dtb",
        str(prepared.dtb),
        "-append",
        prepared.cmdline,
        "-drive",
        f"file={prepared.image_path},format=raw,if=sd",
        "-serial",
        "stdio",
        "-display",
        "none",
        "-monitor",
        "none",
        "-no-reboot",
        "-object",
        "rng-random,filename=/dev/urandom,id=rng0",
        "-device",
        "virtio-rng-device,rng=rng0",
        "-device",
        "usb-net,netdev=net0",
        "-netdev",
        "user,id=net0",
    ]

    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("w", encoding="utf-8") as log_file:
        process = subprocess.Popen(  # noqa: S603 - command constructed above
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )

        success_flag = threading.Event()
        stream_done = threading.Event()

        def reader() -> None:
            try:
                for line in _stream_qemu_output(process, log_file):
                    if any(marker in line for marker in SERIAL_SUCCESS_MARKERS):
                        success_flag.set()
                        break
            finally:
                stream_done.set()

        reader_thread = threading.Thread(target=reader, daemon=True)
        reader_thread.start()

        start = time.monotonic()
        success = False
        try:
            while True:
                if success_flag.is_set():
                    success = True
                    break

                elapsed = time.monotonic() - start
                if elapsed > timeout:
                    raise SmokeTestError(
                        f"Timed out after {timeout}s waiting for first-boot completion"
                    )

                remaining = timeout - elapsed
                try:
                    process.wait(timeout=min(1.0, remaining))
                except subprocess.TimeoutExpired:
                    continue
                else:
                    success = success_flag.is_set()
                    break
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=60)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
            stream_done.wait(timeout=5)
            reader_thread.join(timeout=5)

        if not success:
            raise SmokeTestError("first-boot success markers not observed in serial output")


def collect_reports(image: Path, work_dir: Path, dest: Path) -> None:
    with attach_loop(image) as loop:
        boot_device = f"{loop}p1"
        root_device = f"{loop}p2"
        boot_mount = work_dir / "collect-boot"
        root_mount = work_dir / "collect-root"

        dest.mkdir(parents=True, exist_ok=True)

        with mount_partition(boot_device, boot_mount) as boot_dir:
            report_dir = boot_dir / "first-boot-report"
            if not report_dir.exists():
                raise SmokeTestError("first-boot-report directory was not generated")
            target = dest / "first-boot-report"
            if target.exists():
                shutil.rmtree(target)
            shutil.copytree(report_dir, target)

        with mount_partition(root_device, root_mount) as root_dir:
            state_dir = root_dir / "var/log/sugarkube"
            if state_dir.exists():
                target = dest / "sugarkube-state"
                if target.exists():
                    shutil.rmtree(target)
                shutil.copytree(state_dir, target)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--image",
        type=Path,
        required=True,
        help="Path to the built sugarkube.img or sugarkube.img.xz file",
    )
    parser.add_argument(
        "--artifacts-dir",
        type=Path,
        required=True,
        help="Directory to store serial logs and generated reports",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=540,
        help="Seconds to wait for first boot completion",
    )
    parser.add_argument(
        "--qemu-binary",
        default="qemu-system-aarch64",
        help="Override the qemu-system binary (default: qemu-system-aarch64)",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    artifacts_dir: Path = args.artifacts_dir
    artifacts_dir.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="sugarkube-qemu-") as tmpdir:
        work_dir = Path(tmpdir)
        try:
            image = decompress_image(args.image, work_dir)
            prepared = prepare_image(image, work_dir)
            run_qemu(
                prepared,
                timeout=args.timeout,
                qemu_binary=args.qemu_binary,
                log_path=artifacts_dir / "serial.log",
            )
            collect_reports(image, work_dir, artifacts_dir)
        except SmokeTestError as exc:
            (artifacts_dir / "error.json").write_text(
                json.dumps({"error": str(exc)}, indent=2) + "\n"
            )
            print(f"ERROR: {exc}", file=sys.stderr)
            return 1

    (artifacts_dir / "smoke-success.json").write_text(
        json.dumps({"status": "pass"}, indent=2) + "\n"
    )
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    sys.exit(main())
