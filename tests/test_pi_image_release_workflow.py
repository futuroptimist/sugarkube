from pathlib import Path


WORKFLOW = Path(".github/workflows/pi-image-release.yml")


def test_release_workflow_clones_sugarkube_by_default() -> None:
    workflow = WORKFLOW.read_text()
    assert "clone_sugarkube:" in workflow
    assert "default: true" in workflow
    assert (
        "CLONE_SUGARKUBE: ${{ inputs.clone_sugarkube == false && 'false' || 'true' }}"
        in workflow
    )


def test_release_workflow_normalizes_checksum_to_relative_filename() -> None:
    workflow = WORKFLOW.read_text()
    assert "Normalize release checksum filename" in workflow
    assert "sha256sum sugarkube.img.xz" in workflow
    assert "sugarkube.img.xz\" >sugarkube.img.xz.sha256" in workflow
