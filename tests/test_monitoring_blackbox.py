from __future__ import annotations

from collections import Counter
from pathlib import Path

import json
import subprocess

ROOT = Path(__file__).resolve().parents[1]
PROBE_FILE = ROOT / "monitoring" / "probes" / "public-blackbox.yaml"
BLACKBOX_VALUES = ROOT / "platform" / "observability" / "prometheus-blackbox-exporter-values.yaml"
PLACEHOLDERS = ("example.test", "REPLACE", "localhost", "127.0.0.1", "0.0.0.0")
APPS = {"dspace", "tokenplace", "danielsmith", "jobbot3000"}
ENVS = {"staging", "prod"}
ROUTES = {"root", "healthz", "livez", "config", "resume", "tracker", "manifest", "metadata"}
CRITICALITIES = {"critical", "warning"}


def _load_all(path: Path) -> list[dict]:
    script = "require \"yaml\"; require \"json\"; puts YAML.load_stream(File.read(ARGV[0])).compact.to_json"
    completed = subprocess.run(["ruby", "-e", script, str(path)], check=True, text=True, capture_output=True)
    return json.loads(completed.stdout)


def _probe_docs() -> list[dict]:
    docs = _load_all(PROBE_FILE)
    assert docs, "expected at least one Probe"
    assert all(doc.get("kind") == "Probe" for doc in docs)
    return docs


def test_blackbox_values_yaml_is_valid_and_small_module_set() -> None:
    values_config = _load_all(BLACKBOX_VALUES)[0]
    values_yaml = values_config["data"]["values.yaml"]
    completed = subprocess.run(["ruby", "-e", "require \"yaml\"; require \"json\"; puts YAML.safe_load(STDIN.read).to_json"], input=values_yaml, check=True, text=True, capture_output=True)
    values = json.loads(completed.stdout)

    assert values["ingress"]["enabled"] is False
    modules = values["config"]["modules"]
    assert set(modules) == {"http_2xx", "http_json_health", "http_static_content"}
    for module in modules.values():
        assert module["prober"] == "http"
        http = module["http"]
        assert http["follow_redirects"] is True
        assert http["fail_if_not_ssl"] is True
        assert http["tls_config"]["insecure_skip_verify"] is False


def test_probe_names_are_unique_and_have_release_label() -> None:
    probes = _probe_docs()
    names = [probe["metadata"]["name"] for probe in probes]
    duplicates = [name for name, count in Counter(names).items() if count > 1]
    assert not duplicates

    for probe in probes:
        metadata = probe["metadata"]
        assert metadata["namespace"] == "monitoring"
        assert metadata.get("labels", {}).get("release") == "kube-prometheus-stack"


def test_probe_targets_have_bounded_required_labels_and_no_placeholders() -> None:
    for probe in _probe_docs():
        spec = probe["spec"]
        assert spec["prober"]["url"] == "prometheus-blackbox-exporter.monitoring.svc.cluster.local:9115"
        static_config = spec["targets"]["staticConfig"]
        targets = static_config["static"]
        assert len(targets) == 1
        target = targets[0]
        assert target.startswith("https://")
        assert not any(token in target for token in PLACEHOLDERS)

        labels = static_config["labels"]
        assert labels["app"] in APPS
        assert labels["environment"] in ENVS
        assert labels["route"] in ROUTES
        assert labels["criticality"] in CRITICALITIES
        assert not labels["route"].startswith("http")


def test_expected_canonical_app_environment_coverage() -> None:
    seen = {
        (probe["spec"]["targets"]["staticConfig"]["labels"]["app"],
         probe["spec"]["targets"]["staticConfig"]["labels"]["environment"])
        for probe in _probe_docs()
    }
    assert ("dspace", "staging") in seen
    assert ("dspace", "prod") in seen
    assert ("tokenplace", "staging") in seen
    assert ("tokenplace", "prod") in seen
    assert ("danielsmith", "staging") in seen
    assert ("danielsmith", "prod") in seen
    assert ("jobbot3000", "staging") in seen
    assert ("jobbot3000", "prod") not in seen
