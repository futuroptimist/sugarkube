#!/usr/bin/env python3
"""Fail-closed structural validation for staging Alertmanager configuration."""

import argparse
import base64
import json
import sys
import subprocess

SECRET = "alertmanager-pagerduty"
FILE = "/etc/alertmanager/secrets/alertmanager-pagerduty/routing-key"
RECEIVER = "pagerduty-synthetic-test"


def yaml_documents(text):
    documents = []
    for part in __import__("re").split(r"(?m)^---\s*$", text):
        if not part.strip():
            continue
        result = subprocess.run(
            [
                "ruby",
                "-ryaml",
                "-rjson",
                "-e",
                "puts JSON.generate(YAML.safe_load(STDIN.read, permitted_classes: [Symbol], permitted_symbols: [], aliases: false))",
            ],
            input=part,
            text=True,
            capture_output=True,
        )
        if result.returncode:
            fail("input is malformed")
        documents.append(json.loads(result.stdout))
    return documents


MATCHERS = {
    'alertname="SugarkubePagerDutyTest"',
    'environment="staging"',
    'cluster="sugarkube-int"',
    'severity="critical"',
}


def fail(message):
    raise SystemExit(f"ERROR: unsafe staging Alertmanager configuration: {message}.")


def validate_config(config):
    route = config.get("route", {})
    if route.get("receiver") != "null":
        fail('root receiver must remain "null"')
    routes = route.get("routes", [])
    selected = [item for item in routes if item.get("receiver") == RECEIVER]
    if len(selected) != 1 or set(selected[0].get("matchers", [])) != MATCHERS:
        fail("PagerDuty must have exactly the narrow synthetic route")

    def targets(items):
        for item in items:
            yield item.get("receiver")
            yield from targets(item.get("routes", []))

    if list(targets(routes)).count(RECEIVER) != 1:
        fail("unexpected broad or duplicate PagerDuty route")
    found = [item for item in config.get("receivers", []) if item.get("name") == RECEIVER]
    if len(found) != 1:
        fail("synthetic PagerDuty receiver is missing or duplicated")
    pd = found[0].get("pagerduty_configs", [])
    if (
        len(pd) != 1
        or pd[0].get("routing_key_file") != FILE
        or pd[0].get("send_resolved") is not True
    ):
        fail("PagerDuty must use the expected file and send resolved events")
    if any(key in pd[0] for key in ("routing_key", "service_key")):
        fail("inline PagerDuty credentials are forbidden")
    if [item for item in config.get("receivers", []) if item.get("name") == "null"] != [
        {"name": "null"}
    ]:
        fail('the no-op "null" receiver changed')


def rendered(stream):
    docs = [doc for doc in yaml_documents(stream.read()) if isinstance(doc, dict)]
    resources = [doc for doc in docs if doc.get("kind") == "Alertmanager"]
    if len(resources) != 1:
        fail("render must contain exactly one Alertmanager resource")
    if SECRET not in resources[0].get("spec", {}).get("secrets", []):
        fail(f"Alertmanager does not reference Secret {SECRET}")
    configs = []
    for doc in docs:
        if doc.get("kind") != "Secret":
            continue
        raw = doc.get("stringData", {}).get("alertmanager.yaml")
        if raw:
            configs.append(yaml_documents(raw)[0])
        encoded = doc.get("data", {}).get("alertmanager.yaml")
        if encoded:
            try:
                configs.append(yaml_documents(base64.b64decode(encoded, validate=True).decode())[0])
            except (ValueError, UnicodeError):
                fail("rendered Alertmanager configuration is malformed")
    if len(configs) != 1:
        fail("render must contain exactly one generated Alertmanager configuration")
    validate_config(configs[0])


def live(stream):
    document = json.load(stream)
    if SECRET not in document.get("alertmanager", {}).get("spec", {}).get("secrets", []):
        fail(f"live Alertmanager does not reference Secret {SECRET}")
    try:
        config = yaml_documents(
            base64.b64decode(
                document["config_secret"]["data"]["alertmanager.yaml"], validate=True
            ).decode()
        )[0]
    except (KeyError, ValueError, UnicodeError):
        fail("live generated Alertmanager configuration is missing or malformed")
    validate_config(config)


parser = argparse.ArgumentParser()
parser.add_argument("mode", choices=("rendered", "live"))
args = parser.parse_args()
try:
    globals()[args.mode](sys.stdin)
except (json.JSONDecodeError, UnicodeError):
    fail("input is malformed")
