from pathlib import Path


def test_release_workflow_clones_sugarkube() -> None:
    workflow = Path(".github/workflows/pi-image-release.yml").read_text()
    assert "CLONE_SUGARKUBE: true" in workflow
