"""Unit tests for the QEMU smoke test harness."""

from __future__ import annotations

import importlib.util
import json
import lzma
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

MODULE_PATH = Path(__file__).resolve().parent.parent / "scripts" / "qemu_pi_smoke_test.py"
SPEC = importlib.util.spec_from_file_location("qemu_smoke", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def test_decompress_image_expands_xz(tmp_path: Path) -> None:
    source = tmp_path / "sugarkube.img.xz"
    raw = tmp_path / "raw.img"
    raw.write_bytes(b"data")
    with lzma.open(source, "wb") as handle:
        handle.write(raw.read_bytes())

    dest = MODULE.decompress_image(source, tmp_path)
    assert dest.exists()
    assert dest.read_bytes() == b"data"


def test_decompress_image_copies_plain_file(tmp_path: Path) -> None:
    source = tmp_path / "sugarkube.img"
    source.write_bytes(b"abc")
    dest = MODULE.decompress_image(source, tmp_path)
    assert dest.read_bytes() == b"abc"


def test_normalise_cmdline_rewrites_root_and_console() -> None:
    result = MODULE._normalise_cmdline("root=PARTUUID=123 quiet")
    assert "root=/dev/mmcblk0p2" in result
    assert "console=ttyAMA0,115200" in result
    assert "sugarkube.smoketest=1" in result


def test_find_dtb_prefers_config(tmp_path: Path) -> None:
    boot = tmp_path
    (boot / "config.txt").write_text("device_tree=bcm2712-rpi-5-b.dtb\n")
    expected = boot / "bcm2712-rpi-5-b.dtb"
    expected.write_text("dtb")
    assert MODULE._find_dtb(boot) == expected


def test_find_dtb_falls_back(tmp_path: Path) -> None:
    candidate = tmp_path / "bcm2711-rpi-4-b.dtb"
    candidate.write_text("dtb")
    assert MODULE._find_dtb(tmp_path) == candidate


def test_prepare_image_installs_stub_and_dropin(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    image = tmp_path / "sugarkube.img"
    image.write_bytes(b"fake")

    boot_dir = tmp_path / "mnt-boot"
    root_dir = tmp_path / "mnt-root"
    boot_dir.mkdir()
    root_dir.mkdir()
    (boot_dir / "kernel8.img").write_text("kernel")
    (boot_dir / "cmdline.txt").write_text("root=PARTUUID=dead quiet")
    (boot_dir / "bcm2711-rpi-4-b.dtb").write_text("dtb")

    outputs = []

    def fake_run(command, **_):
        outputs.append(command)
        if command[:2] == ["losetup", "--find"]:
            return subprocess.CompletedProcess(command, 0, stdout="/dev/loop7\n", stderr="")
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(MODULE, "_run", fake_run)

    prepared = MODULE.prepare_image(image, tmp_path)
    stub = root_dir / MODULE.STUB_VERIFIER_PATH.relative_to("/")
    dropin = root_dir / "etc/systemd/system/first-boot.service.d" / MODULE.DROPIN_NAME

    assert stub.exists()
    assert "Sugarkube smoke verifier" in stub.read_text()
    assert dropin.exists()
    assert f"Environment=FIRST_BOOT_VERIFIER={MODULE.STUB_VERIFIER_PATH}" in dropin.read_text()
    assert prepared.kernel.name == "kernel8.img"
    assert prepared.dtb.name == "bcm2711-rpi-4-b.dtb"
    assert "root=/dev/mmcblk0p2" in prepared.cmdline
    marker = root_dir / "var/log/sugarkube/rootfs-expanded"
    assert marker.exists()
    assert any(cmd[0] == "losetup" for cmd in outputs)


class FakeProcess:
    def __init__(self, lines: list[str]) -> None:
        self._lines = iter(lines)
        self.stdout = self
        self.returncode: int | None = None

    def __iter__(self) -> "FakeProcess":
        return self

    def __next__(self) -> str:
        try:
            return next(self._lines)
        except StopIteration as exc:
            if self.returncode is None:
                self.returncode = 0
            raise exc

    def terminate(self) -> None:
        self.returncode = 0

    def wait(self, timeout: int | None = None) -> int:
        if self.returncode is None:
            raise subprocess.TimeoutExpired(cmd=["qemu"], timeout=timeout)
        return self.returncode

    def kill(self) -> None:
        self.returncode = -9

    def poll(self) -> int | None:
        return self.returncode


def test_run_qemu_records_success(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    log_path = tmp_path / "serial.log"
    prepared = MODULE.PreparedImage(
        image_path=tmp_path / "image.img",
        kernel=tmp_path / "kernel8.img",
        dtb=tmp_path / "bcm2711-rpi-4-b.dtb",
        cmdline="console=ttyAMA0",
    )
    prepared.kernel.write_text("k")
    prepared.dtb.write_text("d")

    process = FakeProcess(
        [
            "Booting...\n",
            "[first-boot] summary.json written\n",
        ]
    )

    monkeypatch.setattr(
        MODULE.subprocess,
        "Popen",
        lambda *_, **__: process,
    )

    MODULE.run_qemu(prepared, timeout=30, qemu_binary="qemu", log_path=log_path)
    assert "summary" in log_path.read_text()


def test_run_qemu_raises_on_timeout(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    log_path = tmp_path / "serial.log"
    prepared = MODULE.PreparedImage(
        image_path=tmp_path / "image.img",
        kernel=tmp_path / "kernel8.img",
        dtb=tmp_path / "bcm2711-rpi-4-b.dtb",
        cmdline="console=ttyAMA0",
    )
    prepared.kernel.write_text("k")
    prepared.dtb.write_text("d")

    process = FakeProcess(["still booting\n"])

    monkeypatch.setattr(MODULE.subprocess, "Popen", lambda *_, **__: process)

    with pytest.raises(MODULE.SmokeTestError):
        MODULE.run_qemu(prepared, timeout=0, qemu_binary="qemu", log_path=log_path)


def test_run_qemu_raises_if_process_exits_without_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    log_path = tmp_path / "serial.log"
    prepared = MODULE.PreparedImage(
        image_path=tmp_path / "image.img",
        kernel=tmp_path / "kernel8.img",
        dtb=tmp_path / "bcm2711-rpi-4-b.dtb",
        cmdline="console=ttyAMA0",
    )
    prepared.kernel.write_text("k")
    prepared.dtb.write_text("d")

    process = FakeProcess(["booting\n", "still booting\n"])

    monkeypatch.setattr(MODULE.subprocess, "Popen", lambda *_, **__: process)

    with pytest.raises(MODULE.SmokeTestError):
        MODULE.run_qemu(prepared, timeout=5, qemu_binary="qemu", log_path=log_path)


def test_collect_reports_copies_directories(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    image = tmp_path / "image.img"
    image.write_bytes(b"data")

    boot_dir = tmp_path / "collect-boot"
    root_dir = tmp_path / "collect-root"
    boot_dir.mkdir()
    root_dir.mkdir(parents=True, exist_ok=True)
    report = boot_dir / "first-boot-report"
    report.mkdir()
    (report / "summary.json").write_text("{}\n")
    state = root_dir / "var/log/sugarkube"
    state.mkdir(parents=True)
    (state / "first-boot.ok").write_text("ok\n")

    def fake_run(command, **_):
        if command[:2] == ["losetup", "--find"]:
            return subprocess.CompletedProcess(command, 0, stdout="/dev/loop0\n", stderr="")
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(MODULE, "_run", fake_run)

    dest = tmp_path / "artifacts"
    MODULE.collect_reports(image, tmp_path, dest)
    assert (dest / "first-boot-report" / "summary.json").exists()
    assert (dest / "sugarkube-state" / "first-boot.ok").exists()


def test_collect_reports_missing_summary(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    image = tmp_path / "image.img"
    image.write_bytes(b"data")

    boot_dir = tmp_path / "collect-boot"
    boot_dir.mkdir()

    def fake_run(command, **_):
        if command[:2] == ["losetup", "--find"]:
            return subprocess.CompletedProcess(command, 0, stdout="/dev/loop2\n", stderr="")
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(MODULE, "_run", fake_run)

    with pytest.raises(MODULE.SmokeTestError):
        MODULE.collect_reports(image, tmp_path, tmp_path / "dest")


def test_main_success(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    image = tmp_path / "image.img"
    image.write_text("i")

    called = SimpleNamespace(decompress=False, prepare=False, run=False, collect=False)

    def fake_decompress(src, dest):  # noqa: ARG001 - signature compatibility
        called.decompress = True
        return image

    monkeypatch.setattr(MODULE, "decompress_image", fake_decompress)

    def fake_prepare(img, work):
        called.prepare = True
        return MODULE.PreparedImage(img, work / "kernel8.img", work / "bcm.dtb", "cmd")

    monkeypatch.setattr(MODULE, "prepare_image", fake_prepare)

    def fake_run(prepared, **_):
        called.run = True

    monkeypatch.setattr(MODULE, "run_qemu", fake_run)

    def fake_collect(*_, **__):
        called.collect = True

    monkeypatch.setattr(MODULE, "collect_reports", fake_collect)

    artifacts = tmp_path / "artifacts"
    exit_code = MODULE.main(
        [
            "--image",
            str(image),
            "--artifacts-dir",
            str(artifacts),
            "--qemu-binary",
            "qemu",
            "--timeout",
            "10",
        ]
    )
    assert exit_code == 0
    summary = json.loads((artifacts / "smoke-success.json").read_text())
    assert summary["status"] == "pass"
    assert called.decompress and called.prepare and called.run and called.collect


def test_main_records_errors(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    image = tmp_path / "image.img"
    image.write_text("i")

    def fake_decompress(*_, **__):  # noqa: ARG001 - compat
        return image

    def fake_prepare(*_, **__):  # noqa: ARG001 - compat
        return MODULE.PreparedImage(image, image, image, "")

    def fake_run(*_, **__):  # noqa: ARG001 - compat
        raise MODULE.SmokeTestError("boom")

    monkeypatch.setattr(MODULE, "decompress_image", fake_decompress)
    monkeypatch.setattr(MODULE, "prepare_image", fake_prepare)
    monkeypatch.setattr(MODULE, "run_qemu", fake_run)

    artifacts = tmp_path / "artifacts"
    exit_code = MODULE.main(
        [
            "--image",
            str(image),
            "--artifacts-dir",
            str(artifacts),
        ]
    )
    assert exit_code == 1
    payload = json.loads((artifacts / "error.json").read_text())
    assert payload["error"] == "boom"
