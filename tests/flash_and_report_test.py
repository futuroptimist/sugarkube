import importlib.util
import json
import os
import subprocess
import sys
import types
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
SCRIPT = BASE_DIR / "scripts" / "flash_and_report.py"


def _load_flash_module():
    spec = importlib.util.spec_from_file_location("flash_and_report", SCRIPT)
    if spec is None or spec.loader is None:
        raise AssertionError("Unable to load flash_and_report module")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _create_image(tmp_path: Path, size: int = 1024 * 64) -> tuple[Path, bytes]:
    raw = tmp_path / "sugarkube.img"
    payload = os.urandom(size)
    raw.write_bytes(payload)

    import lzma

    xz_path = tmp_path / "sugarkube.img.xz"
    with lzma.open(xz_path, "wb", preset=3) as dest:
        dest.write(raw.read_bytes())
    return xz_path, payload


def test_flash_and_report_generates_artifacts(tmp_path):
    image_xz, payload = _create_image(tmp_path)
    device_path = tmp_path / "device.img"
    device_path.write_bytes(b"\x00" * len(payload))
    expected = tmp_path / "expected.yaml"
    observed = tmp_path / "observed.yaml"

    expected.write_text("#cloud-config\nwrite_files: []\n", encoding="utf-8")
    observed.write_text(
        "#cloud-config\nwrite_files:\n  - path: /etc/example\n",
        encoding="utf-8",
    )

    cmd = [
        sys.executable,
        str(SCRIPT),
        "--image",
        str(image_xz),
        "--device",
        str(device_path),
        "--report-dir",
        str(tmp_path),
        "--cloud-init-expected",
        str(expected),
        "--cloud-init-observed",
        str(observed),
    ]

    result = subprocess.run(cmd, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr

    reports = sorted(tmp_path.glob("flash-report-*.md"))
    assert reports, "markdown report missing"
    report_md = reports[-1]
    report_html = report_md.with_suffix(".html")
    report_json = report_md.with_suffix(".json")

    assert report_html.exists(), "html report missing"
    assert report_json.exists(), "json report missing"

    md_content = report_md.read_text(encoding="utf-8")
    assert "Device SHA-256" in md_content
    assert "cloud-init diff" in md_content

    data = json.loads(report_json.read_text(encoding="utf-8"))
    assert data["device"]["verification"] == "match"
    assert "diff" in data["cloud_init"]
    assert "--no-eject" in data["device"]["command"], "flash wrapper should keep device online"
    assert data["device"].get("forced_no_eject") is True

    flashed_bytes = device_path.read_bytes()
    expanded_sha = data["image"]["expanded_sha256"]
    import hashlib

    assert hashlib.sha256(flashed_bytes).hexdigest() == expanded_sha
    assert flashed_bytes == payload


def test_describe_device_includes_system_id(monkeypatch, tmp_path):
    module = _load_flash_module()

    device_path = tmp_path / "device"
    device_path.write_bytes(b"")

    dummy = types.SimpleNamespace(
        path=str(device_path),
        description="Mock Device",
        is_removable=True,
        human_size="1 GB",
        bus="usb",
        mountpoints=["/media/mock"],
        system_id=42,
    )

    monkeypatch.setattr(
        module,
        "flash_pi_media",
        types.SimpleNamespace(discover_devices=lambda: [dummy]),
        raising=False,
    )

    info = module._describe_device(str(device_path))
    assert info["system_id"] == 42
    assert info["description"] == "Mock Device"
