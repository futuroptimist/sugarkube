"""Offline safety-contract tests for the staging WAN drill."""

from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/cloudflare_wan_dependency_loss_drill.sh"


def test_plan_is_default_and_invokes_no_external_commands(tmp_path):
    result = subprocess.run(
        ["/bin/bash", str(SCRIPT), "--env", "staging"],
        text=True,
        capture_output=True,
        env={"PATH": f"{tmp_path}:/usr/bin:/bin"},
    )
    assert result.returncode == 0
    assert "PLAN ONLY" in result.stdout
    assert "No ruleset is flushed" in result.stdout


def test_execution_rejects_non_staging_before_cluster_access(tmp_path):
    result = subprocess.run(
        ["/bin/bash", str(SCRIPT), "--execute", "--env", "prod"],
        text=True,
        capture_output=True,
        env={"PATH": f"{tmp_path}:/usr/bin:/bin"},
    )
    assert result.returncode != 0
    assert "staging-only" in result.stderr


def test_fail_closed_contract_is_explicit():
    text = SCRIPT.read_text()
    required = [
        "EXPECTED_CONTEXT=sugar-staging",
        "EXPECTED_REVISION=2",
        "git status --porcelain",
        "exactly two Ready",
        "distinct nodes",
        "active Cloudflare alert",
        "EXPECTED_IMAGE",
        "WAN_DRILL_NODE_EXEC",
        "confirmation must exactly equal",
        "cleanup watchdog installation",
        "owner-tagged rule already exists",
        "exact pod network namespace",
        "UID changed",
        "same-process recovery",
        "systemd-run",
        "--on-active=210s",
        "nft delete table",
        "just cf-tunnel-verify env=staging",
        "NetworkPolicy-only results never pass",
    ]
    for phrase in required:
        assert phrase in text
    assert "flush ruleset" not in text
    assert "StrictHostKeyChecking=no" not in text
    assert "secret tunnel-token -o json" not in text.lower()
    assert "secret tunnel-token -o 'jsonpath={.metadata" in text


def test_signal_and_partial_failure_cleanup_are_trapped():
    text = SCRIPT.read_text()
    assert "trap 'cleanup 130' INT" in text
    assert "trap 'cleanup 143' TERM" in text
    assert "MANUAL CLEANUP" in text
    assert text.index("cleanup watchdog installation failed") < text.index(
        "disruption setup failed"
    )
