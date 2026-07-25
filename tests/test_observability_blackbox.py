import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/observability_blackbox.sh"
VALUES = ROOT / "clusters/staging/observability/prometheus-blackbox-exporter.values.yaml"
LEGACY = [
    "blackbox-dspace-prod-root",
    "blackbox-dspace-prod-config",
    "blackbox-dspace-prod-healthz",
    "blackbox-dspace-prod-livez",
    "blackbox-tokenplace-prod-root",
    "blackbox-tokenplace-prod-healthz",
    "blackbox-tokenplace-prod-livez",
    "blackbox-tokenplace-prod-metadata",
    "blackbox-danielsmith-prod-root",
    "blackbox-danielsmith-prod-healthz",
    "blackbox-danielsmith-prod-livez",
]
COVERAGE_BOOTSTRAP_ENV = (
    "COV_CORE_SOURCE",
    "COV_CORE_CONFIG",
    "COV_CORE_DATAFILE",
    "COVERAGE_PROCESS_START",
)


def expected_names():
    text = (ROOT / "clusters/staging/observability/probes/public-apps.yaml").read_text()
    return [
        line.strip().split(": ", 1)[1]
        for line in text.splitlines()
        if line.startswith("  name: blackbox-")
    ]


def verifier_bundle(health="up", success="1"):
    pairs = [(name, name.removeprefix("blackbox-").split("-staging-")) for name in expected_names()]
    targets = [
        {
            "labels": {
                "job": f"probe/monitoring/{name}",
                "app": pair[0],
                "route": pair[1],
                "environment": "staging",
            },
            "health": health,
        }
        for name, pair in pairs
    ]
    metrics = {}
    for family in (
        "probe_success",
        "probe_duration_seconds",
        "probe_http_status_code",
        "probe_dns_lookup_time_seconds",
        "probe_ssl_earliest_cert_expiry",
    ):
        metrics[family] = {
            "status": "success",
            "data": {
                "resultType": "vector",
                "result": [
                    {
                        "metric": {
                            "job": f"probe/monitoring/{name}",
                            "app": pair[0],
                            "route": pair[1],
                        },
                        "value": [1, success if family == "probe_success" else "2"],
                    }
                    for name, pair in pairs
                ],
            },
        }
    return {
        "targets": {"status": "success", "data": {"activeTargets": targets}},
        "metrics": metrics,
    }


HELM_STUB = r'''#!/usr/bin/python3
import os, sys
args = sys.argv[1:]
with open(os.environ["LOG"], "a") as log:
    log.write("helm " + " ".join(args) + "\n")
scenario = os.environ.get("SCENARIO", "success")
if args[:1] == ["template"]:
    print("""kind: Deployment
metadata:
  name: prometheus-blackbox-exporter
spec:
  replicas: 1
---
kind: ServiceMonitor
metadata:
  name: prometheus-blackbox-exporter
  labels:
    release: kube-prometheus-stack""")
elif args[:1] == ["list"]:
    base = any("kube-prometheus-stack" in value for value in args)
    if base:
        if scenario != "missing_base": print("kube-prometheus-stack")
    elif scenario not in ("release_absent", "upgrade_absent"):
        print("prometheus-blackbox-exporter")
elif args and args[0] in ("install", "upgrade") and scenario == "helm_failure":
    sys.exit(42)
'''

KUBECTL_STUB = r"""#!/usr/bin/python3
import json, os, sys
args = sys.argv[1:]
with open(os.environ["LOG"], "a") as log:
    log.write("kubectl " + " ".join(args) + "\n")
scenario = os.environ.get("SCENARIO", "success")
joined = " ".join(args)
if args[:2] == ["config", "current-context"]:
    print("wrong-context" if scenario == "bad_context" else "sugar-staging")
elif args[:1] == ["kustomize"]:
    print("kind: Probe\nmetadata:\n  name: rendered-probe")
elif "get crd" in joined and scenario == "missing_crds": sys.exit(1)
elif "get service kube-prometheus-stack-prometheus" in joined and scenario == "missing_service": sys.exit(1)
elif "rollout status" in joined and scenario == "not_ready": sys.exit(1)
elif "get deployment prometheus-blackbox-exporter -o jsonpath=" in joined:
    print("1 0 0" if scenario == "replicas" else "1 1 1", end="")
elif "get service prometheus-blackbox-exporter -o jsonpath=" in joined:
    print("NodePort" if scenario == "service_type" else "ClusterIP", end="")
elif "get ingress" in joined:
    if scenario == "ingress": print("ingress.networking.k8s.io/exporter")
elif "get service -l" in joined and "nodePort" in joined:
    if scenario == "nodeport": print("30115")
elif "get servicemonitor" in joined:
    if scenario != "missing_monitor": print("kube-prometheus-stack", end="")
elif "get probe -l" in joined and "-o json" in joined:
    print(open(os.environ["PROBES_JSON"]).read())
elif "--raw" in joined:
    count_file = os.environ["RAW_COUNT"]
    try: count = int(open(count_file).read())
    except (FileNotFoundError, ValueError): count = 0
    open(count_file, "w").write(str(count + 1))
    transport = os.environ.get("TRANSPORT")
    operation = "targets" if "targets?" in joined else "metric"
    if transport == operation:
        sys.stderr.write("Unauthorized Authorization: Bearer secret https://raw.invalid/path\n")
        sys.exit(23)
    bundle = json.load(open(os.environ["PROM_JSON"]))
    if "targets?" in joined:
        payload = bundle["targets"]
        if scenario == "delayed" and count < 6:
            payload = json.loads(json.dumps(payload)); payload["data"]["activeTargets"].pop()
        if scenario == "persistent_missing":
            payload = json.loads(json.dumps(payload)); payload["data"]["activeTargets"].pop()
        if scenario == "persistent_down":
            payload = json.loads(json.dumps(payload)); payload["data"]["activeTargets"][0]["health"] = "down"
    else:
        family = next(name for name in bundle["metrics"] if name in joined)
        payload = bundle["metrics"][family]
    print(json.dumps(payload))
"""

PYTHON_STUB = r"""#!/usr/bin/python3
import os, sys
if len(sys.argv) > 1 and sys.argv[1].endswith("cluster_identity.py"):
    with open(os.environ["LOG"], "a") as log: log.write("identity " + " ".join(sys.argv[2:]) + "\n")
    if os.environ.get("SCENARIO") == "bad_identity": sys.exit(1)
    sys.exit(0)
os.execv(os.environ["REAL_PYTHON"], [os.environ["REAL_PYTHON"], *sys.argv[1:]])
"""

SLEEP_STUB = r"""#!/bin/sh
echo "sleep $*" >>"$LOG"
"""


@dataclass
class Scenario:
    root: Path
    env: dict

    @property
    def log(self):
        path = self.root / "operations.log"
        return path.read_text().splitlines() if path.exists() else []

    def run(self, command, environment="staging", **extra):
        env = {**self.env, **{key: str(value) for key, value in extra.items()}}
        for key in COVERAGE_BOOTSTRAP_ENV:
            env.pop(key, None)
        args = [str(SCRIPT), command]
        if environment is not None:
            args.append(f"env={environment}")
        return subprocess.run(args, cwd=ROOT, env=env, text=True, capture_output=True)


@pytest.fixture
def scenario(tmp_path):
    bindir = tmp_path / "bin"
    bindir.mkdir()
    for name, content in {
        "helm": HELM_STUB,
        "kubectl": KUBECTL_STUB,
        "python3": PYTHON_STUB,
        "sleep": SLEEP_STUB,
    }.items():
        path = bindir / name
        path.write_text(content)
        path.chmod(0o755)
    probes = tmp_path / "probes.json"
    docs = subprocess.run(
        [
            "ruby",
            "-ryaml",
            "-rjson",
            "-e",
            "puts JSON.generate(YAML.load_stream(File.read(ARGV[0])))",
            str(ROOT / "clusters/staging/observability/probes/public-apps.yaml"),
        ],
        check=True,
        text=True,
        capture_output=True,
    )
    probes.write_text(json.dumps({"items": json.loads(docs.stdout)}))
    prom = tmp_path / "prom.json"
    prom.write_text(json.dumps(verifier_bundle()))
    env = {
        **os.environ,
        "PATH": f"{bindir}:{os.environ['PATH']}",
        "LOG": str(tmp_path / "operations.log"),
        "PROBES_JSON": str(probes),
        "PROM_JSON": str(prom),
        "RAW_COUNT": str(tmp_path / "raw-count"),
        "REAL_PYTHON": sys.executable,
        "TMPDIR": str(tmp_path),
        "SUGARKUBE_BLACKBOX_VERIFY_ATTEMPTS": "2",
        "SUGARKUBE_BLACKBOX_VERIFY_INTERVAL_SECONDS": "1",
    }
    return Scenario(tmp_path, env)


def mutations(log):
    return [
        line
        for line in log
        if line.startswith(("helm install", "helm upgrade"))
        or " apply " in f" {line} "
        or " delete " in f" {line} "
    ]


def test_missing_and_production_envs_fail_before_cluster_access(scenario):
    for environment in (None, "prod", "production", "dev"):
        result = scenario.run("render", environment)
        assert result.returncode == 2
    assert scenario.log == []


@pytest.mark.parametrize("environment", ["staging", "int"])
def test_environment_normalization_renders_offline(scenario, environment):
    result = scenario.run("render", environment)
    assert result.returncode == 0
    assert any(line.startswith("helm repo add") for line in scenario.log)
    assert any(line.startswith("kubectl kustomize") for line in scenario.log)
    assert not mutations(scenario.log)


@pytest.mark.parametrize("failure", ["bad_context", "bad_identity"])
def test_identity_guards_precede_release_queries_and_mutation(scenario, failure):
    result = scenario.run("install", SCENARIO=failure)
    assert result.returncode != 0
    assert not any("helm list" in line for line in scenario.log)
    assert not mutations(scenario.log)


@pytest.mark.parametrize("failure", ["missing_base", "missing_crds", "missing_service"])
def test_preflight_failures_suppress_all_mutation(scenario, failure):
    result = scenario.run("install", SCENARIO=failure)
    assert result.returncode == 5
    assert not mutations(scenario.log)


def test_rendering_precedes_release_queries(scenario):
    result = scenario.run("install", SCENARIO="release_absent")
    assert result.returncode == 0
    template = next(i for i, line in enumerate(scenario.log) if line.startswith("helm template"))
    kustomize = next(
        i for i, line in enumerate(scenario.log) if line.startswith("kubectl kustomize")
    )
    query = next(i for i, line in enumerate(scenario.log) if line.startswith("helm list"))
    assert template < query and kustomize < query


@pytest.mark.parametrize("command,state", [("install", "success"), ("upgrade", "upgrade_absent")])
def test_wrong_release_state_rejects_mutation(scenario, command, state):
    result = scenario.run(command, SCENARIO=state)
    assert result.returncode == 6
    assert not mutations(scenario.log)


@pytest.mark.parametrize("command,state", [("install", "release_absent"), ("upgrade", "success")])
def test_successful_mutation_uses_pinned_complete_values_and_order(scenario, command, state):
    result = scenario.run(command, SCENARIO=state, SUGARKUBE_OBSERVABILITY_HELM_TIMEOUT="7m")
    assert result.returncode == 0
    mutation = next(line for line in scenario.log if line.startswith(f"helm {command}"))
    assert "--version 11.15.1" in mutation
    assert f"-f {VALUES}" in mutation
    assert "--wait --timeout 7m" in mutation
    assert "--reuse-values" not in mutation
    delete = next(line for line in scenario.log if " delete probe " in line)
    apply = next(line for line in scenario.log if line.startswith("kubectl apply"))
    assert scenario.log.index(mutation) < scenario.log.index(delete) < scenario.log.index(apply)
    assert delete.endswith("delete probe " + " ".join(LEGACY) + " --ignore-not-found")


def test_failed_helm_mutation_suppresses_cleanup_and_apply(scenario):
    result = scenario.run("upgrade", SCENARIO="helm_failure")
    assert result.returncode == 42
    assert not any(
        " delete " in f" {line} " or line.startswith("kubectl apply") for line in scenario.log
    )


@pytest.mark.parametrize("command", ["status", "verify"])
def test_read_only_commands_never_mutate(scenario, command):
    result = scenario.run(command)
    assert result.returncode == 0
    assert not mutations(scenario.log)


@pytest.mark.parametrize(
    "failure", ["not_ready", "replicas", "service_type", "ingress", "nodeport", "missing_monitor"]
)
def test_resource_guards_fail_before_prometheus_queries(scenario, failure):
    result = scenario.run("verify", SCENARIO=failure)
    assert result.returncode == 1 if failure == "not_ready" else result.returncode == 7
    assert not any("--raw" in line for line in scenario.log)


def test_delayed_target_discovery_retries_then_succeeds(scenario):
    result = scenario.run("verify", SCENARIO="delayed", SUGARKUBE_BLACKBOX_VERIFY_ATTEMPTS=3)
    assert result.returncode == 0
    assert scenario.log.count("sleep 1") == 1
    assert sum("targets?state=active" in line for line in scenario.log) == 2


@pytest.mark.parametrize("failure", ["persistent_missing", "persistent_down"])
def test_persistent_target_failure_is_bounded_and_redacted(scenario, failure):
    result = scenario.run(
        "verify",
        SCENARIO=failure,
        COV_CORE_SOURCE="invalid-source",
        COV_CORE_CONFIG=scenario.root / "missing-coveragerc",
        COV_CORE_DATAFILE=scenario.root / "unwritable" / ".coverage",
        COVERAGE_PROCESS_START=scenario.root / "missing-coveragerc",
    )
    assert result.returncode == 10
    assert scenario.log.count("sleep 1") == 1
    assert sum("targets?state=active" in line for line in scenario.log) == 2
    assert "https://" not in result.stderr
    assert "Authorization" not in result.stderr
    assert len(result.stderr.splitlines()) <= 20


@pytest.mark.parametrize(
    "transport,operation", [("targets", "targets"), ("metric", "probe_success")]
)
def test_prometheus_transport_failures_are_redacted_and_cleanup(scenario, transport, operation):
    result = scenario.run("verify", TRANSPORT=transport)
    assert result.returncode == 9
    assert (
        f"operation={operation} category=authentication status=23 error=<redacted>" in result.stderr
    )
    for sentinel in ("Authorization", "Bearer", "secret", "https://raw.invalid", "/path"):
        assert sentinel not in result.stderr
    assert not list(scenario.root.glob("sugarkube-blackbox-prometheus.*"))


def verify(payload, final=False, *args):
    env = {**os.environ, "FINAL_ATTEMPT": "1" if final else "0"}
    return subprocess.run(
        [str(ROOT / "scripts/verify_blackbox_prometheus.py"), *args],
        input=json.dumps(payload) if not isinstance(payload, str) else payload,
        text=True,
        capture_output=True,
        env=env,
    )


def test_prometheus_verifier_accepts_exact_lifecycle_jobs_and_ignores_unrelated():
    payload = verifier_bundle()
    payload["targets"]["data"]["activeTargets"].append(
        {"labels": {"job": "probe/monitoring/unrelated"}, "health": "down"}
    )
    assert verify(payload).returncode == 0


def test_prometheus_verifier_converges_then_reports_bounded_diagnostics():
    for change in ("missing", "down", "probe_failure", "family"):
        payload = verifier_bundle()
        if change == "missing":
            payload["targets"]["data"]["activeTargets"].pop()
        elif change == "down":
            payload["targets"]["data"]["activeTargets"][0]["health"] = "down"
        elif change == "probe_failure":
            payload["metrics"]["probe_success"]["data"]["result"][0]["value"][1] = "0"
        else:
            payload["metrics"].pop("probe_duration_seconds")
        result = verify(payload, change != "family")
        assert result.returncode in {9, 10}
        assert "https://" not in result.stderr
        assert len(result.stderr.splitlines()) <= 18


def test_prometheus_verifier_fails_immediately_on_bad_responses():
    bad = [
        "not-json",
        [],
        {"targets": {}, "metrics": {}},
        {**verifier_bundle(), "targets": {"status": "error", "data": {}}},
    ]
    for payload in bad:
        assert verify(payload).returncode == 9


def test_probe_validator_requires_exact_names_and_mappings():
    docs = subprocess.run(
        [
            "ruby",
            "-ryaml",
            "-rjson",
            "-e",
            "puts JSON.generate(YAML.load_stream(File.read(ARGV[0])))",
            str(ROOT / "clusters/staging/observability/probes/public-apps.yaml"),
        ],
        check=True,
        text=True,
        capture_output=True,
    )
    items = {"items": json.loads(docs.stdout)}
    assert verify(items, False, "--probes").returncode == 0
    items["items"][0]["metadata"]["labels"]["route"] = "wrong"
    assert verify(items, False, "--probes").returncode == 7
