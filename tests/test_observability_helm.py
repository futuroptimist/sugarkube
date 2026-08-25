import fcntl
import json
import os
import pty
import re
import signal
import subprocess
import sys
import termios
import time
from contextlib import suppress
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
VERSION = ROOT / "platform" / "observability" / "helm" / "kube-prometheus-stack.version"
COMMON = ROOT / "platform" / "observability" / "helm" / "kube-prometheus-stack.values.common.yaml"
STAGING = ROOT / "clusters" / "staging" / "observability" / "kube-prometheus-stack.values.yaml"
PROD = ROOT / "clusters" / "prod" / "observability" / "kube-prometheus-stack.values.yaml"
CANONICAL_DSPACE_RULES = (
    ROOT / "platform" / "observability" / "rules" / "dspace-release-integrity.yaml"
)
CANONICAL_CLOUDFLARE_RULES = (
    ROOT / "platform" / "observability" / "rules" / "cloudflare-tunnel.yaml"
)
SCRIPT = ROOT / "scripts" / "observability_helm.sh"
ALERTMANAGER_VALIDATOR = ROOT / "scripts" / "verify_observability_alertmanager.rb"
DASHBOARD = ROOT / "clusters/staging/observability/dashboards/sugarkube-staging-observability.json"
PROD_DASHBOARD = ROOT / "clusters/prod/observability/dashboards/sugarkube-prod-observability.json"
JUSTFILE = ROOT / "justfile"
FLUX_SYNC = ROOT / "flux" / "gotk-sync.yaml"
LEGACY = [
    ROOT / "platform" / "observability" / "kube-prometheus-stack.yaml",
    ROOT / "platform" / "observability" / "kube-prometheus-stack-values.yaml",
    ROOT / "clusters" / "dev" / "patches" / "kube-prometheus-stack-values.yaml",
    ROOT / "clusters" / "staging" / "patches" / "kube-prometheus-stack-values.yaml",
    ROOT / "clusters" / "prod" / "patches" / "kube-prometheus-stack-values.yaml",
]
DSPACE_ALERT_MATCHER = (
    'alertname=~"^(DspaceBuildRevisionMismatch|DspaceMixedBuildRevisions|'
    "DspaceDeploymentImagePinMismatch|DspaceChatSyntheticFailed|"
    'DspaceMetricsTargetDown)$"'
)
DSPACE_ALERT_NAMES = (
    "DspaceBuildRevisionMismatch",
    "DspaceMixedBuildRevisions",
    "DspaceDeploymentImagePinMismatch",
    "DspaceChatSyntheticFailed",
    "DspaceMetricsTargetDown",
)


def watchdog_canary():
    uuid = "12345678" + "-1234-4123-8123-123456789abc"
    return "https://" + "hc-ping.com/" + uuid, uuid


def terminate_and_reap_process_group(process: subprocess.Popen[str]) -> None:
    with suppress(ProcessLookupError):
        os.killpg(process.pid, signal.SIGTERM)
    try:
        process.communicate(timeout=1)
    except subprocess.TimeoutExpired:
        with suppress(ProcessLookupError):
            os.killpg(process.pid, signal.SIGKILL)
        process.communicate()


def watchdog_cleanup_state(process: subprocess.Popen[str], tmp_path: Path) -> list[str]:
    missing_cleanup_states = []
    if process.poll() is None:
        missing_cleanup_states.append("watchdog drill exit")
    if not (tmp_path / "pagerduty.reaped").exists():
        missing_cleanup_states.append("port-forward reap marker")
    if list(tmp_path.glob("sugarkube-watchdog-silence.*")):
        missing_cleanup_states.append("temporary directory removal")
    return missing_cleanup_states


def wait_for_watchdog_signal_cleanup(
    process: subprocess.Popen[str], tmp_path: Path, *, cleanup_deadline_seconds: int = 15
) -> tuple[str, str]:
    cleanup_deadline = time.monotonic() + cleanup_deadline_seconds
    missing_cleanup_states = ["watchdog drill exit"]
    while time.monotonic() < cleanup_deadline:
        missing_cleanup_states = watchdog_cleanup_state(process, tmp_path)
        if not missing_cleanup_states:
            return process.communicate()
        time.sleep(0.01)
    terminate_and_reap_process_group(process)
    pytest.fail(
        "watchdog drill cleanup timed out after "
        f"{cleanup_deadline_seconds}s waiting for "
        + ", ".join(missing_cleanup_states)
    )


def yaml_load(path: Path):
    result = subprocess.run(
        [
            "ruby",
            "-ryaml",
            "-rjson",
            "-e",
            "puts JSON.generate(YAML.safe_load_file(ARGV[0], aliases: false))",
            str(path),
        ],
        check=True,
        text=True,
        capture_output=True,
    )
    return json.loads(result.stdout)


def test_chart_version_and_values_define_shared_staging_and_production_baseline():
    assert VERSION.read_text(encoding="utf-8").strip() == "87.19.0"
    common = yaml_load(COMMON)
    staging = yaml_load(STAGING)
    spec = common["prometheus"]["prometheusSpec"]
    assert spec["replicas"] == 1
    assert spec["retention"] == "90d"
    assert spec["retentionSize"] == "100GB"
    assert spec["enableAdminAPI"] is False
    assert spec["resources"] == {
        "requests": {"cpu": "200m", "memory": "512Mi"},
        "limits": {"memory": "2Gi"},
    }
    pvc = spec["storageSpec"]["volumeClaimTemplate"]["spec"]
    assert pvc["storageClassName"] == "local-path"
    assert pvc["storageClassName"] != "longhorn"
    assert pvc["accessModes"] == ["ReadWriteOnce"]
    assert pvc["resources"]["requests"]["storage"] == "128Gi"
    for overlay in (staging, yaml_load(PROD)):
        overlay_spec = overlay["prometheus"]["prometheusSpec"]
        assert not {"retention", "retentionSize", "storageSpec"} & overlay_spec.keys()
        merged_spec = {**spec, **overlay_spec}
        assert (
            merged_spec["retention"],
            merged_spec["retentionSize"],
            merged_spec["storageSpec"]["volumeClaimTemplate"]["spec"]["resources"][
                "requests"
            ]["storage"],
        ) == ("90d", "100GB", "128Gi")
    assert staging["prometheus"]["prometheusSpec"]["externalLabels"] == {"cluster": "sugarkube-int"}
    alertmanager = staging["alertmanager"]
    assert alertmanager["alertmanagerSpec"]["secrets"] == [
        "alertmanager-pagerduty",
        "alertmanager-healthchecks-watchdog",
    ]
    route = alertmanager["config"]["route"]
    assert route["receiver"] == "null"
    assert {
        key: route[key] for key in ("group_by", "group_wait", "group_interval", "repeat_interval")
    } == {
        "group_by": None,
        "group_wait": None,
        "group_interval": None,
        "repeat_interval": None,
    }
    assert route["routes"][2] == {
        "receiver": "pagerduty-synthetic-test",
        "matchers": [
            'alertname="SugarkubePagerDutyTest"',
            'environment="staging"',
            'cluster="sugarkube-int"',
            'severity="critical"',
        ],
    }
    dspace_route = route["routes"][0]
    assert dspace_route["receiver"] == "pagerduty-dspace"
    assert dspace_route["matchers"][0] == DSPACE_ALERT_MATCHER
    watchdog_route = route["routes"][3]
    assert watchdog_route["receiver"] == "healthchecks-watchdog"
    assert watchdog_route["repeat_interval"] == "5m"
    pagerduty_receiver = next(
        receiver
        for receiver in alertmanager["config"]["receivers"]
        if receiver["name"] == "pagerduty-synthetic-test"
    )
    pagerduty = pagerduty_receiver["pagerduty_configs"][0]
    assert pagerduty == {
        "routing_key_file": "/etc/alertmanager/secrets/alertmanager-pagerduty/routing-key",
        "send_resolved": True,
    }


def test_grafana_alertmanager_k3s_monitor_values_are_guarded():
    common = yaml_load(COMMON)
    grafana = common["grafana"]
    assert grafana["admin"] == {
        "existingSecret": "grafana-admin-credentials",
        "userKey": "admin-user",
        "passwordKey": "admin-password",
    }
    assert grafana["persistence"]["enabled"] is False
    assert grafana["ingress"]["enabled"] is False
    assert grafana["service"] == {"type": "NodePort", "nodePort": 30300}
    alertmanager = common["alertmanager"]
    assert alertmanager["alertmanagerSpec"]["replicas"] == 1
    assert alertmanager["config"]["route"]["receiver"] == "null"
    assert alertmanager["config"]["route"]["receiver"] is not None
    assert alertmanager["config"]["receivers"] == [{"name": "null"}]
    for monitor in ("kubeEtcd", "kubeControllerManager", "kubeScheduler", "kubeProxy"):
        assert common[monitor]["enabled"] is False


def test_production_values_have_exact_safe_overrides_without_public_exposure_or_credentials():
    assert STAGING.exists() and PROD.exists()
    prod = yaml_load(PROD)
    assert prod == {
        "defaultRules": {"disabled": {"Watchdog": True}},
        "prometheus": {
            "prometheusSpec": {"externalLabels": {"cluster": "sugarkube-prod"}}
        },
        "alertmanager": {
            "alertmanagerSpec": {"secrets": []},
            "config": {
                "global": None, "inhibit_rules": None, "templates": None,
                "route": {"group_by": None, "group_wait": None, "group_interval": None,
                          "repeat_interval": None, "receiver": "null", "routes": None},
                "receivers": [{"name": "null"}],
            },
        },
    }
    text = COMMON.read_text(encoding="utf-8") + PROD.read_text(encoding="utf-8")
    forbidden = [
        "longhorn",
        "IngressRoute",
        "kind: Ingress",
        "pass" + "word:",
        "admin" + "Pass" + "word",
        "cloudflare-tunnel",
        "CloudflareTunnel",
    ]
    for needle in forbidden:
        assert needle not in text
    assert "30300" in text
    assert "enableAdminAPI: false" in text


def test_production_values_disable_builtin_watchdog_rule():
    prod = yaml_load(PROD)
    assert prod["defaultRules"]["disabled"]["Watchdog"] is True


def rendered_alertmanager_fixture(
    *, secret="alertmanager-pagerduty", path=None, matchers=None, inline=False
):
    path = path or "/etc/alertmanager/secrets/alertmanager-pagerduty/routing-key"
    matchers = matchers or [
        'alertname="SugarkubePagerDutyTest"',
        'environment="staging"',
        'cluster="sugarkube-int"',
        'severity="critical"',
    ]
    inline_field = "\n            " + "routing_" + "key: forbidden-stub" if inline else ""
    matcher_yaml = "\n".join(f"            - '{matcher}'" for matcher in matchers)
    return f"""---
apiVersion: monitoring.coreos.com/v1
kind: Alertmanager
metadata:
  name: kube-prometheus-stack-alertmanager
spec:
  secrets: [{secret}, alertmanager-healthchecks-watchdog]
---
apiVersion: v1
kind: Secret
metadata:
  name: alertmanager-kube-prometheus-stack-alertmanager
stringData:
  alertmanager.yaml: |
    route:
      receiver: "null"
      routes:
        - receiver: pagerduty-dspace
          matchers:
            - '{DSPACE_ALERT_MATCHER}'
            - 'environment="staging"'
            - 'cluster="sugarkube-int"'
            - 'severity="critical"'
        - receiver: pagerduty-dspace
          matchers:
            - 'alertname="CloudflareTunnelNoHealthyConnections"'
            - 'environment="staging"'
            - 'cluster="sugarkube-int"'
            - 'severity="critical"'
        - receiver: pagerduty-synthetic-test
          matchers:
{matcher_yaml}
        - receiver: healthchecks-watchdog
          matchers:
            - 'alertname="SugarkubeObservabilityWatchdog"'
            - 'environment="staging"'
            - 'cluster="sugarkube-int"'
            - 'purpose="observability-watchdog"'
          group_by: [alertname, cluster, environment]
          group_wait: 30s
          group_interval: 1m
          repeat_interval: 5m
          continue: false
    receivers:
      - name: "null"
      - name: pagerduty-synthetic-test
        pagerduty_configs:
          - routing_key_file: {path}
            send_resolved: true{inline_field}
      - name: pagerduty-dspace
        pagerduty_configs:
          - routing_key_file: {path}
            send_resolved: true
      - name: healthchecks-watchdog
        webhook_configs:
          - url_file: /etc/alertmanager/secrets/alertmanager-healthchecks-watchdog/ping-url
            send_resolved: false
            max_alerts: 1
            timeout: 10s
"""


@pytest.mark.parametrize(
    ("kwargs", "diagnostic"),
    [
        ({"secret": "wrong-secret"}, "exactly the two expected"),
        ({"path": "/wrong/path"}, "PagerDuty configuration is malformed"),
        ({"matchers": ['severity="critical"']}, "exact synthetic allowlist"),
        ({"inline": True}, "inline credentials or webhook URLs are forbidden"),
    ],
)
def test_alertmanager_validator_rejects_missing_mount_wrong_path_inline_and_broad_route(
    tmp_path, kwargs, diagnostic
):
    manifest = tmp_path / "rendered.yaml"
    manifest.write_text(rendered_alertmanager_fixture(**kwargs), encoding="utf-8")
    result = subprocess.run(
        ["ruby", str(ALERTMANAGER_VALIDATOR), "staging", "rendered", str(manifest)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 16
    assert diagnostic in result.stderr
    assert "forbidden-stub" not in result.stderr


def test_alertmanager_validator_accepts_valid_rendered_fixture(tmp_path):
    manifest = tmp_path / "rendered.yaml"
    manifest.write_text(rendered_alertmanager_fixture(), encoding="utf-8")
    result = subprocess.run(
        ["ruby", str(ALERTMANAGER_VALIDATOR), "staging", "rendered", str(manifest)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "structure verified" in result.stderr


@pytest.mark.parametrize(
    "manifest",
    [
        "---\nkind: Alertmanager\nspec: [unterminated\n",
        rendered_alertmanager_fixture().replace(
            "alertmanager.yaml: |", "alertmanager.yaml: !!invalid"
        ),
    ],
)
def test_alertmanager_validator_redacts_malformed_yaml(tmp_path, manifest):
    path = tmp_path / "malformed.yaml"
    path.write_text(manifest, encoding="utf-8")
    result = subprocess.run(
        ["ruby", str(ALERTMANAGER_VALIDATOR), "staging", "rendered", str(path)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 16
    assert "sensitive values not printed" in result.stderr
    assert "Traceback" not in result.stderr
    assert "Psych::" not in result.stderr


def test_alertmanager_validator_redacts_invalid_base64(tmp_path):
    manifest = tmp_path / "invalid-base64.yaml"
    manifest.write_text(
        rendered_alertmanager_fixture().replace(
            "stringData:\n  alertmanager.yaml: |\n" + "    route:",
            "data:\n  alertmanager.yaml: 'not-base64!'\nunused:\n  value: |\n    route:",
        ),
        encoding="utf-8",
    )
    result = subprocess.run(
        ["ruby", str(ALERTMANAGER_VALIDATOR), "staging", "rendered", str(manifest)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 16
    assert "sensitive values not printed" in result.stderr
    assert "not-base64" not in result.stderr


@pytest.mark.parametrize(
    ("mutation", "diagnostic"),
    [
        (
            lambda text: text + text.split("---\napiVersion: v1", 1)[0],
            "expected exactly one kube-prometheus-stack Alertmanager",
        ),
        (
            lambda text: text.replace(
                "      routes:\n        - receiver: pagerduty-dspace",
                "      routes:\n        - receiver: nested\n          routes:\n            - receiver: pagerduty-dspace",
            ),
            "DSPACE route ordering or receiver changed",
        ),
        (
            lambda text: text.replace(
                "    receivers:\n",
                "    receivers:\n      - name: alternate\n        pagerduty_configs: []\n",
            ),
            "receiver list must contain exactly",
        ),
        (
            lambda text: text.replace(
                "            send_resolved: true",
                "            send_resolved: true\n          - routing_key_file: /another/file",
            ),
            "PagerDuty configuration is malformed",
        ),
        (
            lambda text: text.replace(
                "        pagerduty_configs:",
                "        email_configs: []\n        pagerduty_configs:",
            ),
            "PagerDuty receiver is malformed",
        ),
        (
            lambda text: text.replace(
                "        webhook_configs:",
                "        slack_configs: []\n        webhook_configs:",
            ),
            "Healthchecks receiver is malformed",
        ),
        (
            lambda text: text.replace(
                "            - 'severity=\"critical\"'",
                "            - 'severity=\"critical\"'\n          continue: false",
            ),
            "DSPACE route must contain only receiver and exact matchers",
        ),
        (
            lambda text: text.replace(
                "            - 'severity=\"critical\"'",
                "            - 'severity=\"critical\"'\n          routes: []",
            ),
            "DSPACE route must contain only receiver and exact matchers",
        ),
        (
            lambda text: text.replace(
                "    receivers:",
                "    routing_" + "key: forbidden-stub\n    receivers:",
            ),
            "inline credentials or webhook URLs are forbidden",
        ),
        (
            lambda text: text.replace(
                "      - name: pagerduty-synthetic-test",
                "      - name: alternate\n        pagerduty_configs:\n          - service_"
                + "key: forbidden-stub\n      - name: pagerduty-synthetic-test",
            ).replace(
                "      routes:",
                "      routes:\n        - receiver: alternate\n          matchers: ['severity=~\".*\"']",
            ),
            "inline credentials or webhook URLs are forbidden",
        ),
    ],
    ids=[
        "duplicate-resource",
        "nested-route",
        "alternate-receiver",
        "additional-config",
        "pagerduty-extra-integration",
        "healthchecks-extra-integration",
        "continuation",
        "nested-children",
        "recursive-inline-key",
        "broad-nested-alternate-inline",
    ],
)
def test_alertmanager_validator_rejects_deterministic_contract_mutations(
    tmp_path, mutation, diagnostic
):
    manifest = tmp_path / "mutation.yaml"
    manifest.write_text(mutation(rendered_alertmanager_fixture()), encoding="utf-8")
    result = subprocess.run(
        ["ruby", str(ALERTMANAGER_VALIDATOR), "staging", "rendered", str(manifest)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 16
    assert diagnostic in result.stderr
    assert "structure invalid" in result.stderr
    assert "forbidden-stub" not in result.stderr


def test_discovery_contract_uses_release_label():
    spec = yaml_load(COMMON)["prometheus"]["prometheusSpec"]
    for selector in ("serviceMonitorSelector", "podMonitorSelector", "probeSelector"):
        assert spec[selector]["matchLabels"] == {"release": "kube-prometheus-stack"}


def test_lifecycle_uses_pinned_version_ordered_values_and_no_reuse_values():
    script = SCRIPT.read_text(encoding="utf-8")
    assert 'CHART="prometheus-community/kube-prometheus-stack"' in script
    assert 'PROD_VALUES="${ROOT}/clusters/prod/observability/kube-prometheus-stack.values.yaml"' in script
    assert '-f "${COMMON_VALUES}" -f "${ENV_VALUES}"' in script
    assert "--reuse-values" not in script
    assert "--atomic" in script
    assert "longhorn" not in script.lower()


def test_print_resolved_reports_complete_stable_source_chain(tmp_path):
    result, _ = run_helper(tmp_path, "render")
    assert result.returncode == 0

    sources = [str(COMMON), str(STAGING), str(CANONICAL_DSPACE_RULES), str(DASHBOARD)]
    positions = [result.stdout.index(source) for source in sources]
    assert positions == sorted(positions)
    assert "generated mode-0600 rules overlay sourced from" in result.stdout
    assert "sugarkube-observability-rules." not in result.stdout


def test_operations_runbook_describes_dspace_operator_contract():
    operations = (ROOT / "docs" / "observability-operations.md").read_text(encoding="utf-8")
    for source in (
        "platform/observability/rules/dspace-release-integrity.yaml",
        "docs/observability-dspace-release-integrity.md",
    ):
        assert source in operations

    assert "SugarkubePagerDutyTest" in operations
    assert "deployed and has passed" in operations
    assert "The deployed staging allowlist also routes exactly" in operations
    assert "All five rules are loaded, healthy, and inactive in steady state" in operations
    assert "it did not deliberately fire all five" in operations
    assert "pagerduty-dspace" in operations
    assert "send_resolved: true" in operations
    assert 'fall through to `"null"`' in operations
    assert "watchdog route, its order" in operations
    assert "30-second group wait" in operations
    for alert in DSPACE_ALERT_NAMES:
        assert alert in operations
    for stale in (
        "Repository configuration is is deployed",
        "both values files in order",
        "bundled and real workload alerts still fall through",
    ):
        assert stale not in operations


def test_dspace_rules_have_one_canonical_source_and_exact_overlay(tmp_path):
    staging = yaml_load(STAGING)
    assert "dspace-release-integrity" not in staging["additionalPrometheusRulesMap"]

    result, audit = run_helper(tmp_path, "render")
    assert result.returncode == 0
    overlay = yaml_load(tmp_path / "rules-overlay.yaml")
    assert overlay == {
        "additionalPrometheusRulesMap": {
            "dspace-release-integrity": yaml_load(CANONICAL_DSPACE_RULES),
            "cloudflare-tunnel": yaml_load(CANONICAL_CLOUDFLARE_RULES),
        }
    }
    overlay_paths = re.findall(r"/[^ ]*sugarkube-observability-rules\.[^ ]*\.yaml", audit)
    assert overlay_paths
    assert all(not Path(path).exists() for path in overlay_paths)


@pytest.mark.parametrize(
    ("command", "helm_mode", "helm_action"),
    [
        ("render", "absent", "template"),
        ("install", "absent", "install"),
        ("upgrade", "present", "upgrade"),
    ],
)
def test_all_helm_paths_apply_canonical_rules_overlay_last(
    tmp_path, command, helm_mode, helm_action
):
    result, audit = run_helper(tmp_path, command, helm_mode=helm_mode)
    assert result.returncode == 0
    action_lines = [line for line in audit.splitlines() if f"helm {helm_action} " in line]
    assert action_lines
    for line in action_lines:
        common = line.index(str(COMMON))
        staging = line.index(str(STAGING))
        overlay = line.index("sugarkube-observability-rules.")
        assert common < staging < overlay


def test_rules_overlay_is_cleaned_when_render_fails(tmp_path):
    result, audit = run_helper(tmp_path, "render", helm_mode="render-fail")
    assert result.returncode != 0
    overlay_paths = re.findall(r"/[^ ]*sugarkube-observability-rules\.[^ ]*\.yaml", audit)
    assert overlay_paths
    assert all(not Path(path).exists() for path in overlay_paths)


def test_install_upgrade_are_distinct_and_render_before_mutation():
    script = SCRIPT.read_text(encoding="utf-8")
    install = re.search(r"install_release\(\).*?\nupgrade_release\(", script, re.S).group(0)
    upgrade = re.search(r"upgrade_release\(\).*?\nstatus\(", script, re.S).group(0)
    assert "render_to" in install and "helm install" in install
    assert install.index("assert_integration_secrets") < install.index("render_to")
    assert install.index("render_to") < install.index("helm install")
    assert 'state="$(release_state)"' in install
    assert "already exists" in install
    assert "render_to" in upgrade and "helm upgrade" in upgrade
    assert upgrade.index("assert_integration_secrets") < upgrade.index("render_to")
    assert upgrade.index("render_to") < upgrade.index("helm upgrade")
    assert 'state="$(release_state)"' in upgrade
    assert "requires an existing Helm release" in upgrade


def test_environment_context_guards_precede_mutation():
    script = SCRIPT.read_text(encoding="utf-8")
    assert 'EXPECTED_CONTEXT="sugar-prod"' in script
    assert "production live actions require an explicitly supplied KUBECONFIG" in script
    assert 'cluster_identity.py" assert' in script
    assert script.index("assert_context") < script.index("helm install")
    assert script.index("assert_context") < script.index("helm upgrade")


def test_status_and_verify_are_read_only():
    script = SCRIPT.read_text(encoding="utf-8")
    status = re.search(r"status\(\).*?\nverify\(", script, re.S).group(0)
    verify = re.search(r"verify\(\).*?\n\npagerduty_test\(", script, re.S).group(0)
    mutating = [
        " helm install",
        " helm upgrade",
        "kubectl apply",
        "kubectl create",
        "kubectl patch",
        "kubectl delete",
    ]
    for body in (status, verify):
        for token in mutating:
            assert token not in body
    assert "30300" in verify
    assert "get servicemonitor dspace" in verify
    assert "value intentionally not printed" in verify
    assert '--timeout="${TIMEOUT}"' in verify
    assert "desiredNumberScheduled" in verify and "numberReady" in verify
    assert "|| true" not in verify
    assert "verify_dspace_targets" in verify
    assert 'all(target.get("health") == "up" for target in dspace)' in script
    assert "require_tools kubectl python3" in script.split("verify_dspace_targets()", 1)[1]
    assert '--request-timeout="${request_timeout}" --raw' in script


def test_justfile_exposes_observability_recipes():
    text = JUSTFILE.read_text(encoding="utf-8")
    for recipe in (
        "observability-render",
        "observability-install",
        "observability-upgrade",
        "observability-status",
        "observability-verify",
        "observability-dashboard-verify",
        "observability-pagerduty-test",
    ):
        assert f"{recipe} env=''" in text
        assert f"scripts/observability_helm.sh {recipe.removeprefix('observability-')}" in text

    watchdog_recipes = {
        "observability-watchdog-secret-install": "watchdog-secret-install",
        "observability-watchdog-secret-check": "watchdog-secret-check",
        "observability-watchdog-verify": "watchdog-verify",
        "observability-watchdog-drill-start": "watchdog-drill-create",
        "observability-watchdog-drill-status": "watchdog-drill-status",
        "observability-watchdog-drill-clear": "watchdog-drill-clear",
    }
    for recipe, subcommand in watchdog_recipes.items():
        recipe_block = text.split(f"{recipe} env='':", 1)[1].split("\n\n", 1)[0]
        assert f"scripts/observability_helm.sh {subcommand} '{{{{ env }}}}'" in recipe_block
        assert "env=staging" not in recipe_block
        assert "env={{ env }}" not in recipe_block

    for recipe, subcommand in (
        ("observability-grafana-secret-install", "grafana-secret-install"),
        ("observability-grafana-secret-check", "grafana-secret-check"),
    ):
        recipe_block = text.split(f"{recipe} env='':", 1)[1].split("\n\n", 1)[0]
        assert f"scripts/observability_helm.sh {subcommand} '{{{{ env }}}}'" in recipe_block


def test_justfile_normalizes_repeated_env_prefixes_before_staging_metrics_checks():
    text = JUSTFILE.read_text(encoding="utf-8")
    normalization = (
        'while [ "${env_name#env=}" != "${env_name}" ]; '
        'do env_name="${env_name#env=}"; done'
    )
    for recipe in ("observability-install", "observability-upgrade", "observability-verify"):
        recipe_block = text.split(f"{recipe} env='':", 1)[1].split("\n\n", 1)[0]
        assert normalization in recipe_block
        assert '[ "${env_name}" = staging ] || [ "${env_name}" = int ]' in recipe_block


def test_watchdog_documentation_timing_matches_configuration():
    operations = (ROOT / "docs" / "observability-operations.md").read_text(encoding="utf-8")
    assert not re.search(
        r"The Alertmanager-driven observability watchdog,.{0,200}remain later tasks",
        operations,
        re.DOTALL,
    )
    for recipe in (
        "secret-install",
        "secret-check",
        "verify",
        "drill-start",
        "drill-status",
        "drill-clear",
    ):
        assert f"just observability-watchdog-{recipe} env=staging" in operations

    staging = yaml_load(STAGING)
    route = staging["alertmanager"]["config"]["route"]["routes"][3]
    assert route["repeat_interval"] == "5m"
    assert re.search(r"five-minute period and\s+two-minute grace", operations)
    assert re.search(r"eight-minute Alertmanager\s+silence", operations)


def test_observability_docs_match_linked_issue_heartbeat_status():
    alerting = (ROOT / "docs" / "observability-alerting.md").read_text(encoding="utf-8")
    operations = (ROOT / "docs" / "observability-operations.md").read_text(encoding="utf-8")
    installed = "installed on `sugarkube3`, `sugarkube4`, and `sugarkube5`"

    assert installed in alerting
    assert installed in operations
    for stale_claim in (
        "ready for a separate post-merge install",
        "await separate post-merge installation",
        "After this change merges, perform these steps",
    ):
        assert stale_claim not in alerting
        assert stale_claim not in operations


def test_legacy_flux_longhorn_files_are_clearly_marked_inactive():
    for path in LEGACY:
        text = path.read_text(encoding="utf-8")
        assert "LEGACY/FUTURE ONLY" in text
        assert "Do not apply to live staging or production" in text
        assert "Do not combine both lifecycle paths" in text


def test_legacy_flux_resources_are_absent_from_reconciliation_graph():
    platform = (ROOT / "platform" / "observability" / "kustomization.yaml").read_text(
        encoding="utf-8"
    )
    staging = (ROOT / "clusters" / "staging" / "kustomization.yaml").read_text(encoding="utf-8")
    development = (ROOT / "clusters" / "dev" / "kustomization.yaml").read_text(encoding="utf-8")
    production = (ROOT / "clusters" / "prod" / "kustomization.yaml").read_text(encoding="utf-8")
    assert "kube-prometheus-stack.yaml" not in platform
    assert "kube-prometheus-stack-values.yaml" not in platform
    assert "patches/kube-prometheus-stack-values.yaml" not in development
    assert "patches/kube-prometheus-stack-values.yaml" not in staging
    assert "patches/kube-prometheus-stack-values.yaml" not in production
    assert "no Flux CRDs" in platform
    assert "never established Flux ownership" in platform


def test_flux_health_checks_exclude_manually_managed_observability():
    text = FLUX_SYNC.read_text(encoding="utf-8")
    health_checks = text.split("  healthChecks:\n", 1)[1].split("  sourceRef:\n", 1)[0]
    names = set(re.findall(r"^      name: (.+)$", health_checks, re.M))
    assert "kube-prometheus-stack-prometheus" not in names
    assert "kube-prometheus-stack-alertmanager" not in names
    assert names == {"traefik", "cloudflared", "longhorn-driver-deployer"}
    assert "manually managed" in text
    assert "just observability-verify" in text


def run_grafana_secret_helper(
    tmp_path: Path,
    command="grafana-secret-install",
    *,
    env_name="prod",
    context="sugar-prod",
    kubeconfig=True,
    identity="prod",
    tty_text="operator\ncorrect horse battery staple\ncorrect horse battery staple\n",
    test_tty=True,
    extra_env=None,
    args=(),
    xtrace=False,
    secret_state="present",
):
    """Run only the Grafana Secret lifecycle against redacting command stubs."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(parents=True)
    audit = tmp_path / "audit"
    script_tmp = tmp_path / "tmp"
    script_tmp.mkdir()
    capture_read, capture_write = os.pipe()
    (bin_dir / "kubectl").write_text(
        r"""#!/bin/sh
case "$*" in
  *"config current-context") echo "$CONTEXT" ;;
  *"config view --minify"*) echo https://cluster.invalid ;;
  *"get nodes -o json"*) printf '%s\n' '{"items":[{"metadata":{"name":"n1","labels":{"sugarkube.env":"'"$IDENTITY"'","sugarkube.cluster":"sugar"}}}]}' ;;
  "create namespace monitoring --dry-run=client -o yaml") echo 'kind: Namespace'; echo 'metadata: {name: monitoring}'; echo 'mutate namespace monitoring' >> "$AUDIT" ;;
  "apply -f -")
    [ ! -e /dev/fd/4 ] && [ ! -e /dev/fd/5 ]
    manifest=$(cat)
    case "$manifest" in
      *"kind: Namespace"*"name: monitoring"*) echo 'apply namespace monitoring' >> "$AUDIT" ;;
      *"kind: Secret"*"name: grafana-admin-credentials"*"namespace: monitoring"*) echo 'apply secret monitoring/grafana-admin-credentials' >> "$AUDIT" ;;
      *) echo 'unexpected mutation' >> "$AUDIT"; exit 91 ;;
    esac
    ;;
  *"create secret generic grafana-admin-credentials"*)
    [ "$7" = "--from-file=admin-user=/dev/fd/4" ]
    [ "$8" = "--from-file=admin-password=/dev/fd/5" ]
    python3 -c \
      'import os, sys; os.write(int(sys.argv[1]), os.read(4, 1048576) + b"\n" + os.read(5, 1048576))' \
      "$CAPTURE_FD"
    echo 'mutate secret monitoring/grafana-admin-credentials' >> "$AUDIT"
    printf '%s\n' 'kind: Secret' 'metadata:' '  name: grafana-admin-credentials' '  namespace: monitoring'
    ;;
  *"get secret grafana-admin-credentials -o go-template="*)
    [ "$7" = 'go-template={{if and (index .data "admin-user") (index .data "admin-password")}}present{{end}}' ]
    echo secret-check >> "$AUDIT"
    [ "$SECRET_STATE" = missing ] && exit 44
    [ "$SECRET_STATE" = present ] && echo present
    ;;
  *) echo "unexpected kubectl operation" >> "$AUDIT"; exit 90 ;;
esac
""",
        encoding="utf-8",
    )
    (bin_dir / "kubectl").chmod(0o755)
    (bin_dir / "python3").write_text(
        r"""#!/bin/sh
case "${1:-}" in
  *validate_observability_dashboard.py)
    echo "forbidden operation: dashboard validator" >> "$AUDIT"
    exit 99
    ;;
esac
exec "$REAL_PYTHON" "$@"
""",
        encoding="utf-8",
    )
    (bin_dir / "python3").chmod(0o755)
    forbidden_stub = """#!/bin/sh
echo "forbidden operation: $(basename "$0")" >> "$AUDIT"
exit 99
"""
    for command_name in (
        "helm",
        "flux",
        "sops",
        "dashboard",
        "application-metrics",
        "blackbox",
        "pagerduty",
        "watchdog",
    ):
        guard = bin_dir / command_name
        guard.write_text(forbidden_stub, encoding="utf-8")
        guard.chmod(0o755)
    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{bin_dir}:{env['PATH']}",
            "AUDIT": str(audit),
            "CONTEXT": context,
            "IDENTITY": identity,
            "SECRET_STATE": secret_state,
            "CAPTURE_FD": str(capture_write),
            "REAL_PYTHON": sys.executable,
            "TMPDIR": str(script_tmp),
        }
    )
    if kubeconfig:
        env["KUBECONFIG"] = str(tmp_path / "kubeconfig")
    else:
        env.pop("KUBECONFIG", None)
    invocation = ["bash"]
    if xtrace:
        invocation.append("-x")
    invocation.extend([str(SCRIPT), command, env_name, *args])
    if test_tty and command == "grafana-secret-install":
        if extra_env:
            env.update(extra_env)
        master_fd, slave_fd = pty.openpty()

        def establish_controlling_tty():
            os.setsid()
            fcntl.ioctl(slave_fd, termios.TIOCSCTTY, 0)

        process = subprocess.Popen(
            invocation,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=env,
            pass_fds=(slave_fd, capture_write),
            preexec_fn=establish_controlling_tty,
        )
        os.close(slave_fd)
        os.write(master_fd, tty_text.encode())
        stdout, stderr = process.communicate()
        os.close(master_fd)
        result = subprocess.CompletedProcess(invocation, process.returncode, stdout, stderr)
    else:
        tty_read, tty_write = os.pipe()
        os.write(tty_write, tty_text.encode())
        os.close(tty_write)
        env["SUGARKUBE_GRAFANA_SECRET_TTY"] = f"/dev/fd/{tty_read}"
        env["SUGARKUBE_GRAFANA_SECRET_TEST_NONTTY"] = "1"
        if extra_env:
            env.update(extra_env)
        result = subprocess.run(
            invocation,
            text=True,
            capture_output=True,
            env=env,
            pass_fds=(tty_read, capture_write),
            check=False,
        )
        os.close(tty_read)
    os.close(capture_write)
    captured = b""
    while chunk := os.read(capture_read, 4096):
        captured += chunk
    os.close(capture_read)
    credentials = tuple(captured.decode().split("\n", 1)) if captured else ()
    return result, audit.read_text(encoding="utf-8") if audit.exists() else "", credentials


def test_grafana_secret_prod_guards_precede_tty_and_mutation(tmp_path):
    for kwargs in (
        {"kubeconfig": False},
        {"context": "sugar-staging"},
        {"identity": "staging"},
    ):
        result, audit, credentials = run_grafana_secret_helper(
            tmp_path / str(len(list(tmp_path.iterdir()))), **kwargs
        )
        assert result.returncode != 0
        assert audit == ""
        assert credentials == ()


def test_grafana_secret_prod_rejects_test_override_and_regular_file(tmp_path):
    result, audit, _ = run_grafana_secret_helper(tmp_path, test_tty=False)
    assert result.returncode != 0
    assert audit == ""


def test_grafana_secret_nonprod_test_override_is_deterministic(tmp_path):
    result, audit, _ = run_grafana_secret_helper(
        tmp_path,
        env_name="staging",
        context="sugar-staging",
        identity="staging",
        test_tty=False,
    )
    assert result.returncode == 0, result.stderr
    assert audit.splitlines() == [
        "mutate namespace monitoring",
        "apply namespace monitoring",
        "mutate secret monitoring/grafana-admin-credentials",
        "apply secret monitoring/grafana-admin-credentials",
    ]


def test_grafana_secret_check_staging_skips_dashboard_and_is_read_only(tmp_path):
    result, audit, _ = run_grafana_secret_helper(
        tmp_path,
        command="grafana-secret-check",
        env_name="staging",
        context="sugar-staging",
        identity="staging",
    )
    assert result.returncode == 0, result.stderr
    assert audit == "secret-check\n"


def test_grafana_secret_tty_open_failure_is_redacted(tmp_path):
    missing = tmp_path / "missing-tty"
    result, audit, _ = run_grafana_secret_helper(
        tmp_path,
        env_name="staging",
        context="sugar-staging",
        identity="staging",
        test_tty=False,
        extra_env={"SUGARKUBE_GRAFANA_SECRET_TTY": str(missing)},
    )
    assert result.returncode != 0
    assert audit == ""
    assert "could not open the Grafana credential terminal" in result.stderr
    assert str(missing) not in result.stdout + result.stderr


@pytest.mark.parametrize(
    "kwargs",
    [
        {"test_tty": False},
        {"xtrace": True},
        {"extra_env": {"GRAFANA_ADMIN_USER": "ENV_SENTINEL_VALUE"}},
        {"extra_env": {"GRAFANA_ADMIN_PASSWORD": "ENV_SENTINEL_VALUE"}},
        {"extra_env": {"GF_SECURITY_ADMIN_USER": "ENV_SENTINEL_VALUE"}},
        {"extra_env": {"GF_SECURITY_ADMIN_PASSWORD": "ENV_SENTINEL_VALUE"}},
        {"args": ("ARG_SENTINEL_VALUE",)},
        {"tty_text": "\nINPUT_SENTINEL_VALUE\nINPUT_SENTINEL_VALUE\n"},
        {"tty_text": "operator\n\n\n"},
        {"tty_text": "operator\none\ntwo\n"},
    ],
)
def test_grafana_secret_install_fails_closed_before_mutation(tmp_path, kwargs):
    result, audit, _ = run_grafana_secret_helper(tmp_path, **kwargs)
    assert result.returncode != 0
    assert audit == ""
    combined = result.stdout + result.stderr
    for value in ("ENV_SENTINEL_VALUE", "ARG_SENTINEL_VALUE", "INPUT_SENTINEL_VALUE", "operator"):
        assert value not in combined


def test_grafana_secret_install_is_exact_redacted_and_rotatable(tmp_path):
    expected_mutations = [
        "mutate namespace monitoring",
        "apply namespace monitoring",
        "mutate secret monitoring/grafana-admin-credentials",
        "apply secret monitoring/grafana-admin-credentials",
    ]
    before = {path.name for path in tmp_path.iterdir()}
    result, audit, credentials = run_grafana_secret_helper(tmp_path)
    assert result.returncode == 0, result.stderr
    assert audit.splitlines() == expected_mutations
    assert credentials == ("operator", "correct horse battery staple")
    combined = result.stdout + result.stderr + audit
    assert "operator" not in combined
    assert "correct horse battery staple" not in combined
    for forbidden in (
        "helm",
        "flux",
        "sops",
        "dashboard",
        "application-metrics",
        "blackbox",
        "pagerduty",
        "watchdog",
    ):
        assert forbidden not in audit.lower()
    assert {path.name for path in tmp_path.iterdir()} - before == {"bin", "audit", "tmp"}
    assert list((tmp_path / "tmp").iterdir()) == []
    repeated, repeated_audit, repeated_credentials = run_grafana_secret_helper(
        tmp_path / "repeat"
    )
    assert repeated.returncode == 0, repeated.stderr
    assert repeated_audit.splitlines() == expected_mutations
    assert repeated_credentials == ("operator", "correct horse battery staple")
    second_user = "rotation-user-sentinel"
    second_password = "rotation-password-sentinel"
    result, audit, credentials = run_grafana_secret_helper(
        tmp_path / "rotation",
        tty_text=f"{second_user}\n{second_password}\n{second_password}\n",
    )
    assert result.returncode == 0
    assert audit.splitlines() == expected_mutations
    assert credentials == (second_user, second_password)
    assert second_user not in result.stdout + result.stderr + audit
    assert second_password not in result.stdout + result.stderr + audit
    assert list((tmp_path / "rotation" / "tmp").iterdir()) == []


@pytest.mark.parametrize("state,success", [("present", True), ("missing", False), ("empty", False)])
def test_grafana_secret_check_is_read_only_and_redacted(tmp_path, state, success):
    result, audit, _ = run_grafana_secret_helper(
        tmp_path, command="grafana-secret-check", secret_state=state
    )
    assert (result.returncode == 0) is success
    assert audit == "secret-check\n"
    assert "operator" not in result.stdout + result.stderr
    assert "admin-user" not in result.stdout + result.stderr
    assert "admin-password" not in result.stdout + result.stderr


def test_grafana_secret_check_restores_requested_xtrace(tmp_path):
    result, audit, _ = run_grafana_secret_helper(
        tmp_path, command="grafana-secret-check", xtrace=True
    )
    assert result.returncode == 0
    assert audit == "secret-check\n"
    assert "+ assert_context" in result.stderr
    assert "+ assert_grafana_secret" in result.stderr


def test_grafana_secret_check_rejects_arguments_before_restoring_xtrace(tmp_path):
    sentinel = "CHECK_CREDENTIAL_SENTINEL"
    result, audit, _ = run_grafana_secret_helper(
        tmp_path,
        command="grafana-secret-check",
        xtrace=True,
        args=(sentinel,),
        extra_env={"GRAFANA_ADMIN_PASSWORD": sentinel},
    )
    assert result.returncode != 0
    assert audit == ""
    assert sentinel not in result.stdout + result.stderr + audit


def run_helper(
    tmp_path: Path,
    command: str,
    *,
    env_name="staging",
    helm_mode="absent",
    context="sugar-staging",
    kubectl_mode="healthy",
    pvc_mode="converged",
    target_responses=None,
    target_response_delay="0",
    retry_attempts="3",
    retry_interval="1",
    action=None,
    pagerduty_mode="success",
    watchdog_silence_mode=None,
    pagerduty_forward_line="Forwarding from 127.0.0.1:43128 -> 9093",
    watchdog_tty_text=None,
    command_args=(),
    extra_env=None,
    watchdog_silences=None,
    watchdog_log_text="",
    interrupt_signal=None,
):
    """Run the lifecycle against deterministic command stubs and return its audit log."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(parents=True)
    audit = tmp_path / "audit"
    (bin_dir / "helm").write_text(
        """#!/bin/sh
echo "helm $*" >> "$AUDIT"
for argument in "$@"; do
  case "$argument" in
    *sugarkube-observability-rules.*.yaml) cp "$argument" "$OVERLAY_CAPTURE" ;;
  esac
done
case "$*" in
  *"repo add"*|*"repo update"*) exit 0 ;;
  *template*)
    [ "$HELM_MODE" != render-fail ] || exit 31
    printf '%s\n' 'apiVersion: v1' 'kind: ConfigMap' 'metadata:' '  name: kube-prometheus-stack-grafana-dashboards-sugarkube' '  labels:' '    dashboard-provider: sugarkube' 'data:' "  $DASHBOARD_FILE:" '    |-'
    sed 's/^/      /' "$DASHBOARD"
    printf '%s\n' '---' 'kind: ConfigMap' 'data:' '  dashboardproviders.yaml: |' '    providers:' '      - name: sugarkube' '        options:' '          path: /var/lib/grafana/dashboards/sugarkube' '---' 'kind: Deployment' 'spec:' '  template:' '    spec:' '      containers:' '        - volumeMounts:' '            - name: dashboards-sugarkube' "              mountPath: /var/lib/grafana/dashboards/sugarkube/$DASHBOARD_FILE" "              subPath: $DASHBOARD_FILE"
    if [ "$ENV_NAME" = prod ]; then
      printf '%s\n' '---' 'apiVersion: monitoring.coreos.com/v1' 'kind: Alertmanager' 'metadata:' '  name: kube-prometheus-stack-alertmanager' 'spec:' '  secrets: []' '---' 'apiVersion: v1' 'kind: Secret' 'metadata:' '  name: alertmanager-kube-prometheus-stack-alertmanager' 'stringData:' '  alertmanager.yaml: |' '    route:' '      receiver: "null"' '    receivers:' '      - name: "null"'
      exit 0
    fi
    printf '%s\n' '---' 'apiVersion: monitoring.coreos.com/v1' 'kind: Alertmanager' 'metadata:' '  name: kube-prometheus-stack-alertmanager' 'spec:' '  secrets:' '    - alertmanager-pagerduty' '    - alertmanager-healthchecks-watchdog'
    printf '%s\n' '---' 'apiVersion: v1' 'kind: Secret' 'metadata:' '  name: alertmanager-kube-prometheus-stack-alertmanager' 'stringData:' '  alertmanager.yaml: |'
    sed 's/^/    /' "$ALERTMANAGER_CONFIG"
    exit 0
    ;;
  *list*) [ "$HELM_MODE" != query-fail ] || exit 32; [ "$HELM_MODE" = present ] && echo kube-prometheus-stack; exit 0 ;;
  *) exit 0 ;;
esac
""",
        encoding="utf-8",
    )
    (bin_dir / "kubectl").write_text(
        """#!/bin/sh
echo "kubectl $*" >> "$AUDIT"
case "$*" in
  "config current-context") echo "$CONTEXT" ;;
  *"get nodes -o json"*)
    environment="$ENV_NAME"
    case "$KUBECTL_MODE" in identity-mismatch|watchdog-cluster-mismatch) [ "$ENV_NAME" = prod ] && environment=staging || environment=prod ;; esac
    printf '%s\n' '{"items":[{"metadata":{"name":"n1","labels":{"sugarkube.env":"'"$environment"'","sugarkube.cluster":"sugar"}}}]}'
    ;;
  *"get daemonset kube-prometheus-stack-prometheus-node-exporter"*) [ "$KUBECTL_MODE" = two-nodes ] && echo '2 2' || echo '3 3' ;;
  *"get pvc --all-namespaces -o json"*)
    case "$PVC_MODE" in
      absent) printf '%s\n' '{"items":[]}' ;;
      discovery-fail) exit 52 ;;
      ambiguous) printf '%s\n' '{"items":[{"metadata":{"namespace":"monitoring","name":"prometheus-a","labels":{"app.kubernetes.io/name":"prometheus"}}},{"metadata":{"namespace":"monitoring","name":"prometheus-b","labels":{"app.kubernetes.io/name":"prometheus"}}}]}' ;;
      incomplete) printf '%s\n' '{"items":[{"metadata":{"namespace":"monitoring","name":"prometheus-db","labels":{"app.kubernetes.io/name":"prometheus"}},"spec":{"storageClassName":"local-path"},"status":{"phase":"Bound"}}]}' ;;
      *)
        size=128Gi
        [ "$PVC_MODE" != nonexpandable-20gi ] || size=20Gi
        [ "$PVC_MODE" != expandable-mismatch ] || size=64Gi
        [ "$PVC_MODE" != storageclass-fail ] || size=20Gi
        [ "$PVC_MODE" != storageclass-ambiguous ] || size=20Gi
        printf '%s\n' '{"items":[{"metadata":{"namespace":"monitoring","name":"prometheus-db","labels":{"app.kubernetes.io/name":"prometheus"}},"spec":{"storageClassName":"local-path","accessModes":["ReadWriteOnce"],"resources":{"requests":{"storage":"'"$size"'"}}},"status":{"phase":"Bound"}}]}'
        ;;
    esac ;;
  *"get pvc -o json"*) printf '%s\n' '{"items":[{"metadata":{"name":"generated-pvc","labels":{"app.kubernetes.io/name":"prometheus"}},"spec":{"storageClassName":"local-path","accessModes":["ReadWriteOnce"],"resources":{"requests":{"storage":"128Gi"}}},"status":{"phase":"Bound"}}]}' ;;
  *"get storageclass local-path -o json"*)
    case "$PVC_MODE" in storageclass-fail|converged-storageclass-fail) exit 53 ;; esac
    [ "$PVC_MODE" != storageclass-ambiguous ] || { printf '%s\n' '{"allowVolumeExpansion":"maybe"}'; exit 0; }
    [ "$PVC_MODE" = expandable-mismatch ] && expansion=true || expansion=false
    printf '%s\n' '{"allowVolumeExpansion":'"$expansion"'}' ;;
  *"get statefulset prometheus-kube-prometheus-stack-prometheus -o json"*)
    if [ "$KUBECTL_MODE" = stale-retention ]; then retention=7d; retention_size=15GB; else retention=90d; retention_size=100GB; fi
    printf '%s\n' '{"spec":{"template":{"spec":{"containers":[{"name":"config-reloader","args":[]},{"name":"prometheus","args":["--storage.tsdb.retention.time='"$retention"'","--storage.tsdb.retention.size='"$retention_size"'"]}]}}}}' ;;
  *"get prometheus kube-prometheus-stack-prometheus"*) echo 1 ;;
  *"get alertmanager kube-prometheus-stack-alertmanager -o yaml"*)
    if [ "$ENV_NAME" = prod ]; then printf '%s\n' 'apiVersion: monitoring.coreos.com/v1' 'kind: Alertmanager' 'metadata:' '  name: kube-prometheus-stack-alertmanager' 'spec:' '  secrets: []'; else printf '%s\n' 'apiVersion: monitoring.coreos.com/v1' 'kind: Alertmanager' 'metadata:' '  name: kube-prometheus-stack-alertmanager' 'spec:' '  secrets:' '    - alertmanager-pagerduty' '    - alertmanager-healthchecks-watchdog'; fi ;;
  *"get alertmanager kube-prometheus-stack-alertmanager"*) echo 1 ;;
  *"get secret alertmanager-kube-prometheus-stack-alertmanager -o yaml"*)
    printf '%s\n' 'apiVersion: v1' 'kind: Secret' 'metadata:' '  name: alertmanager-kube-prometheus-stack-alertmanager' 'stringData:' '  alertmanager.yaml: |'
    if [ "$KUBECTL_MODE" = malformed-alertmanager ]; then
      printf '%s\n' '    route: [unterminated'
    elif [ "$ENV_NAME" = prod ]; then
      printf '%s\n' '    route:' '      receiver: "null"' '    receivers:' '      - name: "null"'
    else
      sed 's/^/    /' "$ALERTMANAGER_CONFIG"
    fi
    ;;
  *"get secret grafana-admin-credentials -o go-template="*) [ "$KUBECTL_MODE" != missing-grafana ] || exit 44; [ "$KUBECTL_MODE" != empty-grafana ] && echo present ;;
  *"get secret alertmanager-pagerduty -o go-template="*) [ "$KUBECTL_MODE" != missing-pagerduty ] || exit 44; [ "$KUBECTL_MODE" != empty-pagerduty ] && echo present ;;
  *"get secret alertmanager-healthchecks-watchdog -o go-template="*) [ "$KUBECTL_MODE" != missing-watchdog ] || exit 44; [ "$KUBECTL_MODE" != empty-watchdog ] && echo present ;;
  *"create secret generic alertmanager-healthchecks-watchdog --from-file=ping-url=/dev/stdin --dry-run=client -o yaml"*)
    cat > "$WATCHDOG_CREATE_STDIN"
    [ "$KUBECTL_MODE" != watchdog-create-fail ] || exit 46
    printf '%s\n' 'apiVersion: v1' 'kind: Secret' 'metadata:' '  name: alertmanager-healthchecks-watchdog' 'data:' '  ping-url: REDACTED_TEST_DATA'
    ;;
  *"apply -f -"*)
    cat > "$WATCHDOG_APPLY_STDIN"
    [ "$KUBECTL_MODE" != watchdog-apply-fail ] || exit 47
    ;;
  *"proxy/api/v1/rules"*)
    extra=''
    [ "$KUBECTL_MODE" != watchdog-extra-rule-label ] || extra=',"sentinel":"REJECTED_RULE_PAYLOAD_SENTINEL"'
    printf '%s\n' '{"data":{"groups":[{"rules":[{"name":"SugarkubeObservabilityWatchdog","state":"firing","query":"vector(1)","labels":{"environment":"staging","cluster":"sugarkube-int","purpose":"observability-watchdog"'"$extra"'}}]}]}}'
    ;;
  *"/api/v2/alerts"*) printf '%s\n' '[{"status":{"state":"active"},"labels":{"alertname":"SugarkubeObservabilityWatchdog","environment":"staging","cluster":"sugarkube-int","purpose":"observability-watchdog","prometheus":"platform-added"}}]' ;;
  *"get pods -l app.kubernetes.io/name=alertmanager -o json"*)
    phase=Running
    secret=alertmanager-healthchecks-watchdog
    volume=watchdog
    mount=/etc/alertmanager/secrets/alertmanager-healthchecks-watchdog
    readonly=true
    case "$KUBECTL_MODE" in
      watchdog-no-pods) printf '%s\n' '{"items":[],"private":"POD_FIXTURE_SENTINEL"}'; exit 0 ;;
      watchdog-malformed-pods) printf '%s\n' '{"items":"PRIVATE_MALFORMED_POD_FIXTURE"}'; exit 0 ;;
      watchdog-pod-not-running) phase=Pending ;;
      watchdog-missing-volume) volume=unmounted ;;
      watchdog-wrong-secret-volume) secret=another-secret ;;
      watchdog-missing-mount) volume=mounted-under-another-name ;;
      watchdog-wrong-mount-path) mount=/etc/alertmanager/secrets/wrong ;;
      watchdog-mount-not-readonly) readonly=false ;;
    esac
    pod='{"metadata":{"name":"alertmanager-kube-prometheus-stack-alertmanager-0","labels":{"alertmanager":"kube-prometheus-stack-alertmanager"}},"status":{"phase":"'"$phase"'"},"spec":{"volumes":[{"name":"'"$volume"'","secret":{"secretName":"'"$secret"'"}}],"containers":[{"volumeMounts":[{"name":"watchdog","mountPath":"'"$mount"'","readOnly":'"$readonly"'}]}]},"private":"POD_FIXTURE_SENTINEL"}'
    case "$KUBECTL_MODE" in
      watchdog-unrelated-pod) pod='{"metadata":{"name":"unrelated-alertmanager-0","labels":{"alertmanager":"another-resource"}},"status":{"phase":"Running"},"spec":{}}' ;;
      watchdog-malformed-status) pod="$(printf '%s' "$pod" | sed 's/"status":{"phase":"Running"}/"status":"PRIVATE_MALFORMED_POD_FIXTURE"/')" ;;
      watchdog-malformed-metadata) pod="$(printf '%s' "$pod" | sed 's/"metadata":{/"metadata":"PRIVATE_MALFORMED_POD_FIXTURE","ignored":{/')" ;;
      watchdog-malformed-labels) pod="$(printf '%s' "$pod" | sed 's/"labels":{/"labels":"PRIVATE_MALFORMED_POD_FIXTURE","ignoredLabels":{/')" ;;
      watchdog-malformed-name) pod="$(printf '%s' "$pod" | sed 's|alertmanager-kube-prometheus-stack-alertmanager-0|PRIVATE_MALFORMED_POD_FIXTURE\\nhttps://fixture.invalid/user:credential@example|')" ;;
      watchdog-malformed-spec) pod="$(printf '%s' "$pod" | sed 's/"spec":{/"spec":"PRIVATE_MALFORMED_POD_FIXTURE","ignoredSpec":{/')" ;;
      watchdog-malformed-volumes) pod="$(printf '%s' "$pod" | sed 's/"volumes":\\[/"volumes":"PRIVATE_MALFORMED_POD_FIXTURE","ignored":[/')" ;;
      watchdog-malformed-volume) pod="$(printf '%s' "$pod" | sed 's/{"name":"watchdog","secret"/"PRIVATE_MALFORMED_POD_FIXTURE",{"name":"watchdog","secret"/')" ;;
      watchdog-malformed-containers) pod="$(printf '%s' "$pod" | sed 's/"containers":\\[/"containers":"PRIVATE_MALFORMED_POD_FIXTURE","ignoredContainers":[/')" ;;
      watchdog-malformed-container) pod="$(printf '%s' "$pod" | sed 's/{"volumeMounts"/"PRIVATE_MALFORMED_POD_FIXTURE",{"volumeMounts"/')" ;;
      watchdog-malformed-mounts) pod="$(printf '%s' "$pod" | sed 's/"volumeMounts":\\[/"volumeMounts":"PRIVATE_MALFORMED_POD_FIXTURE","ignoredMounts":[/')" ;;
      watchdog-malformed-mount) pod="$(printf '%s' "$pod" | sed 's/{"name":"watchdog","mountPath"/"PRIVATE_MALFORMED_POD_FIXTURE",{"name":"watchdog","mountPath"/')" ;;
      watchdog-multiple-pods|watchdog-second-log-fails) pod="$pod,$(printf '%s' "$pod" | sed 's/alertmanager-0/alertmanager-1/')" ;;
    esac
    printf '%s\n' '{"items":['"$pod"']}'
    ;;
  *"logs pod/alertmanager-kube-prometheus-stack-alertmanager-"*" -c alertmanager "*)
    case "$KUBECTL_MODE" in
      watchdog-logs-fail) echo 'PRIVATE_LOG_RETRIEVAL_SENTINEL' >&2; exit 51 ;;
      watchdog-second-log-fails) case "$*" in *"-1 -c alertmanager"*) echo 'PRIVATE_LOG_RETRIEVAL_SENTINEL' >&2; exit 51 ;; esac ;;
    esac
    case "$*" in
      *"alertmanager-0 -c alertmanager"*) printf '%s' "${WATCHDOG_LOG_TEXT_0:-$WATCHDOG_LOG_TEXT}" ;;
      *"alertmanager-1 -c alertmanager"*) printf '%s' "${WATCHDOG_LOG_TEXT_1:-$WATCHDOG_LOG_TEXT}" ;;
    esac
    ;;
  *"create --raw /api/v1/namespaces/monitoring/services/http:kube-prometheus-stack-alertmanager:9093/proxy/api/v2/silences -f -"*)
    cat > "$WATCHDOG_SILENCE_PAYLOAD"
    [ "$KUBECTL_MODE" != watchdog-silence-create-fail ] || exit 48
    [ "$KUBECTL_MODE" != watchdog-silence-create-malformed ] || { printf '%s\n' '{malformed'; exit 0; }
    printf '%s\n' '{"silenceID":"created-owned-silence"}'
    ;;
  *"get --raw /api/v1/namespaces/monitoring/services/http:kube-prometheus-stack-alertmanager:9093/proxy/api/v2/silences"*)
    [ "$KUBECTL_MODE" != watchdog-silences-fail ] || exit 49
    [ "$KUBECTL_MODE" != watchdog-silences-malformed ] || { printf '%s\n' '{malformed'; exit 0; }
    [ "$KUBECTL_MODE" != watchdog-silences-nonutf8 ] || { printf '\377PRIVATE_NON_UTF8_SENTINEL\n'; exit 0; }
    cat "$WATCHDOG_SILENCES"
    ;;
  *"delete --raw /api/v1/namespaces/monitoring/services/http:kube-prometheus-stack-alertmanager:9093/proxy/api/v2/silence/"*)
    printf '%s\n' "${3##*/}" >> "$WATCHDOG_SILENCE_DELETIONS"
    [ "$KUBECTL_MODE" != watchdog-silence-delete-fail ] || exit 50
    ;;
  *"port-forward"*"service/kube-prometheus-stack-alertmanager"*":9093"*)
    [ "$PAGERDUTY_MODE" != forward-exit ] || { echo PORT_FORWARD_SENTINEL; exit 42; }
    echo "$PAGERDUTY_FORWARD_LINE"
    echo $$ > "$PAGERDUTY_PID"
    trap 'echo reaped > "$PAGERDUTY_REAPED"; exit 0' TERM INT
    while :; do /bin/sleep 1; done
    ;;
  *"get ingress "*) exit 0 ;;
  *"get svc kube-prometheus-stack-grafana"*) echo 30300 ;;
  *"get servicemonitor dspace"*"metadata.labels.release"*) [ "$KUBECTL_MODE" = wrong-release ] && echo wrong || echo kube-prometheus-stack ;;
  *"get servicemonitor dspace"*"bearerTokenSecret.name"*) [ "$KUBECTL_MODE" != missing-secret-ref ] && echo dspace-token ;;
  *"get secret dspace-token -o name"*) [ "$KUBECTL_MODE" != missing-secret ] || exit 44; echo secret/dspace-token ;;
  *"get --request-timeout="*" --raw "*)
    [ "$KUBECTL_MODE" != query-fail ] || exit 45
    [ "$TARGET_RESPONSE_DELAY" = 0 ] || /bin/sleep "$TARGET_RESPONSE_DELAY"
    if [ -n "$TARGET_RESPONSES" ]; then
      count=0
      [ ! -f "$TARGET_COUNTER" ] || count=$(cat "$TARGET_COUNTER")
      count=$((count + 1))
      echo "$count" > "$TARGET_COUNTER"
      sed -n "${count}p" "$TARGET_RESPONSES"
    else
      printf '%s\n' '{"status":"success","data":{"activeTargets":[{"labels":{"app":"dspace","namespace":"dspace"},"health":"up"}]}}'
    fi
    ;;
  *) exit 0 ;;
esac
""",
        encoding="utf-8",
    )
    (bin_dir / "curl").write_text(
        """#!/bin/sh
echo "curl $*" >> "$AUDIT"
data=""
noproxy=""
output=""
url=""
while [ "$#" -gt 0 ]; do
  [ "$1" != --data-binary ] || { shift; data=${1#@}; }
  [ "$1" != --noproxy ] || { shift; noproxy=$1; }
  [ "$1" != --output ] || { shift; output=$1; }
  url=$1
  shift
done
[ "$noproxy" = '*' ] || exit 64
[ -z "$data" ] || case "$url" in
  */api/v2/silences) cp "$data" "$WATCHDOG_SILENCE_PAYLOAD" ;;
  *) cp "$data" "$ALERT_PAYLOAD" ;;
esac
mode=$PAGERDUTY_MODE
case "$url" in */api/v2/silences) mode=$WATCHDOG_SILENCE_MODE ;; esac
case "$mode" in
  transport) echo CURL_RESPONSE_SENTINEL >&2; exit 7 ;;
  forward-exit-during-curl) kill -9 "$(cat "$PAGERDUTY_PID")"; /bin/sleep 0.1; code=200 ;;
  signal-wait) printf 'ready\n' > "$WATCHDOG_SIGNAL_READY"; /bin/sleep 30; code=200 ;;
  http000) code=000 ;;
  http415) code=415 ;;
  http400) code=400 ;;
  http503) code=503 ;;
  malformed) code=not-a-status ;;
  *) code=200 ;;
esac
case "$url" in
  */api/v2/silences)
    case "$WATCHDOG_SILENCE_MODE" in
      response-malformed) printf '%s' '{malformed' > "$output" ;;
      response-missing) printf '%s' '{"fixture":"PRIVATE_RESPONSE_SENTINEL"}' > "$output" ;;
      response-invalid-id) printf '%s' '{"silenceID":"PRIVATE_RESPONSE_SENTINEL\ncredential"}' > "$output" ;;
      *) printf '%s' '{"silenceID":"created-owned-silence"}' > "$output" ;;
    esac
    ;;
  *) printf RESPONSE_SENTINEL > "$output" ;;
esac
printf '%s' "$code"
""",
        encoding="utf-8",
    )
    (bin_dir / "sleep").write_text(
        '#!/bin/sh\necho "sleep $*" >> "$AUDIT"\n',
        encoding="utf-8",
    )
    for stub in bin_dir.iterdir():
        stub.chmod(0o755)
    env = os.environ | {
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "AUDIT": str(audit),
        "OVERLAY_CAPTURE": str(tmp_path / "rules-overlay.yaml"),
        "HELM_MODE": helm_mode,
        "ENV_NAME": env_name,
        "CONTEXT": context,
        "KUBECTL_MODE": kubectl_mode,
        "PVC_MODE": pvc_mode,
        "KUBECONFIG": str(tmp_path / "kubeconfig"),
        "TMPDIR": str(tmp_path),
        "TARGET_RESPONSES": "",
        "TARGET_COUNTER": str(tmp_path / "target-counter"),
        "TARGET_RESPONSE_DELAY": target_response_delay,
        "ALERT_PAYLOAD": str(tmp_path / "alert-payload"),
        "PAGERDUTY_MODE": pagerduty_mode,
        "WATCHDOG_SILENCE_MODE": watchdog_silence_mode or pagerduty_mode,
        "PAGERDUTY_FORWARD_LINE": pagerduty_forward_line,
        "PAGERDUTY_PID": str(tmp_path / "pagerduty.pid"),
        "PAGERDUTY_REAPED": str(tmp_path / "pagerduty.reaped"),
        "ALERTMANAGER_CONFIG": str(tmp_path / "alertmanager-config.yaml"),
        "SUGARKUBE_OBSERVABILITY_TARGET_HEALTH_ATTEMPTS": retry_attempts,
        "SUGARKUBE_OBSERVABILITY_TARGET_HEALTH_INTERVAL_SECONDS": retry_interval,
        "SUGARKUBE_WATCHDOG_OBSERVATION_SECONDS": "0",
        "SUGARKUBE_WATCHDOG_TEST_ALLOW_SHORT_OBSERVATION": "1",
        "SUGARKUBE_WATCHDOG_TTY": str(tmp_path / "watchdog-tty"),
        "SUGARKUBE_WATCHDOG_TEST_NONTTY": "1",
        "WATCHDOG_CREATE_STDIN": str(tmp_path / "watchdog-create-stdin"),
        "WATCHDOG_APPLY_STDIN": str(tmp_path / "watchdog-apply-stdin"),
        "WATCHDOG_SILENCE_PAYLOAD": str(tmp_path / "watchdog-silence-payload"),
        "WATCHDOG_SIGNAL_READY": str(tmp_path / "watchdog-signal-ready"),
        "WATCHDOG_SILENCE_DELETIONS": str(tmp_path / "watchdog-silence-deletions"),
        "WATCHDOG_SILENCES": str(tmp_path / "watchdog-silences.json"),
        "WATCHDOG_LOG_TEXT": watchdog_log_text,
        "DASHBOARD": str(PROD_DASHBOARD if env_name == "prod" else DASHBOARD),
        "DASHBOARD_FILE": (PROD_DASHBOARD if env_name == "prod" else DASHBOARD).name,
    }
    (tmp_path / "watchdog-tty").write_text(watchdog_tty_text or "", encoding="utf-8")
    (tmp_path / "watchdog-silences.json").write_text(
        json.dumps(watchdog_silences or []), encoding="utf-8"
    )
    if extra_env:
        env.update(extra_env)
    (tmp_path / "alertmanager-config.yaml").write_text(
        f"""route:
  receiver: "null"
  routes:
    - receiver: pagerduty-dspace
      matchers:
        - {DSPACE_ALERT_MATCHER}
        - environment="staging"
        - cluster="sugarkube-int"
        - severity="critical"
    - receiver: pagerduty-dspace
      matchers:
        - alertname="CloudflareTunnelNoHealthyConnections"
        - environment="staging"
        - cluster="sugarkube-int"
        - severity="critical"
    - receiver: pagerduty-synthetic-test
      matchers:
        - alertname="SugarkubePagerDutyTest"
        - environment="staging"
        - cluster="sugarkube-int"
        - severity="critical"
    - receiver: healthchecks-watchdog
      matchers:
        - alertname="SugarkubeObservabilityWatchdog"
        - environment="staging"
        - cluster="sugarkube-int"
        - purpose="observability-watchdog"
      group_by: [alertname, cluster, environment]
      group_wait: 30s
      group_interval: 1m
      repeat_interval: 5m
      continue: false
receivers:
  - name: "null"
  - name: pagerduty-synthetic-test
    pagerduty_configs:
      - routing_key_file: /etc/alertmanager/secrets/alertmanager-pagerduty/routing-key
        send_resolved: true
  - name: pagerduty-dspace
    pagerduty_configs:
      - routing_key_file: /etc/alertmanager/secrets/alertmanager-pagerduty/routing-key
        send_resolved: true
  - name: healthchecks-watchdog
    webhook_configs:
      - url_file: /etc/alertmanager/secrets/alertmanager-healthchecks-watchdog/ping-url
        send_resolved: false
        max_alerts: 1
        timeout: 10s
""",
        encoding="utf-8",
    )
    if target_responses is not None:
        responses = tmp_path / "target-responses"
        if any(isinstance(response, bytes) for response in target_responses):
            responses.write_bytes(
                b"\n".join(
                    response if isinstance(response, bytes) else response.encode()
                    for response in target_responses
                )
                + b"\n"
            )
        else:
            responses.write_text("\n".join(target_responses) + "\n", encoding="utf-8")
        env["TARGET_RESPONSES"] = str(responses)
    argv = [
        "bash",
        str(SCRIPT),
        command,
        f"env={env_name}",
        *([action] if action is not None else []),
        *command_args,
    ]
    if interrupt_signal is None:
        result = subprocess.run(argv, text=True, capture_output=True, env=env, check=False)
    else:
        process = subprocess.Popen(
            argv,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
            start_new_session=True,
        )
        readiness_deadline = time.monotonic() + 5
        while time.monotonic() < readiness_deadline:
            if (tmp_path / "watchdog-signal-ready").exists():
                break
            if process.poll() is not None:
                break
            time.sleep(0.01)
        assert process.poll() is None, "watchdog drill exited before signal injection"
        assert (tmp_path / "pagerduty.pid").exists(), "port-forward did not start"
        assert list(tmp_path.glob("sugarkube-watchdog-silence.*")), "temporary directory missing"
        assert (tmp_path / "watchdog-signal-ready").exists(), "curl did not enter signal wait"
        os.killpg(process.pid, interrupt_signal)
        stdout, stderr = wait_for_watchdog_signal_cleanup(process, tmp_path)
        result = subprocess.CompletedProcess(argv, process.returncode, stdout, stderr)
    return result, audit.read_text(encoding="utf-8") if audit.exists() else ""


def test_fallback_secret_scanner_allows_only_complete_placeholders():
    namespace = {"__name__": "scan_secrets_test"}
    exec((ROOT / "scripts" / "scan-secrets.py").read_text(encoding="utf-8"), namespace)
    credential_word = "pass" + "word"
    metadata = "+  " + credential_word + "Key: admin-" + credential_word
    documented_key = "+  - Pass" + "word key: `admin-" + credential_word + "`."
    assert not namespace["regex_scan"](["+++ b/values.yaml", metadata])
    assert not namespace["regex_scan"](["+++ b/docs.md", documented_key])
    suffixes = (
        " to" + "ken=secret",
        " api_" + "key=secret",
        " " + credential_word + "=secret",
    )
    for suffix in suffixes:
        assert namespace["regex_scan"](["+++ b/values.yaml", metadata + suffix])
        assert namespace["regex_scan"](["+++ b/docs.md", documented_key + suffix])
    risky_comment = " # " + credential_word + "=real-secret"
    assert namespace["regex_scan"](["+++ b/values.yaml", metadata + risky_comment])


def test_terminate_and_reap_process_group_escalates_after_timeout(monkeypatch):
    class FakeProcess:
        pid = 4321

        def __init__(self):
            self.timeouts = []

        def communicate(self, timeout=None):
            self.timeouts.append(timeout)
            if timeout == 1:
                raise subprocess.TimeoutExpired(cmd=["fake"], timeout=timeout)
            return "", ""

    process = FakeProcess()
    signals = []
    monkeypatch.setattr(os, "killpg", lambda pid, sig: signals.append((pid, sig)))

    terminate_and_reap_process_group(process)

    assert signals == [(4321, signal.SIGTERM), (4321, signal.SIGKILL)]
    assert process.timeouts == [1, None]


def test_wait_for_watchdog_signal_cleanup_returns_output_after_cleanup(tmp_path):
    class FakeProcess:
        pid = 4321
        returncode = 130

        def poll(self):
            return self.returncode

        def communicate(self):
            return "stdout", "stderr"

    (tmp_path / "pagerduty.reaped").write_text("reaped", encoding="utf-8")

    assert wait_for_watchdog_signal_cleanup(FakeProcess(), tmp_path) == ("stdout", "stderr")


def test_wait_for_watchdog_signal_cleanup_times_out_with_missing_state_message(
    tmp_path, monkeypatch
):
    class FakeProcess:
        pid = 4321

        def poll(self):
            return None

    (tmp_path / "sugarkube-watchdog-silence.fixture").mkdir()
    monotonic_values = [0.0, 0.0]

    def fake_monotonic():
        return monotonic_values.pop(0) if monotonic_values else 16.0

    monkeypatch.setattr(time, "monotonic", fake_monotonic)
    monkeypatch.setattr(time, "sleep", lambda _: None)
    reaped = []
    monkeypatch.setattr(
        sys.modules[__name__],
        "terminate_and_reap_process_group",
        lambda process: reaped.append(process.pid),
    )

    with pytest.raises(
        pytest.fail.Exception,
        match=(
            "watchdog drill exit, port-forward reap marker, "
            "temporary directory removal"
        ),
    ):
        wait_for_watchdog_signal_cleanup(FakeProcess(), tmp_path)

    assert reaped == [4321]


def test_pre_mutation_guards_are_fail_closed(tmp_path):
    unsupported = subprocess.run(
        ["bash", str(SCRIPT), "install", "env=prod"], capture_output=True, text=True, check=False
    )
    assert unsupported.returncode != 0
    mismatch, audit = run_helper(tmp_path / "mismatch", "install", context="other")
    assert mismatch.returncode != 0 and "helm install" not in audit
    render_fail, audit = run_helper(tmp_path / "render", "install", helm_mode="render-fail")
    assert render_fail.returncode != 0 and "helm list" not in audit and "helm install" not in audit
    query_fail, audit = run_helper(tmp_path / "query", "install", helm_mode="query-fail")
    assert query_fail.returncode != 0 and " template " in audit and "helm install" not in audit


def test_install_and_upgrade_require_distinct_release_states(tmp_path):
    installed, audit = run_helper(tmp_path / "install", "install", helm_mode="absent")
    assert installed.returncode == 0 and "helm install" in audit
    rejected, audit = run_helper(tmp_path / "reject-install", "install", helm_mode="present")
    assert rejected.returncode != 0 and "helm install" not in audit
    upgraded, audit = run_helper(tmp_path / "upgrade", "upgrade", helm_mode="present")
    assert upgraded.returncode == 0 and "helm upgrade" in audit
    rejected, audit = run_helper(tmp_path / "reject-upgrade", "upgrade", helm_mode="absent")
    assert rejected.returncode != 0 and "helm upgrade" not in audit


@pytest.mark.parametrize(("pvc_mode", "capability"), [("nonexpandable-20gi", "false"), ("expandable-mismatch", "true")])
def test_mutation_blocks_mismatched_existing_pvc_without_storage_changes(
    tmp_path, pvc_mode, capability
):
    result, audit = run_helper(
        tmp_path, "upgrade", helm_mode="present", pvc_mode=pvc_mode
    )
    assert result.returncode != 0
    assert "PVC migration required" in result.stderr
    assert "environment=staging claim=prometheus-db" in result.stderr
    assert "desired_request=128Gi storage_class=local-path" in result.stderr
    assert f"expansion_capability={capability}" in result.stderr
    assert "helm upgrade" not in audit
    assert not re.search(r"kubectl .*\b(?:patch|delete|apply|create)\b", audit)


def test_mutation_accepts_absent_or_converged_pvc(tmp_path):
    fresh, fresh_audit = run_helper(tmp_path / "fresh", "install", pvc_mode="absent")
    converged, converged_audit = run_helper(
        tmp_path / "converged", "upgrade", helm_mode="present", pvc_mode="converged"
    )
    assert fresh.returncode == 0 and "helm install" in fresh_audit
    assert "fresh-install path permitted" in fresh.stdout
    assert converged.returncode == 0 and "helm upgrade" in converged_audit
    assert "already matches ReadWriteOnce/local-path/128Gi" in converged.stdout


@pytest.mark.parametrize(
    "pvc_mode",
    [
        "absent",
        "discovery-fail",
        "ambiguous",
        "incomplete",
        "storageclass-fail",
        "storageclass-ambiguous",
    ],
)
def test_mutation_fails_closed_on_missing_or_ambiguous_pvc_discovery(tmp_path, pvc_mode):
    result, audit = run_helper(
        tmp_path, "upgrade", helm_mode="present", pvc_mode=pvc_mode
    )
    assert result.returncode != 0
    assert "PVC migration required" in result.stderr
    assert "expansion_capability=unknown" in result.stderr
    assert "helm upgrade" not in audit
    assert not re.search(r"kubectl .*\b(?:patch|delete|apply|create)\b", audit)


def test_converged_pvc_does_not_require_storageclass_expansion_discovery(tmp_path):
    result, audit = run_helper(
        tmp_path, "upgrade", helm_mode="present", pvc_mode="converged-storageclass-fail"
    )
    assert result.returncode == 0, result.stderr
    assert "helm upgrade" in audit
    assert "get storageclass" not in audit


@pytest.mark.parametrize(
    ("kubectl_mode", "success"),
    [("healthy", True), ("stale-retention", False)],
)
def test_verify_checks_effective_statefulset_retention_arguments(tmp_path, kubectl_mode, success):
    result, audit = run_helper(tmp_path, "verify", kubectl_mode=kubectl_mode)
    assert (result.returncode == 0) is success
    assert "rollout status statefulset/prometheus-kube-prometheus-stack-prometheus" in audit
    assert "get statefulset prometheus-kube-prometheus-stack-prometheus -o json" in audit
    if success:
        assert "retention.time=90d" not in result.stderr
    else:
        assert "--storage.tsdb.retention.time=90d" in result.stderr
        assert "--storage.tsdb.retention.size=100GB" in result.stderr


@pytest.mark.parametrize(
    ("command", "helm_mode", "env_name", "context"),
    [
        ("install", "absent", "staging", "sugar-staging"),
        ("upgrade", "present", "staging", "sugar-staging"),
        ("install", "absent", "prod", "sugar-prod"),
        ("upgrade", "present", "prod", "sugar-prod"),
    ],
)
def test_install_and_upgrade_dashboard_arguments(tmp_path, command, helm_mode, env_name, context):
    result, audit = run_helper(
        tmp_path,
        command,
        helm_mode=helm_mode,
        env_name=env_name,
        context=context,
    )

    assert result.returncode == 0, result.stderr
    mutation = next(line for line in audit.splitlines() if line.startswith(f"helm {command} "))
    env_values = PROD if env_name == "prod" else STAGING
    dashboard = PROD_DASHBOARD if env_name == "prod" else DASHBOARD
    dashboard_uid = (
        "sugarkube-prod-observability" if env_name == "prod" else "sugarkube-staging-observability"
    )
    other_values = STAGING if env_name == "prod" else PROD
    other_dashboard = DASHBOARD if env_name == "prod" else PROD_DASHBOARD
    other_dashboard_uid = (
        "sugarkube-staging-observability" if env_name == "prod" else "sugarkube-prod-observability"
    )

    assert mutation.index(f"-f {COMMON}") < mutation.index(f"-f {env_values}")
    assert f"--set-file grafana.dashboards.sugarkube.{dashboard_uid}.json={dashboard}" in mutation
    assert str(other_values) not in mutation
    assert str(other_dashboard) not in mutation
    assert f"grafana.dashboards.sugarkube.{other_dashboard_uid}.json" not in mutation

    overlay = str(tmp_path / "sugarkube-observability-rules.")
    if env_name == "staging":
        assert overlay in mutation
    else:
        assert overlay not in mutation
        assert str(CANONICAL_DSPACE_RULES) not in mutation
        assert str(CANONICAL_CLOUDFLARE_RULES) not in mutation


@pytest.mark.parametrize("mode", ["missing-pagerduty", "empty-pagerduty"])
@pytest.mark.parametrize(("command", "helm_mode"), [("install", "absent"), ("upgrade", "present")])
def test_mutation_requires_nonempty_pagerduty_secret_without_exposure(
    tmp_path, mode, command, helm_mode
):
    result, audit = run_helper(tmp_path, command, helm_mode=helm_mode, kubectl_mode=mode)
    assert result.returncode != 0
    assert f"helm {command}" not in audit
    assert "helm " not in audit
    assert "forbidden-secret-sentinel" not in result.stdout + result.stderr + audit
    assert "routing-key" in result.stderr
    assert (
        "value intentionally not read or printed" in result.stderr or "is absent" in result.stderr
    )


@pytest.mark.parametrize("mode", ["missing-watchdog", "empty-watchdog"])
@pytest.mark.parametrize(("command", "helm_mode"), [("install", "absent"), ("upgrade", "present")])
def test_mutation_requires_nonempty_watchdog_secret_without_helm_mutation(
    tmp_path, mode, command, helm_mode
):
    result, audit = run_helper(tmp_path, command, helm_mode=helm_mode, kubectl_mode=mode)
    assert result.returncode != 0
    assert "helm " not in audit
    assert "ping-url" in result.stderr
    assert "forbidden-secret-sentinel" not in result.stdout + result.stderr + audit


def test_render_is_offline_and_never_invokes_kubectl(tmp_path):
    result, audit = run_helper(tmp_path, "render", context="unavailable")
    assert result.returncode == 0, result.stderr
    assert "kubectl" not in audit
    assert "not queried: offline render" in result.stdout


def test_valid_pagerduty_secret_permits_helm_mutation(tmp_path):
    result, audit = run_helper(tmp_path, "upgrade", helm_mode="present")
    assert result.returncode == 0
    assert "helm upgrade" in audit
    assert "value intentionally not read or printed" in result.stdout


@pytest.mark.parametrize("mode", ["missing-pagerduty", "empty-pagerduty"])
def test_verify_requires_nonempty_pagerduty_secret_and_cleans_temp_files(tmp_path, mode):
    result, audit = run_helper(tmp_path, "verify", kubectl_mode=mode)
    assert result.returncode != 0
    assert "get secret alertmanager-pagerduty" in audit
    assert "routing-key" in result.stderr
    assert not list(tmp_path.glob("sugarkube-alertmanager-*.yaml"))


def test_verify_cleans_temp_files_when_live_validator_fails(tmp_path):
    result, _ = run_helper(tmp_path, "verify", kubectl_mode="malformed-alertmanager")
    assert result.returncode == 16
    assert "sensitive values not printed" in result.stderr
    assert not list(tmp_path.glob("sugarkube-alertmanager-*.yaml"))


def test_pagerduty_test_requires_explicit_action_and_staging(tmp_path):
    absent, audit = run_helper(tmp_path / "absent", "pagerduty-test")
    assert absent.returncode != 0 and "create --raw" not in audit
    invalid, audit = run_helper(tmp_path / "invalid", "pagerduty-test", action="page")
    assert invalid.returncode != 0 and "create --raw" not in audit
    production = subprocess.run(
        ["bash", str(SCRIPT), "pagerduty-test", "env=prod", "fire"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert production.returncode != 0
    mismatch, audit = run_helper(
        tmp_path / "mismatch", "pagerduty-test", context="other", action="action=fire"
    )
    assert mismatch.returncode != 0 and "create --raw" not in audit


def test_pagerduty_fire_and_resolve_share_labels_and_bound_end_times(tmp_path):
    fired, fire_audit = run_helper(tmp_path / "fire", "pagerduty-test", action="action=fire")
    resolved, resolve_audit = run_helper(
        tmp_path / "resolve", "pagerduty-test", action="action=resolve"
    )
    assert fired.returncode == resolved.returncode == 0
    for audit in (fire_audit, resolve_audit):
        assert "create --raw" not in audit
        assert (
            "port-forward --address=127.0.0.1 " "service/kube-prometheus-stack-alertmanager :9093"
        ) in audit
        assert "--noproxy *" in audit
        assert "--header Content-Type: application/json" in audit
        assert "--data-binary @" in audit
        assert "http://127.0.0.1:43128/api/v2/alerts" in audit
    fire = json.loads((tmp_path / "fire" / "alert-payload").read_text())[0]
    resolve = json.loads((tmp_path / "resolve" / "alert-payload").read_text())[0]
    expected = {
        "alertname": "SugarkubePagerDutyTest",
        "environment": "staging",
        "cluster": "sugarkube-int",
        "severity": "critical",
    }
    assert fire["labels"] == resolve["labels"] == expected
    from datetime import datetime

    fire_end = datetime.fromisoformat(fire["endsAt"].replace("Z", "+00:00"))
    resolve_end = datetime.fromisoformat(resolve["endsAt"].replace("Z", "+00:00"))
    assert 14 * 60 <= (fire_end - resolve_end).total_seconds() <= 16 * 60
    expected_annotations = {
        "summary": "Sugarkube staging PagerDuty delivery test",
        "description": (
            "Operator-triggered synthetic alert for the staging PagerDuty fire/resolve drill."
        ),
        "runbook_url": (
            "https://github.com/futuroptimist/sugarkube/blob/main/docs/"
            "observability-operations.md#pagerduty-staging-fire-and-resolve-runbook"
        ),
    }
    assert fire["annotations"] == resolve["annotations"] == expected_annotations
    assert fire["startsAt"] == resolve["startsAt"] == "2020-01-01T00:00:00Z"
    for directory in (tmp_path / "fire", tmp_path / "resolve"):
        assert (directory / "pagerduty.reaped").read_text().strip() == "reaped"
        assert not list(directory.glob("sugarkube-alertmanager-test.*"))


def test_pagerduty_cleanup_trap_remains_installed_before_port_forward_starts():
    script = SCRIPT.read_text(encoding="utf-8")
    pagerduty = script.split("pagerduty_test() (", 1)[1].split("\n)\n\ndashboard_verify()", 1)[0]
    start = pagerduty.index('kubectl -n "${NAMESPACE}" port-forward')
    assert "trap cleanup_pagerduty_test EXIT" in pagerduty[:start]
    assert "trap - EXIT" not in pagerduty


@pytest.mark.parametrize("action", ["fire", "resolve"])
def test_pagerduty_direct_bare_actions_remain_supported(tmp_path, action):
    result, audit = run_helper(tmp_path, "pagerduty-test", action=action)
    assert result.returncode == 0 and "curl " in audit and "create --raw" not in audit
    assert "RESPONSE_SENTINEL" not in result.stdout + result.stderr
    assert not list(tmp_path.glob("sugarkube-alertmanager-test.*"))


@pytest.mark.parametrize(
    "mode", ["transport", "http000", "http415", "http400", "http503", "malformed"]
)
def test_pagerduty_api_failure_is_redacted_and_cleans_response(tmp_path, mode):
    result, _ = run_helper(tmp_path, "pagerduty-test", action="action=fire", pagerduty_mode=mode)
    assert result.returncode == 18
    assert "response redacted" in result.stderr
    assert "RESPONSE_SENTINEL" not in result.stdout + result.stderr
    assert "CURL_RESPONSE_SENTINEL" not in result.stdout + result.stderr
    forward_pid = (tmp_path / "pagerduty.pid").read_text().strip()
    assert not Path(f"/proc/{forward_pid}").exists()
    assert not list(tmp_path.glob("sugarkube-alertmanager-test.*"))


def test_pagerduty_rejects_port_forward_exit_during_submission(tmp_path):
    result, audit = run_helper(
        tmp_path,
        "pagerduty-test",
        action="fire",
        pagerduty_mode="forward-exit-during-curl",
    )
    assert result.returncode == 19 and "curl " in audit
    assert "diagnostics redacted" in result.stderr
    forward_pid = (tmp_path / "pagerduty.pid").read_text().strip()
    assert not Path(f"/proc/{forward_pid}").exists()
    assert not list(tmp_path.glob("sugarkube-alertmanager-test.*"))


@pytest.mark.parametrize(
    ("mode", "line"),
    [
        ("forward-exit", "Forwarding from 127.0.0.1:43128 -> 9093"),
        ("success", ""),
        ("success", "Forwarding from 127.0.0.1:43128 -> 9094"),
        ("success", "Forwarding from 0.0.0.0:43128 -> 9093"),
        ("success", "noise Forwarding from 127.0.0.1:43128 -> 9093"),
    ],
)
def test_pagerduty_port_forward_failures_are_redacted_and_cleaned(tmp_path, mode, line):
    result, audit = run_helper(
        tmp_path,
        "pagerduty-test",
        action="fire",
        pagerduty_mode=mode,
        pagerduty_forward_line=line,
    )
    assert result.returncode == 19
    assert "curl " not in audit
    assert "PORT_FORWARD_SENTINEL" not in result.stdout + result.stderr
    assert not line or line not in result.stdout + result.stderr
    if (tmp_path / "pagerduty.pid").exists():
        assert (tmp_path / "pagerduty.reaped").read_text().strip() == "reaped"
        assert not Path(f"/proc/{(tmp_path / 'pagerduty.pid').read_text().strip()}").exists()
    assert not list(tmp_path.glob("sugarkube-alertmanager-test.*"))


def test_status_requires_staging_identity(tmp_path):
    result, audit = run_helper(tmp_path, "status", context="other")
    assert result.returncode != 0 and "helm -n monitoring status" not in audit


def target_response(*targets, status="success"):
    return json.dumps({"status": status, "data": {"activeTargets": list(targets)}})


def dspace_target(health, *, pod="dspace-0", error="", scrape="2026-07-25T12:00:00Z"):
    return {
        "labels": {
            "app": "dspace",
            "namespace": "dspace",
            "pod": pod,
            "instance": "10.0.0.1:3000",
        },
        "health": health,
        "lastError": error,
        "lastScrape": scrape,
    }


def test_verify_exact_three_nodes_secret_reference_and_first_observation_health(tmp_path):
    healthy, audit = run_helper(tmp_path / "healthy", "verify")
    assert (
        healthy.returncode == 0
        and "get --request-timeout=" in audit
        and "ms --raw /api/v1/namespaces/monitoring/services/http:" in audit
    )
    assert audit.count(" --raw ") == 1
    assert "sleep " not in audit
    for mode in ("two-nodes", "wrong-release", "missing-secret-ref", "missing-secret"):
        result, _ = run_helper(tmp_path / mode, "verify", kubectl_mode=mode)
        assert result.returncode != 0, mode


def test_verify_retries_empty_unknown_and_mixed_then_accepts_one_target(tmp_path):
    responses = [
        target_response(),
        target_response(dspace_target("unknown")),
        target_response(dspace_target("up"), dspace_target("down", pod="dspace-1")),
        target_response(dspace_target("up")),
    ]
    result, audit = run_helper(
        tmp_path, "verify", target_responses=responses, retry_attempts="4", retry_interval="7"
    )
    assert result.returncode == 0
    assert audit.count(" --raw ") == 4
    assert audit.count("sleep ") == 3
    assert result.stderr.count("targets are converging") == 3


def test_verify_accepts_multiple_healthy_targets(tmp_path):
    response = target_response(dspace_target("up"), dspace_target("up", pod="dspace-1"))
    result, audit = run_helper(tmp_path, "verify", target_responses=[response])
    assert result.returncode == 0
    assert audit.count(" --raw ") == 1


def test_verify_empty_targets_time_out_without_vacuous_success(tmp_path):
    result, audit = run_helper(tmp_path, "verify", target_responses=[target_response()] * 3)
    assert result.returncode != 0
    assert audit.count(" --raw ") == 3
    assert audit.count("sleep ") == 2
    assert "no matching targets discovered" in result.stderr


def test_verify_mixed_targets_time_out_with_safe_diagnostics(tmp_path):
    response = target_response(
        dspace_target("up"),
        dspace_target("down", pod="dspace-1", error="connection refused"),
    )
    result, audit = run_helper(tmp_path, "verify", target_responses=[response] * 3)
    assert result.returncode != 0
    assert audit.count(" --raw ") == 3 and audit.count("sleep ") == 2
    safe_values = (
        "dspace-1",
        "down",
        "lastScrape",
        '"instance": "<redacted>"',
        '"lastError": "<redacted>"',
    )
    for value in safe_values:
        assert value in result.stderr
    assert "connection refused" not in result.stderr
    assert "10.0.0.1:3000" not in result.stderr
    assert "dspace-token" not in result.stderr
    assert '"app": "dspace"' not in result.stderr
    assert "activeTargets" not in result.stderr


def test_verify_diagnostics_only_emit_sanitized_scalar_strings(tmp_path):
    markers = (
        "Bear" + "er",
        "Authoriz" + "ation",
        "to" + "ken=",
        "sec" + "ret:",
        "pass" + "word=",
    )
    targets = [
        dspace_target(
            "down", pod=f"{marker} POD_SENTINEL_{index}", scrape=f"{marker} SCRAPE_SENTINEL_{index}"
        )
        for index, marker in enumerate(markers)
    ]
    targets[0]["lastError"] = "Bearer ERROR_SECRET_SENTINEL"
    targets[0]["labels"]["authorization"] = "NESTED_SECRET_SENTINEL"
    targets[0]["labels"]["instance"] = {"raw": "INSTANCE_SECRET_SENTINEL"}
    response = target_response(*targets)
    result, _ = run_helper(tmp_path, "verify", target_responses=[response] * 3)
    assert result.returncode != 0
    assert result.stderr.count('"<redacted>"') >= 10 and '"health": "down"' in result.stderr
    for forbidden in (
        "POD_SENTINEL",
        "SCRAPE_SENTINEL",
        "ERROR_SECRET_SENTINEL",
        "NESTED_SECRET_SENTINEL",
        "INSTANCE_SECRET_SENTINEL",
        "authorization",
        "activeTargets",
        "Traceback",
        "raw",
    ):
        assert forbidden not in result.stderr


def test_verify_api_and_parsing_failures_are_immediate(tmp_path):
    cases = {
        "transport": ("query-fail", None, "kubectl could not query"),
        "malformed": ("healthy", ["not-json"], "malformed JSON"),
        "encoding": ("healthy", [b'{"status":"success","bad":"\xff"}'], "not valid UTF-8"),
        "api": ("healthy", [target_response(status="error")], "query was unsuccessful"),
        "structure": (
            "healthy",
            [json.dumps({"status": "success", "data": {}})],
            "invalid data structure",
        ),
    }
    for name, (mode, responses, message) in cases.items():
        result, audit = run_helper(
            tmp_path / name, "verify", kubectl_mode=mode, target_responses=responses
        )
        assert result.returncode != 0
        assert audit.count(" --raw ") == 1
        assert "sleep " not in audit
        assert message in result.stderr


def test_verify_missing_and_non_string_health_fail_immediately(tmp_path):
    matching = {"labels": {"app": "dspace", "namespace": "dspace"}}
    for name, value in (("missing", None), ("object", {"state": "up"})):
        target = dict(matching)
        if name != "missing":
            target["health"] = value
        result, audit = run_helper(
            tmp_path / name, "verify", target_responses=[target_response(target)]
        )
        assert result.returncode != 0
        assert audit.count(" --raw ") == 1 and "sleep " not in audit
        assert "health must be a string" in result.stderr and "Traceback" not in result.stderr


def test_verify_invalid_retry_configuration_fails_before_polling(tmp_path):
    for name, attempts, interval in (("attempts", "0", "1"), ("interval", "3", "nope")):
        result, audit = run_helper(
            tmp_path / name,
            "verify",
            retry_attempts=attempts,
            retry_interval=interval,
        )
        assert result.returncode != 0
        assert "positive integer" in result.stderr
        assert " --raw " not in audit


def test_verify_treats_leading_zero_retry_configuration_as_decimal(tmp_path):
    result, audit = run_helper(
        tmp_path,
        "verify",
        target_responses=[target_response()] * 8,
        retry_attempts="08",
        retry_interval="01",
    )
    assert result.returncode != 0
    assert audit.count("get --request-timeout=") == 8
    assert audit.count("sleep ") == 7


def test_verify_request_budget_and_default_deadline_are_derived_from_retry_controls(tmp_path):
    result, audit = run_helper(
        tmp_path,
        "verify",
        target_responses=[target_response()] * 20,
        retry_attempts="20",
        retry_interval="15",
    )
    assert result.returncode != 0
    assert audit.count("get --request-timeout=14000ms --raw ") == 20
    assert audit.count("sleep ") == 19
    assert (20 - 1) * 15 + (15 - 1) == 299


def test_verify_request_duration_reduces_cadence_delay(tmp_path):
    result, audit = run_helper(
        tmp_path,
        "verify",
        target_responses=[target_response(), target_response(dspace_target("up"))],
        retry_attempts="2",
        retry_interval="1",
        target_response_delay="0.2",
    )
    assert result.returncode == 0
    delay = float(re.search(r"sleep ([0-9.]+)", audit).group(1))
    assert 0 < delay < 0.9


def test_verify_deadline_uses_latest_safe_diagnostics_without_extra_request(tmp_path):
    target = dspace_target("down", pod="dspace-safe")
    result, audit = run_helper(
        tmp_path,
        "verify",
        target_responses=[target_response(target)],
        retry_attempts="1",
        retry_interval="1",
        target_response_delay="1.05",
    )
    assert result.returncode != 0 and audit.count(" --raw ") == 1
    assert '"pod": "dspace-safe"' in result.stderr and '"health": "down"' in result.stderr
    assert "activeTargets" not in result.stderr and "Traceback" not in result.stderr


def run_dashboard_verifier(
    tmp_path,
    mode="success",
    context="sugar-staging",
    forward_line="Forwarding from 127.0.0.1:43127 -> 3000",
    env_name="staging",
):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(parents=True)
    audit = tmp_path / "audit"
    pid_file = tmp_path / "port-forward.terminated"
    (bin_dir / "kubectl").write_text(
        """#!/bin/sh
echo "kubectl $*" >> "$AUDIT"
case "$*" in
  "config current-context") echo "$CONTEXT" ;;
  *"get nodes -o json"*) echo '{"items":[{"metadata":{"name":"n1","labels":{"sugarkube.env":"'"$ENV_NAME"'","sugarkube.cluster":"sugar-'"$ENV_NAME"'"}}}]}' ;;
  *"get secret grafana-admin-credentials"*"admin-user"*)
    [ "$MODE" != forward-exits-after-ready ] || { touch "$READY_SECRET"; /bin/sleep 0.2; }
    [ "$MODE" != secret-missing ] || exit 41
    [ "$MODE" != secret-malformed ] || { printf not-base64; exit; }
    printf admin | base64 ;;
  *"get secret grafana-admin-credentials"*"admin-pass""word"*) printf placeholder | base64 ;;
  *"port-forward"*)
    [ "$MODE" != forward-fail ] || exit 42
    echo "$FORWARD_LINE"
    echo $$ > "$FORWARD_PID"
    trap 'echo terminated > "$PID_FILE"; exit 0' TERM INT
    if [ "$MODE" = forward-exits-after-ready ]; then
      while [ ! -f "$READY_SECRET" ]; do /bin/sleep 0.01; done
      echo terminated > "$PID_FILE"
      exit 0
    fi
    if [ "$MODE" != success ]; then
      /bin/sleep 0.2
      echo terminated > "$PID_FILE"
      exit 0
    fi
    while :; do /bin/sleep 1; done
    ;;
esac
""",
        encoding="utf-8",
    )
    (bin_dir / "curl").write_text(
        """#!/bin/sh
echo "curl $*" >> "$AUDIT"
case "$*" in *"http://127.0.0.1:43127/"*) ;; *) exit 51 ;; esac
[ -f "$TMPDIR"/sugarkube-grafana-verify.*/netrc ] || exit 52
[ "$MODE" = success ] || /bin/sleep 0.3
case "$MODE" in
  auth401) printf '%s\n%s\n' '{"message":"redacted"}' 401 ;;
  auth403) printf '%s\n%s\n' '{"message":"redacted"}' 403 ;;
  malformed-api) printf '%s\n%s\n' '{' 200 ;;
  wrong-api) printf '%s\n%s\n' '{"dashboard":{"uid":"wrong","title":"wrong"}}' 200 ;;
  interrupt) exit 143 ;;
  *) printf '%s\n%s\n' "$DASHBOARD_RESPONSE" 200 ;;
esac
""",
        encoding="utf-8",
    )
    for stub in bin_dir.iterdir():
        stub.chmod(0o755)
    (bin_dir / "sleep").write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    (bin_dir / "sleep").chmod(0o755)
    env = os.environ | {
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "AUDIT": str(audit),
        "MODE": mode,
        "CONTEXT": context,
        "ENV_NAME": env_name,
        "DASHBOARD_RESPONSE": json.dumps({"dashboard": {
            "uid": "sugarkube-prod-observability" if env_name == "prod" else "sugarkube-staging-observability",
            "title": "Sugarkube Production Observability" if env_name == "prod" else "Sugarkube Staging Observability",
        }}),
        "PID_FILE": str(pid_file),
        "FORWARD_PID": str(tmp_path / "port-forward.pid"),
        "FORWARD_LINE": forward_line,
        "READY_SECRET": str(tmp_path / "secret-requested"),
        "TMPDIR": str(tmp_path),
        "KUBECONFIG": str(tmp_path / "kubeconfig"),
    }
    result = subprocess.run(
        ["bash", str(SCRIPT), "dashboard-verify", f"env={env_name}"],
        env=env,
        capture_output=True,
        text=True,
        start_new_session=True,
    )
    return result, audit.read_text() if audit.exists() else "", pid_file


def test_production_dashboard_verifier_uses_production_identity_and_redacts(tmp_path):
    result, audit, _ = run_dashboard_verifier(
        tmp_path, context="sugar-prod", env_name="prod"
    )
    assert result.returncode == 0, result.stderr
    assert "/api/dashboards/uid/sugarkube-prod-observability" in audit
    assert "Sugarkube Production Observability" not in audit
    assert "placeholder" not in result.stdout + result.stderr


def test_dashboard_verifier_runtime_owns_port_and_cleans_up(tmp_path):
    result, audit, pid_file = run_dashboard_verifier(tmp_path)
    assert result.returncode == 0, result.stderr
    assert "port-forward --address=127.0.0.1" in audit
    assert audit.index("port-forward") < audit.index("get secret") < audit.index("curl ")
    assert "http://127.0.0.1:43127/" in audit
    assert not list(tmp_path.glob("sugarkube-grafana-verify.*"))
    assert pid_file.read_text(encoding="utf-8").strip() == "terminated"


@pytest.mark.parametrize("remote_port", ["3000", "12345", "80"])
def test_dashboard_verifier_accepts_resolved_remote_port(tmp_path, remote_port):
    result, audit, _ = run_dashboard_verifier(
        tmp_path, forward_line=f"Forwarding from 127.0.0.1:43127 -> {remote_port}"
    )
    assert result.returncode == 0, result.stderr
    assert "get secret" in audit


@pytest.mark.parametrize(
    "forward_line",
    [
        "Forwarding from 127.0.0.1:0 -> 3000",
        "Forwarding from 127.0.0.1:65536 -> 3000",
        "Forwarding from 127.0.0.1:43127 -> 0",
        "Forwarding from 127.0.0.1:43127 -> 65536",
        "Forwarding from 0.0.0.0:43127 -> 3000",
        "Forwarding from [::1]:43127 -> 3000",
        "Forwarding from localhost:43127 -> 3000",
        "Forwarding from 127.0.0.1:43127 ->",
        "noise Forwarding from 127.0.0.1:43127 -> 3000",
        "Forwarding from 127.0.0.1:43127 -> 3000 noise",
    ],
)
def test_dashboard_verifier_rejects_invalid_forwarding_lines_before_secret_access(
    tmp_path, forward_line
):
    result, audit, _ = run_dashboard_verifier(tmp_path, forward_line=forward_line)
    assert result.returncode != 0
    assert "get secret" not in audit
    assert "curl " not in audit
    assert forward_line not in result.stdout + result.stderr
    assert not list(tmp_path.glob("sugarkube-grafana-verify.*"))


def test_dashboard_verifier_checks_context_before_secret_access(tmp_path):
    result, audit, _ = run_dashboard_verifier(tmp_path, context="wrong-context")
    assert result.returncode != 0
    assert "get secret" not in audit


def test_dashboard_verifier_rejects_missing_and_malformed_credentials(tmp_path):
    for mode in ("secret-missing", "secret-malformed"):
        result, audit, _ = run_dashboard_verifier(tmp_path / mode, mode)
        assert result.returncode != 0
        assert audit.index("port-forward") < audit.index("get secret")
        assert "curl " not in audit
        assert "placeholder" not in result.stdout + result.stderr


def test_dashboard_verifier_port_forward_failure_never_authenticates(tmp_path):
    failed, audit, _ = run_dashboard_verifier(tmp_path / "forward", "forward-fail")
    assert failed.returncode != 0 and "curl " not in audit
    assert not list((tmp_path / "forward").glob("sugarkube-grafana-verify.*"))


def test_dashboard_verifier_rejects_forward_exit_after_readiness(tmp_path):
    result, audit, pid_file = run_dashboard_verifier(tmp_path, "forward-exits-after-ready")
    assert result.returncode != 0
    assert audit.index("port-forward") < audit.index("get secret")
    assert "curl " not in audit
    assert pid_file.read_text(encoding="utf-8").strip() == "terminated"
    forward_pid = int((tmp_path / "port-forward.pid").read_text(encoding="utf-8"))
    assert not Path(f"/proc/{forward_pid}").exists()
    assert not list(tmp_path.glob("sugarkube-grafana-verify.*"))


def test_dashboard_verifier_auth_failures_are_immediate_and_redacted(tmp_path):
    for mode in ("auth401", "auth403"):
        result, audit, _ = run_dashboard_verifier(tmp_path / mode, mode)
        assert result.returncode != 0 and audit.count("curl ") == 1
        assert "redacted" in result.stderr and "placeholder" not in result.stdout + result.stderr
        assert not list((tmp_path / mode).glob("sugarkube-grafana-verify.*"))


def test_dashboard_verifier_rejects_incorrect_and_malformed_api_json(tmp_path):
    for mode in ("wrong-api", "malformed-api"):
        result, _, _ = run_dashboard_verifier(tmp_path / mode, mode)
        assert result.returncode != 0
        assert "response redacted" in result.stderr
        assert not list((tmp_path / mode).glob("sugarkube-grafana-verify.*"))


def test_dashboard_verifier_cleans_up_when_interrupted(tmp_path):
    result, audit, _ = run_dashboard_verifier(tmp_path, "interrupt")
    assert result.returncode != 0 and "curl " in audit
    body = SCRIPT.read_text(encoding="utf-8").split("dashboard_verify()", 1)[1]
    assert "trap 'exit 130' INT" in body and "trap 'exit 143' TERM" in body
    assert not list(tmp_path.glob("sugarkube-grafana-verify.*"))


def test_watchdog_rule_and_healthchecks_contract_are_exact():
    staging = yaml_load(STAGING)
    group = staging["additionalPrometheusRulesMap"]["sugarkube-observability-watchdog"]["groups"][0]
    assert group["interval"] == "1m"
    assert group["rules"] == [
        {
            "alert": "SugarkubeObservabilityWatchdog",
            "expr": "vector(1)",
            "labels": {
                "environment": "staging",
                "cluster": "sugarkube-int",
                "purpose": "observability-watchdog",
            },
            "annotations": {
                "summary": "Sugarkube staging observability watchdog",
                "runbook_url": "https://github.com/futuroptimist/sugarkube/blob/main/docs/observability-operations.md#observability-watchdog",
            },
        }
    ]
    webhook = staging["alertmanager"]["config"]["receivers"][3]["webhook_configs"][0]
    assert webhook == {
        "url_file": "/etc/alertmanager/secrets/alertmanager-healthchecks-watchdog/ping-url",
        "send_resolved": False,
        "max_alerts": 1,
        "timeout": "10s",
    }
    assert "url" not in webhook


def test_watchdog_operator_contract_is_hidden_bounded_and_staging_only():
    script = SCRIPT.read_text(encoding="utf-8")
    assert "[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}" in script
    assert "read -r -s value <&3" in script
    assert "--from-file=ping-url=/dev/stdin" in script
    assert "WATCHDOG_PING_URL" in script
    assert "timedelta(minutes=8)" in script
    for label in ("alertname", "environment", "cluster", "purpose"):
        assert f'("{label}"' in script
    assert "sugar-staging" in script
    assert "node shutdown" not in script.lower()
    assert "hc-ping\\.com" in script


def test_watchdog_secret_install_uses_hidden_tty_and_stdin_only_kubernetes(tmp_path):
    url, uuid = watchdog_canary()
    result, audit = run_helper(tmp_path, "watchdog-secret-install", watchdog_tty_text=url + "\n")

    assert result.returncode == 0, result.stderr
    assert "create secret generic alertmanager-healthchecks-watchdog" in audit
    assert "--from-file=ping-url=/dev/stdin --dry-run=client -o yaml" in audit
    assert "apply -f -" in audit
    assert (tmp_path / "watchdog-create-stdin").read_text(encoding="utf-8") == url
    manifest = (tmp_path / "watchdog-apply-stdin").read_text(encoding="utf-8")
    assert "kind: Secret" in manifest
    assert "name: alertmanager-healthchecks-watchdog" in manifest

    public = result.stdout + result.stderr + audit + manifest
    assert url not in public and uuid not in public
    expected_secret_files = {"watchdog-tty", "watchdog-create-stdin"}
    unexpected_files = [
        path
        for path in tmp_path.rglob("*")
        if path.is_file() and path.name not in expected_secret_files
    ]
    assert all(
        url not in path.read_text(encoding="utf-8", errors="replace")
        and uuid not in path.read_text(encoding="utf-8", errors="replace")
        for path in unexpected_files
    )


@pytest.mark.parametrize(
    "variation",
    [
        "unhyphenated-uuid",
        "nonhex-uuid",
        "wrong-scheme",
        "wrong-host",
        "suffix",
        "query",
        "fragment",
    ],
)
def test_watchdog_secret_install_rejects_noncanonical_urls_before_mutation(tmp_path, variation):
    url, uuid = watchdog_canary()
    values = {
        "unhyphenated-uuid": url.replace(uuid, uuid.replace("-", "")),
        "nonhex-uuid": url[:-1] + "z",
        "wrong-scheme": url.replace("https://", "http://"),
        "wrong-host": url.replace("hc-ping.com", "example.invalid"),
        "suffix": url + "/fail",
        "query": url + "?next=1",
        "fragment": url + "#fragment",
    }
    value = values[variation]
    result, audit = run_helper(tmp_path, "watchdog-secret-install", watchdog_tty_text=value + "\n")

    assert result.returncode != 0
    assert "create secret" not in audit and "apply -f -" not in audit
    assert value not in result.stdout + result.stderr + audit


@pytest.mark.parametrize(
    "variable",
    ["HEALTHCHECKS_PING_URL", "HEALTHCHECK_PING_URL", "PING_URL", "WATCHDOG_PING_URL"],
)
def test_watchdog_secret_install_refuses_credential_environment_before_mutation(tmp_path, variable):
    url, uuid = watchdog_canary()
    result, audit = run_helper(
        tmp_path,
        "watchdog-secret-install",
        watchdog_tty_text=url + "\n",
        extra_env={variable: url},
    )

    assert result.returncode != 0
    assert "environment variables are refused" in result.stderr
    assert "create secret" not in audit and "apply -f -" not in audit
    assert url not in result.stdout + result.stderr + audit
    assert uuid not in result.stdout + result.stderr + audit


def test_watchdog_secret_install_refuses_credential_argument_before_mutation(tmp_path):
    url, uuid = watchdog_canary()
    result, audit = run_helper(
        tmp_path,
        "watchdog-secret-install",
        watchdog_tty_text=url + "\n",
        command_args=(url,),
    )

    assert result.returncode != 0
    assert "credential arguments are refused" in result.stderr
    assert "create secret" not in audit and "apply -f -" not in audit
    assert url not in result.stdout + result.stderr + audit
    assert uuid not in result.stdout + result.stderr + audit


@pytest.mark.parametrize(
    ("context", "mode"),
    [("another-context", "healthy"), ("sugar-staging", "watchdog-cluster-mismatch")],
)
def test_watchdog_secret_install_staging_mismatch_prevents_mutation(tmp_path, context, mode):
    url, _ = watchdog_canary()
    result, audit = run_helper(
        tmp_path,
        "watchdog-secret-install",
        context=context,
        kubectl_mode=mode,
        watchdog_tty_text=url + "\n",
    )

    assert result.returncode != 0
    assert "create secret" not in audit and "apply -f -" not in audit
    assert url not in result.stdout + result.stderr + audit


@pytest.mark.parametrize("mode", ["watchdog-create-fail", "watchdog-apply-fail"])
def test_watchdog_secret_install_kubernetes_failures_are_sanitized(tmp_path, mode):
    url, uuid = watchdog_canary()
    result, audit = run_helper(
        tmp_path,
        "watchdog-secret-install",
        kubectl_mode=mode,
        watchdog_tty_text=url + "\n",
    )

    assert result.returncode != 0
    assert "installation failed" in result.stderr
    assert "value redacted" in result.stderr
    assert url not in result.stdout + result.stderr + audit
    assert uuid not in result.stdout + result.stderr + audit


def test_watchdog_secret_check_reads_only_the_key_contract(tmp_path):
    result, audit = run_helper(tmp_path, "watchdog-secret-check")

    assert result.returncode == 0, result.stderr
    assert "get secret alertmanager-healthchecks-watchdog -o go-template=" in audit
    assert "ping-url" in audit
    assert "value intentionally not read or printed" in result.stdout
    assert not (tmp_path / "watchdog-create-stdin").exists()
    assert "apply -f -" not in audit


@pytest.mark.parametrize("mode", ["missing-watchdog", "empty-watchdog"])
def test_watchdog_secret_check_rejects_missing_or_empty_ping_url(tmp_path, mode):
    result, audit = run_helper(tmp_path, "watchdog-secret-check", kubectl_mode=mode)

    assert result.returncode != 0
    assert "ping-url" in result.stderr
    assert "create secret" not in audit and "apply -f -" not in audit


def test_watchdog_live_check_accepts_exact_rule_labels_and_external_alert_labels(tmp_path):
    result, audit = run_helper(tmp_path, "watchdog-verify")

    assert result.returncode == 0, result.stderr
    assert "bounded repeat observation verified" in result.stdout
    assert "proxy/api/v1/rules" in audit
    assert "/api/v2/alerts" in audit
    assert "get pods -l app.kubernetes.io/name=alertmanager -o json" in audit
    assert "logs pod/alertmanager-kube-prometheus-stack-alertmanager-0 -c alertmanager" in audit
    assert "statefulset/kube-prometheus-stack-alertmanager" not in audit
    assert not list(tmp_path.glob("sugarkube-watchdog-verify.*"))


def test_watchdog_live_check_inspects_every_matching_operator_pod(tmp_path):
    result, audit = run_helper(tmp_path, "watchdog-verify", kubectl_mode="watchdog-multiple-pods")

    assert result.returncode == 0, result.stderr
    assert audit.count(" -c alertmanager ") == 2
    assert "logs pod/alertmanager-kube-prometheus-stack-alertmanager-0" in audit
    assert "logs pod/alertmanager-kube-prometheus-stack-alertmanager-1" in audit
    assert "statefulset/kube-prometheus-stack-alertmanager" not in audit


@pytest.mark.parametrize("mode", ["watchdog-no-pods", "watchdog-unrelated-pod"])
def test_watchdog_live_check_fails_closed_without_matching_resource_pods(tmp_path, mode):
    result, audit = run_helper(tmp_path, "watchdog-verify", kubectl_mode=mode)

    assert result.returncode != 0
    assert "no operator-managed Alertmanager pods matched the expected resource" in result.stderr
    assert " logs " not in audit
    assert "POD_FIXTURE_SENTINEL" not in result.stdout + result.stderr + audit
    assert not list(tmp_path.glob("sugarkube-watchdog-verify.*"))


@pytest.mark.parametrize(
    "mode",
    [
        "watchdog-malformed-pods",
        "watchdog-malformed-metadata",
        "watchdog-malformed-labels",
        "watchdog-malformed-name",
        "watchdog-malformed-status",
        "watchdog-malformed-spec",
        "watchdog-malformed-volumes",
        "watchdog-malformed-volume",
        "watchdog-malformed-containers",
        "watchdog-malformed-container",
        "watchdog-malformed-mounts",
        "watchdog-malformed-mount",
    ],
)
def test_watchdog_live_check_fails_closed_on_malformed_pod_inventory(tmp_path, mode):
    result, audit = run_helper(tmp_path, "watchdog-verify", kubectl_mode=mode)

    assert result.returncode != 0
    assert "pod data is malformed (response redacted)" in result.stderr
    exposed = result.stdout + result.stderr + audit
    assert "Traceback" not in exposed
    assert "PRIVATE_MALFORMED_POD_FIXTURE" not in exposed
    assert "fixture.invalid" not in exposed
    assert "credential@example" not in exposed
    assert not list(tmp_path.glob("sugarkube-watchdog-verify.*"))


def test_watchdog_live_check_rejects_extra_rule_label_without_printing_payload(tmp_path):
    result, _ = run_helper(tmp_path, "watchdog-verify", kubectl_mode="watchdog-extra-rule-label")

    assert result.returncode != 0
    assert "required labels" in result.stderr
    assert "REJECTED_RULE_PAYLOAD_SENTINEL" not in result.stdout + result.stderr


@pytest.mark.parametrize(
    "mode",
    [
        "watchdog-pod-not-running",
        "watchdog-missing-volume",
        "watchdog-wrong-secret-volume",
        "watchdog-missing-mount",
        "watchdog-wrong-mount-path",
        "watchdog-mount-not-readonly",
    ],
)
def test_watchdog_mount_contract_fails_closed_and_redacts_pod_data(tmp_path, mode):
    result, _ = run_helper(tmp_path, "watchdog-verify", kubectl_mode=mode)

    assert result.returncode != 0
    assert "running Alertmanager pods do not have the exact watchdog Secret mount" in result.stderr
    assert "POD_FIXTURE_SENTINEL" not in result.stdout + result.stderr


@pytest.mark.parametrize(
    ("receiver", "diagnostic"),
    [
        (receiver, diagnostic)
        for receiver in (
            "healthchecks-watchdog",
            "alertmanager-healthchecks-watchdog",
        )
        for diagnostic in ("error", "failed", "failure", "timeout", "refused")
    ],
)
def test_watchdog_delivery_errors_attributable_to_receiver_fail_closed(
    tmp_path, receiver, diagnostic
):
    private_log = f"{receiver} delivery {diagnostic} LOG_FIXTURE_SENTINEL"
    result, _ = run_helper(tmp_path, "watchdog-verify", watchdog_log_text=private_log)

    assert result.returncode != 0
    assert "watchdog receiver delivery error observed" in result.stderr
    assert private_log not in result.stdout + result.stderr
    assert "LOG_FIXTURE_SENTINEL" not in result.stdout + result.stderr


def test_watchdog_delivery_ignores_unrelated_alertmanager_errors(tmp_path):
    private_log = "error loading unrelated template LOG_FIXTURE_SENTINEL"
    result, _ = run_helper(tmp_path, "watchdog-verify", watchdog_log_text=private_log)

    assert result.returncode == 0, result.stderr
    assert "bounded repeat observation verified" in result.stdout
    assert private_log not in result.stdout + result.stderr


def test_watchdog_delivery_does_not_join_separate_pod_logs(tmp_path):
    result, _ = run_helper(
        tmp_path,
        "watchdog-verify",
        kubectl_mode="watchdog-multiple-pods",
        extra_env={
            "WATCHDOG_LOG_TEXT_0": "healthchecks-watchdog",
            "WATCHDOG_LOG_TEXT_1": "error LOG_FIXTURE_SENTINEL",
        },
    )

    assert result.returncode == 0, result.stderr
    assert "bounded repeat observation verified" in result.stdout
    assert "LOG_FIXTURE_SENTINEL" not in result.stdout + result.stderr
    assert not list(tmp_path.glob("sugarkube-watchdog-verify.*"))


def test_watchdog_delivery_same_pod_receiver_error_still_fails(tmp_path):
    private_log = "healthchecks-watchdog error LOG_FIXTURE_SENTINEL"
    result, _ = run_helper(
        tmp_path,
        "watchdog-verify",
        kubectl_mode="watchdog-multiple-pods",
        extra_env={"WATCHDOG_LOG_TEXT_0": private_log, "WATCHDOG_LOG_TEXT_1": "healthy"},
    )

    assert result.returncode != 0
    assert "watchdog receiver delivery error observed" in result.stderr
    assert private_log not in result.stdout + result.stderr
    assert not list(tmp_path.glob("sugarkube-watchdog-verify.*"))


def test_watchdog_delivery_log_retrieval_failure_is_sanitized(tmp_path):
    result, _ = run_helper(tmp_path, "watchdog-verify", kubectl_mode="watchdog-logs-fail")

    assert result.returncode != 0
    assert "Alertmanager logs could not be retrieved (details redacted)" in result.stderr
    assert "PRIVATE_LOG_RETRIEVAL_SENTINEL" not in result.stdout + result.stderr


def test_watchdog_delivery_one_of_multiple_log_retrievals_fails_closed(tmp_path):
    result, audit = run_helper(
        tmp_path, "watchdog-verify", kubectl_mode="watchdog-second-log-fails"
    )

    assert result.returncode != 0
    assert audit.count(" -c alertmanager ") == 2
    assert "Alertmanager logs could not be retrieved (details redacted)" in result.stderr
    assert "PRIVATE_LOG_RETRIEVAL_SENTINEL" not in result.stdout + result.stderr
    assert not list(tmp_path.glob("sugarkube-watchdog-verify.*"))


def watchdog_silence_fixture():
    matchers = [
        {
            "name": "alertname",
            "value": "SugarkubeObservabilityWatchdog",
            "isRegex": False,
            "isEqual": True,
        },
        {"name": "environment", "value": "staging", "isRegex": False, "isEqual": True},
        {"name": "cluster", "value": "sugarkube-int", "isRegex": False, "isEqual": True},
        {
            "name": "purpose",
            "value": "observability-watchdog",
            "isRegex": False,
            "isEqual": True,
        },
    ]

    def silence(
        identifier,
        state,
        *,
        created_by="sugarkube-observability-watchdog-drill",
        comment="Owned staging watchdog failure drill",
        selected_matchers=None,
    ):
        return {
            "id": identifier,
            "status": {"state": state},
            "createdBy": created_by,
            "comment": comment,
            "matchers": matchers if selected_matchers is None else selected_matchers,
            "fixtureDetail": f"private-detail-{identifier}",
        }

    return [
        silence("owned-active", "active"),
        silence("owned-pending", "pending"),
        silence(
            "owned-legacy",
            "active",
            selected_matchers=[
                {key: value for key, value in matcher.items() if key != "isEqual"}
                for matcher in matchers
            ],
        ),
        silence("owned-expired", "expired"),
        silence("foreign-author", "active", created_by="another-operator"),
        silence("foreign-comment", "active", comment="another drill"),
        silence(
            "regex-matcher",
            "active",
            selected_matchers=[matchers[0] | {"isRegex": True}, *matchers[1:]],
        ),
        silence(
            "unequal-matcher",
            "active",
            selected_matchers=[matchers[0] | {"isEqual": False}, *matchers[1:]],
        ),
        silence(
            "string-equality-matcher",
            "active",
            selected_matchers=[matchers[0] | {"isEqual": "true"}, *matchers[1:]],
        ),
        silence(
            "unexpected-matcher-field",
            "active",
            selected_matchers=[matchers[0] | {"unexpected": False}, *matchers[1:]],
        ),
        silence(
            "malformed-matcher-object",
            "active",
            selected_matchers=[{"name": "alertname"}, *matchers[1:]],
        ),
        silence(
            "non-object-matcher",
            "active",
            selected_matchers=["alertname=SugarkubeObservabilityWatchdog", *matchers[1:]],
        ),
        silence(
            "duplicate-matcher",
            "active",
            selected_matchers=[matchers[0], matchers[0], matchers[2], matchers[3]],
        ),
        silence(
            "extra-matcher",
            "active",
            selected_matchers=[*matchers, {"name": "node", "value": "all", "isRegex": False}],
        ),
        silence("missing-matcher", "active", selected_matchers=matchers[:-1]),
        silence(
            "broad-matcher",
            "active",
            selected_matchers=[matchers[0] | {"value": ".*"}, *matchers[1:]],
        ),
        silence("malformed", "active", selected_matchers={"not": "a list"}),
    ]


def test_watchdog_drill_create_submits_exact_bounded_sanitized_payload(tmp_path):
    result, audit = run_helper(tmp_path, "watchdog-drill-create")

    assert result.returncode == 0, result.stderr
    payload = json.loads((tmp_path / "watchdog-silence-payload").read_text(encoding="utf-8"))
    assert payload["matchers"] == [
        {"name": "alertname", "value": "SugarkubeObservabilityWatchdog", "isRegex": False},
        {"name": "environment", "value": "staging", "isRegex": False},
        {"name": "cluster", "value": "sugarkube-int", "isRegex": False},
        {"name": "purpose", "value": "observability-watchdog", "isRegex": False},
    ]
    assert payload["createdBy"] == "sugarkube-observability-watchdog-drill"
    assert payload["comment"] == "Owned staging watchdog failure drill"
    starts_at = __import__("datetime").datetime.fromisoformat(
        payload["startsAt"].replace("Z", "+00:00")
    )
    ends_at = __import__("datetime").datetime.fromisoformat(
        payload["endsAt"].replace("Z", "+00:00")
    )
    assert (ends_at - starts_at).total_seconds() == 8 * 60
    assert "MANUAL CHECKPOINT" in result.stderr
    assert (
        result.stdout
        == "Owned watchdog drill silence created; id=created-owned-silence; automatic expiry=8m.\n"
    )
    assert (
        "port-forward --address=127.0.0.1 " "service/kube-prometheus-stack-alertmanager :9093"
    ) in audit
    assert "--header Content-Type: application/json" in audit
    assert "http://127.0.0.1:43128/api/v2/silences" in audit
    assert (tmp_path / "pagerduty.reaped").read_text(encoding="utf-8").strip() == "reaped"
    assert not list(tmp_path.glob("sugarkube-watchdog-silence.*"))
    assert "shutdown" not in audit.lower() and "hc-ping" not in audit


@pytest.mark.parametrize(
    ("interrupt_signal", "expected_returncode"),
    [(signal.SIGINT, 130), (signal.SIGTERM, 143)],
)
def test_watchdog_drill_create_signals_clean_up_runtime_resources(
    tmp_path, interrupt_signal, expected_returncode
):
    result, _ = run_helper(
        tmp_path,
        "watchdog-drill-create",
        watchdog_silence_mode="signal-wait",
        interrupt_signal=interrupt_signal,
    )

    assert result.returncode == expected_returncode
    port_forward_pid = int((tmp_path / "pagerduty.pid").read_text(encoding="utf-8"))
    with pytest.raises(ProcessLookupError):
        os.kill(port_forward_pid, 0)
    assert (tmp_path / "pagerduty.reaped").read_text(encoding="utf-8").strip() == "reaped"
    assert not list(tmp_path.glob("sugarkube-watchdog-silence.*"))
    output = result.stdout + result.stderr
    assert "PRIVATE_RESPONSE_SENTINEL" not in output
    assert "CURL_RESPONSE_SENTINEL" not in output
    assert "credential" not in output
    assert "Traceback" not in output


@pytest.mark.parametrize(
    "mode",
    [
        "forward-exit",
        "forward-exit-during-curl",
        "transport",
        "http000",
        "http415",
        "http400",
        "http503",
        "malformed",
        "response-malformed",
        "response-missing",
        "response-invalid-id",
    ],
)
def test_watchdog_drill_create_failures_are_closed_redacted_and_cleaned_up(tmp_path, mode):
    result, _ = run_helper(tmp_path, "watchdog-drill-create", pagerduty_mode=mode)

    assert result.returncode != 0
    output = result.stdout + result.stderr
    assert "PRIVATE_RESPONSE_SENTINEL" not in output
    assert "CURL_RESPONSE_SENTINEL" not in output
    assert "PORT_FORWARD_SENTINEL" not in output
    assert "credential" not in output
    assert "Traceback" not in output
    assert not list(tmp_path.glob("sugarkube-watchdog-silence.*"))
    if (tmp_path / "pagerduty.pid").exists() and mode != "forward-exit-during-curl":
        assert (tmp_path / "pagerduty.reaped").read_text(encoding="utf-8").strip() == "reaped"


def test_watchdog_drill_create_rejects_unusable_forward_line(tmp_path):
    result, _ = run_helper(
        tmp_path,
        "watchdog-drill-create",
        pagerduty_forward_line="Forwarding from 0.0.0.0:43128 -> 9093",
    )

    assert result.returncode != 0
    assert "diagnostics redacted" in result.stderr
    assert "Traceback" not in result.stderr
    assert (tmp_path / "pagerduty.reaped").read_text(encoding="utf-8").strip() == "reaped"
    assert not list(tmp_path.glob("sugarkube-watchdog-silence.*"))


def test_watchdog_silence_status_reports_only_exact_owned_active_or_pending(tmp_path):
    fixture = watchdog_silence_fixture()
    result, _ = run_helper(tmp_path, "watchdog-drill-status", watchdog_silences=fixture)

    assert result.returncode == 0, result.stderr
    assert result.stdout.endswith(
        "Owned active/pending watchdog drill silence IDs:\n"
        "owned-active\nowned-pending\nowned-legacy\n"
    )
    for silence in fixture[3:]:
        assert silence["id"] not in result.stdout
        assert silence["fixtureDetail"] not in result.stdout + result.stderr


def test_watchdog_silence_clear_deletes_only_exact_owned_active_or_pending(tmp_path):
    fixture = watchdog_silence_fixture()
    result, _ = run_helper(tmp_path, "watchdog-drill-clear", watchdog_silences=fixture)

    assert result.returncode == 0, result.stderr
    deleted = (tmp_path / "watchdog-silence-deletions").read_text(encoding="utf-8").splitlines()
    assert deleted == ["owned-active", "owned-pending", "owned-legacy"]
    assert result.stdout.endswith("Owned watchdog drill silence cleared.\n")
    assert all(item["fixtureDetail"] not in result.stdout + result.stderr for item in fixture)


def test_watchdog_silence_clear_is_noop_without_owned_silences(tmp_path):
    fixture = watchdog_silence_fixture()[3:]
    result, audit = run_helper(tmp_path, "watchdog-drill-clear", watchdog_silences=fixture)

    assert result.returncode == 0, result.stderr
    assert "No owned active/pending watchdog drill silence to clear." in result.stdout
    assert "delete --raw" not in audit
    assert not (tmp_path / "watchdog-silence-deletions").exists()


@pytest.mark.parametrize(
    ("command", "mode"),
    [
        ("watchdog-drill-status", "watchdog-silences-fail"),
        ("watchdog-drill-status", "watchdog-silences-malformed"),
        ("watchdog-drill-status", "watchdog-silences-nonutf8"),
        ("watchdog-drill-clear", "watchdog-silences-fail"),
        ("watchdog-drill-clear", "watchdog-silences-malformed"),
        ("watchdog-drill-clear", "watchdog-silences-nonutf8"),
    ],
)
def test_watchdog_silence_api_failures_do_not_expose_fixture_contents(tmp_path, command, mode):
    fixture = watchdog_silence_fixture()
    result, _ = run_helper(tmp_path, command, kubectl_mode=mode, watchdog_silences=fixture)

    assert result.returncode != 0
    output = result.stdout + result.stderr
    assert all(item["fixtureDetail"] not in output for item in fixture)
    assert "PRIVATE_NON_UTF8_SENTINEL" not in output
    assert "credential" not in output
    assert "Traceback" not in output
    assert "response redacted" in output
    if command == "watchdog-drill-clear":
        assert not (tmp_path / "watchdog-silence-deletions").exists()


def production_alertmanager_fixture(*, secrets="[]", route_extra="", receiver_extra="", inline=""):
    return f'''---
apiVersion: monitoring.coreos.com/v1
kind: Alertmanager
metadata:
  name: kube-prometheus-stack-alertmanager
spec:
  secrets: {secrets}
---
apiVersion: v1
kind: Secret
metadata:
  name: alertmanager-kube-prometheus-stack-alertmanager
stringData:
  alertmanager.yaml: |
    route:
      receiver: "null"{route_extra}
    receivers:
      - name: "null"{receiver_extra}{inline}
'''


def test_production_offline_render_uses_only_ordered_core_values(tmp_path):
    result, audit = run_helper(tmp_path, "render", env_name="prod", context="unavailable")
    assert result.returncode == 0, result.stderr
    template = next(line for line in audit.splitlines() if "helm template " in line)
    assert template.index(str(COMMON)) < template.index(str(PROD))
    assert str(PROD_DASHBOARD) in template
    for excluded in (str(STAGING), str(DASHBOARD), "sugarkube-observability-rules"):
        assert excluded not in template
    assert "kubectl" not in audit
    assert "pagerduty" not in result.stdout.lower()
    assert "watchdog" not in result.stdout.lower()


@pytest.mark.parametrize(
    ("context", "mode", "extra_env"),
    [
        ("other", "healthy", None),
        ("sugar-staging", "healthy", None),
        ("sugar-prod", "identity-mismatch", None),
        ("sugar-prod", "healthy", {"KUBECONFIG": ""}),
    ],
)
def test_production_install_identity_and_explicit_kubeconfig_fail_before_helm_mutation(
    tmp_path, context, mode, extra_env
):
    result, audit = run_helper(
        tmp_path, "install", env_name="prod", context=context,
        kubectl_mode=mode, extra_env=extra_env,
    )
    assert result.returncode != 0
    assert "helm install" not in audit


def test_production_install_release_and_secret_guards(tmp_path):
    installed, audit = run_helper(
        tmp_path / "ok", "install", env_name="prod", context="sugar-prod", helm_mode="absent"
    )
    assert installed.returncode == 0, installed.stderr
    assert "helm install" in audit and "--atomic" in audit
    assert "alertmanager-pagerduty" not in audit and "alertmanager-healthchecks-watchdog" not in audit
    existing, audit = run_helper(
        tmp_path / "existing", "install", env_name="prod", context="sugar-prod", helm_mode="present"
    )
    assert existing.returncode != 0 and "helm install" not in audit
    missing, audit = run_helper(
        tmp_path / "secret", "install", env_name="prod", context="sugar-prod",
        kubectl_mode="missing-grafana",
    )
    assert missing.returncode != 0 and "helm " not in audit


def test_production_core_verify_skips_staging_integrations(tmp_path):
    result, audit = run_helper(tmp_path, "verify", env_name="prod", context="sugar-prod")
    assert result.returncode == 0, result.stderr
    for required in ("rollout status", "get daemonset", "get pvc -o json", "get svc kube-prometheus-stack-grafana", "get secret grafana-admin-credentials"):
        assert required in audit
    for excluded in ("servicemonitor dspace", "alertmanager-pagerduty", "alertmanager-healthchecks-watchdog", " --raw "):
        assert excluded not in audit


@pytest.mark.parametrize("command", ["pagerduty-test", "watchdog-verify"])
def test_staging_only_subcommands_reject_production(tmp_path, command):
    result, audit = run_helper(tmp_path, command, env_name="prod", context="sugar-prod")
    assert result.returncode != 0
    assert "staging-only" in result.stderr and not audit


@pytest.mark.parametrize(
    "mutation",
    [
        {"route_extra": "\n      routes: []"},
        {"receiver_extra": "\n      - name: extra"},
        {"secrets": "[integration-secret]"},
        {"inline": "\n    routing_key: forbidden-stub"},
    ],
)
def test_production_alertmanager_validator_accepts_null_only_and_rejects_integrations(
    tmp_path, mutation
):
    valid = tmp_path / "valid.yaml"
    valid.write_text(production_alertmanager_fixture(), encoding="utf-8")
    accepted = subprocess.run(
        ["ruby", str(ALERTMANAGER_VALIDATOR), "prod", "rendered", str(valid)],
        capture_output=True, text=True, check=False,
    )
    assert accepted.returncode == 0, accepted.stderr
    invalid = tmp_path / "invalid.yaml"
    invalid.write_text(production_alertmanager_fixture(**mutation), encoding="utf-8")
    rejected = subprocess.run(
        ["ruby", str(ALERTMANAGER_VALIDATOR), "prod", "rendered", str(invalid)],
        capture_output=True, text=True, check=False,
    )
    assert rejected.returncode == 16
    assert "forbidden-stub" not in rejected.stderr


def test_production_alertmanager_secret_mount_has_production_specific_diagnostic(
    tmp_path,
):
    manifest = tmp_path / "integration-secret.yaml"
    manifest.write_text(
        production_alertmanager_fixture(secrets="[integration-secret]"), encoding="utf-8"
    )
    result = subprocess.run(
        ["ruby", str(ALERTMANAGER_VALIDATOR), "prod", "rendered", str(manifest)],
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 16
    assert "production Alertmanager must mount no integration Secrets" in result.stderr
    assert "two expected" not in result.stderr
    assert "alertmanager-pagerduty" not in result.stderr
    assert "alertmanager-healthchecks-watchdog" not in result.stderr
