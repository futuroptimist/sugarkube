from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
PROBES = ROOT / "monitoring" / "probes" / "public-apps.yaml"
PLATFORM = ROOT / "platform" / "observability"
CANONICAL_APPS = {"dspace", "tokenplace", "danielsmith", "jobbot3000"}
CANONICAL_ENVS = {"staging", "prod"}
PLACEHOLDERS = ("example.test", "REPLACE", "localhost", "127.0.0.1", "0.0.0.0")


def _docs():
    text = PROBES.read_text(encoding="utf-8")
    return [doc for doc in re.split(r"^---\s*$", text, flags=re.M) if doc.strip()]


def _metadata_field(doc: str, field: str) -> str:
    match = re.search(rf"^    {re.escape(field)}: ([^\n]+)$", doc, flags=re.M)
    assert match, f"missing metadata label {field} in:\n{doc}"
    return match.group(1).strip().strip('"')


def _target_field(doc: str, field: str) -> str:
    match = re.search(rf"^        {re.escape(field)}: ([^\n]+)$", doc, flags=re.M)
    assert match, f"missing target label {field} in:\n{doc}"
    return match.group(1).strip().strip('"')


def test_blackbox_exporter_helmrelease_is_pinned_and_internal():
    release = (PLATFORM / "prometheus-blackbox-exporter.yaml").read_text(encoding="utf-8")
    values = (PLATFORM / "prometheus-blackbox-exporter-values.yaml").read_text(encoding="utf-8")
    kustomization = (PLATFORM / "kustomization.yaml").read_text(encoding="utf-8")

    assert "kind: HelmRelease" in release
    assert "chart: prometheus-blackbox-exporter" in release
    assert "version: 11.15.1" in release
    assert "name: prometheus-community" in release
    assert "ingress:" not in values
    assert "https_2xx:" in values
    assert "json_health_2xx:" in values
    assert "static_content_2xx:" in values
    assert "prometheus-blackbox-exporter.yaml" in kustomization


def test_probe_names_labels_and_targets_are_bounded():
    names = set()
    for doc in _docs():
        assert "kind: Probe" in doc
        name_match = re.search(r"^  name: ([^\n]+)$", doc, flags=re.M)
        assert name_match, doc
        name = name_match.group(1).strip()
        assert name not in names, f"duplicate Probe name {name}"
        names.add(name)
        assert "namespace: monitoring" in doc
        assert "release: kube-prometheus-stack" in doc
        app = _metadata_field(doc, "app")
        env = _metadata_field(doc, "environment")
        route = _metadata_field(doc, "route")
        criticality = _metadata_field(doc, "criticality")
        assert app in CANONICAL_APPS
        assert env in CANONICAL_ENVS
        assert route in {"root", "healthz", "livez", "config", "resume", "tracker", "manifest", "metadata"}
        assert criticality in {"critical", "warning"}
        assert _target_field(doc, "app") == app
        assert _target_field(doc, "environment") == env
        assert _target_field(doc, "route") == route
        assert _target_field(doc, "criticality") == criticality
        target = re.search(r"^        - (https://[^\n]+)$", doc, flags=re.M)
        assert target, doc
        assert all(bad not in target.group(1) for bad in PLACEHOLDERS)


def test_required_probe_coverage_and_documented_omissions():
    text = PROBES.read_text(encoding="utf-8")
    for app in CANONICAL_APPS:
        assert f"app: {app}" in text
    for env in CANONICAL_ENVS:
        assert f"environment: {env}" in text
    assert "https://staging.jobbot3000.tech/manifest.webmanifest" in text
    assert "jobbot3000-prod" not in text
    docs = (ROOT / "docs" / "observability-blackbox.md").read_text(encoding="utf-8")
    assert "jobbot3000.example.test" in docs
    assert "omitted" in docs.lower()


def test_public_probes_are_only_in_staging_and_prod_overlays():
    shared = (ROOT / "monitoring" / "kustomization.yaml").read_text(encoding="utf-8")
    dev = (ROOT / "clusters" / "dev" / "kustomization.yaml").read_text(encoding="utf-8")
    staging = (ROOT / "clusters" / "staging" / "kustomization.yaml").read_text(encoding="utf-8")
    prod = (ROOT / "clusters" / "prod" / "kustomization.yaml").read_text(encoding="utf-8")

    assert "probes/public-apps.yaml" not in shared
    assert "../../monitoring/probes" not in dev
    assert "../../monitoring/probes" in staging
    assert "../../monitoring/probes" in prod
