"""Tests for generic Sugarkube app config loading and tag validation."""

from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

from scripts import app_config


def _write_config(path: Path, app: str = "custom", **overrides: str) -> Path:
    data = {
        "SUGARKUBE_APP": app,
        "SUGARKUBE_RELEASE": f"{app}-release",
        "SUGARKUBE_NAMESPACE": f"{app}-ns",
        "SUGARKUBE_CHART": f"oci://example.invalid/charts/{app}",
        "SUGARKUBE_VERSION": "1.2.3",
        "SUGARKUBE_VALUES_DEV": "dev.yaml",
        "SUGARKUBE_VALUES_STAGING": "dev.yaml,staging.yaml",
        "SUGARKUBE_VALUES_PROD": "dev.yaml,prod.yaml",
    }
    data.update(overrides)
    path.write_text(
        "\n".join(f"{key}={value}" for key, value in data.items()) + "\n",
        encoding="utf-8",
    )
    return path


def test_example_config_fallback_resolves_staging_values() -> None:
    cfg = app_config.load_config("tokenplace", "staging")

    assert cfg["SUGARKUBE_CONFIG_PATH"].endswith("docs/examples/apps/tokenplace.env")
    assert cfg["SUGARKUBE_RELEASE"] == "tokenplace"
    assert cfg["SUGARKUBE_NAMESPACE"] == "tokenplace"
    assert cfg["SUGARKUBE_VALUES"] == (
        "docs/examples/tokenplace.values.dev.yaml,docs/examples/tokenplace.values.staging.yaml"
    )


def test_config_dir_precedes_example_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
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


def test_explicit_config_path_precedes_config_dir_and_resolves_env_values(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_dir = tmp_path / "configs"
    config_dir.mkdir()
    (config_dir / "custom.env").write_text(
        "\n".join(
            [
                "SUGARKUBE_APP=custom",
                "SUGARKUBE_RELEASE=from-dir",
                "SUGARKUBE_NAMESPACE=from-dir",
                "SUGARKUBE_CHART=oci://example.invalid/charts/from-dir",
                "SUGARKUBE_VERSION=1.2.3",
                "SUGARKUBE_VALUES_DEV=dir-dev.yaml",
                "SUGARKUBE_VALUES_STAGING=dir-dev.yaml,dir-staging.yaml",
                "SUGARKUBE_VALUES_PROD=dir-dev.yaml,dir-prod.yaml",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    explicit_config = tmp_path / "explicit.env"
    explicit_config.write_text(
        "\n".join(
            [
                "SUGARKUBE_APP=custom",
                "SUGARKUBE_RELEASE=from-explicit",
                "SUGARKUBE_NAMESPACE=from-explicit",
                "SUGARKUBE_CHART=oci://example.invalid/charts/from-explicit",
                "SUGARKUBE_VERSION=4.5.6",
                "SUGARKUBE_VALUES_DEV=explicit-dev.yaml",
                "SUGARKUBE_VALUES_STAGING=explicit-dev.yaml,explicit-staging.yaml",
                "SUGARKUBE_VALUES_PROD=explicit-dev.yaml,explicit-prod.yaml",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("SUGARKUBE_APP_CONFIG_DIR", str(config_dir))

    cfg = app_config.load_config("custom", "env=staging", str(explicit_config))

    assert cfg["SUGARKUBE_CONFIG_PATH"] == str(explicit_config)
    assert cfg["SUGARKUBE_RELEASE"] == "from-explicit"
    assert cfg["SUGARKUBE_NAMESPACE"] == "from-explicit"
    assert cfg["SUGARKUBE_VALUES"] == "explicit-dev.yaml,explicit-staging.yaml"


@pytest.mark.parametrize(
    "tag",
    ["main-deadbee", "v3-deadbee", "feature-x-deadbee", "v0.1.0", "3.0.1", "3.1.0-rc.1"],
)
def test_validate_tag_allows_immutable_tags(tag: str) -> None:
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
        "staging-blue",
        "feature-x",
    ],
)
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


def test_normalizes_int_env_and_rejects_invalid_names() -> None:
    assert app_config.normalize_env("env=int") == "staging"

    with pytest.raises(app_config.AppConfigError, match="env must be one of"):
        app_config.normalize_env("qa")

    with pytest.raises(app_config.AppConfigError, match="app must be"):
        app_config.validate_app_name("bad app")


def test_validate_tag_rejects_empty_tag() -> None:
    with pytest.raises(app_config.AppConfigError, match="must not be empty"):
        app_config.validate_tag("")


def test_parse_dotenv_accepts_exported_values(tmp_path: Path) -> None:
    config = tmp_path / "exported.env"
    config.write_text(
        "\n".join(
            [
                "# local operator notes",
                "export SUGARKUBE_APP=exported",
                "SUGARKUBE_RELEASE=exported",
                "SUGARKUBE_NAMESPACE=exported",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    data = app_config.parse_dotenv(config)

    assert data["SUGARKUBE_APP"] == "exported"
    assert data["SUGARKUBE_RELEASE"] == "exported"


@pytest.mark.parametrize(
    ("line", "message"),
    [
        ("not dotenv", "expected KEY=value"),
        ('SUGARKUBE_RELEASE="unterminated', "invalid quoted value"),
        ("SUGARKUBE_RELEASE=two words", "must be a single dotenv value"),
        ("SUGARKUBE_RELEASE=$(whoami)", "shell syntax is not allowed"),
    ],
)
def test_parse_dotenv_rejects_unsafe_or_invalid_values(
    tmp_path: Path, line: str, message: str
) -> None:
    config = tmp_path / "bad.env"
    config.write_text(f"{line}\n", encoding="utf-8")

    with pytest.raises(app_config.AppConfigError, match=message):
        app_config.parse_dotenv(config)


def test_load_config_reports_missing_config_required_keys_app_mismatch_and_values(
    tmp_path: Path,
) -> None:
    with pytest.raises(app_config.AppConfigError, match="no config found"):
        app_config.load_config("missing", "staging", str(tmp_path / "missing.env"))

    missing_required = tmp_path / "missing-required.env"
    missing_required.write_text("SUGARKUBE_APP=broken\n", encoding="utf-8")
    with pytest.raises(app_config.AppConfigError, match="missing required keys"):
        app_config.load_config("broken", "staging", str(missing_required))

    mismatch = _write_config(tmp_path / "mismatch.env", app="other")
    with pytest.raises(app_config.AppConfigError, match="does not match app"):
        app_config.load_config("expected", "staging", str(mismatch))

    missing_values = _write_config(tmp_path / "missing-values.env", SUGARKUBE_VALUES_PROD="")
    with pytest.raises(app_config.AppConfigError, match="missing SUGARKUBE_VALUES_PROD"):
        app_config.load_config("custom", "prod", str(missing_values))


def test_resolve_tag_uses_prod_fallback_file(tmp_path: Path) -> None:
    tag_file = tmp_path / "prod-tag.txt"
    tag_file.write_text("# promoted digest tag\nmain-deadbee\n", encoding="utf-8")

    tag = app_config.resolve_tag(
        {"SUGARKUBE_PROD_TAG_FILE": str(tag_file)},
        "",
        prod_fallback=True,
    )

    assert tag == "main-deadbee"


def test_shell_emit_quotes_expected_exports(tmp_path: Path) -> None:
    config = app_config.load_config(
        "custom",
        "staging",
        str(_write_config(tmp_path / "custom.env", SUGARKUBE_VERIFY_PATHS="/,/healthz")),
    )
    config["SUGARKUBE_TAG"] = "main-deadbee"

    emitted = app_config.shell_emit(config)

    assert "export SUGARKUBE_APP=custom" in emitted
    assert "export SUGARKUBE_ENV=staging" in emitted
    assert "export SUGARKUBE_VERIFY_PATHS=/,/healthz" in emitted
    assert "export SUGARKUBE_TAG=main-deadbee" in emitted


def test_main_supports_json_shell_validate_tag_and_host_value(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    config = _write_config(tmp_path / "custom.env")

    assert app_config.main(["validate-tag", "main-deadbee"]) == 0
    assert capsys.readouterr().out.strip() == "main-deadbee"

    monkeypatch.setattr("sys.stdin", io.StringIO('{"ingress":{"host":"example.test"}}'))
    assert app_config.main(["host-value", "ingress.host"]) == 0
    assert capsys.readouterr().out.strip() == "example.test"

    assert app_config.main(
        ["json", "--app", "custom", "--env", "staging", "--config", str(config)]
    ) == 0
    loaded = json.loads(capsys.readouterr().out)
    assert loaded["SUGARKUBE_VALUES"] == "dev.yaml,staging.yaml"

    assert app_config.main(
        [
            "shell",
            "--app",
            "custom",
            "--env",
            "staging",
            "--config",
            str(config),
            "--tag",
            "tag=main-deadbee",
            "--require-tag",
        ]
    ) == 0
    assert "export SUGARKUBE_TAG=main-deadbee" in capsys.readouterr().out


def test_main_reports_config_errors(capsys: pytest.CaptureFixture[str]) -> None:
    assert app_config.main(["json", "--app", "missing", "--env", "staging"]) == 2
    assert "ERROR: no config found for app 'missing'" in capsys.readouterr().err


def test_example_app_verify_paths_remain_expected() -> None:
    assert app_config.load_config("danielsmith", "staging")["SUGARKUBE_VERIFY_PATHS"] == "/,/livez,/healthz"
    assert app_config.load_config("tokenplace", "staging")["SUGARKUBE_VERIFY_PATHS"] == "/,/livez,/healthz,/relay/diagnostics"
    assert app_config.load_config("dspace", "staging")["SUGARKUBE_VERIFY_PATHS"] == "/config.json,/healthz,/livez"
