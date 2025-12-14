"""Regression tests for Pi image tooling additions."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import yaml

from tests import build_pi_image_test as build_test


def _extract_pull_request_paths(workflow_text: str) -> list[str]:
    """Return the string globs under the pull_request.paths block."""

    paths: list[str] = []
    lines = workflow_text.splitlines()

    in_pull_request = False
    in_paths = False
    pull_request_indent = 0
    paths_indent = 0

    for raw_line in lines:
        line = raw_line.rstrip()
        stripped = line.lstrip()
        indent = len(line) - len(stripped)

        if not in_pull_request:
            if stripped.startswith("pull_request:"):
                in_pull_request = True
                pull_request_indent = indent
            continue

        if indent <= pull_request_indent and stripped:
            # Finished reading the pull_request block.
            break

        if stripped.startswith("paths:"):
            in_paths = True
            paths_indent = indent
            continue

        if in_paths:
            if not stripped:
                continue
            if indent <= paths_indent:
                in_paths = False
                if indent <= pull_request_indent and stripped:
                    break
                continue

            if stripped.startswith("- "):
                value = stripped[2:].strip()
                if value.startswith("'") and value.endswith("'"):
                    value = value[1:-1]
                elif value.startswith('"') and value.endswith('"'):
                    value = value[1:-1]
                if value:
                    paths.append(value)

    return paths


def _extract_work_dir(stdout: str) -> Path:
    match = re.search(r"leaving work dir: (?P<path>\S+)", stdout)
    assert match, stdout
    return Path(match.group("path"))


def test_just_installation_script_includes_fallback(tmp_path):
    env = build_test._setup_build_env(tmp_path)
    env["KEEP_WORK_DIR"] = "1"
    result, _ = build_test._run_build_script(tmp_path, env)
    assert result.returncode == 0

    work_dir = _extract_work_dir(result.stdout)
    script_dir = work_dir / "pi-gen" / "stage2" / "01-sys-tweaks"
    canonical_script = script_dir / "03-run.sh"
    run_chroot_script = script_dir / "03-run-chroot.sh"
    legacy_script = script_dir / "03-run-chroot-just.sh"

    assert canonical_script.exists(), canonical_script
    assert canonical_script.is_symlink(), canonical_script
    assert canonical_script.readlink() == Path("03-run-chroot.sh")

    assert run_chroot_script.exists(), run_chroot_script
    assert run_chroot_script.is_file(), run_chroot_script

    if legacy_script.exists():
        assert legacy_script.is_symlink(), legacy_script
        assert legacy_script.readlink() == Path("03-run-chroot.sh")

    script_text = canonical_script.read_text()

    assert 'apt-get "${APT_OPTS[@]}" install -y --no-install-recommends just' in script_text
    assert "${BUILD_LOG:-${LOG_FILE:-}}" in script_text
    assert 'tee -a "${log_target}"' in script_text
    assert "https://just.systems/install.sh" in script_text
    assert "[sugarkube] just command verified" in script_text
    assert "just --version" in script_text
    assert "just --list" in script_text

    profile_path = (
        work_dir
        / "pi-gen"
        / "stage2"
        / "01-sys-tweaks"
        / "files"
        / "etc"
        / "profile.d"
        / "sugarkube-path.sh"
    )
    assert profile_path.exists(), profile_path
    profile_text = profile_path.read_text()
    assert "/usr/local/bin" in profile_text
    assert "export PATH" in profile_text


def test_pi_image_workflow_checks_for_just_log():
    workflow_path = Path(".github/workflows/pi-image.yml")
    content = workflow_path.read_text()
    assert "grep -FH 'just command verified'" in content
    assert "find deploy -maxdepth 6 -name '*.build.log'" in content


def test_pi_image_workflow_preserves_node_runtime():
    workflow_path = Path(".github/workflows/pi-image.yml")
    content = workflow_path.read_text()
    assert "/opt/hostedtoolcache" not in content
    assert "Verify Node runtime availability" in content
    assert "node --version" in content


def test_pi_image_workflow_fixes_artifact_permissions():
    workflow_path = Path(".github/workflows/pi-image.yml")
    content = workflow_path.read_text()
    assert "fix_pi_image_permissions.sh" in content
    assert 'TARGET_UID="$(id -u)" TARGET_GID="$(id -g)"' in content
    paths = _extract_pull_request_paths(content)
    assert "scripts/create_build_metadata.py" in paths
    assert "tests/create_build_metadata_e2e.sh" in paths
    assert "scripts/fix_pi_image_permissions.sh" in paths
    assert "Run fix permissions e2e test" in content


def test_pi_image_workflow_collects_from_deploy_root():
    workflow_path = Path(".github/workflows/pi-image.yml")
    content = workflow_path.read_text()
    assert "bash scripts/collect_pi_image.sh deploy ./sugarkube.img.xz" in content
    assert "bash scripts/collect_pi_image.sh . ./sugarkube.img.xz" not in content


def test_pi_image_workflow_covers_preset_and_download_scripts():
    workflow_path = Path(".github/workflows/pi-image.yml")
    content = workflow_path.read_text()
    paths = _extract_pull_request_paths(content)

    assert "scripts/download_pi_image.sh" in paths
    assert "scripts/render_pi_imager_preset.py" in paths
    assert "tests/render_pi_imager_preset_e2e.sh" in content
    assert "Run Pi Imager preset e2e test" in content


def test_pi_image_workflow_covers_oci_trigger_paths():
    workflow_path = Path(".github/workflows/pi-image.yml")
    content = workflow_path.read_text()
    paths = _extract_pull_request_paths(content)

    assert "**/Dockerfile" in paths
    assert "**/package.json" in paths
    assert "**/package-lock.json" in paths
    assert "**/pnpm-lock.yaml" in paths
    assert "deploy/**" in paths


def _collect_checkout_refs(workflow_text: str) -> list[str]:
    pattern = re.compile(r"uses:\s*actions/checkout@(?P<ref>[^\s]+)")
    return pattern.findall(workflow_text)


def _collect_action_refs(workflow_text: str, action: str) -> list[str]:
    pattern = re.compile(rf"uses:\s*{re.escape(action)}@(?P<ref>[^\s]+)")
    return pattern.findall(workflow_text)


def test_pi_image_workflow_pins_checkout_version():
    workflow_path = Path(".github/workflows/pi-image.yml")
    content = workflow_path.read_text()
    refs = _collect_checkout_refs(content)
    assert refs, "No actions/checkout references found in pi-image workflow"

    for ref in refs:
        assert ref == "v5", f"Expected actions/checkout@v5, found {ref}"


def test_pi_image_workflow_checkout_refs_exist_upstream():
    workflow_path = Path(".github/workflows/pi-image.yml")
    content = workflow_path.read_text()
    refs = _collect_checkout_refs(content)
    assert refs, "No actions/checkout references found in pi-image workflow"

    for ref in refs:
        try:
            result = subprocess.run(
                [
                    "git",
                    "ls-remote",
                    "--tags",
                    "https://github.com/actions/checkout.git",
                    f"refs/tags/{ref}",
                ],
                check=True,
                capture_output=True,
                text=True,
                timeout=30,
            )
        except subprocess.CalledProcessError as exc:  # pragma: no cover - defensive
            raise AssertionError(
                f"git ls-remote failed for actions/checkout tag {ref}: {exc.stderr}"
            ) from exc

        assert result.stdout.strip(), f"actions/checkout tag {ref} missing upstream"


def test_pi_image_workflow_pins_cache_action_version():
    workflow_path = Path(".github/workflows/pi-image.yml")
    content = workflow_path.read_text()
    refs = _collect_action_refs(content, "actions/cache")
    assert refs, "actions/cache reference missing from pi-image workflow"
    assert all(ref == "v4.3.0" for ref in refs), refs


def test_pi_image_workflow_cache_refs_exist_upstream():
    workflow_path = Path(".github/workflows/pi-image.yml")
    content = workflow_path.read_text()
    refs = _collect_action_refs(content, "actions/cache")
    assert refs, "actions/cache reference missing from pi-image workflow"

    for ref in refs:
        result = subprocess.run(
            [
                "git",
                "ls-remote",
                "--tags",
                "https://github.com/actions/cache.git",
                f"refs/tags/{ref}",
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.stdout.strip(), f"actions/cache tag {ref} missing upstream"


def test_pi_image_workflow_pins_upload_artifact_version():
    workflow_path = Path(".github/workflows/pi-image.yml")
    content = workflow_path.read_text()
    refs = _collect_action_refs(content, "actions/upload-artifact")
    assert refs, "actions/upload-artifact reference missing from pi-image workflow"
    assert all(ref == "v4.6.2" for ref in refs), refs


def test_pi_image_workflow_upload_artifact_refs_exist_upstream():
    workflow_path = Path(".github/workflows/pi-image.yml")
    content = workflow_path.read_text()
    refs = _collect_action_refs(content, "actions/upload-artifact")
    assert refs, "actions/upload-artifact reference missing from pi-image workflow"

    for ref in refs:
        result = subprocess.run(
            [
                "git",
                "ls-remote",
                "--tags",
                "https://github.com/actions/upload-artifact.git",
                f"refs/tags/{ref}",
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.stdout.strip(), f"actions/upload-artifact tag {ref} missing upstream"


def test_pi_image_workflow_uses_cache_key_script():
    workflow_path = Path(".github/workflows/pi-image.yml")
    content = workflow_path.read_text()
    assert "scripts/compute_pi_gen_cache_key.sh" in content
    assert "key=$(bash scripts/compute_pi_gen_cache_key.sh" in content


def test_compute_pi_gen_cache_key_script_has_fallback():
    script_path = Path("scripts/compute_pi_gen_cache_key.sh")
    script_text = script_path.read_text()
    assert "falling back to offline cache key" in script_text
    assert "git ls-remote" in script_text


def test_collect_pi_image_scan_depth_configurable():
    script_path = Path("scripts/collect_pi_image.sh")
    script_text = script_path.read_text()

    assert 'MAX_SCAN_DEPTH="${MAX_SCAN_DEPTH:-6}"' in script_text
    assert 'find "${DEPLOY_ROOT}" -maxdepth "${MAX_SCAN_DEPTH}"' in script_text


def test_pi_image_workflow_wires_oci_parity_smoke_job():
    workflow_path = Path(".github/workflows/pi-image.yml")
    workflow = yaml.safe_load(workflow_path.read_text())
    jobs = workflow.get("jobs", {})

    assert "oci-parity-smoke" in jobs, workflow
    oci_job = jobs["oci-parity-smoke"]
    step_names = [step.get("name", "") for step in oci_job.get("steps", [])]

    assert "Set up QEMU" in step_names
    assert "Build dspace OCI image (amd64 + arm64)" in step_names

    smoke_steps = [step.get("run", "") for step in oci_job.get("steps", [])]
    assert any("canvas ok" in snippet for snippet in smoke_steps)
    assert any("/docs/dCarbon" in snippet for snippet in smoke_steps)
