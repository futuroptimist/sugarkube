"""Regression tests for the danielsmith.io runtime GitHub metrics cache config."""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
EXPECTED_REPOS = {
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
}


def _read(path: str) -> str:
    return (REPO_ROOT / path).read_text(encoding="utf-8")


def _github_metrics_block(env: str) -> str:
    text = _read(f"docs/examples/danielsmith.values.{env}.yaml")
    match = re.search(r"(?ms)^githubMetricsCache:\n(?P<block>.*)$", text)
    assert match, f"missing githubMetricsCache block in {env} values"
    return match.group("block")


def _configured_repos(block: str) -> set[str]:
    repos: set[str] = set()
    owner = ""
    for line in block.splitlines():
        owner_match = re.match(r"\s*- owner: (\S+)\s*$", line)
        if owner_match:
            owner = owner_match.group(1)
            continue
        repo_match = re.match(r"\s*repo: (\S+)\s*$", line)
        if repo_match and owner:
            repos.add(f"{owner}/{repo_match.group(1)}")
            owner = ""
    return repos


def test_staging_and_prod_enable_public_github_metrics_cache() -> None:
    for env in ("staging", "prod"):
        block = _github_metrics_block(env)
        assert re.search(r"(?m)^\s+enabled: true$", block)
        assert re.search(r"(?m)^\s+refreshIntervalSeconds: 3600$", block)
        assert re.search(r"(?m)^\s+cacheTtlSeconds: 7200$", block)
        assert _configured_repos(block) == EXPECTED_REPOS
        assert "DSPACE" not in block
        for forbidden in ("githubToken", "github_token", "GITHUB_TOKEN", "secretName", "envFrom"):
            assert forbidden not in block


def test_dev_keeps_github_metrics_cache_disabled_by_default() -> None:
    dev_values = _read("docs/examples/danielsmith.values.dev.yaml")
    assert "githubMetricsCache:" not in dev_values


def test_docs_explain_public_cache_without_github_secret() -> None:
    runbook = _read("docs/apps/danielsmith.md")
    assert "Runtime GitHub metrics cache" in runbook
    assert "/runtime/github-metrics.json" in runbook
    assert "unauthenticated public GitHub API" in runbook
    assert "Do not add a GitHub token or Secret" in runbook
    assert "envFrom" in runbook


def test_app_config_resolves_danielsmith_staging_and_prod() -> None:
    for env in ("staging", "prod"):
        result = subprocess.run(
            ["python3", "scripts/app_config.py", "json", "--app", "danielsmith", "--env", env],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stderr
        config = json.loads(result.stdout)
        assert config["SUGARKUBE_ENV"] == env
        assert "/runtime/github-metrics.json" in config["SUGARKUBE_VERIFY_PATHS"]
