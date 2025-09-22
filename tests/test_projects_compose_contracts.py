import re
from pathlib import Path

COMPOSE_PATH = Path("scripts/cloud-init/docker-compose.yml")

EXPECTED_IMAGE_DIGESTS = {
    "prom/node-exporter": (
        "sha256:4cb2b9019f1757be8482419002cb7afe028fdba35d47958829e4cfeaf6246d80"
    ),
    "gcr.io/cadvisor/cadvisor": (
        "sha256:e6c562b5e983f13624898b5b6a902c71999580dc362022fc327c309234c485d7"
    ),
    "grafana/agent": ("sha256:d91efdf45e278fa78169e330998eca2d1ffa1417be35f8adbe8e0d959e056991"),
    "netdata/netdata": ("sha256:bebe2029f610e9c24c46dffb9f49296bdb53e8d8b748634cd85787e8621aa4d2"),
}


def load_compose() -> str:
    return COMPOSE_PATH.read_text(encoding="utf-8")


def test_tokenplace_and_dspace_ports_are_exposed():
    content = load_compose()
    assert "  tokenplace:" in content
    assert '    ports:\n      - "5000:5000"' in content, "token.place port 5000 should be exposed"
    assert "  dspace:" in content
    assert '    ports:\n      - "3000:3000"' in content, "dspace port 3000 should be exposed"


def test_observability_images_are_pinned_by_digest():
    content = load_compose()
    images = re.findall(r"^\s*image:\s*(\S+)", content, flags=re.MULTILINE)
    assert images, "Expected to find observability image definitions"

    seen = {image.split("@", 1)[0] for image in images}
    assert (
        set(EXPECTED_IMAGE_DIGESTS) == seen
    ), "Observability images drifted; update EXPECTED_IMAGE_DIGESTS"

    for image in images:
        name, digest = image.split("@", 1)
        assert digest.startswith("sha256:"), f"{name} is not pinned by digest"
        expected = EXPECTED_IMAGE_DIGESTS[name]
        assert digest == expected, f"Digest for {name} changed"
