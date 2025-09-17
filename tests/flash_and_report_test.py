import json
import os
import subprocess
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
SCRIPT = BASE_DIR / "scripts" / "flash_and_report.py"


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

    env = os.environ.copy()
    env["SUGARKUBE_FLASH_ALLOW_NONROOT"] = "1"
    result = subprocess.run(cmd, capture_output=True, text=True, env=env)
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
    assert data["device"]["eject_behavior"] == "forced-no-eject-for-verification"
    assert "diff" in data["cloud_init"]

    flashed_bytes = device_path.read_bytes()
    expanded_sha = data["image"]["expanded_sha256"]
    import hashlib

    assert hashlib.sha256(flashed_bytes).hexdigest() == expanded_sha
    assert flashed_bytes == payload
