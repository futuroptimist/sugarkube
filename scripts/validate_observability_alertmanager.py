#!/usr/bin/env python3
"""Validate the staging Alertmanager render without revealing secret material."""

import base64
import json
import subprocess
import sys
from pathlib import Path

SECRET = "alertmanager-pagerduty"
RECEIVER = "pagerduty-synthetic"
FILE = f"/etc/alertmanager/secrets/{SECRET}/routing-key"
MATCHERS = {
    'alertname="SugarkubePagerDutyTest"',
    'environment="staging"',
    'cluster="sugarkube-int"',
    'severity="critical"',
}


def load_documents(path: Path) -> list[dict]:
    ruby = subprocess.run(
        [
            "ruby",
            "-ryaml",
            "-rjson",
            "-e",
            "puts JSON.generate(YAML.load_stream(File.read(ARGV[0])))",
            str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    documents = json.loads(ruby.stdout)
    return [item for item in documents if isinstance(item, dict)]


def validate_config(config: dict) -> None:
    route = config.get("route", {})
    if route.get("receiver") != "null":
        raise ValueError('root receiver must remain "null"')
    routes = route.get("routes", [])
    pd_routes = [item for item in routes if item.get("receiver") == RECEIVER]
    if len(pd_routes) != 1 or set(pd_routes[0].get("matchers", [])) != MATCHERS:
        raise ValueError("PagerDuty must have exactly the narrow synthetic route")
    receivers = [item for item in config.get("receivers", []) if item.get("name") == RECEIVER]
    if len(receivers) != 1 or len(receivers[0].get("pagerduty_configs", [])) != 1:
        raise ValueError("expected exactly one synthetic PagerDuty receiver")
    pagerduty = receivers[0]["pagerduty_configs"][0]
    if pagerduty.get("routing_key_file") != FILE or pagerduty.get("send_resolved") is not True:
        raise ValueError("PagerDuty receiver requires the expected file and send_resolved")
    if "routing_key" in pagerduty or "service_key" in pagerduty:
        raise ValueError("inline PagerDuty credentials are forbidden")


def validate_render(path: Path) -> None:
    documents = load_documents(path)
    alertmanagers = [doc for doc in documents if doc.get("kind") == "Alertmanager"]
    if len(alertmanagers) != 1 or alertmanagers[0].get("spec", {}).get("secrets") != [SECRET]:
        raise ValueError(f"Alertmanager must reference Secret {SECRET}")
    configs = [
        doc
        for doc in documents
        if doc.get("kind") == "Secret"
        and doc.get("metadata", {}).get("name") == "alertmanager-kube-prometheus-stack-alertmanager"
    ]
    if len(configs) != 1:
        raise ValueError("rendered Alertmanager configuration Secret is missing")
    encoded = configs[0].get("data", {}).get("alertmanager.yaml")
    if not isinstance(encoded, str):
        raise ValueError("rendered Alertmanager configuration is missing")
    raw = base64.b64decode(encoded, validate=True)
    parsed = subprocess.run(
        [
            "ruby",
            "-ryaml",
            "-rjson",
            "-e",
            "puts JSON.generate(YAML.safe_load(STDIN.read, aliases: false))",
        ],
        input=raw,
        check=True,
        capture_output=True,
    )
    validate_config(json.loads(parsed.stdout))


def validate_secret_json(path: Path) -> None:
    secret = json.loads(path.read_text(encoding="utf-8"))
    encoded = secret.get("data", {}).get("alertmanager.yaml")
    if not isinstance(encoded, str):
        raise ValueError("loaded Alertmanager configuration is missing")
    raw = base64.b64decode(encoded, validate=True)
    parsed = subprocess.run(
        [
            "ruby",
            "-ryaml",
            "-rjson",
            "-e",
            "puts JSON.generate(YAML.safe_load(STDIN.read, aliases: false))",
        ],
        input=raw,
        check=True,
        capture_output=True,
    )
    validate_config(json.loads(parsed.stdout))


if __name__ == "__main__":
    try:
        if len(sys.argv) == 2:
            validate_render(Path(sys.argv[1]))
        elif len(sys.argv) == 3 and sys.argv[1] == "--config-secret-json":
            validate_secret_json(Path(sys.argv[2]))
        else:
            raise ValueError(
                "usage: validate_observability_alertmanager.py [--config-secret-json] FILE"
            )
    except (ValueError, OSError, subprocess.SubprocessError, json.JSONDecodeError) as exc:
        print(f"ERROR: invalid Alertmanager structure: {exc}", file=sys.stderr)
        raise SystemExit(1)
    print("Alertmanager PagerDuty structure validated (file reference only).")
