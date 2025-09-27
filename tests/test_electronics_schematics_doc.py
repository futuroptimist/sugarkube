from pathlib import Path


def test_fritzing_section_provides_real_assets() -> None:
    doc = Path("docs/electronics_schematics.md").read_text(encoding="utf-8")
    assert "Placeholder" not in doc
    assert "images/power_ring_wiring.svg" in doc
    assert "| Connector | Function | Suggested Wire |" in doc
