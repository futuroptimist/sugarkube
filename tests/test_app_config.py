from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from scripts import app_config

ROOT = Path(__file__).resolve().parents[1]


def write_config(path: Path, app: str, release: str = "demo") -> None:
    path.write_text(
        f"""
SUGARKUBE_APP={app}
SUGARKUBE_RELEASE={release}
SUGARKUBE_NAMESPACE={release}
SUGARKUBE_CHART=oci://example.test/charts/{release}
SUGARKUBE_VERSION_FILE=docs/apps/{release}.version
SUGARKUBE_PROD_TAG_FILE=docs/apps/{release}.prod.tag
SUGARKUBE_VALUES_DEV=docs/examples/{release}.values.dev.yaml
SUGARKUBE_VALUES_STAGING=docs/examples/{release}.values.dev.yaml,docs/examples/{release}.values.staging.yaml
SUGARKUBE_VALUES_PROD=docs/examples/{release}.values.dev.yaml,docs/examples/{release}.values.prod.yaml
SUGARKUBE_STATUS_HOST_KEY=ingress.host
SUGARKUBE_VERIFY_PATHS=/,/healthz
""".strip() + "\n",
        encoding="utf-8",
    )


def test_app_config_prefers_explicit_path_over_config_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_dir = tmp_path / "dir"
    config_dir.mkdir()
    write_config(config_dir / "demo.env", "demo", release="from-dir")
    explicit = tmp_path / "explicit.env"
    write_config(explicit, "demo", release="from-explicit")
    monkeypatch.setenv("SUGARKUBE_APP_CONFIG_DIR", str(config_dir))

    resolved = app_config.resolve_config("demo", "env=staging", str(explicit))

    assert resolved["SUGARKUBE_CONFIG_PATH"] == str(explicit)
    assert resolved["SUGARKUBE_RELEASE"] == "from-explicit"
    assert resolved["SUGARKUBE_VALUES"] == (
        "docs/examples/from-explicit.values.dev.yaml,"
        "docs/examples/from-explicit.values.staging.yaml"
    )


def test_app_config_uses_config_dir_before_example_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_dir = tmp_path / "apps"
    config_dir.mkdir()
    write_config(config_dir / "dspace.env", "dspace", release="local-dspace")
    monkeypatch.setenv("SUGARKUBE_APP_CONFIG_DIR", str(config_dir))

    resolved = app_config.resolve_config("app=dspace", "staging")

    assert resolved["SUGARKUBE_RELEASE"] == "local-dspace"
    assert resolved["SUGARKUBE_CONFIG_PATH"] == str(config_dir / "dspace.env")


def test_app_config_falls_back_to_documented_examples(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SUGARKUBE_APP_CONFIG_DIR", raising=False)

    resolved = app_config.resolve_config("tokenplace", "staging")

    assert resolved["SUGARKUBE_CONFIG_PATH"].endswith("docs/examples/apps/tokenplace.env")
    assert resolved["SUGARKUBE_CHART"] == "oci://ghcr.io/futuroptimist/charts/tokenplace"
    assert resolved["SUGARKUBE_VALUES"] == (
        "docs/examples/tokenplace.values.dev.yaml,docs/examples/tokenplace.values.staging.yaml"
    )


def test_app_config_rejects_unknown_keys_when_emitting_shell(tmp_path: Path) -> None:
    config = tmp_path / "bad.env"
    write_config(config, "bad")
    config.write_text(
        config.read_text(encoding="utf-8") + "DANGEROUS=$(whoami)\n", encoding="utf-8"
    )

    with pytest.raises(app_config.AppConfigError, match="unknown app config key"):
        app_config.resolve_config("bad", "staging", str(config))


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
        "feature-x",
    ],
)
def test_validate_tag_rejects_mutable_tags(tag: str) -> None:
    with pytest.raises(app_config.AppConfigError, match="immutable|mutable|missing"):
        app_config.validate_tag(tag)


@pytest.mark.usefixtures("ensure_just_available")
def test_generic_app_deploys_pass_expected_helm_args(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    helm_log = tmp_path / "helm.log"
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "helm").write_text(
        f"#!/usr/bin/env bash\nprintf '%s\\n' \"$*\" >> {helm_log}\n",
        encoding="utf-8",
    )
    (bin_dir / "kubectl").write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    (bin_dir / "helm").chmod(0o755)
    (bin_dir / "kubectl").chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("SUGARKUBE_SKIP_KUBECONFIG_ENV", "1")

    cases = {
        "danielsmith": (
            "danielsmith danielsmith oci://ghcr.io/futuroptimist/charts/danielsmith",
            "-f docs/examples/danielsmith.values.dev.yaml "
            "-f docs/examples/danielsmith.values.staging.yaml",
        ),
        "tokenplace": (
            "tokenplace tokenplace oci://ghcr.io/futuroptimist/charts/tokenplace",
            "-f docs/examples/tokenplace.values.dev.yaml "
            "-f docs/examples/tokenplace.values.staging.yaml",
        ),
        "dspace": (
            "dspace dspace oci://ghcr.io/democratizedspace/charts/dspace",
            "-f docs/examples/dspace.values.dev.yaml -f docs/examples/dspace.values.staging.yaml",
        ),
    }
    for app in cases:
        result = subprocess.run(
            [
                shutil.which("just") or "just",
                "app-deploy",
                f"app={app}",
                "env=staging",
                "tag=main-deadbee",
            ],
            cwd=ROOT,
            text=True,
            capture_output=True,
            env=os.environ.copy(),
        )
        assert result.returncode == 0, result.stderr

    log = helm_log.read_text(encoding="utf-8")
    assert log.count("--set image.tag=main-deadbee") == 3
    for expected, values in cases.values():
        release, namespace, chart = expected.split()
        assert f"upgrade {release} {chart} --namespace {namespace}" in log
        assert values in log


@pytest.mark.usefixtures("ensure_just_available")
def test_generic_deploy_rejects_mutable_tag_before_helm(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    helm_log = tmp_path / "helm.log"
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "helm").write_text(
        f"#!/usr/bin/env bash\necho should-not-run >> {helm_log}\n", encoding="utf-8"
    )
    (bin_dir / "helm").chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("SUGARKUBE_SKIP_KUBECONFIG_ENV", "1")

    result = subprocess.run(
        [
            shutil.which("just") or "just",
            "app-deploy",
            "app=danielsmith",
            "env=staging",
            "tag=latest",
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        env=os.environ.copy(),
    )

    assert result.returncode != 0
    assert "mutable tag" in result.stderr
    assert not helm_log.exists()


@pytest.mark.usefixtures("ensure_just_available")
def test_app_specific_wrappers_delegate_to_generic_deploys(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    helm_log = tmp_path / "helm.log"
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "helm").write_text(
        f"#!/usr/bin/env bash\nprintf '%s\\n' \"$*\" >> {helm_log}\n",
        encoding="utf-8",
    )
    (bin_dir / "kubectl").write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    (bin_dir / "helm").chmod(0o755)
    (bin_dir / "kubectl").chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("SUGARKUBE_SKIP_KUBECONFIG_ENV", "1")

    for recipe in ["danielsmith-oci-deploy", "tokenplace-oci-deploy", "dspace-oci-deploy"]:
        result = subprocess.run(
            [shutil.which("just") or "just", recipe, "env=staging", "tag=main-deadbee"],
            cwd=ROOT,
            text=True,
            capture_output=True,
            env=os.environ.copy(),
        )
        assert result.returncode == 0, result.stderr

    log = helm_log.read_text(encoding="utf-8")
    assert "upgrade danielsmith oci://ghcr.io/futuroptimist/charts/danielsmith" in log
    assert "upgrade tokenplace oci://ghcr.io/futuroptimist/charts/tokenplace" in log
    assert "upgrade dspace oci://ghcr.io/democratizedspace/charts/dspace" in log
