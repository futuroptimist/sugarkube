import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROBES = ROOT / "monitoring" / "probes" / "public-apps.yaml"
EXPORTER = ROOT / "platform" / "observability" / "prometheus-blackbox-exporter.yaml"
PLATFORM = ROOT / "platform" / "observability"
CANONICAL_APPS = {"dspace", "tokenplace", "danielsmith", "jobbot3000"}
CANONICAL_ENVS = {"staging", "prod"}
CANONICAL_ROUTES = {"root", "healthz", "livez", "config", "tracker", "manifest", "metadata"}
PLACEHOLDERS = ("example.test", "REPLACE", "localhost", "127.0.0.1", "0.0.0.0")
EXPECTED_TARGETS = {
    ("dspace", "staging", "root", "https://staging.democratized.space/", "https_2xx"),
    (
        "dspace",
        "staging",
        "config",
        "https://staging.democratized.space/config.json",
        "static_content_2xx",
    ),
    (
        "dspace",
        "staging",
        "healthz",
        "https://staging.democratized.space/healthz",
        "json_health_2xx",
    ),
    ("dspace", "staging", "livez", "https://staging.democratized.space/livez", "json_health_2xx"),
    ("dspace", "prod", "root", "https://democratized.space/", "https_2xx"),
    ("dspace", "prod", "config", "https://democratized.space/config.json", "static_content_2xx"),
    ("dspace", "prod", "healthz", "https://democratized.space/healthz", "json_health_2xx"),
    ("dspace", "prod", "livez", "https://democratized.space/livez", "json_health_2xx"),
    ("tokenplace", "staging", "root", "https://staging.token.place/", "https_2xx"),
    ("tokenplace", "staging", "healthz", "https://staging.token.place/healthz", "json_health_2xx"),
    ("tokenplace", "staging", "livez", "https://staging.token.place/livez", "json_health_2xx"),
    (
        "tokenplace",
        "staging",
        "metadata",
        "https://staging.token.place/api/v1/meta",
        "static_content_2xx",
    ),
    ("tokenplace", "prod", "root", "https://token.place/", "https_2xx"),
    ("tokenplace", "prod", "healthz", "https://token.place/healthz", "json_health_2xx"),
    ("tokenplace", "prod", "livez", "https://token.place/livez", "json_health_2xx"),
    ("tokenplace", "prod", "metadata", "https://token.place/api/v1/meta", "static_content_2xx"),
    ("danielsmith", "staging", "root", "https://staging.danielsmith.io/", "https_2xx"),
    (
        "danielsmith",
        "staging",
        "healthz",
        "https://staging.danielsmith.io/healthz",
        "json_health_2xx",
    ),
    ("danielsmith", "staging", "livez", "https://staging.danielsmith.io/livez", "json_health_2xx"),
    ("danielsmith", "prod", "root", "https://danielsmith.io/", "https_2xx"),
    ("danielsmith", "prod", "healthz", "https://danielsmith.io/healthz", "json_health_2xx"),
    ("danielsmith", "prod", "livez", "https://danielsmith.io/livez", "json_health_2xx"),
    ("jobbot3000", "staging", "root", "https://staging.jobbot3000.tech/", "https_2xx"),
    (
        "jobbot3000",
        "staging",
        "healthz",
        "https://staging.jobbot3000.tech/healthz",
        "json_health_2xx",
    ),
    ("jobbot3000", "staging", "livez", "https://staging.jobbot3000.tech/livez", "json_health_2xx"),
    (
        "jobbot3000",
        "staging",
        "tracker",
        "https://staging.jobbot3000.tech/tracker",
        "static_content_2xx",
    ),
    (
        "jobbot3000",
        "staging",
        "manifest",
        "https://staging.jobbot3000.tech/manifest.webmanifest",
        "static_content_2xx",
    ),
}


def _yaml_docs(path: Path):
    text = path.read_text(encoding="utf-8")
    assert text.strip(), f"{path} must not be empty"
    result = subprocess.run(
        [
            "ruby",
            "-ryaml",
            "-rjson",
            "-e",
            "puts JSON.generate(YAML.load_stream(File.read(ARGV[0])).compact)",
            str(path),
        ],
        text=True,
        check=True,
        capture_output=True,
    )
    return json.loads(result.stdout)


def _exporter_values():
    docs = _yaml_docs(EXPORTER)
    configmap = next(
        doc
        for doc in docs
        if doc.get("kind") == "ConfigMap"
        and doc["metadata"]["name"] == "prometheus-blackbox-exporter-values"
    )
    values_text = configmap["data"]["values.yaml"]
    assert values_text.strip()
    result = subprocess.run(
        ["ruby", "-ryaml", "-rjson", "-e", "puts JSON.generate(YAML.load(STDIN.read))"],
        input=values_text,
        text=True,
        check=True,
        capture_output=True,
    )
    return json.loads(result.stdout), docs


def _probe_records():
    records = []
    for doc in _yaml_docs(PROBES):
        assert doc["kind"] == "Probe"
        meta = doc["metadata"]
        labels = meta.get("labels", {})
        spec = doc["spec"]
        static_config = spec["targets"]["staticConfig"]
        target_labels = static_config.get("labels", {})
        targets = static_config.get("static", [])
        assert len(targets) == 1
        for key in ("app", "environment", "route", "criticality"):
            assert labels.get(key), f"metadata label {key} missing on {meta['name']}"
            assert (
                target_labels.get(key) == labels[key]
            ), f"target label {key} missing/drifted on {meta['name']}"
        records.append((meta["name"], labels, targets[0], spec["module"]))
    return records


def test_monitoring_and_observability_yaml_documents_parse():
    paths = sorted(
        path
        for directory in (ROOT / "monitoring", ROOT / "platform" / "observability")
        for path in directory.rglob("*")
        if path.suffix in {".yaml", ".yml"}
    )
    assert paths
    for path in paths:
        _yaml_docs(path)
    _exporter_values()


def test_blackbox_exporter_helmrelease_is_pinned_internal_and_valid():
    values, docs = _exporter_values()
    release = next(doc for doc in docs if doc.get("kind") == "HelmRelease")
    assert release["spec"]["chart"]["spec"]["chart"] == "prometheus-blackbox-exporter"
    assert release["spec"]["chart"]["spec"]["version"] == "11.15.1"
    assert release["spec"]["chart"]["spec"]["sourceRef"]["name"] == "prometheus-community"
    assert "image" not in values
    assert values["service"]["type"] == "ClusterIP"
    assert values["ingress"]["enabled"] is False
    modules = values["config"]["modules"]
    assert set(modules) == {"https_2xx", "json_health_2xx", "static_content_2xx"}
    https_status_codes = modules["https_2xx"]["http"].get("valid_status_codes")
    assert https_status_codes in (
        None,
        [],
    ), "https_2xx must use blackbox_exporter's generic 2xx default"
    assert modules["json_health_2xx"]["http"]["valid_status_codes"] == [200]
    assert modules["static_content_2xx"]["http"]["valid_status_codes"] == [200]
    for module in modules.values():
        http = module["http"]
        assert http["follow_redirects"] is True
        assert http["fail_if_not_ssl"] is True
        assert http["tls_config"]["insecure_skip_verify"] is False
    assert modules["json_health_2xx"]["http"]["body_size_limit"] == "1MiB"
    assert modules["json_health_2xx"]["http"]["fail_if_body_not_matches_regexp"] == [
        '"status"[[:space:]]*:[[:space:]]*"(ok|ready|alive)"'
    ]
    assert modules["static_content_2xx"]["http"]["body_size_limit"] == "1MiB"
    static_matchers = modules["static_content_2xx"]["http"]["fail_if_body_not_matches_regexp"]
    assert static_matchers == ['(offlineWorker|"environment"|"version"|jobbot3000)']
    for pattern in [
        *modules["json_health_2xx"]["http"]["fail_if_body_not_matches_regexp"],
        *static_matchers,
    ]:
        assert not re.search(r"\\\\[{}]", pattern)
        assert not re.search(r"\{\d+,\d{4,}\}", pattern)


def test_blackbox_network_policy_allows_internal_tcp_9115():
    _, docs = _exporter_values()
    policy = next(doc for doc in docs if doc.get("kind") == "NetworkPolicy")
    assert policy["metadata"] == {
        "name": "prometheus-blackbox-exporter-monitoring-egress",
        "namespace": "monitoring",
    }
    assert "Egress" in policy["spec"]["policyTypes"]
    egress = policy["spec"]["egress"]
    assert any(
        port.get("protocol") == "TCP" and port.get("port") == 9115
        for rule in egress
        for port in rule.get("ports", [])
    )
    assert any(
        dest.get("podSelector", {}).get("matchLabels", {}).get("app.kubernetes.io/name")
        == "prometheus-blackbox-exporter"
        for rule in egress
        for dest in rule.get("to", [])
    )


def test_probe_names_labels_targets_and_modules_are_exact():
    records = _probe_records()
    names = [name for name, _, _, _ in records]
    assert len(names) == len(set(names))
    actual = set()
    for name, labels, target, module in records:
        assert name.startswith("blackbox-")
        assert labels["release"] == "kube-prometheus-stack"
        assert labels["app"] in CANONICAL_APPS
        assert labels["environment"] in CANONICAL_ENVS
        assert labels["route"] in CANONICAL_ROUTES
        assert labels["criticality"] in {"critical", "warning"}
        assert target.startswith("https://")
        assert all(bad not in target for bad in PLACEHOLDERS)
        actual.add((labels["app"], labels["environment"], labels["route"], target, module))
    assert actual == EXPECTED_TARGETS
    assert (
        "jobbot3000",
        "staging",
        "tracker",
        "https://staging.jobbot3000.tech/",
        "static_content_2xx",
    ) not in actual


def test_documented_omissions_and_wiring_are_intentional():
    probes_text = PROBES.read_text(encoding="utf-8")
    assert "jobbot3000-prod" not in probes_text
    assert "/resume.pdf" not in probes_text
    docs = (ROOT / "docs" / "observability-blackbox.md").read_text(encoding="utf-8")
    assert "jobbot3000.example.test" in docs
    assert "environment=dev" in docs
    assert "probe_duration_seconds_bucket" not in docs
    assert "avg by (app, environment, route) (probe_duration_seconds)" in docs
    shared = (ROOT / "monitoring" / "kustomization.yaml").read_text(encoding="utf-8")
    probes_kustomization = (ROOT / "monitoring" / "probes" / "kustomization.yaml").read_text(
        encoding="utf-8"
    )
    dev = (ROOT / "clusters" / "dev" / "kustomization.yaml").read_text(encoding="utf-8")
    staging = (ROOT / "clusters" / "staging" / "kustomization.yaml").read_text(encoding="utf-8")
    prod = (ROOT / "clusters" / "prod" / "kustomization.yaml").read_text(encoding="utf-8")
    assert "probes/public-apps.yaml" not in shared
    assert "public-apps.yaml" in probes_kustomization
    assert "../../monitoring/probes" not in dev
    assert "../../monitoring/probes" in staging
    assert "../../monitoring/probes" in prod
