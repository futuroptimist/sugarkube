"""Regression tests for the danielsmith.io GitHub metrics cache overlays and docs."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
EXPECTED_REPOS = [
    "futuroptimist/danielsmith.io",
    "futuroptimist/token.place",
    "futuroptimist/gabriel",
    "futuroptimist/flywheel",
    "futuroptimist/jobbot3000",
    "futuroptimist/gitshelves",
    "futuroptimist/f2clipboard",
    "futuroptimist/sigma",
    "futuroptimist/wove",
    "democratizedspace/dspace",
    "futuroptimist/pr-reaper",
]


def _read(path: str) -> str:
    return (REPO_ROOT / path).read_text(encoding="utf-8")


def _repo_pairs(values_text: str) -> list[str]:
    repos: list[str] = []
    owner = ""
    for raw_line in values_text.splitlines():
        line = raw_line.strip()
        if line.startswith("- owner: "):
            owner = line.removeprefix("- owner: ").strip()
        elif owner and line.startswith("repo: "):
            repos.append(f"{owner}/{line.removeprefix('repo: ').strip()}")
            owner = ""
    return repos


def test_danielsmith_chart_version_pin_includes_github_metrics_sidecar_chart() -> None:
    version_lines = [
        line.strip()
        for line in _read("docs/apps/danielsmith.version").splitlines()
        if line.strip() and not line.startswith("#")
    ]

    assert version_lines == ["0.2.1"]


def test_danielsmith_staging_and_prod_enable_public_github_metrics_cache() -> None:
    for env in ("staging", "prod"):
        values = _read(f"docs/examples/danielsmith.values.{env}.yaml")

        assert "githubMetricsCache:" in values
        assert "  enabled: true" in values
        assert "  refreshIntervalSeconds: 3600" in values
        assert "  cacheTtlSeconds: 7200" in values
        assert _repo_pairs(values) == EXPECTED_REPOS
        github_metrics_block = values.split("githubMetricsCache:", 1)[1]
        assert "githubToken" not in github_metrics_block
        assert "secretRef" not in github_metrics_block
        assert "envFrom" not in github_metrics_block
        assert "valueFrom" not in github_metrics_block


def test_danielsmith_dev_keeps_github_metrics_cache_disabled_by_omission() -> None:
    values = _read("docs/examples/danielsmith.values.dev.yaml")

    assert "githubMetricsCache" not in values


def test_danielsmith_docs_explain_unauthenticated_runtime_cache() -> None:
    docs = "\n".join(
        _read(path)
        for path in [
            "docs/apps/danielsmith.md",
            "docs/k3s-danielsmith-staging.md",
            "docs/k3s-danielsmith-prod.md",
            "docs/app_deployment_contract.md",
        ]
    )

    assert "/runtime/github-metrics.json" in docs
    assert "github-metrics-cache" in docs
    assert "No GitHub token" in docs or "no GitHub token" in docs
    assert "Secret" in docs
    assert "unauthenticated" in docs
    assert "schemaVersion" in docs
    assert "generatedAt" in docs
    assert "repos" in docs


def test_danielsmith_app_config_resolves_for_staging_and_prod() -> None:
    for env in ("staging", "prod"):
        result = subprocess.run(
            [
                "python3",
                "scripts/app_config.py",
                "json",
                "--app",
                "danielsmith",
                "--env",
                env,
                "--config",
                "",
            ],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )

        assert result.returncode == 0, result.stderr
        config = json.loads(result.stdout)
        assert config["SUGARKUBE_ENV"] == env
        assert f"docs/examples/danielsmith.values.{env}.yaml" in config["SUGARKUBE_VALUES"]
        assert config["SUGARKUBE_VERSION_FILE"] == "docs/apps/danielsmith.version"
