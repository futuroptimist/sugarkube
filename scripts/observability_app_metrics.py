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
    "le",
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
                    "derivedApplicationLabels",
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
                expect_keys(relabeling, {"action", "targetLabel", "replacement"}, f"serviceMonitor.relabelings[{idx}]")
                if relabeling["action"] != "replace":
                    fail("serviceMonitor.relabelings action must be replace")
                nonempty(relabeling["targetLabel"], "relabeling targetLabel")
                nonempty(relabeling["replacement"], "relabeling replacement")
            labels = cfg["targetLabels"]
            if not isinstance(labels, dict) or not labels:
                fail("targetLabels must be a nonempty object")
            for k, v in labels.items():
                nonempty(k, "target label name")
                nonempty(v, "target label value")
            mapping = {r["targetLabel"]: r["replacement"] for r in relabelings}
            if len(mapping) != len(relabelings):
                fail("serviceMonitor.relabelings target labels must be unique")
            required_mapping = {
                "app": app,
                "environment": env,
                "release": cfg["serviceMonitorName"],
                "cluster": labels.get("cluster"),
            }
            if mapping != required_mapping:
                fail("serviceMonitor.relabelings must map app, environment, release, and cluster exactly")
            if "namespace" in mapping:
                fail("namespace must be supplied by discovery, not relabel replacement")
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
            derived = cfg["derivedApplicationLabels"]
            if not isinstance(derived, dict):
                fail("derivedApplicationLabels must be an object")
            overlap = set(allowed) & set(derived)
            if overlap:
                fail("static and derived application labels conflict")
            for label, source in derived.items():
                nonempty(label, "derived label name")
                expect_keys(source, {"workload", "container", "env", "normalizer"}, f"derivedApplicationLabels.{label}")
                expect_keys(source["workload"], {"kind", "name"}, f"derivedApplicationLabels.{label}.workload")
                if source["workload"]["kind"] != "Deployment":
                    fail("derived workload kind is unsupported")
                name(source["workload"]["name"], "derived workload name")
                name(source["container"], "derived container")
                if not isinstance(source["env"], str) or not re.fullmatch(r"[A-Z_][A-Z0-9_]{0,62}", source["env"]):
                    fail("derived environment variable name is unsafe")
                if source["normalizer"] != "identity":
                    fail("derived normalizer is unsupported")
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


def normalize_derived_value(value: str, normalizer: str) -> str:
    if normalizer != "identity":
        fail("derived normalizer is unsupported")
    if not isinstance(value, str) or not value or not SAFE_VALUE.fullmatch(value):
        fail("derived build label value is malformed (details redacted)", 1)
    return value


def find_env_value(workload: dict[str, Any], source: dict[str, Any]) -> str:
    containers = workload.get("spec", {}).get("template", {}).get("spec", {}).get("containers")
    if not isinstance(containers, list):
        fail("workload source contract is malformed (details redacted)", 1)
    matches = [c for c in containers if isinstance(c, dict) and c.get("name") == source["container"]]
    if len(matches) != 1:
        fail("workload container source is absent or ambiguous (details redacted)", 1)
    env_entries = matches[0].get("env")
    if not isinstance(env_entries, list):
        fail("workload environment source is absent (details redacted)", 1)
    found = []
    for entry in env_entries:
        if isinstance(entry, dict) and entry.get("name") == source["env"]:
            found.append(entry)
    if len(found) != 1:
        fail("workload environment source is absent or duplicated (details redacted)", 1)
    entry = found[0]
    if "valueFrom" in entry or "value" not in entry:
        fail("workload environment source must be a literal value (details redacted)", 1)
    return normalize_derived_value(entry["value"], source["normalizer"])


def derive_build_labels_from_docs(cfg, docs):
    labels = {}
    for label, source in cfg.get("derivedApplicationLabels", {}).items():
        workload = source["workload"]
        matches = [
            d for d in docs
            if d.get("kind") == workload["kind"]
            and d.get("metadata", {}).get("name") == workload["name"]
            and d.get("metadata", {}).get("namespace", cfg["namespace"]) == cfg["namespace"]
        ]
        if len(matches) != 1:
            fail("rendered workload source is absent or ambiguous (details redacted)", 1)
        labels[label] = find_env_value(matches[0], source)
    return labels


def derive_build_labels_live(cfg):
    docs = []
    seen = set()
    for source in cfg.get("derivedApplicationLabels", {}).values():
        workload = source["workload"]
        key = (workload["kind"], workload["name"])
        if key in seen:
            continue
        seen.add(key)
        docs.append(kjson(["kubectl", "-n", cfg["namespace"], "get", workload["kind"].lower(), workload["name"], "-o", "json"]))
    return derive_build_labels_from_docs(cfg, docs)


def validate_metric_labels(cfg, labels, derived_values=None):
    derived_values = derived_values or {}
    if not isinstance(labels, dict):
        fail("metric labels were malformed (details redacted)", 1)
    for label, value in labels.items():
        low = label.lower()
        is_standard = label in STANDARD_LABELS
        if not is_standard and label not in cfg["allowedApplicationLabels"] and label not in cfg.get("derivedApplicationLabels", {}):
            fail("unbounded application metric label observed (details redacted)", 1)
        if not is_standard and (
            any(w in low for w in cfg["forbiddenApplicationLabels"])
            or any(w in low for w in FORBIDDEN_WORDS)
        ):
            fail("forbidden application metric label observed (details redacted)", 1)
        if label in cfg["allowedApplicationLabels"] and value not in cfg["allowedApplicationLabels"][label]:
            fail("application metric label enum mismatch (details redacted)", 1)
        if label in cfg.get("derivedApplicationLabels", {}) and value != derived_values.get(label):
            fail("derived application metric label mismatch (details redacted)", 1)


def prometheus_label_escape(value: str) -> str:
    return value.replace('\\', '\\\\').replace('"', '\\"').replace('\n', '\\n')


def promql_selector(labels: dict[str, str]) -> str:
    parts = []
    for key in sorted(labels):
        if not re.fullmatch(r"[a-zA-Z_][a-zA-Z0-9_]*", key):
            fail("target label name cannot be used in PromQL selector")
        parts.append(f'{key}="{prometheus_label_escape(labels[key])}"')
    return "{" + ",".join(parts) + "}"


def metric_family_from_series(name: str) -> str:
    for suffix in ("_bucket", "_sum", "_count"):
        if name.endswith(suffix):
            return name[: -len(suffix)]
    return name


def target_discovery_identities(cfg: dict[str, Any]) -> set[str]:
    ns = cfg["namespace"]
    sm = cfg["serviceMonitorName"]
    return {f"serviceMonitor/{ns}/{sm}/0", f"{ns}/{sm}/0"}


def is_relevant_target(cfg: dict[str, Any], target: dict[str, Any]) -> bool:
    labels = target.get("labels")
    discovered = target.get("discoveredLabels")
    if not isinstance(labels, dict) or not isinstance(discovered, dict):
        fail("Prometheus target response is structurally invalid (details redacted)", 1)
    identities = target_discovery_identities(cfg)
    for field in (target.get("scrapePool"), target.get("scrapeConfig"), labels.get("job"), discovered.get("job")):
        if isinstance(field, str) and field in identities:
            return True
    if (
        discovered.get("__meta_kubernetes_namespace") == cfg["namespace"]
        and discovered.get("__meta_prometheus_operator_service_monitor_name") == cfg["serviceMonitorName"]
    ):
        return True
    return False


def target_state_converged(cfg: dict[str, Any], targets: list[dict[str, Any]]) -> bool:
    if len(targets) != cfg["expectedTargetCount"]:
        return False
    if not all(t.get("health") == "up" for t in targets):
        return False
    for target in targets:
        labels = target.get("labels")
        if not isinstance(labels, dict):
            fail("Prometheus target response is structurally invalid (details redacted)", 1)
        for key, expected in cfg["targetLabels"].items():
            if labels.get(key) != expected:
                return False
    return True


def query_required_families(cfg: dict[str, Any], derived_values: dict[str, str]) -> set[str]:
    selector = promql_selector(cfg["targetLabels"])
    found: set[str] = set()
    for metric in cfg["requiredMetricFamilies"]:
        candidates = [metric, f"{metric}_bucket", f"{metric}_sum", f"{metric}_count"]
        for candidate in candidates:
            result = prom("/api/v1/query?query=" + urllib.parse.quote(candidate + selector)).get("result", [])
            if not isinstance(result, list):
                fail("Prometheus query response is structurally invalid (details redacted)", 1)
            for sample in result:
                if not isinstance(sample, dict):
                    fail("Prometheus query response is structurally invalid (details redacted)", 1)
                sample_labels = sample.get("metric")
                validate_metric_labels(cfg, sample_labels, derived_values)
                series_name = sample_labels.get("__name__") if isinstance(sample_labels, dict) else None
                if isinstance(series_name, str) and metric_family_from_series(series_name) == metric:
                    found.add(metric)
    return found

def verify(app, env):
    cfg = appcfg(app, env)
    assert_context()
    check_secret(cfg)
    derived_values = derive_build_labels_live(cfg)
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
        data = prom("/api/v1/targets")
        active = data.get("activeTargets") if isinstance(data, dict) else None
        if not isinstance(active, list):
            fail("Prometheus targets response is structurally invalid (details redacted)", 1)
        if not all(isinstance(t, dict) for t in active):
            fail("Prometheus target response is structurally invalid (details redacted)", 1)
        targets = [t for t in active if is_relevant_target(cfg, t)]
        if target_state_converged(cfg, targets):
            break
        if i + 1 < attempts:
            time.sleep(cfg["retries"]["delaySeconds"])
    if not target_state_converged(cfg, targets):
        fail("Prometheus targets are absent, down, mislabeled, or have unexpected count (details redacted)", 1)

    required = set(cfg["requiredMetricFamilies"])
    found: set[str] = set()
    for i in range(attempts):
        found = query_required_families(cfg, derived_values)
        if found == required:
            break
        if i + 1 < attempts:
            time.sleep(cfg["retries"]["delaySeconds"])
    missing = required - found
    if missing:
        fail(f"required metric family missing: {sorted(missing)[0]}", 1)
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


def load_rendered_docs(input_path: str) -> list[dict[str, Any]]:
    try:
        raw = sys.stdin.read() if input_path == "-" else Path(input_path).read_text(encoding="utf-8")
        converted = subprocess.run(
            ["ruby", "-ryaml", "-rjson", "-e", "puts JSON.generate(YAML.load_stream(STDIN.read).compact)"],
            input=raw,
            text=True,
            capture_output=True,
            check=True,
        ).stdout
        return [d for d in json.loads(converted) if isinstance(d, dict)]
    except (OSError, UnicodeError, subprocess.CalledProcessError, json.JSONDecodeError):
        fail("rendered manifests are malformed (details redacted)")


def validate_render(app: str, env: str, input_path: str, release_namespace: str = "", release_name: str = "") -> None:
    inv = load_config()
    cfg = inv.get("applications", {}).get(app, {}).get("environments", {}).get(env)
    if cfg is None:
        if input_path == "-":
            sys.stdin.read()
        return
    docs = load_rendered_docs(input_path)
    secrets = [d for d in docs if d.get("kind") == "Secret"]
    if secrets:
        fail("rendered manifests must not include credential Secret resources")
    named_sms = [d for d in docs if d.get("kind") == "ServiceMonitor" and d.get("metadata", {}).get("name") == cfg["serviceMonitorName"]]
    sms = []
    for candidate in named_sms:
        rendered_ns = candidate.get("metadata", {}).get("namespace")
        if rendered_ns == cfg["namespace"] or (rendered_ns is None and release_namespace == cfg["namespace"]):
            sms.append(candidate)
    if len(sms) != 1:
        fail("rendered manifests must include exactly one configured ServiceMonitor")
    derive_build_labels_from_docs(cfg, docs)
    sm = sms[0]
    labels = sm.get("metadata", {}).get("labels", {})
    if labels.get("release") != "kube-prometheus-stack":
        fail("rendered ServiceMonitor release label mismatch")
    spec = sm.get("spec", {})
    if spec.get("namespaceSelector", {}).get("matchNames") != [cfg["namespace"]]:
        fail("rendered ServiceMonitor namespace selector mismatch")
    if spec.get("selector", {}).get("matchLabels") != cfg["serviceMonitor"]["selectorMatchLabels"]:
        fail("rendered ServiceMonitor selector mismatch")
    for relabeling in cfg["serviceMonitor"].get("relabelings", []):
        if relabeling.get("targetLabel") == "namespace":
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
    p.add_argument("--release-namespace", default="")
    p.add_argument("--release-name", default="")
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
            validate_render(a.app, a.env, a.input, a.release_namespace, a.release_name)
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
