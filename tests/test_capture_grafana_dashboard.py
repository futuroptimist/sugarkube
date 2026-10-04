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
