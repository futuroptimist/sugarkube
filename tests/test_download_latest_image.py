import hashlib
import io
import sys
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # noqa: E402

import scripts.download_latest_image as download_latest_image  # noqa: E402

API = "https://api.github.com"
REPO = "futuroptimist/sugarkube"
WORKFLOW = "pi-image.yml"


def _zip_bytes(filename: str, content: bytes, sha_file: str) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr(filename, content)
        digest = hashlib.sha256(content).hexdigest()
        z.writestr(sha_file, f"{digest}  {filename}\n")
    return buf.getvalue()


def test_no_runs_exits_nonzero(requests_mock):
    requests_mock.get(
        f"{API}/repos/{REPO}/actions/workflows/{WORKFLOW}/runs",
        json={"workflow_runs": []},
    )
    assert download_latest_image.main([]) == 1


def test_no_artifact_match(requests_mock):
    now = datetime.now(timezone.utc).isoformat()
    run = {
        "id": 1,
        "updated_at": now,
        "artifacts_url": f"{API}/run/1/artifacts",
    }
    requests_mock.get(
        f"{API}/repos/{REPO}/actions/workflows/{WORKFLOW}/runs",
        json={"workflow_runs": [run]},
    )
    requests_mock.get(
        run["artifacts_url"],
        json={"artifacts": [{"name": "other", "archive_download_url": "url"}]},
    )
    pattern = ["--artifact-pattern", "pi-image-*.img.xz"]
    assert download_latest_image.main(pattern) == 1


def test_too_old_run_respects_max_age(requests_mock):
    old = (datetime.now(timezone.utc) - timedelta(hours=5)).isoformat()
    run = {
        "id": 2,
        "updated_at": old,
        "artifacts_url": f"{API}/run/2/artifacts",
    }
    requests_mock.get(
        f"{API}/repos/{REPO}/actions/workflows/{WORKFLOW}/runs",
        json={"workflow_runs": [run]},
    )
    assert download_latest_image.main(["--max-age-hours", "1"]) == 1


def test_success_downloads_and_validates_checksum(
    tmp_path, requests_mock, capsys, monkeypatch
):
    content = b"data"
    zip_bytes = _zip_bytes(
        "pi-image-pi5-heatset.img.xz",
        content,
        "pi-image-pi5-heatset.img.xz.sha256",
    )
    now = datetime.now(timezone.utc).isoformat()
    run = {
        "id": 3,
        "updated_at": now,
        "artifacts_url": f"{API}/run/3/artifacts",
    }
    art = {
        "name": "pi-image-pi5-heatset-123",
        "archive_download_url": f"{API}/artifact/3.zip",
    }
    requests_mock.get(
        f"{API}/repos/{REPO}/actions/workflows/{WORKFLOW}/runs",
        json={"workflow_runs": [run]},
    )
    requests_mock.get(run["artifacts_url"], json={"artifacts": [art]})
    requests_mock.get(art["archive_download_url"], content=zip_bytes)
    monkeypatch.chdir(tmp_path)
    assert download_latest_image.main([]) == 0
    out = capsys.readouterr().out.strip()
    digest = hashlib.sha256(content).hexdigest()
    assert out == f"pi-image-pi5-heatset.img.xz {digest}"
    assert (tmp_path / "pi-image-pi5-heatset.img.xz").exists()
    assert (tmp_path / "pi-image-pi5-heatset.img.xz.sha256").exists()
