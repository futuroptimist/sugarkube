import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VALUES = ROOT / "clusters/staging/observability/kube-prometheus-stack.values.yaml"
SCRIPT = ROOT / "scripts/observability_watchdog.sh"
VALIDATOR = ROOT / "scripts/verify_observability_alertmanager.rb"
OPERATIONS = ROOT / "docs/observability-operations.md"


def yaml_load(path: Path):
    result = subprocess.run(
        [
            "ruby",
            "-ryaml",
            "-rjson",
            "-e",
            "puts JSON.generate(YAML.safe_load_file(ARGV[0]))",
            str(path),
        ],
        check=True,
        text=True,
        capture_output=True,
    )
    return json.loads(result.stdout)


def test_watchdog_rule_and_five_minute_contract_are_exact():
    values = yaml_load(VALUES)
    group = values["additionalPrometheusRulesMap"]["sugarkube-observability-watchdog"]["groups"][0]
    assert group["interval"] == "1m"
    rule = group["rules"][0]
    assert rule["alert"] == "SugarkubeObservabilityWatchdog"
    assert rule["expr"] == "vector(1)"
    assert "for" not in rule
    assert rule["labels"] == {
        "environment": "staging",
        "cluster": "sugarkube-int",
        "purpose": "observability-watchdog",
    }
    assert rule["annotations"] == {
        "summary": "Sugarkube staging observability watchdog",
        "runbook_url": "https://github.com/futuroptimist/sugarkube/blob/main/docs/observability-operations.md#observability-watchdog",
    }
    route = values["alertmanager"]["config"]["route"]["routes"][1]
    assert route["repeat_interval"] == "5m"
    docs = OPERATIONS.read_text(encoding="utf-8")
    assert "**five-minute period and two-minute grace**" in docs


def test_installer_is_hidden_stdin_only_and_env_invocations_are_normalized():
    script = SCRIPT.read_text(encoding="utf-8")
    assert "read -r -s" in script and "</dev/tty" in script
    assert "--from-file=ping-url=/dev/stdin" in script
    assert "--dry-run=client -o yaml" in script and "kubectl apply -f -" in script
    assert "WATCHDOG_PING_URL+x" in script and "HEALTHCHECKS_PING_URL+x" in script
    assert 'while [[ "$value" == env=* ]]' in script
    assert "mktemp" not in script.split("apply_secret()", 1)[1].split("verify_live()", 1)[0]
    docs = OPERATIONS.read_text(encoding="utf-8")
    for command in (
        "observability-watchdog-install",
        "observability-watchdog-status",
        "observability-watchdog-verify",
        "observability-watchdog-drill-create",
        "observability-watchdog-drill-status",
        "observability-watchdog-drill-clear",
    ):
        assert f"{command} env=staging" in docs


def test_drill_payload_is_exact_and_bounded_without_disruption():
    script = SCRIPT.read_text(encoding="utf-8")
    payload = script.split("silence_payload()", 1)[1].split("silence_create()", 1)[0]
    for label in ("alertname", "environment", "cluster", "purpose"):
        assert label in payload
    assert "timedelta(minutes=8)" in payload
    assert '"isRegex":False' in payload
    assert "shutdown" not in script.lower()
    assert "curl" not in script
    assert "ping-url" not in payload


def test_validator_rejects_additional_webhook_receiver(tmp_path):
    base_test = (ROOT / "tests/test_observability_helm.py").read_text(encoding="utf-8")
    # Exercise the real validator through a rendered chart-shaped fixture assembled
    # by importing the existing focused helper, then add a forbidden receiver.
    namespace = {"__file__": str(ROOT / "tests/test_observability_helm.py")}
    exec(compile(base_test.split("@pytest.mark.parametrize", 1)[0], "fixture", "exec"), namespace)
    manifest = namespace["rendered_alertmanager_fixture"]().replace(
        "      - name: healthchecks-watchdog",
        "      - name: extra-webhook\n        webhook_configs: []\n      - name: healthchecks-watchdog",
    )
    path = tmp_path / "rendered.yaml"
    path.write_text(manifest, encoding="utf-8")
    result = subprocess.run(
        ["ruby", str(VALIDATOR), "rendered", str(path)], text=True, capture_output=True, check=False
    )
    assert result.returncode == 16
    assert "receiver list must contain exactly" in result.stderr
