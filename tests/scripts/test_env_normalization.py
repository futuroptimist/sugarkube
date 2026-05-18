"""Regression tests for Sugarkube environment argument normalization."""

from __future__ import annotations

import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
ENV_LIB = REPO_ROOT / "scripts" / "lib" / "env.sh"


def _normalize_env(value: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            "bash",
            "-c",
            "source \"$1\"; sugarkube_normalize_env \"$2\"",
            "bash",
            str(ENV_LIB),
            value,
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


def test_normalize_env_accepts_positional_and_named_forms() -> None:
    """The outage regression was `env=staging` leaking into k3s mDNS names."""
    cases = {
        "staging": "staging",
        "env=staging": "staging",
        "env=env=staging": "staging",
        "dev": "dev",
        "prod": "prod",
    }

    for raw, expected in cases.items():
        result = _normalize_env(raw)
        assert result.returncode == 0, result.stderr
        assert result.stdout == f"{expected}\n"
        assert "env=staging" not in result.stdout


def test_normalize_env_preserves_int_alias_to_staging() -> None:
    result = _normalize_env("int")

    assert result.returncode == 0
    assert result.stdout == "staging\n"
    assert 'env name "int" is deprecated' in result.stderr


def test_normalized_staging_does_not_build_malformed_discovery_names() -> None:
    """Guard the DSPACE outage case that produced `_k3s-sugar-env=staging._tcp`."""
    result = _normalize_env("env=env=staging")
    assert result.returncode == 0, result.stderr

    env_name = result.stdout.strip()
    service_type = f"_k3s-sugar-{env_name}._tcp"
    txt_record = f"env={env_name}"
    service_file = f"/etc/avahi/services/k3s-sugar-{env_name}.service"

    assert env_name == "staging"
    assert service_type == "_k3s-sugar-staging._tcp"
    assert txt_record == "env=staging"
    assert service_file == "/etc/avahi/services/k3s-sugar-staging.service"
    assert "env=staging" not in service_type
    assert "env=env=staging" not in txt_record
    assert "k3s-sugar-env=staging" not in service_file
