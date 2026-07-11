from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROBES = ROOT / "monitoring" / "probes" / "public-blackbox.yaml"
PLACEHOLDERS = ("example.test", "REPLACE", "localhost", "127.0.0.1", "0.0.0.0")
CANONICAL_APPS = {"dspace", "tokenplace", "danielsmith", "jobbot3000"}
CANONICAL_ENVS = {"staging", "prod"}


def _probe_docs() -> list[str]:
    text = PROBES.read_text(encoding="utf-8")
    return [doc for doc in re.split(r"^---\s*$", text, flags=re.MULTILINE) if "kind: Probe" in doc]


def _field(doc: str, key: str) -> str | None:
    match = re.search(rf"^\s*{re.escape(key)}:\s*([^\n]+)$", doc, flags=re.MULTILINE)
    if match:
        return match.group(1).strip().strip("{},")
    inline = re.search(rf"[{{,]\s*{re.escape(key)}:\s*([^,}}]+)", doc)
    return inline.group(1).strip() if inline else None


def test_public_blackbox_probes_have_unique_names_and_release_label() -> None:
    names: list[str] = []
    for doc in _probe_docs():
        name = _field(doc, "name")
        assert name, f"Probe missing metadata.name:\n{doc}"
        names.append(name)
        assert _field(doc, "release") == "kube-prometheus-stack", name
    assert len(names) == len(set(names)), "Probe names must be unique"


def test_public_blackbox_probes_use_bounded_canonical_labels() -> None:
    routes = {"root", "healthz", "livez", "config", "resume", "tracker", "manifest", "metadata"}
    for doc in _probe_docs():
        name = _field(doc, "name") or "unknown"
        labels = {key: _field(doc, key) for key in ("app", "environment", "route", "criticality")}
        assert labels["app"] in CANONICAL_APPS, (name, labels)
        assert labels["environment"] in CANONICAL_ENVS, (name, labels)
        assert labels["route"] in routes, (name, labels)
        assert labels["criticality"] in {"critical", "warning"}, (name, labels)
        assert "http" not in (labels["route"] or ""), (name, labels)


def test_public_blackbox_probes_do_not_use_placeholder_hosts() -> None:
    text = PROBES.read_text(encoding="utf-8")
    for placeholder in PLACEHOLDERS:
        assert placeholder not in text


def test_monitoring_kustomization_includes_blackbox_probes() -> None:
    kustomization = (ROOT / "monitoring" / "kustomization.yaml").read_text(encoding="utf-8")
    assert "probes/public-blackbox.yaml" in kustomization


def test_blackbox_exporter_is_flux_managed_and_pinned() -> None:
    release = (ROOT / "platform" / "observability" / "prometheus-blackbox-exporter.yaml").read_text(
        encoding="utf-8"
    )
    assert "kind: HelmRelease" in release
    assert "chart: prometheus-blackbox-exporter" in release
    version = re.search(r"^\s*version:\s*([^\n]+)$", release, flags=re.MULTILINE)
    assert version and re.fullmatch(r"\d+\.\d+\.\d+", version.group(1).strip())
    values = (
        ROOT / "platform" / "observability" / "prometheus-blackbox-exporter-values.yaml"
    ).read_text(encoding="utf-8")
    for module in ("https_2xx", "https_json_health", "https_static_content"):
        assert f"{module}:" in values
