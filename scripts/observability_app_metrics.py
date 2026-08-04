#!/usr/bin/env python3
"""Declarative application Prometheus metrics checks for Sugarkube."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "platform/observability/app-metrics.json"
PROM = "/api/v1/namespaces/monitoring/services/http:kube-prometheus-stack-prometheus:9090/proxy"
K8S_NAME = re.compile(r"[a-z0-9]([-a-z0-9]*[a-z0-9])?")
DURATION = re.compile(r"[1-9][0-9]*[smh]")
STATUS = re.compile(r"[1-5][0-9][0-9]")
SAFE_VALUE = re.compile(r"[-A-Za-z0-9_./:*]+")
STANDARD_LABELS = {
    "__name__",
    "job",
    "namespace",
    "pod",
    "service",
    "endpoint",
    "container",
    "prometheus",
    "prometheus_replica",
    "instance",
}
FORBIDDEN_WORDS = (
    "token",
    "secret",
    "passwd",
    "passcode",
    "authorization",
    "bearer",
    "cookie",
    "session",
    "email",
    "user",
    "ip",
    "url",
)


class Error(SystemExit):
    def __init__(self, msg: str, code: int = 2):
        super().__init__(f"ERROR: {msg}")
        self.code = code


def fail(msg: str, code: int = 2):
    raise Error(msg, code)


def load_config(path: Path = CONFIG) -> dict[str, Any]:
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        fail(f"cannot read app metrics inventory: {exc}")
    try:
        doc = json.loads(raw)
    except json.JSONDecodeError:
        fail("app metrics inventory is malformed JSON")
    validate_inventory(doc)
    return doc


def expect_keys(obj, keys, where):
    if not isinstance(obj, dict):
        fail(f"{where} must be an object")
    extra = set(obj) - set(keys)
    if extra:
        fail(f"{where} has unknown keys: {', '.join(sorted(extra))}")


def name(v, where):
    if not isinstance(v, str) or not K8S_NAME.fullmatch(v) or len(v) > 63:
        fail(f"{where} must be a safe Kubernetes name")


def nonempty(v, where):
    if not isinstance(v, str) or not v:
        fail(f"{where} must be a nonempty string")
    if not SAFE_VALUE.fullmatch(v):
        fail(f"{where} contains unsafe characters")


def validate_inventory(doc):
    expect_keys(doc, {"schemaVersion", "applications"}, "inventory")
    if doc.get("schemaVersion") != 1:
        fail("unsupported app metrics inventory schemaVersion")
    apps = doc["applications"]
    if not isinstance(apps, dict) or not apps:
        fail("inventory applications must be a nonempty object")
    for app, appdoc in apps.items():
        name(app, f"application {app}")
        expect_keys(appdoc, {"environments"}, f"application {app}")
        for env, cfg in appdoc["environments"].items():
            if env != "staging":
                fail("only staging app metrics verification is supported")
            expect_keys(
                cfg,
                {
                    "namespace",
                    "serviceMonitorName",
                    "expectedTargetCount",
                    "secret",
                    "serviceMonitor",
                    "targetLabels",
                    "publicMetrics",
                    "retries",
                    "requiredMetricFamilies",
                    "allowedApplicationLabels",
                    "forbiddenApplicationLabels",
                },
                f"{app}/{env}",
            )
            name(cfg["namespace"], "namespace")
            name(cfg["serviceMonitorName"], "serviceMonitorName")
            if not isinstance(cfg["expectedTargetCount"], int) or cfg["expectedTargetCount"] < 1:
                fail("expectedTargetCount must be a positive integer")
            expect_keys(cfg["secret"], {"name", "key"}, "secret")
            name(cfg["secret"]["name"], "secret.name")
            name(cfg["secret"]["key"], "secret.key")
            sm = cfg["serviceMonitor"]
            expect_keys(
                sm,
                {"selectorMatchLabels", "path", "interval", "scrapeTimeout", "authorization", "relabelings"},
                "serviceMonitor",
            )
            if sm["path"] != "/metrics":
                fail("serviceMonitor.path must be /metrics")
            for key in ("interval", "scrapeTimeout"):
                if not isinstance(sm[key], str) or not DURATION.fullmatch(sm[key]):
                    fail(f"serviceMonitor.{key} is malformed")
            expect_keys(sm["authorization"], {"type", "credentials"}, "authorization")
            nonempty(sm["authorization"]["type"], "authorization.type")
            expect_keys(sm["authorization"].get("credentials"), {"name", "key"}, "authorization.credentials")
            name(sm["authorization"]["credentials"]["name"], "authorization.credentials.name")
            name(sm["authorization"]["credentials"]["key"], "authorization.credentials.key")
            selector = sm["selectorMatchLabels"]
            if not isinstance(selector, dict) or not selector:
                fail("serviceMonitor.selectorMatchLabels must be a nonempty object")
            for k, v in selector.items():
                nonempty(k, "selector label name")
                nonempty(v, "selector label value")
            relabelings = sm["relabelings"]
            if not isinstance(relabelings, list) or len(relabelings) != 4:
                fail("serviceMonitor.relabelings must contain exactly four entries")
            for idx, relabeling in enumerate(relabelings):
                expect_keys(relabeling, {"targetLabel", "replacement"}, f"serviceMonitor.relabelings[{idx}]")
                nonempty(relabeling["targetLabel"], "relabeling targetLabel")
                nonempty(relabeling["replacement"], "relabeling replacement")
            labels = cfg["targetLabels"]
            if not isinstance(labels, dict) or not labels:
                fail("targetLabels must be a nonempty object")
            for k, v in labels.items():
                nonempty(k, "target label name")
                nonempty(v, "target label value")
            pm = cfg["publicMetrics"]
            expect_keys(pm, {"url", "expectedUnauthenticatedStatus"}, "publicMetrics")
            if (
                not isinstance(pm["url"], str)
                or not pm["url"].startswith("https://")
                or not pm["url"].endswith("/metrics")
            ):
                fail("publicMetrics.url must be an https /metrics URL")
            if not isinstance(pm["expectedUnauthenticatedStatus"], int) or not STATUS.fullmatch(
                str(pm["expectedUnauthenticatedStatus"])
            ):
                fail("public status is malformed")
            rt = cfg["retries"]
            expect_keys(rt, {"attempts", "delaySeconds"}, "retries")
            if not all(isinstance(rt[k], int) and 1 <= rt[k] <= 60 for k in rt):
                fail("retry settings must be bounded integers")
            metrics = cfg["requiredMetricFamilies"]
            if not isinstance(metrics, list) or not metrics or len(metrics) != len(set(metrics)):
                fail("requiredMetricFamilies must be nonempty and not contain duplicates")
            for metric in metrics:
                if not isinstance(metric, str) or not re.fullmatch(
                    r"[a-zA-Z_:][a-zA-Z0-9_:]*", metric
                ):
                    fail("required metric name is malformed")
            allowed = cfg["allowedApplicationLabels"]
            if not isinstance(allowed, dict):
                fail("allowedApplicationLabels must be an object")
            for k, vals in allowed.items():
                nonempty(k, "allowed label name")
                if not isinstance(vals, list) or not vals or len(vals) != len(set(vals)):
                    fail("allowed label enums must be nonempty unique arrays")
                for v in vals:
                    nonempty(v, f"allowed enum for {k}")
            forbidden = cfg["forbiddenApplicationLabels"]
            if not isinstance(forbidden, list) or len(forbidden) != len(set(forbidden)):
                fail("forbidden labels must be a unique array")
            for f in forbidden:
                nonempty(f, "forbidden label name")


def run(args):
    try:
        return subprocess.run(args, check=True, text=True, capture_output=True).stdout
    except subprocess.CalledProcessError:
        fail("kubectl command failed (details redacted)", 1)


def kjson(args):
    out = run(args)
    try:
        return json.loads(out)
    except json.JSONDecodeError:
        fail("Kubernetes API returned malformed JSON (response redacted)", 1)


def assert_context():
    ctx = run(["kubectl", "config", "current-context"]).strip()
    if ctx != "sugar-staging":
        fail(f"context mismatch: expected sugar-staging, got {ctx or '<none>'}", 3)


def appcfg(app, env):
    if env != "staging":
        fail("application metrics verification refuses production")
    inv = load_config()
    try:
        return inv["applications"][app]["environments"][env]
    except KeyError:
        fail(f"no configured app metrics contract for {app}/{env}")


def check_secret(cfg):
    data = kjson(
        ["kubectl", "-n", cfg["namespace"], "get", "secret", cfg["secret"]["name"], "-o", "json"]
    ).get("data", {})
    if cfg["secret"]["key"] not in data or not data[cfg["secret"]["key"]]:
        fail("Secret/key contract is absent or empty (value not read or printed)", 1)
    print("Application metrics Secret contract exists (value intentionally not read or printed).")


def install_secret(cfg):
    for bad in (
        "TOKEN",
        "METRICS_TOKEN",
        "TOKENPLACE_METRICS_TOKEN",
        "SUGARKUBE_APP_METRICS_TOKEN",
    ):
        if bad in __import__("os").environ:
            fail("credential environment variables are refused")
    if not sys.stdin.isatty():
        fail("ordinary stdin is refused; use an interactive controlling terminal")
    import getpass

    try:
        tty = open(os.environ.get("SUGARKUBE_APP_METRICS_TTY", "/dev/tty"), "r")
    except OSError:
        fail("an interactive controlling terminal is required")
    with tty:
        if not tty.isatty():
            fail("an interactive controlling terminal is required")
        value = getpass.getpass("Enter application metrics bearer token (input hidden): ", stream=tty)
    if not value or "\n" in value or "\0" in value:
        fail("credential is invalid (value redacted)")
    proc1 = subprocess.Popen(
        [
            "kubectl",
            "-n",
            cfg["namespace"],
            "create",
            "secret",
            "generic",
            cfg["secret"]["name"],
            f"--from-file={cfg['secret']['key']}=/dev/stdin",
            "--dry-run=client",
            "-o",
            "yaml",
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=False,
    )
    out, _ = proc1.communicate(value.encode())
    value = None
    if proc1.returncode:
        fail("Secret rendering failed (value redacted)", 1)
    proc2 = subprocess.run(
        ["kubectl", "apply", "-f", "-"],
        input=out,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    if proc2.returncode:
        fail("Secret installation failed (value redacted)", 1)
    print("Application metrics Secret installed or rotated (value not displayed).")


def prom(path):
    doc = kjson(["kubectl", "get", "--raw", PROM + path])
    if doc.get("status") != "success":
        fail("Prometheus API status was not success (response redacted)", 1)
    return doc.get("data")


def validate_metric_labels(cfg, labels):
    if not isinstance(labels, dict):
        fail("metric labels were malformed (details redacted)", 1)
    for label, value in labels.items():
        low = label.lower()
        is_standard = label in STANDARD_LABELS
        if not is_standard and label not in cfg["allowedApplicationLabels"]:
            fail("unbounded application metric label observed (details redacted)", 1)
        if not is_standard and (
            any(w in low for w in cfg["forbiddenApplicationLabels"])
            or any(w in low for w in FORBIDDEN_WORDS)
        ):
            fail("forbidden application metric label observed (details redacted)", 1)
        if (
            label in cfg["allowedApplicationLabels"]
            and value not in cfg["allowedApplicationLabels"][label]
        ):
            fail("application metric label enum mismatch (details redacted)", 1)


def verify(app, env):
    cfg = appcfg(app, env)
    assert_context()
    check_secret(cfg)
    sm = kjson(
        [
            "kubectl",
            "-n",
            cfg["namespace"],
            "get",
            "servicemonitor",
            cfg["serviceMonitorName"],
            "-o",
            "json",
        ]
    )
    endpoints = sm.get("spec", {}).get("endpoints")
    if not isinstance(endpoints, list) or len(endpoints) != 1:
        fail("ServiceMonitor must expose exactly one endpoint", 1)
    ep = endpoints[0]
    auth = ep.get("authorization", {}).get("credentials", {})
    if (
        ep.get("path") != "/metrics"
        or ep.get("interval") != cfg["serviceMonitor"]["interval"]
        or ep.get("scrapeTimeout") != cfg["serviceMonitor"]["scrapeTimeout"]
        or ep.get("relabelings") != cfg["serviceMonitor"].get("relabelings")
        or ep.get("authorization", {}).get("type") != cfg["serviceMonitor"]["authorization"]["type"]
        or auth.get("name") != cfg["secret"]["name"]
        or auth.get("key") != cfg["secret"]["key"]
    ):
        fail("ServiceMonitor endpoint/auth contract mismatch", 1)
    if (
        sm.get("spec", {}).get("selector", {}).get("matchLabels")
        != cfg["serviceMonitor"]["selectorMatchLabels"]
    ):
        fail("ServiceMonitor selector mismatch", 1)
    targets = []
    attempts = cfg["retries"]["attempts"]
    for i in range(attempts):
        active = prom("/api/v1/targets").get("activeTargets", [])
        targets = [
            t
            for t in active
            if all(t.get("labels", {}).get(k) == v for k, v in cfg["targetLabels"].items())
        ]
        if len(targets) == cfg["expectedTargetCount"] and all(
            t.get("health") == "up" for t in targets
        ):
            break
        if i + 1 < attempts:
            time.sleep(cfg["retries"]["delaySeconds"])
    if len(targets) != cfg["expectedTargetCount"] or not all(
        t.get("health") == "up" for t in targets
    ):
        fail("Prometheus targets are absent, down, or have unexpected count (details redacted)", 1)
    for t in targets:
        for k, v in cfg["targetLabels"].items():
            if t.get("labels", {}).get(k) != v:
                fail("target labels mismatch (details redacted)", 1)
    for metric in cfg["requiredMetricFamilies"]:
        result = prom("/api/v1/query?query=" + urllib.parse.quote(metric)).get("result", [])
        if not result:
            fail(f"required metric family missing: {metric}", 1)
        for sample in result:
            validate_metric_labels(cfg, sample.get("metric", {}))
    try:
        opener = urllib.request.build_opener(urllib.request.HTTPHandler)
        opener.open(cfg["publicMetrics"]["url"], timeout=10).read(0)
        got = 200
    except urllib.error.HTTPError as e:
        got = e.code
    except Exception:
        fail("public /metrics unauthenticated check failed (details redacted)", 1)
    if got != cfg["publicMetrics"]["expectedUnauthenticatedStatus"]:
        fail("public /metrics unauthenticated status mismatch (body redacted)", 1)
    print(f"Application metrics verified for {app} env={env}.")



def validate_render(app: str, env: str, input_path: str) -> None:
    inv = load_config()
    cfg = inv.get("applications", {}).get(app, {}).get("environments", {}).get(env)
    if cfg is None:
        return
    try:
        raw = sys.stdin.read() if input_path == "-" else Path(input_path).read_text(encoding="utf-8")
        converted = subprocess.run(
            ["ruby", "-ryaml", "-rjson", "-e", "puts JSON.generate(YAML.load_stream(STDIN.read).compact)"],
            input=raw,
            text=True,
            capture_output=True,
            check=True,
        ).stdout
        docs = [d for d in json.loads(converted) if isinstance(d, dict)]
    except (OSError, UnicodeError, subprocess.CalledProcessError, json.JSONDecodeError):
        fail("rendered manifests are malformed (details redacted)")
    secrets = [d for d in docs if d.get("kind") == "Secret"]
    if secrets:
        fail("rendered manifests must not include credential Secret resources")
    sms = [d for d in docs if d.get("kind") == "ServiceMonitor" and d.get("metadata", {}).get("name") == cfg["serviceMonitorName"] and d.get("metadata", {}).get("namespace") == cfg["namespace"]]
    if len(sms) != 1:
        fail("rendered manifests must include exactly one configured ServiceMonitor")
    sm = sms[0]
    labels = sm.get("metadata", {}).get("labels", {})
    if labels.get("release") != "kube-prometheus-stack":
        fail("rendered ServiceMonitor release label mismatch")
    spec = sm.get("spec", {})
    if spec.get("selector", {}).get("matchLabels") != cfg["serviceMonitor"]["selectorMatchLabels"]:
        fail("rendered ServiceMonitor selector mismatch")
    if "namespace" in cfg["serviceMonitor"].get("relabelings", [{}])[0].get("targetLabel", ""):
        fail("namespace must be supplied by discovery, not relabel replacement")
    endpoints = spec.get("endpoints")
    if not isinstance(endpoints, list) or len(endpoints) != 1:
        fail("rendered ServiceMonitor must have exactly one endpoint")
    ep = endpoints[0]
    auth = ep.get("authorization", {})
    creds = auth.get("credentials", {})
    if (ep.get("path") != cfg["serviceMonitor"]["path"] or ep.get("interval") != cfg["serviceMonitor"]["interval"] or ep.get("scrapeTimeout") != cfg["serviceMonitor"]["scrapeTimeout"] or auth.get("type") != cfg["serviceMonitor"]["authorization"]["type"] or creds.get("name") != cfg["secret"]["name"] or creds.get("key") != cfg["secret"]["key"] or ep.get("relabelings") != cfg["serviceMonitor"]["relabelings"]):
        fail("rendered ServiceMonitor endpoint/auth/relabeling contract mismatch")

def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument(
        "mode", choices=["validate", "validate-render", "secret-check", "secret-install", "verify", "verify-all"]
    )
    p.add_argument("--app")
    p.add_argument("--env", default="staging")
    p.add_argument("--input", default="-")
    a, extra = p.parse_known_args(argv)
    if extra:
        print("ERROR: unexpected arguments are refused (values redacted)", file=sys.stderr)
        return 2
    try:
        if a.mode == "validate":
            load_config()
            print("Application metrics inventory is valid.")
            return 0
        if a.mode == "validate-render":
            if not a.app:
                fail("--app is required")
            validate_render(a.app, a.env, a.input)
            print("Rendered application metrics contract is valid.")
            return 0
        if a.mode == "verify-all":
            inv = load_config()
            for app in inv["applications"]:
                verify(app, "staging")
            return 0
        if not a.app:
            fail("--app is required")
        cfg = appcfg(a.app, a.env)
        assert_context()
        if a.mode == "secret-check":
            check_secret(cfg)
        elif a.mode == "secret-install":
            install_secret(cfg)
        elif a.mode == "verify":
            verify(a.app, a.env)
        return 0
    except Error as e:
        print(e, file=sys.stderr)
        return e.code


if __name__ == "__main__":
    raise SystemExit(main())
