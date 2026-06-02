"""Tests for generic Sugarkube app config loading and tag validation."""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts import app_config


def test_example_config_fallback_resolves_staging_values() -> None:
    cfg = app_config.load_config("tokenplace", "staging")

    assert cfg["SUGARKUBE_CONFIG_PATH"].endswith("docs/examples/apps/tokenplace.env")
    assert cfg["SUGARKUBE_RELEASE"] == "tokenplace"
    assert cfg["SUGARKUBE_NAMESPACE"] == "tokenplace"
    assert cfg["SUGARKUBE_VALUES"] == (
        "docs/examples/tokenplace.values.dev.yaml,docs/examples/tokenplace.values.staging.yaml"
    )


def test_config_dir_precedes_example_fallback(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config_dir = tmp_path / "configs"
    config_dir.mkdir()
    (config_dir / "custom.env").write_text(
        "\n".join(
            [
                "SUGARKUBE_APP=custom",
                "SUGARKUBE_RELEASE=custom-release",
                "SUGARKUBE_NAMESPACE=custom-ns",
                "SUGARKUBE_CHART=oci://example.invalid/charts/custom",
                "SUGARKUBE_VERSION=1.2.3",
                "SUGARKUBE_VALUES_DEV=dev.yaml",
                "SUGARKUBE_VALUES_STAGING=dev.yaml,staging.yaml",
                "SUGARKUBE_VALUES_PROD=dev.yaml,prod.yaml",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("SUGARKUBE_APP_CONFIG_DIR", str(config_dir))

    cfg = app_config.load_config("custom", "env=staging")

    assert cfg["SUGARKUBE_CONFIG_PATH"] == str(config_dir / "custom.env")
    assert cfg["SUGARKUBE_VALUES"] == "dev.yaml,staging.yaml"


@pytest.mark.parametrize("tag", ["main-deadbee", "v3-deadbee", "feature-x-deadbee", "v0.1.0", "3.0.1", "3.1.0-rc.1"])
def test_validate_tag_allows_immutable_tags(tag: str) -> None:
    assert app_config.validate_tag(tag) == tag


@pytest.mark.parametrize("tag", ["latest", "main", "master", "dev", "develop", "staging", "prod", "production", "release", "staging-blue", "feature-x"])
def test_validate_tag_rejects_moving_tags(tag: str) -> None:
    with pytest.raises(app_config.AppConfigError, match="tag"):
        app_config.validate_tag(tag)


def test_rejects_unknown_dotenv_keys(tmp_path: Path) -> None:
    config = tmp_path / "bad.env"
    config.write_text(
        "\n".join(
            [
                "SUGARKUBE_APP=bad",
                "SUGARKUBE_RELEASE=bad",
                "SUGARKUBE_NAMESPACE=bad",
                "SUGARKUBE_CHART=oci://example.invalid/charts/bad",
                "SUGARKUBE_VERSION=1.2.3",
                "SUGARKUBE_VALUES_DEV=dev.yaml",
                "SUGARKUBE_VALUES_STAGING=staging.yaml",
                "SUGARKUBE_VALUES_PROD=prod.yaml",
                "BASH_ENV=/tmp/pwn",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(app_config.AppConfigError, match="unknown app config key"):
        app_config.load_config("bad", "staging", str(config))


def test_dotenv_parser_strips_inline_comments(tmp_path: Path) -> None:
    config = tmp_path / "commented.env"
    config.write_text(
        "\n".join(
            [
                "SUGARKUBE_APP=commented",
                "SUGARKUBE_RELEASE=commented",
                "SUGARKUBE_NAMESPACE=commented",
                "SUGARKUBE_CHART=oci://example.invalid/charts/commented",
                "SUGARKUBE_VERSION_FILE=docs/apps/commented.version # approved chart pin",
                "SUGARKUBE_VALUES_DEV=dev.yaml",
                "SUGARKUBE_VALUES_STAGING=dev.yaml,staging.yaml # staging overlays",
                "SUGARKUBE_VALUES_PROD=dev.yaml,prod.yaml",
                "SUGARKUBE_VERIFY_PATHS=/,/healthz # prod checks",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    cfg = app_config.load_config("commented", "staging", str(config))

    assert cfg["SUGARKUBE_VALUES"] == "dev.yaml,staging.yaml"
    assert cfg["SUGARKUBE_VERIFY_PATHS"] == "/,/healthz"
    assert cfg["SUGARKUBE_VERSION_FILE"] == "docs/apps/commented.version"


def test_requires_chart_version_pin(tmp_path: Path) -> None:
    config = tmp_path / "unpinned.env"
    config.write_text(
        "\n".join(
            [
                "SUGARKUBE_APP=unpinned",
                "SUGARKUBE_RELEASE=unpinned",
                "SUGARKUBE_NAMESPACE=unpinned",
                "SUGARKUBE_CHART=oci://example.invalid/charts/unpinned",
                "SUGARKUBE_VALUES_DEV=dev.yaml",
                "SUGARKUBE_VALUES_STAGING=dev.yaml,staging.yaml",
                "SUGARKUBE_VALUES_PROD=dev.yaml,prod.yaml",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(app_config.AppConfigError, match="missing chart version pin"):
        app_config.load_config("unpinned", "staging", str(config))
