"""Contract tests for projects docker-compose configuration."""

from __future__ import annotations

from itertools import islice
from pathlib import Path

COMPOSE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "cloud-init" / "docker-compose.yml"


def _read_lines() -> list[str]:
    return COMPOSE_PATH.read_text().splitlines()


def _between_markers(lines: list[str], start_marker: str, end_marker: str) -> list[str]:
    capturing = False
    block: list[str] = []
    for line in lines:
        if start_marker in line:
            capturing = True
            continue
        if end_marker in line:
            break
        if capturing:
            block.append(line)
    return block


def _service_block(lines: list[str], service: str) -> list[str]:
    start_index = None
    for idx, line in enumerate(lines):
        if line.strip() == f"{service}:" and line.startswith("  "):
            start_index = idx
            break
    if start_index is None:
        raise AssertionError(f"Service '{service}' not found in compose file")

    block: list[str] = []
    for line in islice(lines, start_index + 1, None):
        stripped = line.strip()
        if not stripped:
            block.append(line)
            continue
        if line.startswith("  ") and not line.startswith("    "):
            if stripped.startswith("#"):
                break
            break
        block.append(line)
    return block


def _extract_image(block: list[str]) -> str:
    for line in block:
        stripped = line.strip()
        if stripped.startswith("image:"):
            value = stripped.split(":", 1)[1].strip()
            if "#" in value:
                value = value.split("#", 1)[0].strip()
            return value
    raise AssertionError("No image reference found in service block")


def test_tokenplace_exposes_port_5000():
    lines = _read_lines()
    block = _between_markers(lines, "# tokenplace-start", "# tokenplace-end")
    flattened = [line.strip() for line in block]
    assert "ports:" in flattened, "token.place service should expose ports"
    port_entries = []
    for entry in flattened:
        if entry.startswith("-"):
            value = entry[1:].strip()
            if value.startswith('"') and value.endswith('"'):
                value = value[1:-1]
            port_entries.append(value)
    assert "5000:5000" in port_entries, "token.place should publish port 5000"


def test_dspace_exposes_port_3000():
    lines = _read_lines()
    block = _between_markers(lines, "# dspace-start", "# dspace-end")
    flattened = [line.strip() for line in block]
    assert "ports:" in flattened, "dspace service should expose ports"
    port_entries = []
    for entry in flattened:
        if entry.startswith("-"):
            value = entry[1:].strip()
            if value.startswith('"') and value.endswith('"'):
                value = value[1:-1]
            port_entries.append(value)
    assert "3000:3000" in port_entries, "dspace should publish port 3000"


def test_observability_images_are_pinned():
    lines = _read_lines()
    expected = {
        "node-exporter": (
            "prom/node-exporter@sha256:",
            "4cb2b9019f1757be8482419002cb7afe028fdba35d47958829e4cfeaf6246d80",
        ),
        "cadvisor": (
            "gcr.io/cadvisor/cadvisor@sha256:",
            "e6c562b5e983f13624898b5b6a902c71999580dc362022fc327c309234c485d7",
        ),
        "grafana-agent": (
            "grafana/agent@sha256:",
            "4e015c830781b818dd305b3280d8f1c4aea4181b78bb88adcc3d5bc710d0ed38",
        ),
        "netdata": (
            "netdata/netdata@sha256:",
            "bebe2029f610e9c24c46dffb9f49296bdb53e8d8b748634cd85787e8621aa4d2",
        ),
    }

    for service, image_parts in expected.items():
        image = "".join(image_parts)
        block = _service_block(lines, service)
        actual = _extract_image(block)
        assert actual == image, f"{service} image should remain pinned"
        assert "@sha256:" in actual, f"{service} must pin to a digest"
