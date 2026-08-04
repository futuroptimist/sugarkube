#!/usr/bin/env python3
"""Generic verifier for declaratively configured authenticated app metrics."""

from __future__ import annotations
import argparse
import json
import re
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "platform/observability/app-metrics.json"
SAFE = re.compile(r"^[a-z0-9]([-a-z0-9]*[a-z0-9])?$")
LABEL = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")
DUR = re.compile(r"^[1-9][0-9]*s$")
METRIC = re.compile(r"^[a-zA-Z_:][a-zA-Z0-9_:]*$")
STANDARD = {
    "job",
    "namespace",
    "service",
    "endpoint",
    "container",
    "prometheus",
    "prometheus_replica",
    "pod",
    "instance",
}


class Error(Exception):
    pass


def die(msg, code=2):
    print(f"ERROR: {msg}", file=sys.stderr)
    return code


def load(path=CONFIG):
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception as e:
        raise Error("malformed app metrics inventory (details redacted)") from e
    if set(data) != {"applications"} or not isinstance(data["applications"], dict):
        raise Error("inventory must contain only applications")
    for app, ad in data["applications"].items():
        if not SAFE.fullmatch(app):
            raise Error("unsafe application name")
        if set(ad) != {"environments"} or set(ad["environments"]) != {"staging"}:
            raise Error("only staging app metrics are supported")
        c = ad["environments"]["staging"]
        allowed = {
            "kubernetesContext",
            "namespace",
            "serviceMonitorName",
            "expectedTargetCount",
            "secret",
            "endpoint",
            "targetLabels",
            "retries",
            "requiredMetricFamilies",
            "allowedApplicationLabels",
            "forbiddenApplicationLabels",
        }
        if set(c) != allowed:
            raise Error(f"unknown app metrics keys for {app}")
        for k in ("namespace", "serviceMonitorName"):
            if not SAFE.fullmatch(c[k]):
                raise Error("unsafe Kubernetes identifier")
        if c["kubernetesContext"] != "sugar-staging":
            raise Error("staging context must be sugar-staging")
        if not isinstance(c["expectedTargetCount"], int) or c["expectedTargetCount"] < 1:
            raise Error("invalid expected target count")
        if (
            set(c["secret"]) != {"name", "key"}
            or not SAFE.fullmatch(c["secret"]["name"])
            or not SAFE.fullmatch(c["secret"]["key"])
        ):
            raise Error("invalid secret contract")
        if set(c["endpoint"]) != {
            "path",
            "interval",
            "scrapeTimeout",
            "publicUrl",
            "expectedUnauthenticatedStatus",
        }:
            raise Error("invalid endpoint declaration")
        if (
            c["endpoint"]["path"] != "/metrics"
            or not DUR.fullmatch(c["endpoint"]["interval"])
            or not DUR.fullmatch(c["endpoint"]["scrapeTimeout"])
        ):
            raise Error("invalid endpoint timing/path")
        if c["endpoint"]["expectedUnauthenticatedStatus"] != 401:
            raise Error("invalid unauthenticated status")
        if set(c["targetLabels"]) != {"app", "environment", "release", "cluster"} or any(
            not isinstance(v, str) or not v for v in c["targetLabels"].values()
        ):
            raise Error("invalid canonical target labels")
        mets = c["requiredMetricFamilies"]
        if len(mets) != len(set(mets)) or any(not METRIC.fullmatch(m) for m in mets):
            raise Error("duplicate or malformed metric name")
        enums = c["allowedApplicationLabels"]
        if not isinstance(enums, dict) or any(
            not LABEL.fullmatch(k)
            or not isinstance(v, list)
            or not v
            or len(v) != len(set(v))
            or any(not isinstance(x, str) or not x or len(x) > 100 for x in v)
            for k, v in enums.items()
        ):
            raise Error("invalid enum declarations")
        forbidden = c["forbiddenApplicationLabels"]
        if (
            not isinstance(forbidden, list)
            or len(forbidden) != len(set(forbidden))
            or any(not LABEL.fullmatch(x) for x in forbidden)
        ):
            raise Error("invalid forbidden label declarations")
    return data


def cfg(app, env, path=CONFIG):
    env = (
        "staging"
        if env in ("staging", "env=staging", "int", "env=int")
        else env.replace("env=", "")
    )
    if env != "staging":
        raise Error("production app metrics verification is refused; pass env=staging")
    d = load(path)["applications"]
    if app not in d:
        raise Error("app is not configured for metrics verification")
    return d[app]["environments"][env]


def run(cmd):
    p = subprocess.run(cmd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if p.returncode:
        raise Error("command failed (details redacted)")
    return p.stdout


def secret_install(app, env):
    c = cfg(app, env)
    if any(
        k
        for k in ("TOKEN", "METRICS_TOKEN", "TOKENPLACE_METRICS_TOKEN")
        if __import__("os").environ.get(k)
    ):
        raise Error("credential environment variables are refused")
    if not sys.stdin.isatty():
        raise Error("an interactive controlling terminal is required")
    import getpass

    v = getpass.getpass(
        "Enter application metrics bearer token (input hidden): ", stream=sys.stderr
    )
    if not v or "\n" in v:
        raise Error("credential is invalid (value redacted)")
    p1 = subprocess.Popen(
        [
            "kubectl",
            "-n",
            c["namespace"],
            "create",
            "secret",
            "generic",
            c["secret"]["name"],
            f'--from-file={c["secret"]["key"]}=/dev/stdin',
            "--dry-run=client",
            "-o",
            "yaml",
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    out, err = p1.communicate(v)
    v = None
    if p1.returncode:
        raise Error("Secret rendering failed (value redacted)")
    p2 = subprocess.run(
        ["kubectl", "apply", "-f", "-"],
        input=out,
        text=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )
    if p2.returncode:
        raise Error("Secret installation failed (value redacted)")
    print("Application metrics Secret installed or rotated (value not displayed).")


def secret_check(app, env):
    c = cfg(app, env)
    out = run(
        [
            "kubectl",
            "-n",
            c["namespace"],
            "get",
            "secret",
            c["secret"]["name"],
            "-o",
            f'go-template={{{{if index .data "{c["secret"]["key"]}"}}}}present{{{{end}}}}',
        ]
    )
    if out != "present":
        raise Error(
            "required Secret/key is absent or empty (value intentionally not read or printed)"
        )
    print("Application metrics Secret contract exists (value intentionally not read or printed).")


def verify(app, env):
    c = cfg(app, env)
    if run(["kubectl", "config", "current-context"]).strip() != c["kubernetesContext"]:
        raise Error("context mismatch for staging app metrics")
    secret_check(app, env)
    sm = json.loads(
        run(
            [
                "kubectl",
                "-n",
                c["namespace"],
                "get",
                "servicemonitor",
                c["serviceMonitorName"],
                "-o",
                "json",
            ]
        )
    )
    ep = sm["spec"]["endpoints"][0]
    auth = ep.get("authorization", {}).get("credentials", {})
    if (
        ep.get("path") != c["endpoint"]["path"]
        or ep.get("interval") != c["endpoint"]["interval"]
        or ep.get("scrapeTimeout") != c["endpoint"]["scrapeTimeout"]
        or auth.get("name") != c["secret"]["name"]
        or auth.get("key") != c["secret"]["key"]
    ):
        raise Error("ServiceMonitor endpoint/auth contract mismatch")
    try:
        urllib.request.urlopen(c["endpoint"]["publicUrl"], timeout=10)
    except Exception as e:
        if getattr(e, "code", None) != c["endpoint"]["expectedUnauthenticatedStatus"]:
            raise Error("public metrics endpoint returned unexpected unauthenticated status")
    for i in range(c["retries"]["attempts"]):
        targets = json.loads(
            run(
                [
                    "kubectl",
                    "get",
                    "--raw",
                    "/api/v1/namespaces/monitoring/services/http:kube-prometheus-stack-prometheus:9090/proxy/api/v1/targets",
                ]
            )
        )
        if targets.get("status") != "success":
            raise Error("Prometheus API status was unsuccessful")
        active = targets.get("data", {}).get("activeTargets", [])
        matched = [
            t
            for t in active
            if all(t.get("labels", {}).get(k) == v for k, v in c["targetLabels"].items())
        ]
        if len(matched) == c["expectedTargetCount"] and all(
            t.get("health") == "up" for t in matched
        ):
            break
        if i + 1 == c["retries"]["attempts"]:
            raise Error("configured targets are absent, down, or partial (responses redacted)")
        time.sleep(c["retries"]["delaySeconds"])
    series = json.loads(
        run(
            [
                "kubectl",
                "get",
                "--raw",
                '/api/v1/namespaces/monitoring/services/http:kube-prometheus-stack-prometheus:9090/proxy/api/v1/series?match[]={__name__=~".*"}',
            ]
        )
    )
    if series.get("status") != "success" or not isinstance(series.get("data"), list):
        raise Error("Prometheus series response is structurally invalid")
    names = {s.get("__name__") for s in series["data"]}
    missing = [m for m in c["requiredMetricFamilies"] if m not in names]
    if missing:
        raise Error("required metric families are missing")
    forbidden = set(c["forbiddenApplicationLabels"])
    for s in series["data"]:
        for k, v in s.items():
            if k in forbidden:
                raise Error("forbidden application label present")
            if k in c["allowedApplicationLabels"] and v not in c["allowedApplicationLabels"][k]:
                raise Error("unbounded application label value present")
    print(f"Application metrics verified for {app} staging.")


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "command",
        choices=["validate-config", "secret-install", "secret-check", "verify", "verify-all"],
    )
    ap.add_argument("--app")
    ap.add_argument("--env", default="staging")
    ap.add_argument("--config", default=str(CONFIG))
    a = ap.parse_args(argv)
    try:
        if a.command == "validate-config":
            load(Path(a.config))
            print("Application metrics inventory is valid.")
            return 0
        if a.command == "verify-all":
            for app in load(Path(a.config))["applications"]:
                verify(app, a.env)
        elif a.command == "secret-install":
            secret_install(a.app, a.env)
        elif a.command == "secret-check":
            secret_check(a.app, a.env)
        elif a.command == "verify":
            verify(a.app, a.env)
        return 0
    except (Error, json.JSONDecodeError, UnicodeError, KeyError, TypeError) as e:
        return die(str(e))


if __name__ == "__main__":
    sys.exit(main())
