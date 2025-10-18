"""Unit tests for the QEMU smoke test harness."""

from __future__ import annotations

import importlib.util
import json
import lzma
import shutil
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


def test_decompress_image_copies_into_work_dir(tmp_path: Path) -> None:
    source_dir = tmp_path / "src"
    work_dir = tmp_path / "work"
    source_dir.mkdir()
    work_dir.mkdir()
    source = source_dir / "sugarkube.img"
    source.write_bytes(b"contents")

    dest = MODULE.decompress_image(source, work_dir)

    assert dest != source
    assert dest.read_bytes() == b"contents"


def test_detect_machine_prefers_raspi4(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(command, **kwargs):  # noqa: ANN001 - mimic subprocess signature
        assert command == ["qemu", "-machine", "help"]
        return subprocess.CompletedProcess(
            command,
            0,
            stdout="raspi4    Raspberry Pi 4\nraspi3    Raspberry Pi 3\n",
            stderr="",
        )

    monkeypatch.setattr(MODULE.subprocess, "run", fake_run)

    assert MODULE._detect_machine("qemu") == "raspi4"


def test_detect_machine_falls_back_to_raspi3(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(command, **kwargs):  # noqa: ANN001 - mimic subprocess signature
        assert command == ["qemu", "-machine", "help"]
        return subprocess.CompletedProcess(
            command,
            0,
            stdout="virt-2.12  Generic Virt\nraspi3    Raspberry Pi 3\n",
            stderr="",
        )

    monkeypatch.setattr(MODULE.subprocess, "run", fake_run)

    assert MODULE._detect_machine("qemu") == "raspi3"


def test_run_helper_adds_sudo(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[list[str], dict[str, object]]] = []

    def fake_run(command, **kwargs):  # noqa: ANN001 - mimic subprocess signature
        calls.append((list(command), kwargs))
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(MODULE.subprocess, "run", fake_run)

    MODULE._run(["echo", "hi"], sudo=True, capture_output=True, text=False)

    assert calls
    executed, kwargs = calls[0]
    assert executed[:2] == ["sudo", "-n"]
    assert executed[2:] == ["echo", "hi"]
    assert kwargs["capture_output"] is True
    assert kwargs["text"] is False


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
        if command and command[0] == "install":
            try:
                flag_index = command.index("-T")
            except ValueError as exc:  # pragma: no cover - defensive
                raise AssertionError("install invocation missing -T flag") from exc
            source = Path(command[flag_index + 1])
            dest = Path(command[flag_index + 2])
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, dest)
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(MODULE, "_run", fake_run)

    prepared = MODULE.prepare_image(image, tmp_path)
    stub = root_dir / MODULE.STUB_VERIFIER_PATH.relative_to("/")
    dropin = root_dir / "etc/systemd/system/first-boot.service.d" / MODULE.DROPIN_NAME

    assert stub.exists()
    stub_text = stub.read_text()
    assert "Sugarkube smoke verifier" in stub_text
    assert '"pi_home_repos"' in stub_text
    assert dropin.exists()
    dropin_text = dropin.read_text()
    assert f"Environment=FIRST_BOOT_VERIFIER={MODULE.STUB_VERIFIER_PATH}" in dropin_text
    assert "Environment=PYTHONUNBUFFERED=1" in dropin_text
    assert "StandardOutput=journal+console" in dropin_text
    assert "StandardError=journal+console" in dropin_text
    assert prepared.kernel.name == "kernel8.img"
    assert prepared.dtb.name == "bcm2711-rpi-4-b.dtb"
    assert "root=/dev/mmcblk0p2" in prepared.cmdline
    marker = root_dir / "var/log/sugarkube/rootfs-expanded"
    assert marker.exists()
    assert any(cmd[0] == "losetup" for cmd in outputs)


def test_attach_loop_requires_loop_device(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(command, **_):
        if command[:2] == ["losetup", "--find"]:
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")
        raise AssertionError("unexpected command")

    monkeypatch.setattr(MODULE, "_run", fake_run)

    with pytest.raises(MODULE.SmokeTestError):
        with MODULE.attach_loop(Path("image.img")):
            pass


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

    monkeypatch.setattr(MODULE, "_detect_machine", lambda *_: "raspi4")

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

    monkeypatch.setattr(MODULE, "_detect_machine", lambda *_: "raspi4")
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

    monkeypatch.setattr(MODULE, "_detect_machine", lambda *_: "raspi4")
    monkeypatch.setattr(MODULE.subprocess, "Popen", lambda *_, **__: process)

    with pytest.raises(MODULE.SmokeTestError):
        MODULE.run_qemu(prepared, timeout=5, qemu_binary="qemu", log_path=log_path)


class StubbornProcess:
    def __init__(self) -> None:
        self.stdout = self
        self.returncode: int | None = None
        self.terminated = False
        self.killed = False

    def __iter__(self) -> "StubbornProcess":
        return self

    def __next__(self) -> str:
        raise StopIteration

    def wait(self, timeout: float | None = None) -> int:
        if self.killed or self.returncode is not None:
            return self.returncode or 0
        raise subprocess.TimeoutExpired(cmd=["qemu"], timeout=timeout)

    def terminate(self) -> None:
        self.terminated = True

    def kill(self) -> None:
        self.killed = True
        self.returncode = -9

    def poll(self) -> int | None:
        return self.returncode


def test_run_qemu_kills_unresponsive_process(
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

    process = StubbornProcess()

    def fake_monotonic_factory():
        value = -0.6

        def fake_monotonic() -> float:
            nonlocal value
            value += 0.6
            return value

        return fake_monotonic

    monkeypatch.setattr(MODULE, "_detect_machine", lambda *_: "raspi4")
    monkeypatch.setattr(MODULE.subprocess, "Popen", lambda *_, **__: process)
    monkeypatch.setattr(MODULE.time, "monotonic", fake_monotonic_factory())

    with pytest.raises(MODULE.SmokeTestError):
        MODULE.run_qemu(prepared, timeout=1, qemu_binary="qemu", log_path=log_path)

    assert process.terminated is True
    assert process.killed is True


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


def test_collect_reports_overwrites_existing(
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

    dest = tmp_path / "artifacts"
    existing_report = dest / "first-boot-report"
    existing_report.mkdir(parents=True)
    (existing_report / "old.txt").write_text("old\n")
    existing_state = dest / "sugarkube-state"
    existing_state.mkdir(parents=True)
    (existing_state / "old.txt").write_text("old\n")

    def fake_run(command, **_):
        if command[:2] == ["losetup", "--find"]:
            return subprocess.CompletedProcess(command, 0, stdout="/dev/loop3\n", stderr="")
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(MODULE, "_run", fake_run)

    MODULE.collect_reports(image, tmp_path, dest)

    assert not (existing_report / "old.txt").exists()
    assert (dest / "first-boot-report" / "summary.json").exists()
    assert not (existing_state / "old.txt").exists()
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


def test_main_tolerates_missing_serial_markers_when_reports_exist(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    image = tmp_path / "image.img"
    image.write_text("i")

    def fake_decompress(*_, **__):  # noqa: ARG001 - compat
        return image

    def fake_prepare(*_, **__):  # noqa: ARG001 - compat
        return MODULE.PreparedImage(image, image, image, "")

    def fake_run(*_, **__):  # noqa: ARG001 - compat
        raise MODULE.SmokeTestError("first-boot success markers not observed in serial output")

    def fake_collect(_image: Path, _work: Path, dest: Path) -> None:
        report_dir = dest / "first-boot-report"
        report_dir.mkdir(parents=True, exist_ok=True)
        (report_dir / "summary.json").write_text("{}\n")
        state_dir = dest / "sugarkube-state"
        state_dir.mkdir(parents=True, exist_ok=True)
        (state_dir / "first-boot.ok").write_text("ok\n")

    monkeypatch.setattr(MODULE, "decompress_image", fake_decompress)
    monkeypatch.setattr(MODULE, "prepare_image", fake_prepare)
    monkeypatch.setattr(MODULE, "run_qemu", fake_run)
    monkeypatch.setattr(MODULE, "collect_reports", fake_collect)

    artifacts = tmp_path / "artifacts"
    exit_code = MODULE.main(
        [
            "--image",
            str(image),
            "--artifacts-dir",
            str(artifacts),
        ]
    )

    assert exit_code == 0
    summary = json.loads((artifacts / "smoke-success.json").read_text())
    assert summary["status"] == "pass"


def test_main_requires_ok_marker_or_passing_summary(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    image = tmp_path / "image.img"
    image.write_text("i")

    def fake_decompress(*_, **__):  # noqa: ARG001 - compat
        return image

    def fake_prepare(*_, **__):  # noqa: ARG001 - compat
        return MODULE.PreparedImage(image, image, image, "")

    def fake_run(*_, **__):  # noqa: ARG001 - compat
        raise MODULE.SmokeTestError("first-boot success markers not observed in serial output")

    def fake_collect(_image: Path, _work: Path, dest: Path) -> None:
        report_dir = dest / "first-boot-report"
        report_dir.mkdir(parents=True, exist_ok=True)
        (report_dir / "summary.json").write_text(json.dumps({"overall": "fail"}))
        # intentionally omit first-boot.ok marker

    monkeypatch.setattr(MODULE, "decompress_image", fake_decompress)
    monkeypatch.setattr(MODULE, "prepare_image", fake_prepare)
    monkeypatch.setattr(MODULE, "run_qemu", fake_run)
    monkeypatch.setattr(MODULE, "collect_reports", fake_collect)

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
    error = json.loads((artifacts / "error.json").read_text())
    assert error["error"] == "first-boot success markers not observed in serial output"


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
