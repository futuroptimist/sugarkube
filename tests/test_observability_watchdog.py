import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VALUES = ROOT / "clusters/staging/observability/kube-prometheus-stack.values.yaml"
SCRIPT = ROOT / "scripts/observability_watchdog.sh"
JUSTFILE = ROOT / "justfile"


def load_values():
    result = subprocess.run(
        [
            "ruby",
            "-ryaml",
            "-rjson",
            "-e",
            "puts JSON.generate(YAML.safe_load_file(ARGV[0]))",
            str(VALUES),
        ],
        check=True,
        text=True,
        capture_output=True,
    )
    return json.loads(result.stdout)


def test_exact_watchdog_rule_and_five_minute_delivery_contract():
    values = load_values()
    group = values["additionalPrometheusRulesMap"]["sugarkube-observability-watchdog"]["groups"][0]
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
    watchdog = values["alertmanager"]["config"]["route"]["routes"][1]
    assert watchdog["repeat_interval"] == "5m"
    docs = (ROOT / "docs/observability-operations.md").read_text()
    assert "**five-minute period**" in docs and "**two-minute grace**" in docs


def test_secret_file_receiver_and_no_inline_url():
    values = load_values()
    receiver = values["alertmanager"]["config"]["receivers"][2]
    assert receiver == {
        "name": "healthchecks-watchdog",
        "webhook_configs": [
            {
                "url_file": "/etc/alertmanager/secrets/alertmanager-healthchecks-watchdog/ping-url",
                "send_resolved": False,
                "http_config": {"follow_redirects": True},
                "max_alerts": 1,
                "timeout": "10s",
            }
        ],
    }
    assert "url" not in receiver["webhook_configs"][0]


def test_installer_hidden_input_redaction_and_env_normalization_are_explicit():
    script = SCRIPT.read_text()
    assert "read -r -s" in script and "</dev/tty" in script
    assert "must not be supplied through argv" in script
    assert "must not be supplied through environment variables" in script
    assert "--from-file=ping-url=/dev/stdin" in script
    assert "value not printed" in script
    justfile = JUSTFILE.read_text()
    for recipe in (
        "secret-install",
        "secret-check",
        "verify",
        "drill-create",
        "drill-status",
        "drill-clear",
    ):
        assert f"observability-watchdog-{recipe} env=''" in justfile
        assert f"observability_watchdog.sh {recipe} '{{{{ env }}}}'" in justfile
    rejected = subprocess.run(
        ["bash", str(SCRIPT), "secret-check", "env=env=prod"], text=True, capture_output=True
    )
    assert rejected.returncode != 0 and "env=env=prod" not in rejected.stderr


def test_drill_payload_is_exact_and_bounded_without_real_wait():
    script = SCRIPT.read_text()
    labels = {
        "alertname": "SugarkubeObservabilityWatchdog",
        "environment": "staging",
        "cluster": "sugarkube-int",
        "purpose": "observability-watchdog",
    }
    assert f"labels={json.dumps(labels, separators=(',', ':'))}" in script
    assert "timedelta(minutes=8)" in script
    assert 'isRegex":False' in script and 'isEqual":True' in script
    assert "shutdown" not in re.sub(r'echo "[^"]*"', "", script)
    assert "hc-ping.com" not in script.replace('"hc-ping.com"', "")


def test_helm_lifecycle_checks_both_secret_contracts_before_mutation():
    helm = (ROOT / "scripts/observability_helm.sh").read_text()
    assert "assert_alerting_secrets() { assert_pagerduty_secret; assert_watchdog_secret; }" in helm
    for function in ("install_release()", "upgrade_release()"):
        body = helm.split(function, 1)[1].split("\n", 1)[0]
        assert body.index("assert_alerting_secrets") < body.index("render_to") < body.index("helm ")
    assert 'index .data "ping-url"' in helm
    assert "must contain a nonempty ping-url" in helm
