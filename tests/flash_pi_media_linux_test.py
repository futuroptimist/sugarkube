"""Linux-specific flash_pi_media hardware ID coverage."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import flash_pi_media as flash


class DummyCompletedProcess:
    def __init__(self, stdout: str):
        self.returncode = 0
        self.stdout = stdout


def _make_device(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.touch()
    return path


def test_resolve_linux_system_id_prefers_by_id(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    device = _make_device(tmp_path / "dev" / "sda")
    by_id = tmp_path / "by-id"
    by_id.mkdir()
    (by_id / "usb-TestDisk-123").symlink_to(device)

    monkeypatch.setattr(flash, "LINUX_BY_ID_ROOT", by_id)
    monkeypatch.setattr(flash, "LINUX_SYS_BLOCK_ROOT", tmp_path / "sys-block")

    identifier = flash._resolve_linux_system_id(str(device))
    assert identifier == "usb-TestDisk-123"


def test_resolve_linux_system_id_reads_sysfs_serial(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    device = _make_device(tmp_path / "dev" / "sdb")
    by_id = tmp_path / "empty-by-id"
    by_id.mkdir()
    sys_block = tmp_path / "sys-block"
    serial_path = sys_block / "sdb" / "device" / "serial"
    serial_path.parent.mkdir(parents=True, exist_ok=True)
    serial_path.write_text("SER123\n", encoding="utf-8")

    monkeypatch.setattr(flash, "LINUX_BY_ID_ROOT", by_id)
    monkeypatch.setattr(flash, "LINUX_SYS_BLOCK_ROOT", sys_block)

    identifier = flash._resolve_linux_system_id(str(device))
    assert identifier == "SER123"


def test_list_linux_devices_uses_serial_from_lsblk(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    payload = {
        "blockdevices": [
            {
                "type": "disk",
                "name": "sdc",
                "path": "/dev/sdc",
                "size": "1048576",
                "model": "TestDisk",
                "rm": 1,
                "tran": "usb",
                "serial": "SERIAL-XYZ",
            }
        ]
    }
    monkeypatch.setattr(flash.shutil, "which", lambda _: "/bin/lsblk")
    monkeypatch.setattr(
        flash,
        "_run",
        lambda *args, **kwargs: DummyCompletedProcess(json.dumps(payload)),
    )
    monkeypatch.setattr(flash, "LINUX_BY_ID_ROOT", tmp_path / "by-id")
    monkeypatch.setattr(flash, "LINUX_SYS_BLOCK_ROOT", tmp_path / "sys-block")

    devices = flash._list_linux_devices()
    assert devices
    assert devices[0].system_id == "SERIAL-XYZ"


def test_list_linux_devices_falls_back_to_by_id(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    payload = {
        "blockdevices": [
            {
                "type": "disk",
                "name": "sdd",
                "path": "/dev/sdd",
                "size": "2097152",
                "model": "TestDisk",
                "rm": 1,
                "tran": "usb",
            }
        ]
    }
    by_id = tmp_path / "by-id"
    by_id.mkdir()
    device_path = tmp_path / "dev" / "sdd"
    _make_device(device_path)
    (by_id / "usb-TestDisk-999").symlink_to(device_path)

    monkeypatch.setattr(flash.shutil, "which", lambda _: "/bin/lsblk")
    monkeypatch.setattr(
        flash,
        "_run",
        lambda *args, **kwargs: DummyCompletedProcess(json.dumps(payload)),
    )
    monkeypatch.setattr(flash, "LINUX_BY_ID_ROOT", by_id)
    monkeypatch.setattr(flash, "LINUX_SYS_BLOCK_ROOT", tmp_path / "sys-block")

    devices = flash._list_linux_devices()
    assert devices
    assert devices[0].system_id == "usb-TestDisk-999"


def test_resolve_boot_partition_linux(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    payload = {
        "blockdevices": [
            {
                "type": "disk",
                "path": "/dev/sdz",
                "children": [
                    {"path": "/dev/sdz1", "start": "2048", "mountpoint": "/mnt/boot"},
                    {"path": "/dev/sdz2", "start": "4096"},
                ],
            }
        ]
    }
    monkeypatch.setattr(flash.shutil, "which", lambda _: "/bin/lsblk")
    monkeypatch.setattr(
        flash,
        "_run",
        lambda *args, **kwargs: DummyCompletedProcess(json.dumps(payload)),
    )

    partition = flash._resolve_boot_partition_linux(
        flash.Device(path="/dev/sdz", description="disk", size=0, is_removable=True)
    )

    assert partition is not None
    assert partition.path == "/dev/sdz1"
    assert partition.mountpoint == "/mnt/boot"
