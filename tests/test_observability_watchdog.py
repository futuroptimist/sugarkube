import json
import re
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VALUES = ROOT / "clusters/staging/observability/kube-prometheus-stack.values.yaml"
SCRIPT = ROOT / "scripts/observability_watchdog.sh"
JUSTFILE = ROOT / "justfile"
DOCS = ROOT / "docs/observability-operations.md"


def yaml_load(path):
    result = subprocess.run(["ruby", "-ryaml", "-rjson", "-e", "puts JSON.generate(YAML.safe_load_file(ARGV[0], aliases: false))", str(path)], check=True, text=True, capture_output=True)
    return json.loads(result.stdout)


def test_exact_rule_and_healthchecks_contract():
    values = yaml_load(VALUES)
    group = values["additionalPrometheusRulesMap"]["sugarkube-observability-watchdog"]["groups"][0]
    assert group["interval"] == "1m"
    assert group["rules"] == [{
        "alert": "SugarkubeObservabilityWatchdog", "expr": "vector(1)",
        "labels": {"environment": "staging", "cluster": "sugarkube-int", "purpose": "observability-watchdog"},
        "annotations": {"summary": "Sugarkube staging observability watchdog", "runbook_url": "https://github.com/futuroptimist/sugarkube/blob/main/docs/observability-operations.md#observability-watchdog"},
    }]
    alertmanager = values["alertmanager"]
    assert alertmanager["alertmanagerSpec"]["secrets"] == ["alertmanager-pagerduty", "alertmanager-healthchecks-watchdog"]
    assert [route["receiver"] for route in alertmanager["config"]["route"]["routes"]] == ["pagerduty-synthetic-test", "healthchecks-watchdog"]
    watchdog = alertmanager["config"]["route"]["routes"][1]
    assert watchdog == {
        "receiver": "healthchecks-watchdog",
        "matchers": ['alertname="SugarkubeObservabilityWatchdog"', 'environment="staging"', 'cluster="sugarkube-int"', 'purpose="observability-watchdog"'],
        "group_wait": "30s", "group_interval": "1m", "repeat_interval": "5m",
        "group_by": ["alertname", "cluster", "environment"],
    }
    webhook = alertmanager["config"]["receivers"][2]["webhook_configs"][0]
    assert webhook == {"url_file": "/etc/alertmanager/secrets/alertmanager-healthchecks-watchdog/ping-url", "send_resolved": False, "max_alerts": 1, "timeout": "10s"}
    assert "url" not in webhook


def test_hidden_installer_and_exact_bounded_drill_contract():
    script = SCRIPT.read_text()
    assert 'exec 3<"$TTY"' in script and "read -r -s value <&3" in script
    assert '--from-file="$KEY=/dev/stdin"' in script and "kubectl apply -f -" in script
    assert "credentials in command arguments are refused" in script
    assert "PING_URL" in script and "environment variables are refused" in script
    assert "timedelta(minutes=8)" in script
    payload = re.search(r'want=\{([^\n]+)\}', script).group(1)
    for label in ("alertname", "environment", "cluster", "purpose"):
        assert f'"{label}"' in payload
    assert "shutdown" not in script.lower()
    assert "hc-ping.com" not in script.split("validate", 1)[-1] or "curl" in script


def test_documented_staging_recipes_and_five_minute_timing():
    justfile = JUSTFILE.read_text()
    docs = DOCS.read_text()
    for recipe in ("install", "secret-check", "verify", "drill-create", "drill-status", "drill-clear"):
        assert f"observability-watchdog-{recipe}" in justfile
    assert "just observability-watchdog-install env=staging" in docs
    assert "five-minute period" in docs and "two-minute grace" in docs
    assert "eight-minute expiry" in docs
    assert "pause the Healthchecks check" in docs
