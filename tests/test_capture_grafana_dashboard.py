import argparse
import json
import stat
import struct
import sys
import zlib
from datetime import datetime, timezone
from email.message import Message
from io import BytesIO
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import capture_grafana_dashboard as capture  # noqa: E402


def chunk(kind, payload):
    return (
        struct.pack(">I", len(payload))
        + kind
        + payload
        + struct.pack(">I", zlib.crc32(kind + payload))
    )


def png():
    return (
        capture.PNG_SIGNATURE
        + chunk(b"IHDR", struct.pack(">IIBBBBB", 2, 1, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(b"\0" * 7))
        + chunk(b"IEND", b"")
    )


def arguments(tmp_path, **overrides):
    fields = dict(
        url="https://grafana.example.internal/grafana",
        environment="staging",
        start="now-30d",
        end="now",
        panel_id=35,
        width=2,
        height=1,
        output_dir=str(tmp_path),
    )
    fields.update(overrides)
    return argparse.Namespace(**fields)


class Renderer:
    def __init__(self, body=None, status=200, content_type="image/png"):
        self.body = png() if body is None else body
        self.status = status
        self.content_type = content_type
        self.request = None

    def open(self, request, timeout):
        self.request = request
        assert timeout == 180
        response = BytesIO(self.body)
        response.status = self.status
        response.headers = Message()
        response.headers["Content-Type"] = self.content_type
        return response


@pytest.mark.parametrize("environment,panel_id", [("staging", 35), ("prod", None)])
def test_capture_preserves_absolute_window_and_private_artifacts(tmp_path, environment, panel_id):
    renderer = Renderer()
    now = datetime(2026, 10, 1, tzinfo=timezone.utc)
    args = arguments(tmp_path, environment=environment, panel_id=panel_id)
    path = capture.capture(args, "local-test-credential", renderer, now)
    route = "d-solo" if panel_id is not None else "d"
    parsed = urlsplit(renderer.request.full_url)
    assert parsed.path == (
        f"/grafana/render/{route}/sugarkube-{environment}-observability/observability"
    )
    query = parse_qs(parsed.query)
    assert int(query["to"][0]) - int(query["from"][0]) == 30 * 86400 * 1000
    assert query["tz"] == ["UTC"]
    assert renderer.request.get_header("Authorization") == "Bearer local-test-credential"
    assert "local-test-credential" not in renderer.request.full_url
    assert path.read_bytes() == png()
    metadata = path.with_suffix(".json")
    document = json.loads(metadata.read_text())
    assert document["environment"] == environment
    assert document["panel_id"] == panel_id
    assert "local-test-credential" not in metadata.read_text()
    for artifact in (path, metadata):
        assert stat.S_IMODE(artifact.stat().st_mode) == 0o600


@pytest.mark.parametrize(
    "body,status,content_type",
    [
        (b"renderer unavailable", 200, "text/html"),
        (b"not an image", 200, "image/png"),
        (png()[:-1], 200, "image/png"),
        (png(), 503, "image/png"),
    ],
)
def test_failed_render_never_creates_evidence(tmp_path, body, status, content_type):
    with pytest.raises(ValueError):
        capture.capture(
            arguments(tmp_path), "local-test-credential", Renderer(body, status, content_type)
        )
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize(
    "overrides",
    [
        {"url": "https://user:credential@example.internal"},
        {"url": "https://example.internal?credential=secret"},
        {"url": "file:///tmp/grafana"},
        {"start": "now", "end": "now-6h"},
        {"start": "yesterday"},
        {"width": 0},
        {"height": 16001},
        {"panel_id": -1},
    ],
)
def test_invalid_capture_configuration_is_rejected_before_request(tmp_path, overrides):
    renderer = Renderer()
    with pytest.raises(ValueError):
        capture.capture(arguments(tmp_path, **overrides), "local-test-credential", renderer)
    assert renderer.request is None
    assert not list(tmp_path.iterdir())


def test_redirects_cannot_forward_credentials():
    assert capture.NoRedirect().redirect_request(None, None, 302, "", {}, "https://other") is None


def test_renderer_is_pinned_but_disabled_on_pi_nodes_and_retention_is_preserved():
    path = ROOT / "platform/observability/helm/kube-prometheus-stack.values.common.yaml"
    values = yaml.safe_load(path.read_text())
    renderer = values["grafana"]["imageRenderer"]
    assert renderer["enabled"] is False
    assert renderer["image"]["tag"] == "5.12.5"
    assert renderer["healthcheckPath"] == "/healthz"
    assert renderer["existingSecret"] == "grafana-renderer-auth"
    assert renderer["resources"]["requests"] == {"cpu": "4", "memory": "16Gi"}
    spec = values["prometheus"]["prometheusSpec"]
    assert (spec["retention"], spec["retentionSize"]) == ("90d", "100GB")


def test_optional_producer_dependencies_are_visible_in_both_dashboards():
    for environment in ("staging", "prod"):
        path = ROOT / (
            f"clusters/{environment}/observability/dashboards/"
            f"sugarkube-{environment}-observability.json"
        )
        panels = json.loads(path.read_text())["panels"]
        for panel in panels:
            if panel["title"].startswith("Daniel") and panel["type"] != "row":
                assert "Requires the optional" in panel["description"]
                assert panel["fieldConfig"]["defaults"]["noValue"] == "NO DATA"


@pytest.mark.parametrize("failed_write", [1, 2])
@pytest.mark.parametrize("failure", [OSError, KeyboardInterrupt])
def test_write_failure_removes_only_this_capture(tmp_path, monkeypatch, failed_write, failure):
    existing = tmp_path / "previous-capture.png"
    existing.write_bytes(b"previous evidence")
    original_fdopen = capture.os.fdopen
    writes = 0

    class InterruptedWrite:
        def __init__(self, descriptor, mode):
            self.stream = original_fdopen(descriptor, mode)

        def __enter__(self):
            return self

        def __exit__(self, *args):
            self.stream.close()

        def flush(self):
            self.stream.flush()

        def fileno(self):
            return self.stream.fileno()

        def write(self, payload):
            nonlocal writes
            writes += 1
            if writes == failed_write:
                self.stream.write(payload[:8])
                raise failure("simulated interrupted write")
            return self.stream.write(payload)

    monkeypatch.setattr(capture.os, "fdopen", InterruptedWrite)
    with pytest.raises(failure):
        capture.capture(arguments(tmp_path), "local-test-credential", Renderer())
    assert list(tmp_path.iterdir()) == [existing]
    assert existing.read_bytes() == b"previous evidence"


def test_existing_sidecar_is_preserved_on_collision(tmp_path):
    now = datetime(2026, 10, 1, tzinfo=timezone.utc)
    sidecar = tmp_path / "sugarkube-staging-observability-panel-35-20261001T000000000000Z.json"
    sidecar.write_bytes(b"previous metadata")
    with pytest.raises(FileExistsError):
        capture.capture(arguments(tmp_path), "local-test-credential", Renderer(), now)
    assert list(tmp_path.iterdir()) == [sidecar]
    assert sidecar.read_bytes() == b"previous metadata"


@pytest.mark.parametrize("failed_sync", [1, 2, 3])
def test_sync_failure_removes_incomplete_evidence(tmp_path, monkeypatch, failed_sync):
    syncs = 0

    def failing_sync(descriptor):
        nonlocal syncs
        syncs += 1
        if syncs == failed_sync:
            raise OSError("simulated durability failure")

    monkeypatch.setattr(capture.os, "fsync", failing_sync)
    with pytest.raises(OSError):
        capture.capture(arguments(tmp_path), "local-test-credential", Renderer())
    assert not list(tmp_path.iterdir())


def test_epoch_milliseconds_are_preserved():
    assert capture.instant("1790812800000", 0) == 1790812800000


@pytest.mark.parametrize("credential", ["", "invalid\ncredential", "invalid\rcredential"])
def test_invalid_credential_is_rejected_before_request(tmp_path, credential):
    renderer = Renderer()
    with pytest.raises(ValueError):
        capture.capture(arguments(tmp_path), credential, renderer)
    assert renderer.request is None


@pytest.mark.parametrize("prompt", [False, True])
@pytest.mark.parametrize("succeeds", [False, True])
def test_cli_credentials_output_and_safe_errors(tmp_path, monkeypatch, capsys, prompt, succeeds):
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "capture_grafana_dashboard.py",
            "--url",
            "https://grafana.example.internal",
            "--environment",
            "staging",
            "--width",
            "2",
            "--height",
            "1",
            "--output-dir",
            str(tmp_path),
        ],
    )
    credential = "private-cli-credential"
    if prompt:
        monkeypatch.delenv("GRAFANA_CAPTURE_CREDENTIAL", raising=False)
        monkeypatch.setattr(capture.getpass, "getpass", lambda message: credential)
    else:
        monkeypatch.setenv("GRAFANA_CAPTURE_CREDENTIAL", credential)
        monkeypatch.setattr(
            capture.getpass, "getpass", lambda message: pytest.fail("unexpected prompt")
        )
    renderer = Renderer() if succeeds else Renderer(body=b"error " + credential.encode())
    monkeypatch.setattr(capture.urllib.request, "build_opener", lambda *args: renderer)
    assert capture.main() == (0 if succeeds else 1)
    output = capsys.readouterr()
    assert credential not in output.out + output.err
    assert renderer.request.get_header("Authorization") == "Bearer " + credential
    if succeeds:
        assert Path(output.out.strip()).is_file()
        assert output.err == ""
    else:
        assert output.out == ""
        assert "Capture failed" in output.err
        assert not list(tmp_path.iterdir())


def test_script_entry_point(tmp_path, monkeypatch):
    import runpy

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "capture_grafana_dashboard.py",
            "--url",
            "https://grafana.example.internal",
            "--environment",
            "prod",
            "--width",
            "2",
            "--height",
            "1",
            "--output-dir",
            str(tmp_path),
        ],
    )
    monkeypatch.setenv("GRAFANA_CAPTURE_CREDENTIAL", "local-test-credential")
    monkeypatch.setattr(capture.urllib.request, "build_opener", lambda *args: Renderer())
    with pytest.raises(SystemExit) as result:
        runpy.run_path(str(ROOT / "scripts/capture_grafana_dashboard.py"), run_name="__main__")
    assert result.value.code == 0
    assert len(list(tmp_path.iterdir())) == 2


@pytest.mark.parametrize("mode", [0o777, 0o770, 0o755])
def test_existing_output_directory_must_be_private(tmp_path, mode):
    destination = tmp_path / "unsafe"
    destination.mkdir(mode=mode)
    destination.chmod(mode)
    with pytest.raises(ValueError, match="private permissions"):
        capture.capture(arguments(destination), "local-test-credential", Renderer())
    assert not list(destination.iterdir())


def test_output_directory_symlink_is_rejected(tmp_path):
    target = tmp_path / "target"
    target.mkdir(mode=0o700)
    destination = tmp_path / "link"
    destination.symlink_to(target, target_is_directory=True)
    with pytest.raises(OSError):
        capture.capture(arguments(destination), "local-test-credential", Renderer())
    assert not list(target.iterdir())


def test_output_directory_owner_must_match(tmp_path, monkeypatch):
    actual_uid = capture.os.getuid()
    monkeypatch.setattr(capture.os, "getuid", lambda: actual_uid + 1)
    with pytest.raises(ValueError, match="owned by this user"):
        capture.capture(arguments(tmp_path), "local-test-credential", Renderer())
    assert not list(tmp_path.iterdir())


def test_artifacts_use_verified_directory_descriptor(tmp_path, monkeypatch):
    original_open = capture.os.open
    opened_directory = None
    relative_opens = []

    def verified_open(path, flags, mode=0o777, *, dir_fd=None):
        nonlocal opened_directory
        descriptor = original_open(path, flags, mode, dir_fd=dir_fd)
        if flags & capture.os.O_DIRECTORY:
            assert flags & capture.os.O_NOFOLLOW
            opened_directory = descriptor
        elif flags & capture.os.O_CREAT:
            assert dir_fd == opened_directory
            assert Path(path).name == path
            relative_opens.append(path)
        return descriptor

    monkeypatch.setattr(capture.os, "open", verified_open)
    capture.capture(arguments(tmp_path), "local-test-credential", Renderer())
    assert len(relative_opens) == 2


def malformed_pngs():
    header = chunk(b"IHDR", struct.pack(">IIBBBBB", 2, 1, 8, 2, 0, 0, 0))
    data = chunk(b"IDAT", zlib.compress(b"\0" * 7))
    end = chunk(b"IEND", b"")
    bad_crc = bytearray(data)
    bad_crc[-1] ^= 1
    prefix = capture.PNG_SIGNATURE + header
    return [
        prefix + bytes(bad_crc) + end,
        prefix + struct.pack(">I", 100000) + b"IDAT" + end,
        prefix + header + data + end,
        prefix + end,
        prefix + chunk(b"IEND", b"unexpected") + end,
        prefix + end + data + end,
    ]


@pytest.mark.parametrize("content", malformed_pngs())
def test_corrupt_png_chunks_are_not_archived(tmp_path, content):
    with pytest.raises(ValueError, match="PNG"):
        capture.capture(arguments(tmp_path), "local-test-credential", Renderer(body=content))
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize(
    "content",
    [
        capture.PNG_SIGNATURE,
        capture.PNG_SIGNATURE + b"short",
        capture.PNG_SIGNATURE + chunk(b"IHDR", b"short"),
        capture.PNG_SIGNATURE + chunk(b"IDAT", b"unexpected"),
    ],
)
def test_incomplete_chunk_sequences_are_rejected(content):
    assert not capture.valid_png_chunks(content)
