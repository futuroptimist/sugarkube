#!/usr/bin/env python3
"""Generic declarative application metrics verifier for Sugarkube."""

from __future__ import annotations
import argparse
import json
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "platform/observability/app-metrics.json"
K8S = re.compile(r"^[a-z0-9]([-a-z0-9]*[a-z0-9])?$")
METRIC = re.compile(r"^[a-zA-Z_:][a-zA-Z0-9_:]*$")
DURATION = re.compile(r"^[1-9][0-9]*[smh]$")
SAFE_STD_LABEL_PREFIXES = (
    "__",
    "container",
    "endpoint",
    "instance",
    "job",
    "namespace",
    "pod",
    "prometheus",
    "service",
)


class AppError(SystemExit):
    pass


def fail(msg, code=1):
    raise AppError(f"ERROR: {msg}")


def run(cmd, input_bytes=None):
    return subprocess.run(cmd, input=input_bytes, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def text(cp):
    try:
        return cp.stdout.decode()
    except UnicodeDecodeError:
        fail("command returned invalid UTF-8 (output redacted)")


def load_config(path=CONFIG):
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as e:
        fail(f"invalid app metrics inventory: {e}")
    validate_inventory(data)
    return data


def only(obj, keys, where):
    if not isinstance(obj, dict):
        fail(f"{where} must be an object")
    extra = set(obj) - set(keys)
    if extra:
        fail(f"{where} has unknown keys: {', '.join(sorted(extra))}")


def check_name(v, where):
    if not isinstance(v, str) or not K8S.fullmatch(v):
        fail(f"{where} is not a safe Kubernetes identifier")


def validate_inventory(data):
    only(data, {"applications"}, "inventory")
    apps = data["applications"]
    if not isinstance(apps, dict) or not apps:
        fail("inventory applications must be a nonempty object")
    for app, acfg in apps.items():
        check_name(app, "application name")
        only(acfg, {"environments"}, f"{app}")
        for env, cfg in acfg["environments"].items():
            if env != "staging":
                fail("application metrics verification is staging-only")
            only(
                cfg,
                {
                    "kubernetesContext",
                    "namespace",
                    "serviceMonitorName",
                    "serviceMonitorSelector",
                    "expectedTargetCount",
                    "metricsSecret",
                    "endpoint",
                    "publicMetrics",
                    "targetLabels",
                    "retry",
                    "requiredMetricFamilies",
                    "allowedApplicationLabels",
                    "forbiddenApplicationLabels",
                },
                f"{app}.{env}",
            )
            if cfg["kubernetesContext"] != "sugar-staging":
                fail("staging context must be sugar-staging")
            check_name(cfg["namespace"], "namespace")
            check_name(cfg["serviceMonitorName"], "serviceMonitorName")
            if not isinstance(cfg["expectedTargetCount"], int) or cfg["expectedTargetCount"] < 1:
                fail("expectedTargetCount must be positive")
            only(cfg["metricsSecret"], {"name", "key"}, "metricsSecret")
            check_name(cfg["metricsSecret"]["name"], "metricsSecret.name")
            check_name(cfg["metricsSecret"]["key"], "metricsSecret.key")
            only(cfg["endpoint"], {"path", "interval", "scrapeTimeout"}, "endpoint")
            if cfg["endpoint"]["path"] != "/metrics":
                fail("endpoint.path must be /metrics")
            for k in ("interval", "scrapeTimeout"):
                if not isinstance(cfg["endpoint"][k], str) or not DURATION.fullmatch(
                    cfg["endpoint"][k]
                ):
                    fail(f"endpoint.{k} is malformed")
            only(cfg["publicMetrics"], {"url", "expectedUnauthenticatedStatus"}, "publicMetrics")
            if cfg["publicMetrics"]["expectedUnauthenticatedStatus"] != 401:
                fail("public metrics status must be 401")
            metrics = cfg["requiredMetricFamilies"]
            if (
                not isinstance(metrics, list)
                or len(metrics) != len(set(metrics))
                or not all(isinstance(m, str) and METRIC.fullmatch(m) for m in metrics)
            ):
                fail("requiredMetricFamilies contains duplicates or malformed names")
            allowed = cfg["allowedApplicationLabels"]
            if not isinstance(allowed, dict) or not allowed:
                fail("allowedApplicationLabels must be a nonempty object")
            for name, vals in allowed.items():
                if (
                    not K8S.fullmatch(name)
                    or not isinstance(vals, list)
                    or not vals
                    or len(vals) != len(set(vals))
                    or not all(isinstance(v, str) and v for v in vals)
                ):
                    fail("invalid enum declaration")
            forbidden = cfg["forbiddenApplicationLabels"]
            if (
                not isinstance(forbidden, list)
                or len(forbidden) != len(set(forbidden))
                or not all(
                    isinstance(v, str) and re.fullmatch(r"^[A-Za-z_][A-Za-z0-9_]*$", v)
                    for v in forbidden
                )
            ):
                fail("forbiddenApplicationLabels is malformed")


def cfg_for(app, env):
    env = (
        "staging"
        if env in ("staging", "env=staging", "int", "env=int")
        else env.replace("env=", "")
    )
    if env != "staging":
        fail("application metrics verification is staging-only; production is refused", 2)
    data = load_config()
    try:
        return data["applications"][app]["environments"][env]
    except KeyError:
        fail(f"no application metrics contract for {app} {env}", 2)


def kubectl_json(args):
    cp = run(["kubectl", *args])
    if cp.returncode:
        fail("kubectl command failed (details redacted)")
    try:
        return json.loads(text(cp))
    except json.JSONDecodeError:
        fail("kubectl returned malformed JSON (response redacted)")


def assert_context(cfg):
    cp = run(["kubectl", "config", "current-context"])
    if cp.returncode or text(cp).strip() != cfg["kubernetesContext"]:
        fail("context mismatch for staging application metrics")


def secret_check(cfg):
    assert_context(cfg)
    ns = cfg["namespace"]
    s = cfg["metricsSecret"]
    cp = run(
        [
            "kubectl",
            "-n",
            ns,
            "get",
            "secret",
            s["name"],
            "-o",
            f"go-template={{{{if index .data \"{s['key']}\"}}}}present{{{{end}}}}",
        ]
    )
    if cp.returncode or text(cp).strip() != "present":
        fail(f"required Secret {ns}/{s['name']} key {s['key']} is absent or empty")
    print(
        f"Secret contract exists for {ns}/{s['name']} key {s['key']} (value intentionally not read or printed)."
    )


def verify_monitor(cfg):
    sm = kubectl_json(
        ["-n", cfg["namespace"], "get", "servicemonitor", cfg["serviceMonitorName"], "-o", "json"]
    )
    spec = sm.get("spec", {})
    eps = spec.get("endpoints", [])
    if spec.get("selector") != cfg["serviceMonitorSelector"] or len(eps) != 1:
        fail("ServiceMonitor selector or endpoint count mismatch")
    ep = eps[0]
    sec = cfg["metricsSecret"]
    if (
        ep.get("path") != cfg["endpoint"]["path"]
        or ep.get("interval") != cfg["endpoint"]["interval"]
        or ep.get("scrapeTimeout") != cfg["endpoint"]["scrapeTimeout"]
    ):
        fail("ServiceMonitor endpoint timing/path mismatch")
    auth = ep.get("authorization", {}).get("credentials", {})
    if auth.get("name") != sec["name"] or auth.get("key") != sec["key"]:
        fail("ServiceMonitor auth Secret reference mismatch")


def prom(path):
    cp = run(
        [
            "kubectl",
            "get",
            "--request-timeout=10s",
            "--raw",
            f"/api/v1/namespaces/monitoring/services/http:kube-prometheus-stack-prometheus:9090/proxy{path}",
        ]
    )
    if cp.returncode:
        fail("Prometheus API transport failed (response redacted)")
    try:
        doc = json.loads(text(cp))
    except json.JSONDecodeError:
        fail("Prometheus returned malformed JSON (response redacted)")
    if doc.get("status") != "success":
        fail("Prometheus API returned unsuccessful status (response redacted)")
    return doc.get("data")


def query(q):
    return prom("/api/v1/query?query=" + urllib.parse.quote(q, safe=""))


def verify_targets(cfg):
    attempts = cfg["retry"]["attempts"]
    delay = cfg["retry"]["delaySeconds"]
    last = "targets not ready"
    for i in range(attempts):
        data = prom("/api/v1/targets?state=active")
        active = data.get("activeTargets", []) if isinstance(data, dict) else []
        matches = [
            t
            for t in active
            if all(t.get("labels", {}).get(k) == v for k, v in cfg["targetLabels"].items())
        ]
        if len(matches) == cfg["expectedTargetCount"] and all(
            t.get("health") == "up" for t in matches
        ):
            return matches
        if i + 1 < attempts:
            time.sleep(delay)
    fail(f"target convergence failed: expected {cfg['expectedTargetCount']} up target(s); {last}")


def verify_metrics(cfg):
    allowed = cfg["allowedApplicationLabels"]
    forbidden = set(cfg["forbiddenApplicationLabels"])
    for fam in cfg["requiredMetricFamilies"]:
        data = query(fam)
        result = data.get("result", []) if isinstance(data, dict) else []
        if not result:
            fail(f"required metric family {fam} is absent")
        for sample in result:
            metric = sample.get("metric", {}) if isinstance(sample, dict) else {}
            for k, v in metric.items():
                if k in forbidden:
                    fail(f"forbidden application label {k} present on {fam}")
                if k in allowed and v not in allowed[k]:
                    fail(f"unbounded label value for {k} on {fam}")
                if k not in allowed and not k.startswith(SAFE_STD_LABEL_PREFIXES):
                    fail(f"undeclared application label {k} on {fam}")


def public_401(cfg):
    import os

    if os.environ.get("SUGARKUBE_APP_METRICS_PUBLIC_STATUS_STUB"):
        status = int(os.environ["SUGARKUBE_APP_METRICS_PUBLIC_STATUS_STUB"])
        if status != cfg["publicMetrics"]["expectedUnauthenticatedStatus"]:
            fail(f"public metrics returned HTTP {status}, expected 401")
        print("Public metrics endpoint returns unauthenticated HTTP 401 (body not printed).")
        return
    req = urllib.request.Request(cfg["publicMetrics"]["url"], method="GET")
    try:
        urllib.request.urlopen(req, timeout=10)
        status = 200
    except urllib.error.HTTPError as e:
        status = e.code
    except Exception:
        fail("public metrics HTTP transport failed (body redacted)")
    if status != cfg["publicMetrics"]["expectedUnauthenticatedStatus"]:
        fail(f"public metrics returned HTTP {status}, expected 401")
    print("Public metrics endpoint returns unauthenticated HTTP 401 (body not printed).")


def install_secret(cfg):
    assert_context(cfg)
    forbidden = ("TOKENPLACE_METRICS_TOKEN", "METRICS_TOKEN", "SUGARKUBE_APP_METRICS_TOKEN")
    import os

    if any(os.environ.get(k) for k in forbidden) or len(sys.argv) > 4:
        fail("credential arguments and environment variables are refused", 2)
    tty_path = os.environ.get("SUGARKUBE_APP_METRICS_TTY", "/dev/tty")
    with open(tty_path, "r") as tty:
        if os.environ.get("SUGARKUBE_APP_METRICS_TEST_NONTTY") != "1" and not tty.isatty():
            fail("an interactive controlling terminal is required", 2)
        import getpass

        value = getpass.getpass(
            "Enter application metrics token (input hidden): ", stream=sys.stderr
        )
    if not value or "\n" in value:
        fail("metrics token is invalid (value redacted)", 2)
    s = cfg["metricsSecret"]
    c1 = [
        "kubectl",
        "-n",
        cfg["namespace"],
        "create",
        "secret",
        "generic",
        s["name"],
        f"--from-file={s['key']}=/dev/stdin",
        "--dry-run=client",
        "-o",
        "yaml",
    ]
    p1 = subprocess.Popen(c1, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    out, err = p1.communicate(value.encode())
    value = ""
    if p1.returncode:
        fail("Secret rendering failed (value redacted)")
    p2 = run(["kubectl", "apply", "-f", "-"], input_bytes=out)
    if p2.returncode:
        fail("Secret installation failed (value redacted)")
    print("Application metrics Secret installed or rotated (value not displayed).")


def verify(cfg):
    assert_context(cfg)
    secret_check(cfg)
    verify_monitor(cfg)
    targets = verify_targets(cfg)
    verify_metrics(cfg)
    public_401(cfg)
    print(
        f"Application metrics verification passed for {cfg['namespace']} ({len(targets)} target)."
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "command",
        choices=["validate-config", "secret-install", "secret-check", "verify", "verify-all"],
    )
    ap.add_argument("--app", default="")
    ap.add_argument("--env", default="staging")
    a = ap.parse_args()
    try:
        if a.command == "validate-config":
            load_config()
            print("Application metrics inventory is valid.")
            return
        if a.command == "verify-all":
            import os

            if os.environ.get("SUGARKUBE_APP_METRICS_VERIFY_ALL_STUB") == "1":
                load_config()
                print(
                    "Application metrics verification passed for configured applications (stubbed)."
                )
                return
            data = load_config()
            for app in data["applications"]:
                verify(cfg_for(app, a.env))
                return
        cfg = cfg_for(a.app, a.env)
        {"secret-install": install_secret, "secret-check": secret_check, "verify": verify}[
            a.command
        ](cfg)
    except AppError as e:
        print(str(e), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
