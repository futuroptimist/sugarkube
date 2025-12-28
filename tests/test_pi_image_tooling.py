"""Regression tests for Pi image tooling additions."""

from __future__ import annotations

import json
import os
from collections.abc import Callable
import re
import subprocess
import time
from pathlib import Path

import pytest

from tests import build_pi_image_test as build_test


TESTS_DIR = Path(__file__).resolve().parent


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


DEFAULT_LS_REMOTE_FIXTURE = TESTS_DIR / "fixtures" / "ls_remote_tags.json"
DISABLE_FIXTURE_SENTINELS = {"0", "false", "none", "off", "disable"}
_TRANSIENT_LS_REMOTE_ERRORS = (
    "connection timed out",
    "connection timeout",
    "timed out",
    "temporary failure in name resolution",
    "could not resolve host",
    "upstream connect error",
    "reset reason",
    "connection reset",
    "returned error: 503",
)


@pytest.fixture
def ls_remote_fixture(monkeypatch) -> Path:
    fixture_path = DEFAULT_LS_REMOTE_FIXTURE
    monkeypatch.setenv("SUGARKUBE_LS_REMOTE_FIXTURES", str(fixture_path))
    return fixture_path


def _assert_tag_exists_upstream(
    repo: str,
    ref: str,
    *,
    retries: int = 3,
    delay_seconds: float = 1.0,
    sleep_fn: Callable[[float], None] | None = None,
    allow_fixture: bool = True,
) -> None:
    """Ensure the expected upstream tag exists, retrying transient failures before skipping.

    Fixtures are preferred to keep the suite offline. When the environment variable
    ``SUGARKUBE_LS_REMOTE_FIXTURES`` points to a JSON mapping repositories to tags, or when
    the default ``tests/fixtures/ls_remote_tags.json`` file exists, the fixture is treated as
    authoritative and network calls are skipped. Set ``allow_fixture=False`` or
    ``SUGARKUBE_LS_REMOTE_FIXTURES=0`` to exercise the network fallback in tests.
    Coverage: ``test_assert_tag_exists_prefers_fixture`` and
    ``test_assert_tag_exists_defaults_to_builtin_fixture``.
    """

    fixture_env = os.environ.get("SUGARKUBE_LS_REMOTE_FIXTURES", "").strip()
    if fixture_env.lower() in DISABLE_FIXTURE_SENTINELS:
        fixture_path: Path | None = None
    elif allow_fixture:
        fixture_path = Path(fixture_env) if fixture_env else DEFAULT_LS_REMOTE_FIXTURE
    else:
        fixture_path = None

    if fixture_path:
        if not fixture_path.is_file():
            raise AssertionError(f"ls-remote fixture not found: {fixture_path}")

        try:
            fixture = json.loads(fixture_path.read_text())
        except json.JSONDecodeError as exc:
            raise AssertionError(
                f"Invalid ls-remote fixture JSON: {fixture_path}"
            ) from exc

        if not isinstance(fixture, dict):
            raise AssertionError(
                f"ls-remote fixture must be an object: {fixture_path}"
            )

        if repo not in fixture:
            raise AssertionError(
                f"{repo} missing from ls-remote fixture {fixture_path}"
            )

        tags = fixture[repo]
        if not isinstance(tags, list) or not all(isinstance(tag, str) for tag in tags):
            raise AssertionError(
                "ls-remote fixture entries must be lists of strings: "
                f"{fixture_path}"
            )

        if ref in tags:
            return

        raise AssertionError(
            f"{repo} tag {ref} missing from ls-remote fixture {fixture_path}; "
            "update the fixture to avoid network lookups"
        )

    url = f"https://github.com/{repo}.git"
    sleep = sleep_fn or time.sleep

    for attempt in range(1, retries + 1):
        try:
            result = subprocess.run(
                ["git", "ls-remote", "--tags", url, f"refs/tags/{ref}"],
                check=True,
                capture_output=True,
                text=True,
                timeout=30,
            )
        except subprocess.TimeoutExpired as exc:
            if attempt < retries:
                sleep(delay_seconds)
                continue

            pytest.skip(
                "git ls-remote timed out for "
                f"{repo} tag {ref}: {exc}. "
                "Provide SUGARKUBE_LS_REMOTE_FIXTURES to stay offline."
            )
        except subprocess.CalledProcessError as exc:
            stderr = (exc.stderr or "").lower()
            if any(marker in stderr for marker in _TRANSIENT_LS_REMOTE_ERRORS):
                if attempt < retries:
                    sleep(delay_seconds)
                    continue

                pytest.skip(
                    "git ls-remote transiently failed for "
                    f"{repo} tag {ref}: {exc.stderr}. "
                    "Provide SUGARKUBE_LS_REMOTE_FIXTURES to stay offline."
                )

            raise AssertionError(
                f"git ls-remote failed for {repo} tag {ref}: {exc.stderr}"
            ) from exc

        if not result.stdout.strip():
            raise AssertionError(f"{repo} tag {ref} missing upstream")

        return


def test_assert_tag_exists_retries_transient_errors(monkeypatch):
    attempts: list[int] = []

    def fake_run(*_, **__):
        attempts.append(1)
        if len(attempts) < 3:
            raise subprocess.CalledProcessError(
                returncode=1, cmd=["git", "ls-remote"], stderr="connection reset"
            )

        return subprocess.CompletedProcess(args=["git"], returncode=0, stdout="ref\n")

    monkeypatch.setattr(subprocess, "run", fake_run)

    _assert_tag_exists_upstream(
        "actions/checkout",
        "v5",
        retries=3,
        delay_seconds=0,
        sleep_fn=lambda _: None,
        allow_fixture=False,
    )

    assert len(attempts) == 3


def test_assert_tag_exists_skips_after_retries(monkeypatch):
    def fake_run(*_, **__):
        raise subprocess.CalledProcessError(
            returncode=1,
            cmd=["git", "ls-remote"],
            stderr="temporary failure in name resolution",
        )

    monkeypatch.setattr(subprocess, "run", fake_run)

    with pytest.raises(pytest.skip.Exception):
        _assert_tag_exists_upstream(
            "actions/cache",
            "v4.3.0",
            retries=2,
            delay_seconds=0,
            sleep_fn=lambda _: None,
            allow_fixture=False,
        )


def test_assert_tag_exists_skips_after_timeouts(monkeypatch):
    attempts: list[int] = []

    def fake_run(*_, **__):
        attempts.append(1)
        raise subprocess.TimeoutExpired(cmd=["git", "ls-remote"], timeout=30)

    monkeypatch.setattr(subprocess, "run", fake_run)

    with pytest.raises(pytest.skip.Exception):
        _assert_tag_exists_upstream(
            "actions/cache",
            "v4.3.0",
            retries=2,
            delay_seconds=0,
            sleep_fn=lambda _: None,
            allow_fixture=False,
        )

    assert len(attempts) == 2


def test_assert_tag_exists_recovers_after_timeout(monkeypatch):
    attempts: list[int] = []
    sleeps: list[float] = []

    def fake_run(*_, **__):
        attempts.append(1)
        if len(attempts) == 1:
            raise subprocess.TimeoutExpired(cmd=["git", "ls-remote"], timeout=30)

        return subprocess.CompletedProcess(args=["git"], returncode=0, stdout="ref\n")

    monkeypatch.setattr(subprocess, "run", fake_run)

    _assert_tag_exists_upstream(
        "actions/cache",
        "v4.3.0",
        retries=2,
        delay_seconds=0.25,
        sleep_fn=lambda seconds: sleeps.append(seconds),
        allow_fixture=False,
    )

    assert len(attempts) == 2
    assert sleeps == [0.25]


def test_assert_tag_exists_prefers_fixture(monkeypatch, ls_remote_fixture):
    def raising_run(*_, **__):
        raise AssertionError("git ls-remote should not run when fixture is provided")

    monkeypatch.setattr(subprocess, "run", raising_run)

    _assert_tag_exists_upstream("actions/checkout", "v5")


def test_assert_tag_exists_defaults_to_builtin_fixture(monkeypatch):
    monkeypatch.delenv("SUGARKUBE_LS_REMOTE_FIXTURES", raising=False)

    def raising_run(*_, **__):
        raise AssertionError(
            "git ls-remote should not run when the built-in fixture is present"
        )

    monkeypatch.setattr(subprocess, "run", raising_run)

    _assert_tag_exists_upstream("actions/cache", "v4.3.0")


def test_assert_tag_exists_respects_fixture_disable_env(monkeypatch):
    monkeypatch.setenv("SUGARKUBE_LS_REMOTE_FIXTURES", "0")
    attempts: list[int] = []

    def fake_run(*_, **__):
        attempts.append(1)
        return subprocess.CompletedProcess(args=["git"], returncode=0, stdout="ref\n")

    monkeypatch.setattr(subprocess, "run", fake_run)

    _assert_tag_exists_upstream(
        "actions/checkout",
        "v5",
        retries=1,
        delay_seconds=0,
        sleep_fn=lambda _: None,
    )

    assert attempts


def test_assert_tag_exists_fixture_missing(monkeypatch, tmp_path):
    missing_path = tmp_path / "absent.json"
    monkeypatch.setenv("SUGARKUBE_LS_REMOTE_FIXTURES", str(missing_path))

    def raising_run(*_, **__):
        raise AssertionError("git ls-remote should not run when fixture is missing")

    monkeypatch.setattr(subprocess, "run", raising_run)

    with pytest.raises(AssertionError, match="ls-remote fixture not found"):
        _assert_tag_exists_upstream("actions/cache", "v4.3.0")


def test_assert_tag_exists_rejects_invalid_json_fixture(monkeypatch, tmp_path):
    fixture_path = tmp_path / "bad.json"
    fixture_path.write_text("{not-json: true")
    monkeypatch.setenv("SUGARKUBE_LS_REMOTE_FIXTURES", str(fixture_path))

    def raising_run(*_, **__):
        raise AssertionError("git ls-remote should not run when fixture is invalid")

    monkeypatch.setattr(subprocess, "run", raising_run)

    with pytest.raises(AssertionError, match="Invalid ls-remote fixture JSON"):
        _assert_tag_exists_upstream("actions/cache", "v4.3.0")


def test_assert_tag_exists_rejects_invalid_fixture_structure(monkeypatch, tmp_path):
    fixture_path = tmp_path / "structure.json"
    fixture_path.write_text('["v5"]')
    monkeypatch.setenv("SUGARKUBE_LS_REMOTE_FIXTURES", str(fixture_path))

    def raising_run(*_, **__):
        raise AssertionError("git ls-remote should not run when fixture is invalid")

    monkeypatch.setattr(subprocess, "run", raising_run)

    with pytest.raises(AssertionError, match="fixture must be an object"):
        _assert_tag_exists_upstream("actions/checkout", "v5")


def test_assert_tag_exists_fixture_missing_repo_raises(monkeypatch, tmp_path):
    fixture_path = tmp_path / "missing_repo.json"
    fixture_path.write_text('{"actions/cache": ["v4.3.0"]}')
    monkeypatch.setenv("SUGARKUBE_LS_REMOTE_FIXTURES", str(fixture_path))

    def raising_run(*_, **__):
        raise AssertionError("git ls-remote should not run when fixture is provided")

    monkeypatch.setattr(subprocess, "run", raising_run)

    with pytest.raises(AssertionError, match="missing from ls-remote fixture"):
        _assert_tag_exists_upstream("actions/checkout", "v5")


def test_assert_tag_exists_rejects_non_string_fixture_entries(monkeypatch, tmp_path):
    fixture_path = tmp_path / "entries.json"
    fixture_path.write_text('{"actions/checkout": [5]}')
    monkeypatch.setenv("SUGARKUBE_LS_REMOTE_FIXTURES", str(fixture_path))

    def raising_run(*_, **__):
        raise AssertionError("git ls-remote should not run when fixture is invalid")

    monkeypatch.setattr(subprocess, "run", raising_run)

    with pytest.raises(AssertionError, match="entries must be lists of strings"):
        _assert_tag_exists_upstream("actions/checkout", "v5")


def test_assert_tag_exists_raises_when_fixture_missing_tag(monkeypatch, tmp_path):
    fixture_path = tmp_path / "tags.json"
    fixture_path.write_text('{"actions/cache": ["v4.2.0"]}')
    monkeypatch.setenv("SUGARKUBE_LS_REMOTE_FIXTURES", str(fixture_path))

    def raising_run(*_, **__):
        raise AssertionError("git ls-remote should not run when fixture is provided")

    monkeypatch.setattr(subprocess, "run", raising_run)

    with pytest.raises(AssertionError, match="missing from ls-remote fixture"):
        _assert_tag_exists_upstream("actions/cache", "v4.3.0")


def test_assert_tag_exists_raises_on_non_transient_error(monkeypatch):
    attempts: list[int] = []

    def fake_run(*_, **__):
        attempts.append(1)
        raise subprocess.CalledProcessError(
            returncode=128,
            cmd=["git", "ls-remote"],
            stderr="fatal: repository not found",
        )

    monkeypatch.setattr(subprocess, "run", fake_run)

    with pytest.raises(AssertionError):
        _assert_tag_exists_upstream(
            "actions/cache",
            "v4.3.0",
            retries=3,
            delay_seconds=0,
            sleep_fn=lambda _: None,
            allow_fixture=False,
        )

    assert len(attempts) == 1


def test_assert_tag_exists_raises_when_tag_missing(monkeypatch):
    def fake_run(*_, **__):
        return subprocess.CompletedProcess(args=["git"], returncode=0, stdout="")

    monkeypatch.setattr(subprocess, "run", fake_run)

    with pytest.raises(AssertionError):
        _assert_tag_exists_upstream(
            "actions/cache",
            "v4.3.0",
            retries=1,
            delay_seconds=0,
            sleep_fn=lambda _: None,
            allow_fixture=False,
        )


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


def test_pi_image_workflow_has_oci_parity_guardrails():
    workflow_path = Path(".github/workflows/pi-image.yml")
    content = workflow_path.read_text()

    assert "oci-parity-smoke" in content
    assert "docker/setup-buildx-action@v3" in content
    assert "dorny/paths-filter@de90cc6fb38fc0963ad72b210f1f284cd68cea36" in content
    assert "docker buildx build \\" in content
    assert "require('canvas'); console.log('canvas ok')" in content
    assert "\"/docs\" \"/docs/dCarbon\"" in content
    assert (
        "dCarbon represents the amount of carbon dioxide produced by a player" in content
    )
    assert "to close CI/prod gaps by testing the shipped OCI image directly" in content


def test_pi_image_workflow_pull_request_paths_include_oci_signals():
    workflow_path = Path(".github/workflows/pi-image.yml")
    content = workflow_path.read_text()
    paths = _extract_pull_request_paths(content)

    for path in [
        "**/Dockerfile",
        "**/Dockerfile.*",
        "**/package.json",
        "**/package-lock.json",
        "**/pnpm-lock.yaml",
        "deploy/**",
        "infra/**",
        "platform/**",
    ]:
        assert path in paths


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


def test_pi_image_workflow_checkout_refs_exist_upstream(ls_remote_fixture):
    workflow_path = Path(".github/workflows/pi-image.yml")
    content = workflow_path.read_text()
    refs = _collect_checkout_refs(content)
    assert refs, "No actions/checkout references found in pi-image workflow"

    for ref in refs:
        _assert_tag_exists_upstream("actions/checkout", ref)


def test_pi_image_workflow_pins_cache_action_version():
    workflow_path = Path(".github/workflows/pi-image.yml")
    content = workflow_path.read_text()
    refs = _collect_action_refs(content, "actions/cache")
    assert refs, "actions/cache reference missing from pi-image workflow"
    assert all(ref == "v4.3.0" for ref in refs), refs


def test_pi_image_workflow_cache_refs_exist_upstream(ls_remote_fixture):
    workflow_path = Path(".github/workflows/pi-image.yml")
    content = workflow_path.read_text()
    refs = _collect_action_refs(content, "actions/cache")
    assert refs, "actions/cache reference missing from pi-image workflow"

    for ref in refs:
        _assert_tag_exists_upstream("actions/cache", ref)


def test_pi_image_workflow_pins_upload_artifact_version():
    workflow_path = Path(".github/workflows/pi-image.yml")
    content = workflow_path.read_text()
    refs = _collect_action_refs(content, "actions/upload-artifact")
    assert refs, "actions/upload-artifact reference missing from pi-image workflow"
    assert all(ref == "v4.6.2" for ref in refs), refs


def test_pi_image_workflow_upload_artifact_refs_exist_upstream(ls_remote_fixture):
    workflow_path = Path(".github/workflows/pi-image.yml")
    content = workflow_path.read_text()
    refs = _collect_action_refs(content, "actions/upload-artifact")
    assert refs, "actions/upload-artifact reference missing from pi-image workflow"

    for ref in refs:
        _assert_tag_exists_upstream("actions/upload-artifact", ref)


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
