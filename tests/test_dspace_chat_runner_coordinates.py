"""Regression coverage for the exact accepted DSPACE runner revision/manifest pair."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from scripts import dspace_chat_synthetic_runtime as runtime
from scripts import install_dspace_chat_synthetic as installer

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config/dspace-chat-synthetic.json"

UNRELATED_REVISION = "1" * 40
WRONG_MANIFEST_SHA256 = "0" * 64


def asset_hashes(path: Path) -> dict[str, str]:
    manifest = json.loads((path / "manifest.json").read_text())
    return manifest.get("assets", manifest)


def write_asset_manifest(path: Path, hashes: dict[str, str], *, legacy: bool = False) -> None:
    manifest = (
        hashes
        if legacy
        else {
            "schemaVersion": installer.ASSET_MANIFEST_SCHEMA_VERSION,
            "capabilities": {installer.CLASSIFICATION_PERSISTENCE_CAPABILITY: True},
            "assets": hashes,
        }
    )
    (path / "manifest.json").write_text(json.dumps(manifest, sort_keys=True, indent=2) + "\n")


def staged_with_revision(
    tmp_path: Path,
    revision: str,
    manifest_sha: str | None,
    *,
    legacy: bool = False,
    unique: str = "staged",
) -> Path:
    """Render a staged asset tree with an overridden runner coordinate."""
    staged = tmp_path / unique
    installer.render(staged)
    config_path = staged / "etc/sugarkube/dspace-chat-synthetic.json"
    config = json.loads(config_path.read_text())
    config["runnerRevision"] = revision
    if manifest_sha is None:
        config.pop("runnerManifestSha256", None)
    else:
        config["runnerManifestSha256"] = manifest_sha
    config_path.write_text(json.dumps(config, sort_keys=True, indent=2) + "\n")
    hashes = asset_hashes(staged)
    hashes["etc/sugarkube/dspace-chat-synthetic.json"] = installer.sha(config_path)
    write_asset_manifest(staged, hashes, legacy=legacy)
    return staged


def test_config_and_installer_constants_match_the_exact_new_coordinate() -> None:
    config = json.loads(CONFIG.read_text(encoding="utf-8"))
    assert installer.CURRENT_RUNNER_REVISION == "f14b9e978cff52930c3f8adc1fe96beae6936cef"
    assert installer.CURRENT_RUNNER_MANIFEST_SHA256 == (
        "b0d08bda3cb459ca5576a57b5f1066427b9c1612e6e148ad0a9af1f3caeb57a5"
    )
    assert config["runnerRevision"] == installer.CURRENT_RUNNER_REVISION
    assert config["runnerManifestSha256"] == installer.CURRENT_RUNNER_MANIFEST_SHA256


def test_materialize_cli_default_revision_is_the_current_coordinate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source"
    output = tmp_path / "output"
    browser = tmp_path / "browser"
    captured = []
    monkeypatch.setattr(installer, "materialize", lambda *args: captured.append(args))
    monkeypatch.setattr(installer, "runtime_module", lambda: runtime)
    monkeypatch.setattr(
        runtime,
        "validate_node_contract",
        lambda value, _root: value["nodeContract"],
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "install_dspace_chat_synthetic.py",
            "materialize",
            "--source",
            str(source),
            "--output",
            str(output),
            "--pnpm",
            "/fixture/pnpm",
            "--pnpm-version",
            "9.0.0",
            "--browser-bundle",
            str(browser),
            "--browser-source-root",
            "/",
        ],
    )

    assert installer.main() == 0
    assert captured[0][1] == installer.CURRENT_RUNNER_REVISION


def test_current_revision_with_exact_manifest_is_accepted(tmp_path: Path) -> None:
    staged = staged_with_revision(
        tmp_path, installer.CURRENT_RUNNER_REVISION, installer.CURRENT_RUNNER_MANIFEST_SHA256
    )

    installer.validate_retained_asset(staged)
    installer.validate_current_candidate(staged)


@pytest.mark.parametrize(
    "manifest_sha",
    [WRONG_MANIFEST_SHA256, None, "not-a-sha256"],
    ids=["wrong", "missing", "malformed"],
)
def test_current_revision_requires_its_exact_manifest(
    tmp_path: Path, manifest_sha: str | None
) -> None:
    staged = staged_with_revision(tmp_path, installer.CURRENT_RUNNER_REVISION, manifest_sha)

    with pytest.raises(ValueError, match="unapproved runner revision"):
        installer.validate_retained_asset(staged)


def test_unrelated_revision_is_rejected_even_with_the_exact_new_manifest(
    tmp_path: Path,
) -> None:
    staged = staged_with_revision(
        tmp_path, UNRELATED_REVISION, installer.CURRENT_RUNNER_MANIFEST_SHA256
    )

    with pytest.raises(ValueError, match="unapproved runner revision"):
        installer.validate_retained_asset(staged)


@pytest.mark.parametrize(
    "manifest_sha",
    [None, "2" * 64, installer.CURRENT_RUNNER_MANIFEST_SHA256],
    ids=["absent", "arbitrary", "even-the-new-manifest-value"],
)
def test_historical_revision_stays_approved_regardless_of_manifest(
    tmp_path: Path, manifest_sha: str | None
) -> None:
    staged = staged_with_revision(tmp_path, installer.APPROVED_RUNNER_REVISION, manifest_sha)

    installer.validate_retained_asset(staged)


def test_legacy_manifest_shape_is_retained_but_not_a_current_candidate(
    tmp_path: Path,
) -> None:
    staged = staged_with_revision(tmp_path, installer.APPROVED_RUNNER_REVISION, None, legacy=True)

    installer.validate_retained_asset(staged)
    with pytest.raises(ValueError, match="current asset manifest contract is required"):
        installer.validate_current_candidate(staged)


def test_current_candidate_still_rejects_tampered_assets(tmp_path: Path) -> None:
    staged = staged_with_revision(
        tmp_path, installer.CURRENT_RUNNER_REVISION, installer.CURRENT_RUNNER_MANIFEST_SHA256
    )
    tampered = staged / next(iter(installer.ASSETS))
    tampered.write_bytes(tampered.read_bytes() + b"tampered")

    with pytest.raises(ValueError, match="staged asset hash mismatch"):
        installer.validate_retained_asset(staged)


def test_current_candidate_still_requires_a_persistent_timer(tmp_path: Path) -> None:
    staged = staged_with_revision(
        tmp_path, installer.CURRENT_RUNNER_REVISION, installer.CURRENT_RUNNER_MANIFEST_SHA256
    )
    timer = staged / "etc/systemd/system/dspace-chat-synthetic.timer"
    timer.write_text(timer.read_text().replace("Persistent=true\n", ""))
    hashes = asset_hashes(staged)
    hashes["etc/systemd/system/dspace-chat-synthetic.timer"] = installer.sha(timer)
    write_asset_manifest(staged, hashes)

    with pytest.raises(ValueError, match="timer is not persistent"):
        installer.validate_retained_asset(staged)


def test_current_candidate_still_requires_runtime_directory_preservation(
    tmp_path: Path,
) -> None:
    staged = staged_with_revision(
        tmp_path, installer.CURRENT_RUNNER_REVISION, installer.CURRENT_RUNNER_MANIFEST_SHA256
    )
    service = staged / "etc/systemd/system/dspace-chat-synthetic.service"
    service.write_text(service.read_text().replace("RuntimeDirectoryPreserve=yes\n", ""))
    hashes = asset_hashes(staged)
    hashes["etc/systemd/system/dspace-chat-synthetic.service"] = installer.sha(service)
    write_asset_manifest(staged, hashes)

    with pytest.raises(ValueError, match="classification runtime directory is not preserved"):
        installer.validate_current_candidate(staged)
