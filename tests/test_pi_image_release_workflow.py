from pathlib import Path


WORKFLOW = Path(".github/workflows/pi-image-release.yml")


def _workflow_text() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def test_release_workflow_is_manual_only() -> None:
    workflow = _workflow_text()

    assert "workflow_dispatch:" in workflow
    assert "\n  push:" not in workflow
    assert "\n  schedule:" not in workflow
    assert "cron:" not in workflow


def test_release_workflow_exposes_intentional_inputs() -> None:
    workflow = _workflow_text()

    for snippet in [
        "release_channel:",
        "clone_sugarkube:",
        "clone_token_place:",
        "clone_dspace:",
        "publish_release:",
        "run_qemu_smoke:",
        "default: stable",
        "default: false",
        "default: true",
    ]:
        assert snippet in workflow

    assert "RELEASE_CHANNEL: ${{ inputs.release_channel }}" in workflow
    assert "CLONE_SUGARKUBE: ${{ inputs.clone_sugarkube" in workflow
    assert "CLONE_TOKEN_PLACE: ${{ inputs.clone_token_place" in workflow
    assert "CLONE_DSPACE: ${{ inputs.clone_dspace" in workflow
    assert "if: inputs.publish_release" in workflow
    assert "if: inputs.run_qemu_smoke" in workflow


def test_release_workflow_preserves_node_runtime_after_cleanup() -> None:
    workflow = _workflow_text()

    assert "/opt/hostedtoolcache" not in workflow
    assert "Verify Node runtime availability" in workflow
    assert "node --version" in workflow


def test_release_workflow_uses_shared_cache_key_and_pinned_actions() -> None:
    workflow = _workflow_text()

    assert "scripts/compute_pi_gen_cache_key.sh" in workflow
    assert "key=$(bash scripts/compute_pi_gen_cache_key.sh" in workflow
    assert "actions/cache@v4.3.0" in workflow
    assert "actions/upload-artifact@v4.6.2" in workflow


def test_release_workflow_verifies_and_signs_artifacts_before_optional_publish() -> None:
    workflow = _workflow_text()

    assert "Fix permissions on pi-image artifacts" in workflow
    assert "bash scripts/fix_pi_image_permissions.sh" in workflow
    assert "Verify image artifacts" in workflow
    assert "sha256sum -c ./sugarkube.img.xz.sha256" in workflow
    assert "sigstore/cosign-installer@v3.5.0" in workflow
    assert "cosign sign-blob --yes" in workflow
    assert "sugarkube.img.xz.stage-summary.json" in workflow
    assert "Upload QEMU smoke artifacts" in workflow
    assert "if-no-files-found: warn" in workflow
