"""Tests for the generic Sugarkube app config loader."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from scripts import app_config

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_example_config_resolves_staging_values() -> None:
    config = app_config.load_app_config("danielsmith", "env=staging")

    assert config["SUGARKUBE_CONFIG_PATH"].endswith("docs/examples/apps/danielsmith.env")
    assert config["SUGARKUBE_RELEASE"] == "danielsmith"
    assert (
        config["SUGARKUBE_VALUES"]
        == "docs/examples/danielsmith.values.dev.yaml,docs/examples/danielsmith.values.staging.yaml"
    )


def test_config_resolution_prefers_explicit_then_env_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    env_dir = tmp_path / "env-dir"
    env_dir.mkdir()
    explicit = tmp_path / "explicit.env"
    env_config = env_dir / "demo.env"
    base = """
SUGARKUBE_APP=demo
SUGARKUBE_RELEASE={release}
SUGARKUBE_NAMESPACE=demo
SUGARKUBE_CHART=oci://example.invalid/charts/demo
SUGARKUBE_VERSION_FILE=docs/apps/demo.version
SUGARKUBE_PROD_TAG_FILE=docs/apps/demo.prod.tag
SUGARKUBE_VALUES_DEV=dev.yaml
SUGARKUBE_VALUES_STAGING=dev.yaml,staging.yaml
SUGARKUBE_VALUES_PROD=dev.yaml,prod.yaml
""".lstrip()
    explicit.write_text(base.format(release="explicit"), encoding="utf-8")
    env_config.write_text(base.format(release="envdir"), encoding="utf-8")
    monkeypatch.setenv("SUGARKUBE_APP_CONFIG_DIR", str(env_dir))

    assert app_config.load_app_config("demo", "staging", str(explicit))["SUGARKUBE_RELEASE"] == "explicit"
    assert app_config.load_app_config("demo", "staging")["SUGARKUBE_RELEASE"] == "envdir"


@pytest.mark.parametrize(
    "tag",
    ["main-deadbee", "v3-deadbee", "feature-x-deadbee", "v0.1.0", "3.0.1", "3.1.0", "v1.2.3-rc.1"],
)
def test_validate_immutable_tag_accepts_supported_shapes(tag: str) -> None:
    assert app_config.validate_immutable_tag(f"tag={tag}") == tag


@pytest.mark.parametrize(
    "tag",
    ["latest", "main", "master", "dev", "develop", "staging", "prod", "production", "release", "main-latest", "foo-prod", "feature-x"],
)
def test_validate_immutable_tag_rejects_moving_tags(tag: str) -> None:
    with pytest.raises(app_config.ConfigError) as excinfo:
        app_config.validate_immutable_tag(tag)

    assert "mutable" in str(excinfo.value) or "immutable" in str(excinfo.value) or "moving" in str(excinfo.value)


def test_rejects_unknown_config_keys_when_emitting_shell(tmp_path: Path) -> None:
    config = tmp_path / "bad.env"
    config.write_text("SUGARKUBE_APP=bad\nDANGEROUS=$(echo nope)\n", encoding="utf-8")

    result = subprocess.run(
        [
            os.environ.get("PYTHON", "python3"),
            str(REPO_ROOT / "scripts" / "app_config.py"),
            "config",
            "--app",
            "bad",
            "--env",
            "staging",
            "--config",
            str(config),
            "--format",
            "shell",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0
    assert "unsupported app config key" in result.stderr
