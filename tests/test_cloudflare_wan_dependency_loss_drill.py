"""Offline safety-contract tests for the Cloudflare WAN dependency-loss drill."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DRILL = ROOT / "scripts" / "cloudflare_wan_dependency_loss_drill.sh"
TEXT = DRILL.read_text()


def run(*args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(DRILL), *args],
        cwd=ROOT,
        env=os.environ | (env or {}),
        text=True,
        capture_output=True,
    )


def test_shell_is_valid() -> None:
    subprocess.run(["bash", "-n", str(DRILL)], check=True)


def test_dry_run_performs_no_mutation_or_external_preflight(tmp_path: Path) -> None:
    marker = tmp_path / "called"
    bomb = tmp_path / "date"
    bomb.write_text(f"#!/bin/sh\ntouch {marker}\nprintf 20260809T000000Z\n")
    bomb.chmod(0o755)
    result = run(env={"PATH": f"{tmp_path}:/usr/bin:/bin"})
    assert result.returncode == 0
    assert "PLAN ONLY" in result.stdout
    assert not marker.exists(), "dry-run should not even invoke cluster/node stubs"


def test_non_staging_is_rejected_before_any_mutation() -> None:
    result = run("--env=prod")
    assert result.returncode != 0
    assert "staging-only" in result.stderr


def test_operator_confirmation_is_enforced_before_preflight() -> None:
    result = run("--execute", "--confirm=no")
    assert result.returncode != 0
    assert "confirmation must exactly equal" in result.stderr


@pytest.mark.parametrize(
    "needle",
    [
        'EXPECTED_CONTEXT=sugar-staging',
        "git status --porcelain",
        "CF_DRILL_APPROVED_REVISION",
        "EXPECTED_HELM_REVISION=2",
        "EXPECTED_IMAGE=",
        "exactly two Ready, exactly labelled connector pods",
        "connector pods must be on distinct nodes",
        "Prometheus targets are unhealthy",
        "a Cloudflare alert is active",
        "approved staging endpoint manifest must contain exactly 16 URLs",
    ],
)
def test_preflight_fail_closed_guards_are_present(needle: str) -> None:
    assert needle in TEXT


def test_wrong_context_revision_image_helm_and_ambiguous_pods_are_guarded() -> None:
    assert "context must be" in TEXT
    assert "repository revision is not approved" in TEXT
    assert "immutable image is not approved" in TEXT
    assert "Cloudflare Helm revision must be 2" in TEXT
    assert "exactly two Ready" in TEXT


def test_exact_network_namespace_resolution_is_required() -> None:
    assert "crictl inspectp" in TEXT
    assert 'io.kubernetes.pod.uid' in TEXT
    assert "readlink /proc/${pid}/ns/net" in TEXT
    assert "cannot prove exact pod network namespace identity" in TEXT


def test_owner_collision_is_refused() -> None:
    assert "nft list table inet ${table}" in TEXT
    assert "owner-tagged rule already exists" in TEXT


def test_watchdogs_are_installed_on_both_nodes_before_disruption() -> None:
    watchdog = TEXT.index("# A transient host service survives")
    install = TEXT.index('install="sudo nsenter', watchdog)
    assert "for i in 0 1; do" in TEXT[watchdog:install]
    assert "systemd-run" in TEXT[watchdog:install]


def test_one_node_setup_failure_cleans_the_installed_node() -> None:
    attempted = TEXT.index('attempted_indices+=("${i}")')
    install = TEXT.index('node_exec "${pod_nodes[$i]}" "${install}"', attempted)
    assert attempted < install, "ambiguous installation attempts must be tracked first"
    assert "trap 'cleanup $?' EXIT" in TEXT
    assert "rule setup failed" in TEXT


def test_failed_normal_cleanup_remains_tracked_for_exit_retry() -> None:
    normal_cleanup = TEXT.index("declare -a cleanup_retry_indices=()")
    failure = TEXT.index('cleanup_retry_indices+=("${i}")', normal_cleanup)
    preserve = TEXT.index('attempted_indices=("${cleanup_retry_indices[@]}")', failure)
    abort = TEXT.index("automated exact cleanup could not be proven", preserve)
    assert failure < preserve < abort


def test_nft_table_name_is_short_and_does_not_embed_owner() -> None:
    table_function = TEXT.split("table_for() {", 1)[1].split("\n}", 1)[0]
    assert "sha256sum" in table_function
    assert "cfwd_" in table_function
    assert '${owner//-/_}' not in table_function


def test_lifecycle_contract_is_checked_before_disruption() -> None:
    deployment_check = TEXT.index('has("livenessProbe") | not')
    watchdogs = TEXT.index("# A transient host service survives")
    assert deployment_check < watchdogs
    assert '.readinessProbe.httpGet.path=="/ready"' in TEXT
    assert ".readinessProbe.httpGet.port==2000" in TEXT


def test_interruption_requires_same_uids_and_restart_counts() -> None:
    assert "did not prove same-process NotReady and zero HA connections" in TEXT
    interruption = TEXT.split("deadline=$((SECONDS+90))", 1)[1].split(
        'sleep "${DISRUPTION_SECONDS}"', 1
    )[0]
    assert ".metadata.uid==$u0" in interruption
    assert "restartCount" in interruption
    assert 'status=="False"' in interruption


def test_accidental_restart_is_rejected() -> None:
    assert TEXT.count("status.containerStatuses[].restartCount") >= 3
    assert "same-process" in TEXT


def test_timeout_and_signals_run_cleanup() -> None:
    assert "DISRUPTION_SECONDS=180" in TEXT
    assert "RECOVERY_SECONDS=300" in TEXT
    assert "trap 'exit 130' INT" in TEXT
    assert "trap 'exit 143' TERM" in TEXT
    assert "sleep 240" in TEXT


def test_only_exact_table_deletion_is_used_without_broad_flush() -> None:
    assert "nft delete table inet ${table}" in TEXT
    for forbidden in ("nft flush", "iptables -F", "iptables --flush", "delete ruleset"):
        assert forbidden not in TEXT


def test_recovery_requires_same_pods_and_four_connections_each() -> None:
    assert "same-pod recovery with unchanged restart counts" in TEXT
    assert "cloudflared_tunnel_ha_connections" in TEXT
    assert ">= 4" in TEXT


def test_secret_values_are_never_requested_or_printed() -> None:
    assert "get secret tunnel-token -o jsonpath='{.metadata" in TEXT
    for forbidden in (".data.token", "-o yaml", "get secret tunnel-token -o json\n", "base64 -d"):
        assert forbidden not in TEXT


def test_evidence_is_sanitized_and_outside_repository_by_default() -> None:
    assert "${HOME}/operator-evidence/" in TEXT
    assert "secretMetadata" in TEXT
    assert "umask 077" in TEXT


def test_networkpolicy_only_approach_is_not_a_pass_contract() -> None:
    assert "NetworkPolicy" not in TEXT
    docs = (ROOT / "docs" / "cloudflare_tunnel.md").read_text()
    assert "implementation-defined" in docs
    assert "inconclusive dependency-loss test" in docs
    assert "A policy alone is not required or\n   expected to make `/ready` false" in docs


def test_node_execution_does_not_weaken_authentication() -> None:
    assert "StrictHostKeyChecking=no" not in TEXT
    assert "sshpass" not in TEXT
    assert "authorized_keys" not in TEXT
    assert "CF_DRILL_NODE_EXECUTOR" in TEXT


def test_recipe_is_clearly_named_and_defaults_to_plan() -> None:
    justfile = (ROOT / "justfile").read_text()
    assert "cf-tunnel-wan-dependency-loss-drill env='staging' *args=''" in justfile
    assert "cloudflare_wan_dependency_loss_drill.sh" in justfile
