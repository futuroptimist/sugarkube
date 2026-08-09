"""Offline contract tests for the staging Cloudflare WAN drill."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "scripts/cloudflare_wan_dependency_loss_drill.sh"
SCRIPT = SCRIPT_PATH.read_text()


def test_default_is_a_non_mutating_plan():
    assert "execute=0" in SCRIPT
    assert "((execute)) || exit 0" in SCRIPT
    assert SCRIPT.index("((execute)) || exit 0") < SCRIPT.index("nft add table")


def test_environment_and_context_are_fail_closed():
    assert '[[ "${env_name}" == staging ]]' in SCRIPT
    assert "EXPECTED_CONTEXT=sugar-staging" in SCRIPT
    assert "kubectl config current-context" in SCRIPT


def test_repository_revision_and_clean_tree_are_required():
    assert "CF_WAN_APPROVED_REVISION" in SCRIPT
    assert "status --porcelain --untracked-files=normal" in SCRIPT


def test_release_image_and_pod_selection_are_exact():
    assert "cloudflare-tunnel must be Helm revision 2" in SCRIPT
    assert "e39ee8da81ad5e05d77f38d2f51c60ca51bf2a8450ac3abab50c17fdb91d91bf" in SCRIPT
    assert "($p|length)==2" in SCRIPT
    assert "map(.spec.nodeName)|unique|length)==2" in SCRIPT


def test_metrics_alerts_and_endpoints_are_preflights():
    assert "cloudflared_tunnel_ha_connections" in SCRIPT
    assert "CloudflareTunnel(NoHealthyConnections|ConnectionsDegraded|MetricsTargetsDown)" in SCRIPT
    assert "approved staging endpoint inventory must contain exactly 16" in SCRIPT


def test_exact_sandbox_resolution_is_required():
    assert "crictl pods --namespace cloudflare --name '^${pod}$'" in SCRIPT
    assert "cannot resolve exact sandbox network namespace" in SCRIPT
    assert "inspectp" in SCRIPT and "'.info.pid'" in SCRIPT


def test_existing_owner_table_is_refused():
    assert "nft list table inet ${table}" in SCRIPT
    assert "owner-tagged rule already exists" in SCRIPT


def test_watchdogs_precede_all_disruption():
    watchdog = SCRIPT.index("systemd-run --unit=${table}_cleanup")
    disruption = SCRIPT.index("# Only after every watchdog exists")
    assert watchdog < disruption
    assert "--on-active=${MAX_DISRUPTION_SECONDS}s" in SCRIPT


def test_partial_setup_and_signals_run_cleanup():
    assert "trap cleanup EXIT INT TERM" in SCRIPT
    assert "installed_nodes+=(\"${node}\")" in SCRIPT
    assert "for ((i=${#installed_nodes[@]}-1; i>=0; i--))" in SCRIPT


def test_interruption_rejects_restarts_and_requires_zero_connections():
    assert "a connector UID or restart count changed during interruption" in SCRIPT
    assert 'if [[ "${ready}" == 0 && "${ha}" == 2 ]]' in SCRIPT


def test_cleanup_is_exact_and_never_flushes_rules():
    assert "nft delete table inet ${table}" in SCRIPT
    assert "Run these exact commands through the approved node runner" in SCRIPT
    assert "nft flush" not in SCRIPT
    assert "iptables" not in SCRIPT


def test_recovery_requires_same_processes_and_four_connections():
    assert "a connector was replaced or restarted during recovery" in SCRIPT
    assert 'if [[ "${ready}" == 2 && "${ha}" == 2 ]]' in SCRIPT
    assert "SECONDS+300" in SCRIPT


def test_secret_values_are_never_requested_or_printed():
    secret_commands = [line for line in SCRIPT.splitlines() if "get secret" in line]
    assert secret_commands
    assert all("-o json" in line and "jq '{apiVersion,kind,metadata:" in line for line in secret_commands)
    assert all(".data" not in line for line in secret_commands)
    assert "tunnel-token -o jsonpath" not in SCRIPT


def test_exact_operator_confirmation_is_enforced():
    assert "INTERRUPT BOTH STAGING CLOUDFLARE CONNECTORS" in SCRIPT
    assert '[[ "${confirmation}" == "${EXPECTED_CONFIRMATION}" ]]' in SCRIPT


def test_evidence_is_sanitized_and_networkpolicy_is_not_used():
    assert "secret-metadata-before.json" in SCRIPT
    assert "pods-before.json" in SCRIPT
    assert "NetworkPolicy" not in SCRIPT


def test_just_recipe_is_clearly_named():
    justfile = (ROOT / "justfile").read_text()
    assert "cf-tunnel-wan-dependency-loss-drill env='staging' execute='false'" in justfile
    assert "scripts/cloudflare_wan_dependency_loss_drill.sh" in justfile
