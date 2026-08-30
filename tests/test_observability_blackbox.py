import contextlib
import io
import json
import os
import runpy
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/observability_blackbox.sh"
VALUES = ROOT / "clusters/staging/observability/prometheus-blackbox-exporter.values.yaml"
POLICY = (
    ROOT / "clusters/staging/observability/network-policies/prometheus-to-blackbox-exporter.yaml"
)
POLICIES = POLICY.parent
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


def expected_names(environment="staging"):
    text = (ROOT / f"clusters/{environment}/observability/probes/public-apps.yaml").read_text()
    return [
        line.strip().split(": ", 1)[1]
        for line in text.splitlines()
        if line.startswith("  name: blackbox-")
    ]


def verifier_bundle(health="up", success="1", environment="staging"):
    pairs = [
        (name, name.removeprefix("blackbox-").split(f"-{environment}-"))
        for name in expected_names(environment)
    ]
    targets = [
        {
            "labels": {
                "job": f"probe/monitoring/{name}",
                "app": pair[0],
                "route": pair[1],
                "environment": environment,
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
                            "environment": environment,
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
    if "kube-prometheus-stack" in args and "prometheus-blackbox-exporter" not in args:
        name = "changed-prometheus" if scenario == "changed_prometheus_name" else "kube-prometheus-stack-prometheus"
        print("""apiVersion: monitoring.coreos.com/v1
kind: Prometheus
metadata:
  name: %s""" % name)
    else:
        exporter_name = "changed-exporter" if scenario == "changed_exporter_labels" else "prometheus-blackbox-exporter"
        print("""kind: Deployment
metadata:
  name: prometheus-blackbox-exporter
spec:
  replicas: 1
  template:
    metadata:
      labels:
        app.kubernetes.io/name: %s
        app.kubernetes.io/instance: prometheus-blackbox-exporter
---
kind: ServiceMonitor
metadata:
  name: prometheus-blackbox-exporter
  labels:
    release: kube-prometheus-stack""" % exporter_name)
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
    print("wrong-context" if scenario == "bad_context" else "sugar-" + os.environ.get("STUB_ENV", "staging"))
elif args[:1] == ["kustomize"]:
    if "network-policies" in joined:
        print(open(os.environ["POLICY"]).read())
    else: print(open(os.environ["PROBES_YAML"]).read())
elif args[:2] == ["apply", "-f"] and scenario == "policy_apply_failure" and "policy" in args[2]:
    sys.exit(41)
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
elif "get networkpolicy allow-kube-prometheus-stack-to-blackbox-exporter -o json" in joined:
    if scenario == "missing_policy": sys.exit(1)
    policy = json.load(open(os.environ["POLICY_JSON"]))
    spec = policy["spec"]
    if scenario == "old_egress_policy":
        spec = policy["spec"] = {"podSelector": {"matchLabels": {"operator.prometheus.io/name": "kube-prometheus-stack-prometheus"}}, "policyTypes": ["Egress"], "egress": [{"to": [{"podSelector": {"matchLabels": {"app.kubernetes.io/instance": "prometheus-blackbox-exporter", "app.kubernetes.io/name": "prometheus-blackbox-exporter"}}}], "ports": [{"protocol": "TCP", "port": 9115}]}]}
    elif scenario == "malformed_policy": spec["policyTypes"] = ["Egress"]
    elif scenario == "broad_exporter": spec["podSelector"] = {}
    elif scenario == "broad_prometheus": spec["ingress"][0]["from"][0]["podSelector"] = {}
    elif scenario == "wrong_protocol": spec["ingress"][0]["ports"][0]["protocol"] = "UDP"
    elif scenario == "wrong_port": spec["ingress"][0]["ports"][0]["port"] = 9116
    elif scenario == "additional_protocol": spec["ingress"][0]["ports"].append({"protocol": "UDP", "port": 9115})
    elif scenario == "additional_port": spec["ingress"][0]["ports"].append({"protocol": "TCP", "port": 9116})
    elif scenario == "additional_exporter_selector": spec["podSelector"]["matchLabels"]["extra"] = "forbidden"
    elif scenario == "additional_prometheus_selector": spec["ingress"][0]["from"][0]["podSelector"]["matchLabels"]["extra"] = "forbidden"
    elif scenario == "additional_peer": spec["ingress"][0]["from"].append({"ipBlock": {"cidr": "0.0.0.0/0"}})
    elif scenario == "additional_rule": spec["ingress"].append({"from": [{"podSelector": {}}]})
    elif scenario == "namespace_selector": spec["ingress"][0]["from"][0]["namespaceSelector"] = {}
    elif scenario == "ip_block": spec["ingress"][0]["from"][0] = {"ipBlock": {"cidr": "0.0.0.0/0"}}
    elif scenario == "egress_spec": spec["egress"] = []
    elif scenario == "additional_policy_type": spec["policyTypes"].append("Egress")
    print(json.dumps(policy))
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
        env = dict(self.env)
        normalized = "prod" if environment in ("prod", "production") else "staging"
        env["STUB_ENV"] = normalized
        env["PROBES_YAML"] = str(
            ROOT / f"clusters/{normalized}/observability/probes/public-apps.yaml"
        )
        env["PROBES_JSON"] = env[f"{normalized.upper()}_PROBES_JSON"]
        env["POLICY"] = str(
            ROOT
            / f"clusters/{normalized}/observability/network-policies/prometheus-to-blackbox-exporter.yaml"
        )
        env["POLICY_JSON"] = env[f"{normalized.upper()}_POLICY_JSON"]
        env["PROM_JSON"] = env[f"{normalized.upper()}_PROM_JSON"]
        env.update({key: str(value) for key, value in extra.items()})
        for key in COVERAGE_BOOTSTRAP_ENV:
            env.pop(key, None)
        args = [str(SCRIPT), command]
        if environment is not None:
            args.append(f"env={environment}")
        return subprocess.run(args, cwd=ROOT, env=env, text=True, capture_output=True, check=False)


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
    policy_json = tmp_path / "policy.json"
    policy_docs = subprocess.run(
        [
            "ruby",
            "-ryaml",
            "-rjson",
            "-e",
            "puts JSON.generate(YAML.safe_load(File.read(ARGV[0]), aliases: false))",
            str(POLICY),
        ],
        check=True,
        text=True,
        capture_output=True,
    )
    policy_json.write_text(policy_docs.stdout)
    prom = tmp_path / "prom.json"
    prom.write_text(json.dumps(verifier_bundle()))
    prod_probes = tmp_path / "prod-probes.json"
    prod_docs = subprocess.run(
        [
            "ruby",
            "-ryaml",
            "-rjson",
            "-e",
            "puts JSON.generate(YAML.load_stream(File.read(ARGV[0])))",
            str(ROOT / "clusters/prod/observability/probes/public-apps.yaml"),
        ],
        check=True,
        text=True,
        capture_output=True,
    )
    prod_probes.write_text(json.dumps({"items": json.loads(prod_docs.stdout)}))
    prod_policy_json = tmp_path / "prod-policy.json"
    prod_policy_json.write_text(policy_json.read_text())
    prod_prom = tmp_path / "prod-prom.json"
    prod_prom.write_text(json.dumps(verifier_bundle(environment="prod")))
    env = {
        **os.environ,
        "PATH": f"{bindir}:{os.environ['PATH']}",
        "LOG": str(tmp_path / "operations.log"),
        "PROBES_JSON": str(probes),
        "STAGING_PROBES_JSON": str(probes),
        "PROD_PROBES_JSON": str(prod_probes),
        "PROBES_YAML": str(ROOT / "clusters/staging/observability/probes/public-apps.yaml"),
        "POLICY": str(POLICY),
        "POLICY_JSON": str(policy_json),
        "STAGING_POLICY_JSON": str(policy_json),
        "PROD_POLICY_JSON": str(prod_policy_json),
        "PROM_JSON": str(prom),
        "STAGING_PROM_JSON": str(prom),
        "PROD_PROM_JSON": str(prod_prom),
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


def test_missing_and_unsupported_envs_fail_before_cluster_access(scenario):
    for environment in (None, "dev"):
        result = scenario.run("render", environment)
        assert result.returncode == 2
    assert scenario.log == []


@pytest.mark.parametrize("environment", ["staging", "int", "prod", "production"])
def test_environment_normalization_renders_offline(scenario, environment):
    result = scenario.run("render", environment)
    assert result.returncode == 0
    assert any(line.startswith("helm repo add") for line in scenario.log)
    assert sum(line.startswith("helm template") for line in scenario.log) == 2
    assert sum(line.startswith("kubectl kustomize") for line in scenario.log) == 2
    assert all(
        line.startswith("kubectl kustomize") for line in scenario.log if line.startswith("kubectl ")
    )
    assert not mutations(scenario.log)


def test_render_succeeds_with_unusable_kubeconfig(scenario):
    result = scenario.run("render", KUBECONFIG="/dev/null")
    assert result.returncode == 0
    assert not any("config current-context" in line for line in scenario.log)


@pytest.mark.parametrize("failure", ["changed_prometheus_name", "changed_exporter_labels"])
def test_rendered_selector_drift_fails_before_cluster_access(scenario, failure):
    result = scenario.run("install", SCENARIO=failure)
    assert result.returncode != 0
    assert not any("config current-context" in line for line in scenario.log)
    assert not mutations(scenario.log)


@pytest.mark.parametrize(
    "failure",
    [
        "old_egress_policy",
        "broad_exporter",
        "broad_prometheus",
        "additional_exporter_selector",
        "additional_prometheus_selector",
        "additional_peer",
        "additional_rule",
        "additional_port",
        "additional_protocol",
        "ip_block",
        "namespace_selector",
        "egress_spec",
        "additional_policy_type",
    ],
)
def test_lifecycle_policy_drift_fails_before_cluster_access_or_mutation(scenario, failure):
    policy = json.loads(Path(scenario.env["POLICY_JSON"]).read_text())
    spec = policy["spec"]
    if failure == "old_egress_policy":
        spec = policy["spec"] = {
            "podSelector": {
                "matchLabels": {"operator.prometheus.io/name": "kube-prometheus-stack-prometheus"}
            },
            "policyTypes": ["Egress"],
            "egress": [
                {
                    "to": [
                        {
                            "podSelector": {
                                "matchLabels": {
                                    "app.kubernetes.io/instance": "prometheus-blackbox-exporter",
                                    "app.kubernetes.io/name": "prometheus-blackbox-exporter",
                                }
                            }
                        }
                    ],
                    "ports": [{"protocol": "TCP", "port": 9115}],
                }
            ],
        }
    elif failure == "broad_exporter":
        spec["podSelector"] = {}
    elif failure == "broad_prometheus":
        spec["ingress"][0]["from"][0]["podSelector"] = {}
    elif failure == "additional_exporter_selector":
        spec["podSelector"]["matchLabels"]["extra"] = "forbidden"
    elif failure == "additional_prometheus_selector":
        spec["ingress"][0]["from"][0]["podSelector"]["matchLabels"]["extra"] = "forbidden"
    elif failure == "additional_peer":
        spec["ingress"][0]["from"].append({"podSelector": {}})
    elif failure == "additional_rule":
        spec["ingress"].append({"from": [{"podSelector": {}}]})
    elif failure == "additional_port":
        spec["ingress"][0]["ports"].append({"protocol": "TCP", "port": 9116})
    elif failure == "additional_protocol":
        spec["ingress"][0]["ports"].append({"protocol": "UDP", "port": 9115})
    elif failure == "ip_block":
        spec["ingress"][0]["from"][0] = {"ipBlock": {"cidr": "0.0.0.0/0"}}
    elif failure == "namespace_selector":
        spec["ingress"][0]["from"][0]["namespaceSelector"] = {}
    elif failure == "egress_spec":
        spec["egress"] = []
    else:
        spec["policyTypes"].append("Egress")
    invalid_policy = scenario.root / f"{failure}.yaml"
    invalid_policy.write_text(json.dumps(policy))

    result = scenario.run("upgrade", POLICY=invalid_policy)

    assert result.returncode != 0
    assert not any("config current-context" in line for line in scenario.log)
    assert not mutations(scenario.log)


def test_render_stdout_is_a_clean_separated_kubernetes_stream(scenario):
    result = scenario.run("render")
    assert result.returncode == 0
    parsed = subprocess.run(
        ["ruby", "-ryaml", "-rjson", "-e", "puts JSON.generate(YAML.load_stream(STDIN.read))"],
        input=result.stdout,
        check=True,
        capture_output=True,
        text=True,
    )
    docs = [doc for doc in json.loads(parsed.stdout) if doc]
    assert [doc["kind"] for doc in docs[:3]] == ["Deployment", "ServiceMonitor", "NetworkPolicy"]
    assert [doc["kind"] for doc in docs[3:]] == ["Probe"] * 21
    assert docs[2] == json.loads(Path(scenario.env["POLICY_JSON"]).read_text())
    assert "blackbox environment:" not in result.stdout
    assert "blackbox environment: staging" in result.stderr


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
    kustomizes = [i for i, line in enumerate(scenario.log) if line.startswith("kubectl kustomize")]
    query = next(i for i, line in enumerate(scenario.log) if line.startswith("helm list"))
    cluster_access = next(
        i for i, line in enumerate(scenario.log) if line == "kubectl config current-context"
    )
    assert template < cluster_access < query
    assert all(item < cluster_access for item in kustomizes)


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
    applies = [line for line in scenario.log if line.startswith("kubectl apply")]
    assert len(applies) == 2
    assert (
        scenario.log.index(mutation)
        < scenario.log.index(applies[0])
        < scenario.log.index(delete)
        < scenario.log.index(applies[1])
    )
    assert delete.endswith("delete probe " + " ".join(LEGACY) + " --ignore-not-found")


def test_failed_helm_mutation_suppresses_cleanup_and_apply(scenario):
    result = scenario.run("upgrade", SCENARIO="helm_failure")
    assert result.returncode == 42
    assert not any(
        " delete " in f" {line} " or line.startswith("kubectl apply") for line in scenario.log
    )


def test_failed_policy_apply_suppresses_probe_mutation(scenario):
    result = scenario.run("upgrade", SCENARIO="policy_apply_failure")
    assert result.returncode != 0
    assert not any(" delete probe " in line for line in scenario.log)
    assert sum(line.startswith("kubectl apply") for line in scenario.log) == 1


@pytest.mark.parametrize(
    "failure",
    [
        "missing_policy",
        "old_egress_policy",
        "malformed_policy",
        "broad_exporter",
        "broad_prometheus",
        "wrong_protocol",
        "wrong_port",
        "additional_protocol",
        "additional_port",
        "additional_exporter_selector",
        "additional_prometheus_selector",
        "additional_peer",
        "additional_rule",
        "namespace_selector",
        "ip_block",
        "egress_spec",
        "additional_policy_type",
    ],
)
def test_policy_guard_fails_before_prometheus_queries(scenario, failure):
    result = scenario.run("verify", SCENARIO=failure)
    assert result.returncode == 7
    assert not any("--raw" in line for line in scenario.log)


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
    assert len(result.stderr.splitlines()) <= 25


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


def verify(payload, final=False, *args, environment="staging"):
    stdin = io.StringIO(json.dumps(payload) if not isinstance(payload, str) else payload)
    stdout = io.StringIO()
    stderr = io.StringIO()
    old_argv, old_stdin = sys.argv, sys.stdin
    old_final_attempt = os.environ.get("FINAL_ATTEMPT")
    sys.argv = [str(ROOT / "scripts/verify_blackbox_prometheus.py"), "--env", environment, *args]
    sys.stdin = stdin
    os.environ["FINAL_ATTEMPT"] = "1" if final else "0"
    try:
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            try:
                runpy.run_path(sys.argv[0], run_name="__main__")
            except SystemExit as error:
                returncode = error.code or 0
            else:
                returncode = 0
    finally:
        sys.argv, sys.stdin = old_argv, old_stdin
        if old_final_attempt is None:
            os.environ.pop("FINAL_ATTEMPT", None)
        else:
            os.environ["FINAL_ATTEMPT"] = old_final_attempt
    return subprocess.CompletedProcess(sys.argv, returncode, stdout.getvalue(), stderr.getvalue())


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
        assert len(result.stderr.splitlines()) <= 23


def test_prometheus_verifier_fails_immediately_on_bad_responses():
    bad = [
        "not-json",
        [],
        {"targets": {}, "metrics": {}},
        {**verifier_bundle(), "targets": {"status": "error", "data": {}}},
    ]
    for payload in bad:
        assert verify(payload).returncode == 9


def test_prometheus_verifier_rejects_malformed_targets_and_metrics():
    malformed = []
    for targets in (
        [],
        {"status": "success", "data": []},
        {"status": "success", "data": {"activeTargets": {}}},
        {"status": "success", "data": {"activeTargets": [None]}},
    ):
        payload = verifier_bundle()
        payload["targets"] = targets
        malformed.append(payload)

    payload = verifier_bundle()
    payload["targets"]["data"]["activeTargets"][0]["labels"]["route"] = "wrong"
    malformed.append(payload)

    payload = verifier_bundle()
    payload["metrics"]["probe_success"]["data"]["resultType"] = "matrix"
    malformed.append(payload)

    for payload in malformed:
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
    assert verify({}, False, "--probes").returncode == 7
    assert verify({"items": [None]}, False, "--probes").returncode == 7
    assert verify(items, False, "--unknown").returncode == 9


PROD_MATRIX = {
    "dspace": {
        "root": "https://democratized.space/",
        "config": "https://democratized.space/config.json",
        "healthz": "https://democratized.space/healthz",
        "livez": "https://democratized.space/livez",
    },
    "tokenplace": {
        "root": "https://token.place/",
        "healthz": "https://token.place/healthz",
        "livez": "https://token.place/livez",
        "metadata": "https://token.place/api/v1/meta",
    },
    "danielsmith": {
        "root": "https://danielsmith.io/",
        "healthz": "https://danielsmith.io/healthz",
        "livez": "https://danielsmith.io/livez",
    },
    "jobbot3000": {
        "root": "https://jobbot3000.tech/",
        "healthz": "https://jobbot3000.tech/healthz",
        "livez": "https://jobbot3000.tech/livez",
        "tracker": "https://jobbot3000.tech/tracker",
        "manifest": "https://jobbot3000.tech/manifest.webmanifest",
    },
    "gitshelves": {
        "root": "https://gitshelves.com/",
        "healthz": "https://gitshelves.com/healthz",
        "livez": "https://gitshelves.com/livez",
        "baseplate": "https://gitshelves.com/models/baseplate_2x6.stl",
        "module": "https://gitshelves.com/models/contrib_cube.stl",
    },
}


def load_probe_documents(environment):
    result = subprocess.run(
        [
            "ruby",
            "-ryaml",
            "-rjson",
            "-e",
            "puts JSON.generate(YAML.load_stream(File.read(ARGV[0])))",
            str(ROOT / f"clusters/{environment}/observability/probes/public-apps.yaml"),
        ],
        check=True,
        text=True,
        capture_output=True,
    )
    return json.loads(result.stdout)


def test_production_probe_contract_and_environment_separation():
    prod = load_probe_documents("prod")
    staging = load_probe_documents("staging")
    assert len(prod) == len(staging) == 21
    staging_contract = {
        (p["metadata"]["labels"]["app"], p["metadata"]["labels"]["route"]): (
            p["spec"]["module"],
            p["spec"]["interval"],
            p["metadata"]["labels"]["criticality"],
        )
        for p in staging
    }
    for probe in prod:
        labels = probe["metadata"]["labels"]
        target_labels = probe["spec"]["targets"]["staticConfig"]["labels"]
        app, route = labels["app"], labels["route"]
        assert probe["metadata"]["name"] == f"blackbox-{app}-prod-{route}"
        assert labels["release"] == "kube-prometheus-stack"
        assert labels["environment"] == target_labels["environment"] == "prod"
        assert {k: target_labels[k] for k in ("app", "route", "criticality")} == {
            k: labels[k] for k in ("app", "route", "criticality")
        }
        assert probe["spec"]["targets"]["staticConfig"]["static"] == [PROD_MATRIX[app][route]]
        assert (
            probe["spec"]["module"],
            probe["spec"]["interval"],
            labels["criticality"],
        ) == staging_contract[(app, route)]
    assert "staging." not in json.dumps(prod)
    assert (
        "environment: prod"
        not in (ROOT / "clusters/staging/observability/probes/public-apps.yaml").read_text()
    )


def test_production_render_is_offline_and_uses_production_inputs(scenario):
    result = scenario.run("render", "prod", KUBECONFIG="/definitely/unusable")
    assert result.returncode == 0
    assert not any("config current-context" in line for line in scenario.log)
    assert any(
        "clusters/prod/observability/kube-prometheus-stack.values.yaml" in line
        for line in scenario.log
    )
    assert any(
        "clusters/prod/observability/prometheus-blackbox-exporter.values.yaml" in line
        for line in scenario.log
    )
    assert all(
        "clusters/prod/observability" in line
        for line in scenario.log
        if line.startswith("kubectl kustomize")
    )


def test_production_live_requires_explicit_kubeconfig_before_cluster_access(scenario):
    result = scenario.run("install", "prod")
    assert result.returncode == 3
    assert not any("config current-context" in line or "helm list" in line for line in scenario.log)
    assert not mutations(scenario.log)


@pytest.mark.parametrize("failure", ["bad_context", "bad_identity"])
def test_production_identity_guards_precede_release_queries(scenario, failure):
    result = scenario.run(
        "install", "prod", KUBECONFIG=scenario.root / "prod.yaml", SCENARIO=failure
    )
    assert result.returncode != 0
    assert not any("helm list" in line for line in scenario.log)
    assert not mutations(scenario.log)


def test_production_mutation_has_no_probe_cleanup(scenario):
    result = scenario.run(
        "install", "prod", KUBECONFIG=scenario.root / "prod.yaml", SCENARIO="release_absent"
    )
    assert result.returncode == 0
    assert not any(" delete probe " in line for line in scenario.log)


def test_prod_verifier_rejects_mixed_environment_and_requires_explicit_env():
    assert verify(verifier_bundle(environment="prod"), environment="prod").returncode == 0
    mixed = verifier_bundle(environment="prod")
    mixed["targets"]["data"]["activeTargets"][0]["labels"]["environment"] = "staging"
    assert verify(mixed, environment="prod").returncode == 9
    stdin, stderr, argv = sys.stdin, io.StringIO(), sys.argv
    try:
        sys.stdin = io.StringIO("{}")
        sys.argv = [str(ROOT / "scripts/verify_blackbox_prometheus.py")]
        with contextlib.redirect_stderr(stderr), pytest.raises(SystemExit) as error:
            runpy.run_path(sys.argv[0], run_name="__main__")
        assert error.value.code == 9
    finally:
        sys.stdin, sys.argv = stdin, argv
