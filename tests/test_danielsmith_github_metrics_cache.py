"""Regression tests for danielsmith.io GitHub metrics cache deployment docs."""

from __future__ import annotations

import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

EXPECTED_REPOS = [
    ("futuroptimist", "danielsmith.io"),
    ("futuroptimist", "token.place"),
    ("futuroptimist", "gabriel"),
    ("futuroptimist", "flywheel"),
    ("futuroptimist", "jobbot3000"),
    ("futuroptimist", "gitshelves"),
    ("futuroptimist", "f2clipboard"),
    ("futuroptimist", "sigma"),
    ("futuroptimist", "wove"),
    ("democratizedspace", "dspace"),
    ("futuroptimist", "pr-reaper"),
]


def _read(relative_path: str) -> str:
    return (REPO_ROOT / relative_path).read_text(encoding="utf-8")


def test_staging_and_prod_enable_unauthenticated_github_metrics_cache() -> None:
    for env in ("staging", "prod"):
        text = _read(f"docs/examples/danielsmith.values.{env}.yaml")

        assert "githubMetricsCache:\n  enabled: true" in text
        assert "  refreshIntervalSeconds: 3600" in text
        assert "  cacheTtlSeconds: 9000" in text
        for owner, repo in EXPECTED_REPOS:
            assert f"    - owner: {owner}\n      repo: {repo}" in text

        cache_block = text.split("githubMetricsCache:", 1)[1].lower()
        assert "github_token" not in cache_block
        assert "githubtoken" not in cache_block
        assert "authorization" not in cache_block
        assert "secret" not in cache_block
        assert "envfrom" not in cache_block


def test_danielsmith_verify_paths_include_runtime_cache() -> None:
    env_text = _read("docs/examples/apps/danielsmith.env")
    assert "SUGARKUBE_VERIFY_PATHS=/,/livez,/healthz,/runtime/github-metrics.json" in env_text


def test_danielsmith_docs_explain_no_token_or_secret_needed() -> None:
    text = _read("docs/apps/danielsmith.md")

    assert "## Runtime GitHub metrics cache" in text
    assert "/runtime/github-metrics.json" in text
    assert "unauthenticated public GitHub REST API" in text
    assert "does **not** need a GitHub token" in text
    assert "Kubernetes Secret" in text
    assert "stars can be up to about an hour old" in text
    assert (
        "kubectl --context sugar-staging -n danielsmith logs deploy/danielsmith "
        "-c github-metrics-cache --tail=100"
    ) in text


def test_app_config_resolves_for_danielsmith_staging_and_prod() -> None:
    for env in ("staging", "prod"):
        result = subprocess.run(
            ["python3", "scripts/app_config.py", "json", "--app", "danielsmith", "--env", env],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )

        assert result.returncode == 0, result.stderr
        assert '"SUGARKUBE_APP": "danielsmith"' in result.stdout
        assert (
            '"SUGARKUBE_VERIFY_PATHS": "/,/livez,/healthz,/runtime/github-metrics.json"'
            in result.stdout
        )
