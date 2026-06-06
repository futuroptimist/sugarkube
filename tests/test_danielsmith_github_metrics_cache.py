"""Regression tests for the danielsmith.io GitHub metrics cache config."""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
EXPECTED_PUBLIC_REPOS = {
    "futuroptimist/danielsmith.io",
    "futuroptimist/token.place",
    "futuroptimist/gabriel",
    "futuroptimist/flywheel",
    "futuroptimist/jobbot3000",
    "futuroptimist/gitshelves",
    "futuroptimist/f2clipboard",
    "futuroptimist/sigma",
    "futuroptimist/wove",
    "futuroptimist/pr-reaper",
    "democratizedspace/dspace",
    "futuroptimist/sugarkube",
    "futuroptimist/axel",
}


def _read(relative_path: str) -> str:
    return (REPO_ROOT / relative_path).read_text(encoding="utf-8")


def _github_metrics_block(env: str) -> str:
    text = _read(f"docs/examples/danielsmith.values.{env}.yaml")
    match = re.search(r"(?ms)^githubMetricsCache:\n(?P<body>.*)", text)
    assert match, f"githubMetricsCache block missing from {env} values"
    return match.group("body")


def _repo_slugs(block: str) -> set[str]:
    repos: set[str] = set()
    owner: str | None = None
    for raw_line in block.splitlines():
        line = raw_line.strip()
        if line.startswith("- owner: "):
            owner = line.removeprefix("- owner: ").strip()
        elif line.startswith("repo: ") and owner:
            repos.add(f"{owner}/{line.removeprefix('repo: ').strip()}")
            owner = None
    return repos


def test_staging_and_prod_enable_unauthenticated_github_metrics_cache() -> None:
    for env in ("staging", "prod"):
        block = _github_metrics_block(env)
        assert "enabled: true" in block
        assert "refreshIntervalSeconds: 3600" in block
        assert "cacheTtlSeconds: 7200" in block
        assert "publicPath: /runtime/github-metrics.json" in block
        repos = _repo_slugs(block)
        assert repos == EXPECTED_PUBLIC_REPOS
        assert "democratizedspace/dspace" in repos
        assert "futuroptimist/sugarkube" in repos
        assert "futuroptimist/axel" in repos
        assert "futuroptimist/dspace" not in repos
        for forbidden in ("github_token", "github-token", "gh_token", "access_token"):
            assert forbidden not in block.lower()
        assert "secret" not in block.lower()
        assert "envFrom" not in block


def test_danielsmith_docs_explain_no_github_token_or_secret() -> None:
    docs = _read("docs/apps/danielsmith.md")
    assert "/runtime/github-metrics.json" in docs
    assert "unauthenticated public GitHub" in docs
    assert "does **not** require a GitHub token" in docs
    assert "Kubernetes Secret" in docs
    assert "Do not configure a GitHub token" in docs


def test_danielsmith_docs_name_public_dspace_metrics_repo() -> None:
    docs = _read("docs/apps/danielsmith.md")
    assert "DSPACE stars come from the public `democratizedspace/dspace` repository" in docs
    assert "futuroptimist/dspace" not in docs


def test_danielsmith_docs_use_sidecar_container_name_for_logs() -> None:
    docs = _read("docs/apps/danielsmith.md")

    assert "-c github-metrics --tail=100" in docs
    container_flag = "-c"
    container_name = "github-metrics"
    legacy_suffix = "-cache"
    assert f"{container_flag} {container_name}{legacy_suffix}" not in docs


def test_runtime_cache_path_stays_manual_not_shared_verify_path() -> None:
    app_env = _read("docs/examples/apps/danielsmith.env")
    contract = _read("docs/app_deployment_contract.md")
    docs = _read("docs/apps/danielsmith.md")

    assert "dev disables the GitHub" in app_env
    assert "metrics cache, so stage/prod must verify /runtime/github-metrics.json" in app_env
    assert "manual curl/jq/log sidecar checks in docs/apps/danielsmith.md" in app_env
    assert "SUGARKUBE_VERIFY_PATHS=/,/livez,/healthz\n" in app_env
    assert "SUGARKUBE_VERIFY_PATHS=/,/livez,/healthz,/runtime/github-metrics.json" not in app_env
    assert "| danielsmith.io |" in contract
    assert "| `/,/livez,/healthz` |" in contract
    assert "`app-verify` cannot currently express environment-specific runtime JSON files" in contract
    assert "documented manual" in contract
    assert "staging/prod curl/jq/log verification steps after `app-verify`" in contract
    assert "`app-verify` cannot currently express staging/prod-only runtime JSON checks" in docs
    assert "required manual staging/prod sidecar verification path" in docs
    assert "sidecar cache is not signed off until the manual curl/jq/log checks" in docs
    assert "just app-verify app=danielsmith env=prod" in docs


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
        assert config["SUGARKUBE_VALUES"].endswith(
            f"docs/examples/danielsmith.values.{env}.yaml"
        )
        assert config["SUGARKUBE_VERIFY_PATHS"] == "/,/livez,/healthz"
