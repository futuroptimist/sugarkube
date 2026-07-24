"""Focused tests for DSPACE token.place runtime Helm values."""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from scripts.app_config import load_config  # noqa: E402

OVERLAYS = {
    "staging": REPO_ROOT / "docs/examples/dspace.values.staging.yaml",
    "prod": REPO_ROOT / "docs/examples/dspace.values.prod.yaml",
}
ALL_DSPACE_VALUES = sorted((REPO_ROOT / "docs/examples").glob("dspace.values.*.yaml"))
EXPECTED_VALUES_CHAINS = {
    "staging": "docs/examples/dspace.values.dev.yaml,docs/examples/dspace.values.staging.yaml",
    "prod": "docs/examples/dspace.values.dev.yaml,docs/examples/dspace.values.prod.yaml",
}
TOKEN_PLACE_NAMES = {
    "DSPACE_TOKEN_PLACE_URL",
    "DSPACE_TOKEN_PLACE_CHAT_MODEL",
}
FORBIDDEN_RUNTIME_PATTERNS = (
    re.compile(r"VITE_TOKEN_PLACE_URL", re.IGNORECASE),
    re.compile(r"VITE_TOKEN_PLACE_CHAT_MODEL", re.IGNORECASE),
    re.compile(r"Authorization", re.IGNORECASE),
    re.compile("api" + "Key", re.IGNORECASE),
    re.compile(r"credential", re.IGNORECASE),
)


def _runtime_env(path: Path) -> dict[str, list[str]]:
    """Parse the simple chart env list used by the DSPACE example overlays."""
    env: dict[str, list[str]] = {}
    in_env = False
    current_name: str | None = None
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if line == "env:":
            in_env = True
            continue
        if not in_env:
            continue
        if line.startswith("- name: "):
            current_name = line.removeprefix("- name: ").strip()
            continue
        if line.startswith("value: ") and current_name is not None:
            env.setdefault(current_name, []).append(
                line.removeprefix("value: ").strip().strip('"')
            )
            current_name = None
    return env


def test_dspace_staging_overlay_points_to_staging_token_place() -> None:
    env = _runtime_env(OVERLAYS["staging"])

    assert env["DSPACE_TOKEN_PLACE_URL"] == ["https://staging.token.place"]
    assert env["DSPACE_TOKEN_PLACE_CHAT_MODEL"] == ["llama-3.1-8b-instruct"]


def test_dspace_prod_overlay_points_to_prod_token_place() -> None:
    env = _runtime_env(OVERLAYS["prod"])

    assert env["DSPACE_TOKEN_PLACE_URL"] == ["https://token.place"]
    assert env["DSPACE_TOKEN_PLACE_CHAT_MODEL"] == ["llama-3.1-8b-instruct"]


def test_dspace_deployment_overlays_have_no_vite_runtime_env() -> None:
    for path in OVERLAYS.values():
        env = _runtime_env(path)
        assert TOKEN_PLACE_NAMES <= env.keys()
        vite_names = sorted(name for name in env if name.startswith("VITE_"))
        assert vite_names == []


def test_all_dspace_values_do_not_carry_forbidden_runtime_names_or_credentials() -> None:
    for path in ALL_DSPACE_VALUES:
        text = path.read_text(encoding="utf-8")
        for pattern in FORBIDDEN_RUNTIME_PATTERNS:
            assert pattern.search(text) is None, f"{pattern.pattern} found in {path}"


def test_dspace_values_chains_resolve_expected_deployment_overlays() -> None:
    for env, expected_values in EXPECTED_VALUES_CHAINS.items():
        config = load_config("dspace", env)
        assert config["SUGARKUBE_VALUES"] == expected_values


def _first_version(path: Path) -> str:
    for line in path.read_text(encoding="utf-8").splitlines():
        version = line.split("#", 1)[0].strip()
        if version:
            return version
    raise AssertionError(f"no version in {path}")


def test_dspace_environment_chart_pins_and_prod_tag_are_fixed() -> None:
    staging = load_config("dspace", "staging")
    prod = load_config("dspace", "prod")

    assert staging["SUGARKUBE_VERSION_FILE"] == "docs/apps/dspace.staging.version"
    assert staging["SUGARKUBE_RESOLVED_VERSION"] == "3.1.0"
    assert _first_version(REPO_ROOT / "docs/apps/dspace.staging.version") == "3.1.0"
    assert prod["SUGARKUBE_VERSION_FILE"] == "docs/apps/dspace.prod.version"
    assert prod["SUGARKUBE_RESOLVED_VERSION"] == "3.0.1"
    assert _first_version(REPO_ROOT / "docs/apps/dspace.prod.version") == "3.0.1"
    assert _first_version(REPO_ROOT / "docs/apps/dspace.version") == "3.0.1"
    assert _first_version(REPO_ROOT / "docs/apps/dspace.prod.tag") == "main-1a31a56"


def test_dspace_staging_values_enable_authenticated_metrics_servicemonitor() -> None:
    text = OVERLAYS["staging"].read_text(encoding="utf-8")

    assert text.count("serviceMonitor:") == 1
    assert "metrics:\n  enabled: true" in text
    assert "existingSecret: dspace-staging-metrics-token" in text
    assert "secretKey: token" in text
    assert "serviceMonitor:\n  enabled: true" in text
    assert "release: kube-prometheus-stack" in text
    assert "cluster: sugarkube-int" in text
    assert "bearer" not in text.lower()


def test_dspace_prod_values_do_not_enable_metrics_or_servicemonitor() -> None:
    text = OVERLAYS["prod"].read_text(encoding="utf-8")

    assert "serviceMonitor:" not in text
    assert "metrics:" not in text
    assert "dspace-staging-metrics-token" not in text
