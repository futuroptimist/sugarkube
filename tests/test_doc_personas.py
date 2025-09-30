"""Verify persona metadata is defined for key documentation pages."""

from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]

PERSONA_EXPECTATIONS = {
    Path("docs/SAFETY.md"): ["hardware"],
    Path("docs/build_guide.md"): ["hardware"],
    Path("docs/contributor_script_map.md"): ["software"],
    Path("docs/docker_repo_walkthrough.md"): ["software"],
    Path("docs/electronics_basics.md"): ["hardware"],
    Path("docs/electronics_schematics.md"): ["hardware"],
    Path("docs/hardware/index.md"): ["hardware"],
    Path("docs/insert_basics.md"): ["hardware"],
    Path("docs/lcd_mount.md"): ["hardware"],
    Path("docs/mac_mini_station.md"): ["hardware"],
    Path("docs/network_setup.md"): ["hardware", "software"],
    Path("docs/pi_boot_troubleshooting.md"): ["hardware", "software"],
    Path("docs/pi_carrier_field_guide.md"): ["hardware", "software"],
    Path("docs/pi_carrier_launch_playbook.md"): ["hardware", "software"],
    Path("docs/pi_carrier_qr_labels.md"): ["hardware", "software"],
    Path("docs/pi_cluster_carrier.md"): ["hardware"],
    Path("docs/pi_headless_provisioning.md"): ["hardware", "software"],
    Path("docs/pi_image_builder_design.md"): ["software"],
    Path("docs/pi_image_cloudflare.md"): ["software"],
    Path("docs/pi_image_contributor_guide.md"): ["software"],
    Path("docs/pi_image_flowcharts.md"): ["software"],
    Path("docs/pi_image_quickstart.md"): ["software"],
    Path("docs/pi_image_team_notifications.md"): ["software"],
    Path("docs/pi_image_telemetry.md"): ["software"],
    Path("docs/pi_multi_node_join_rehearsal.md"): ["hardware", "software"],
    Path("docs/pi_smoke_test.md"): ["software"],
    Path("docs/pi_support_bundles.md"): ["hardware", "software"],
    Path("docs/pi_token_dspace.md"): ["software"],
    Path("docs/pi_workflow_notifications.md"): ["software"],
    Path("docs/power_system_design.md"): ["hardware"],
    Path("docs/projects-compose.md"): ["software"],
    Path("docs/raspi_cluster_setup.md"): ["hardware", "software"],
    Path("docs/solar_basics.md"): ["hardware"],
    Path("docs/software/index.md"): ["software"],
    Path("docs/start-here.md"): ["hardware", "software"],
    Path("docs/ssd_health_monitor.md"): ["hardware", "software"],
    Path("docs/ssd_post_clone_validation.md"): ["hardware", "software"],
    Path("docs/ssd_recovery.md"): ["hardware", "software"],
    Path("docs/token_place_sample_datasets.md"): ["software"],
}


def _extract_front_matter(text: str, relative: Path) -> str:
    if not text.startswith("---\n"):
        pytest.fail(f"{relative} is missing a front matter block")
    closing_index = text.find("\n---", 4)
    if closing_index == -1:
        pytest.fail(f"{relative} front matter does not terminate with '---'")
    return text[4:closing_index]


def _parse_personas(block: str, relative: Path) -> list[str]:
    personas: list[str] = []
    lines = block.splitlines()
    idx = 0
    while idx < len(lines):
        raw = lines[idx]
        stripped = raw.strip()
        if not stripped:
            idx += 1
            continue
        if stripped.startswith("personas:"):
            _, _, remainder = stripped.partition(":")
            remainder = remainder.strip()
            if remainder:
                if remainder.startswith("[") and remainder.endswith("]"):
                    for part in remainder[1:-1].split(","):
                        name = part.strip().strip("'\"")
                        if name:
                            personas.append(name)
                else:
                    personas.append(remainder.strip("'\""))
            else:
                idx += 1
                while idx < len(lines):
                    candidate = lines[idx].strip()
                    if not candidate:
                        idx += 1
                        continue
                    if candidate.startswith("- "):
                        personas.append(candidate[2:].strip())
                        idx += 1
                        continue
                    break
            break
        idx += 1
    if not personas:
        pytest.fail(f"{relative} front matter missing personas key")
    return personas


@pytest.mark.parametrize(
    ("relative", "expected"),
    [(path, personas) for path, personas in PERSONA_EXPECTATIONS.items()],
)
def test_doc_front_matter_personas(relative: Path, expected: list[str]) -> None:
    """Ensure each documented page declares the expected personas."""

    doc_path = REPO_ROOT / relative
    text = doc_path.read_text(encoding="utf-8")
    block = _extract_front_matter(text, relative)
    personas = sorted(_parse_personas(block, relative))
    assert personas == sorted(
        expected
    ), f"{relative} personas mismatch: expected {expected!r}, found {personas!r}"
