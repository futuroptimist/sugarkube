#!/usr/bin/env python3
"""Declarative application metrics verifier for Sugarkube observability."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INVENTORY = ROOT / "docs" / "observability-app-metrics.json"
K8S = re.compile(r"^[a-z0-9]([-a-z0-9]*[a-z0-9])?$")
METRIC = re.compile(r"^[a-zA-Z_:][a-zA-Z0-9_:]*$")
DURATION = re.compile(r"^[1-9][0-9]*[smh]$")
SAFE_STD_LABELS = {
    "__name__",
    "container",
    "endpoint",
    "instance",
    "job",
    "namespace",
    "pod",
    "service",
    "prometheus",
    "prometheus_replica",
    "pod_template_hash",
    "app_kubernetes_io_instance",
    "app_kubernetes_io_name",
    "app_kubernetes_io_component",
}
REDACT = "<redacted>"


class ConfigError(ValueError):
    pass


class VerifyError(RuntimeError):
    pass


def normalize_env(env: str) -> str:
    while env.startswith("env="):
        env = env[4:]
    if env == "int":
        env = "staging"
    if env != "staging":
        raise ConfigError("application metrics verification is staging-only")
    return env


def _dict(v: Any, name: str) -> dict[str, Any]:
    if not isinstance(v, dict):
        raise ConfigError(f"{name} must be an object")
    return v


def _keys(obj: dict[str, Any], allowed: set[str], name: str) -> None:
    extra = set(obj) - allowed
    if extra:
        raise ConfigError(f"unknown {name} key(s): {', '.join(sorted(extra))}")


def _k8s(v: Any, name: str) -> str:
    if not isinstance(v, str) or not K8S.fullmatch(v):
        raise ConfigError(f"{name} is not a safe Kubernetes identifier")
    return v


def _unique_strings(v: Any, name: str, pattern: re.Pattern[str] | None = None) -> list[str]:
    if not isinstance(v, list) or not all(isinstance(x, str) and x for x in v):
        raise ConfigError(f"{name} must be a list of nonempty strings")
    if len(v) != len(set(v)):
        raise ConfigError(f"{name} contains duplicate values")
    if pattern:
        bad = [x for x in v if not pattern.fullmatch(x)]
        if bad:
            raise ConfigError(f"{name} contains malformed value(s)")
    return v


def load_inventory(path: Path = DEFAULT_INVENTORY) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as e:
        raise ConfigError("malformed observability app metrics inventory") from e
    _keys(_dict(data, "inventory"), {"applications"}, "inventory")
    apps = _dict(data["applications"], "applications")
    for app, envs in apps.items():
        _k8s(app, "app")
        for env, cfg in _dict(envs, f"{app} environments").items():
            normalize_env(env)
            validate_config(_dict(cfg, f"{app}/{env}"))
    return data


def validate_config(cfg: dict[str, Any]) -> None:
    _keys(
        cfg,
        {
            "kubernetesContext",
            "namespace",
            "serviceMonitorName",
            "expectedTargetCount",
            "secret",
            "endpoint",
            "publicMetrics",
            "canonicalTargetLabels",
            "retries",
            "requiredMetricFamilies",
            "allowedApplicationLabels",
            "forbiddenApplicationLabels",
        },
        "app metrics config",
    )
    if cfg.get("kubernetesContext") != "sugar-staging":
        raise ConfigError("kubernetesContext must be sugar-staging")
    _k8s(cfg.get("namespace"), "namespace")
    _k8s(cfg.get("serviceMonitorName"), "serviceMonitorName")
    if not isinstance(cfg.get("expectedTargetCount"), int) or cfg["expectedTargetCount"] < 1:
        raise ConfigError("expectedTargetCount must be positive")
    secret = _dict(cfg.get("secret"), "secret")
    _keys(secret, {"name", "key"}, "secret")
    _k8s(secret.get("name"), "secret.name")
    _k8s(secret.get("key"), "secret.key")
    endpoint = _dict(cfg.get("endpoint"), "endpoint")
    _keys(endpoint, {"path", "interval", "scrapeTimeout"}, "endpoint")
    if endpoint.get("path") != "/metrics":
        raise ConfigError("endpoint.path must be /metrics")
    for k in ("interval", "scrapeTimeout"):
        if not isinstance(endpoint.get(k), str) or not DURATION.fullmatch(endpoint[k]):
            raise ConfigError(f"endpoint.{k} is malformed")
    pub = _dict(cfg.get("publicMetrics"), "publicMetrics")
    _keys(pub, {"url", "expectedUnauthenticatedStatus"}, "publicMetrics")
    if (
        not isinstance(pub.get("url"), str)
        or not pub["url"].startswith("https://")
        or not pub["url"].endswith("/metrics")
    ):
        raise ConfigError("public metrics url is unsafe")
    if pub.get("expectedUnauthenticatedStatus") != 401:
        raise ConfigError("expected unauthenticated status must be 401")
    labels = _dict(cfg.get("canonicalTargetLabels"), "canonicalTargetLabels")
    for k in ("app", "environment", "release", "cluster", "namespace"):
        if not isinstance(labels.get(k), str) or not labels[k]:
            raise ConfigError(f"canonicalTargetLabels.{k} is required")
    retries = _dict(cfg.get("retries"), "retries")
    _keys(retries, {"attempts", "delaySeconds"}, "retries")
    for k in ("attempts", "delaySeconds"):
        if not isinstance(retries.get(k), int) or not (1 <= retries[k] <= 60):
            raise ConfigError(f"retries.{k} is out of bounds")
    _unique_strings(cfg.get("requiredMetricFamilies"), "requiredMetricFamilies", METRIC)
    allowed = _dict(cfg.get("allowedApplicationLabels"), "allowedApplicationLabels")
    for name, enum in allowed.items():
        if not re.fullmatch(r"[a-zA-Z_][a-zA-Z0-9_]*", name):
            raise ConfigError("invalid application label name")
        if name in cfg.get("forbiddenApplicationLabels", []):
            raise ConfigError("label cannot be both allowed and forbidden")
        if not isinstance(enum, list) or any(not isinstance(x, str) for x in enum):
            raise ConfigError("invalid enum declaration")
        if name != "le" and not enum:
            raise ConfigError("bounded enum must not be empty")
        if len(enum) != len(set(enum)):
            raise ConfigError("duplicate enum value")
    _unique_strings(cfg.get("forbiddenApplicationLabels"), "forbiddenApplicationLabels")


def run_json(args: list[str]) -> Any:
    p = subprocess.run(args, cwd=ROOT, capture_output=True, check=False)
    if p.returncode:
        raise VerifyError(f"command failed (details {REDACT})")
    try:
        return json.loads(p.stdout.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        raise VerifyError(f"malformed JSON (response {REDACT})") from e


def verify_kubectl_contract(app: str, cfg: dict[str, Any]) -> None:
    ctx = subprocess.run(
        ["kubectl", "config", "current-context"], capture_output=True, text=True, check=False
    )
    if ctx.returncode or ctx.stdout.strip() != cfg["kubernetesContext"]:
        raise VerifyError("Kubernetes context mismatch")
    sm = run_json(
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
    ep = _dict(sm.get("spec", {}).get("endpoints", [])[0], "ServiceMonitor endpoint")
    auth = _dict(ep.get("authorization"), "authorization")
    creds = _dict(auth.get("credentials"), "credentials")
    if (
        ep.get("path") != cfg["endpoint"]["path"]
        or ep.get("interval") != cfg["endpoint"]["interval"]
        or ep.get("scrapeTimeout") != cfg["endpoint"]["scrapeTimeout"]
    ):
        raise VerifyError("ServiceMonitor endpoint contract mismatch")
    if creds.get("name") != cfg["secret"]["name"] or creds.get("key") != cfg["secret"]["key"]:
        raise VerifyError("ServiceMonitor Secret reference mismatch")
    sec = run_json(
        ["kubectl", "-n", cfg["namespace"], "get", "secret", cfg["secret"]["name"], "-o", "json"]
    )
    if (
        cfg["secret"]["key"] not in _dict(sec.get("data"), "secret data")
        or not sec["data"][cfg["secret"]["key"]]
    ):
        raise VerifyError("Secret/key contract missing or empty")


def prom_query(path: str) -> Any:
    doc = run_json(
        [
            "kubectl",
            "get",
            "--raw",
            "/api/v1/namespaces/monitoring/services/"
            f"http:kube-prometheus-stack-prometheus:9090/proxy{path}",
        ]
    )
    if doc.get("status") != "success":
        raise VerifyError("Prometheus API returned unsuccessful status")
    return doc.get("data")


def verify_prometheus(cfg: dict[str, Any]) -> None:
    last = None
    for _ in range(cfg["retries"]["attempts"]):
        try:
            targets = prom_query("/api/v1/targets")
            active = [
                t
                for t in targets.get("activeTargets", [])
                if all(
                    t.get("labels", {}).get(k) == v for k, v in cfg["canonicalTargetLabels"].items()
                )
            ]
            if len(active) == cfg["expectedTargetCount"] and all(
                t.get("health") == "up" for t in active
            ):
                break
            last = "target convergence failed"
        except Exception as e:
            last = e
        time.sleep(cfg["retries"]["delaySeconds"])
    else:
        raise VerifyError(f"target verification failed ({REDACT})") from (
            last if isinstance(last, Exception) else None
        )
    metric_data = prom_query('/api/v1/series?match[]={__name__=~".+"}')
    names = set()
    allowed = cfg["allowedApplicationLabels"]
    forbidden = set(cfg["forbiddenApplicationLabels"])
    for series in metric_data:
        name = series.get("__name__") if isinstance(series, dict) else None
        if not isinstance(name, str):
            raise VerifyError("structurally invalid Prometheus series")
        if name in cfg["requiredMetricFamilies"]:
            names.add(name)
        if name.startswith(cfg["canonicalTargetLabels"]["app"] + "_"):
            for label, value in series.items():
                if label == "__name__" or label in SAFE_STD_LABELS:
                    continue
                if label in forbidden or any(bad in label.lower() for bad in forbidden):
                    raise VerifyError("forbidden application label present")
                if label in allowed and allowed[label] and value not in allowed[label]:
                    raise VerifyError("unbounded application label value")
                if label not in allowed and label not in cfg["canonicalTargetLabels"]:
                    raise VerifyError("undeclared application label present")
    missing = sorted(set(cfg["requiredMetricFamilies"]) - names)
    if missing:
        raise VerifyError("required metric families are missing")


def verify_public_401(cfg: dict[str, Any]) -> None:
    req = urllib.request.Request(cfg["publicMetrics"]["url"], method="GET")
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            status = r.status
    except urllib.error.HTTPError as e:
        status = e.code
    except Exception as e:
        raise VerifyError(f"public metrics transport failed ({REDACT})") from e
    if status != cfg["publicMetrics"]["expectedUnauthenticatedStatus"]:
        raise VerifyError("public metrics unauthenticated status mismatch")


def select(data: dict[str, Any], app: str, env: str) -> dict[str, Any]:
    try:
        return data["applications"][app][normalize_env(env)]
    except KeyError as e:
        raise ConfigError("configured app/env not found") from e


def main(argv=None):
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    for n in ("validate", "secret-check", "verify"):
        s = sub.add_parser(n)
        s.add_argument("--app", default="")
        s.add_argument("--env", default="staging")
        s.add_argument("--inventory", type=Path, default=DEFAULT_INVENTORY)
    a = p.parse_args(argv)
    try:
        data = load_inventory(a.inventory)
        if a.cmd == "validate":
            return 0
        cfg = select(data, a.app, a.env)
        if a.cmd == "secret-check":
            verify_kubectl_contract(a.app, cfg)
            print(
                "Application metrics Secret contract exists "
                "(value intentionally not read or printed)."
            )
            return 0
        verify_kubectl_contract(a.app, cfg)
        verify_prometheus(cfg)
        verify_public_401(cfg)
        print(
            f"Application metrics verified for app={a.app} env=staging "
            "(sensitive details redacted)."
        )
        return 0
    except (ConfigError, VerifyError) as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
