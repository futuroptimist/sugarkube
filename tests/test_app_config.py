"""Tests for generic Sugarkube app config loading and tag validation."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from scripts import app_config

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_app_config_uses_example_fallback_for_existing_apps(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(REPO_ROOT)
    monkeypatch.delenv("SUGARKUBE_APP_CONFIG_DIR", raising=False)

    config = app_config.load_config("tokenplace", "env=staging")

    assert config["SUGARKUBE_CONFIG_PATH"] == "docs/examples/apps/tokenplace.env"
    assert config["SUGARKUBE_RELEASE"] == "tokenplace"
    assert config["SUGARKUBE_VALUES"] == (
        "docs/examples/tokenplace.values.dev.yaml,docs/examples/tokenplace.values.staging.yaml"
    )


def test_app_config_dir_precedes_local_and_example_configs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_dir = tmp_path / "configs"
    config_dir.mkdir()
    override = config_dir / "danielsmith.env"
    override.write_text(
        "\n".join(
            [
                "SUGARKUBE_APP=danielsmith",
                "SUGARKUBE_RELEASE=custom-danielsmith",
                "SUGARKUBE_NAMESPACE=custom-ns",
                "SUGARKUBE_CHART=oci://example.test/charts/danielsmith",
                "SUGARKUBE_VERSION_FILE=docs/apps/danielsmith.version",
                "SUGARKUBE_PROD_TAG_FILE=docs/apps/danielsmith.prod.tag",
                "SUGARKUBE_VALUES_DEV=values-dev.yaml",
                "SUGARKUBE_VALUES_STAGING=values-dev.yaml,values-staging.yaml",
                "SUGARKUBE_VALUES_PROD=values-dev.yaml,values-prod.yaml",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.chdir(REPO_ROOT)
    monkeypatch.setenv("SUGARKUBE_APP_CONFIG_DIR", str(config_dir))

    config = app_config.load_config("danielsmith", "staging")

    assert config["SUGARKUBE_CONFIG_PATH"] == str(override)
    assert config["SUGARKUBE_RELEASE"] == "custom-danielsmith"
    assert config["SUGARKUBE_VALUES"] == "values-dev.yaml,values-staging.yaml"


def test_explicit_config_precedes_config_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_dir = tmp_path / "configs"
    config_dir.mkdir()
    (config_dir / "dspace.env").write_text("SUGARKUBE_APP=dspace\n", encoding="utf-8")
    explicit = tmp_path / "explicit.env"
    explicit.write_text(
        "\n".join(
            [
                "SUGARKUBE_APP=dspace",
                "SUGARKUBE_RELEASE=explicit-dspace",
                "SUGARKUBE_NAMESPACE=dspace",
                "SUGARKUBE_CHART=oci://example.test/charts/dspace",
                "SUGARKUBE_VERSION_FILE=docs/apps/dspace.version",
                "SUGARKUBE_PROD_TAG_FILE=docs/apps/dspace.prod.tag",
                "SUGARKUBE_VALUES_DEV=dev.yaml",
                "SUGARKUBE_VALUES_STAGING=dev.yaml,staging.yaml",
                "SUGARKUBE_VALUES_PROD=dev.yaml,prod.yaml",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.chdir(REPO_ROOT)
    monkeypatch.setenv("SUGARKUBE_APP_CONFIG_DIR", str(config_dir))

    config = app_config.load_config("dspace", "staging", str(explicit))

    assert config["SUGARKUBE_CONFIG_PATH"] == str(explicit)
    assert config["SUGARKUBE_RELEASE"] == "explicit-dspace"


@pytest.mark.parametrize(
    "tag",
    ["main-deadbee", "v3-deadbee", "feature-x-deadbee", "v0.1.0", "3.0.1", "3.1.0", "v1.2.3-rc.1"],
)
def test_validate_tag_accepts_immutable_tags(tag: str) -> None:
    assert app_config.validate_tag(tag) == tag


@pytest.mark.parametrize(
    "tag",
    [
        "latest",
        "main",
        "master",
        "dev",
        "develop",
        "staging",
        "prod",
        "production",
        "release",
        "main-latest",
        "feature-prod",
    ],
)
def test_validate_tag_rejects_moving_tags(tag: str) -> None:
    with pytest.raises(app_config.AppConfigError, match="tag"):
        app_config.validate_tag(tag)


def test_parse_dotenv_rejects_unknown_keys_and_shell_syntax(tmp_path: Path) -> None:
    config = tmp_path / "bad.env"
    config.write_text(
        "\n".join(
            [
                "SUGARKUBE_APP=dspace",
                "SUGARKUBE_RELEASE=$(whoami)",
                "SUGARKUBE_NAMESPACE=dspace",
                "SUGARKUBE_CHART=oci://example.test/charts/dspace",
                "SUGARKUBE_VERSION_FILE=docs/apps/dspace.version",
                "SUGARKUBE_PROD_TAG_FILE=docs/apps/dspace.prod.tag",
                "SUGARKUBE_VALUES_DEV=dev.yaml",
                "SUGARKUBE_VALUES_STAGING=dev.yaml,staging.yaml",
                "SUGARKUBE_VALUES_PROD=dev.yaml,prod.yaml",
                "UNRELATED=value",
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(app_config.AppConfigError, match="shell syntax"):
        app_config.parse_dotenv(config)


def test_app_config_cli_shell_output_is_export_safe() -> None:
    result = subprocess.run(
        [
            "python3",
            "scripts/app_config.py",
            "config",
            "--app",
            "dspace",
            "--env",
            "staging",
            "--format",
            "shell",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "export SUGARKUBE_APP=dspace" in result.stdout
    assert "export SUGARKUBE_VALUES=" in result.stdout
