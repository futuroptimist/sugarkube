from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
PROBE_FILE = REPO_ROOT / "monitoring" / "probes" / "app-public-blackbox.yaml"
PLACEHOLDERS = ("example.test", "REPLACE", "localhost")
CANONICAL_APPS = {"dspace", "tokenplace", "danielsmith", "jobbot3000"}
CANONICAL_ENVS = {"staging", "prod"}


def _probe_docs() -> list[str]:
    return [
        doc.strip()
        for doc in PROBE_FILE.read_text(encoding="utf-8").split("---")
        if doc.strip()
    ]


def _field(doc: str, name: str) -> str | None:
    match = re.search(rf"(?m)^\s*{re.escape(name)}:\s*([^\n]+)\s*$", doc)
    return match.group(1).strip() if match else None


def test_monitoring_yaml_is_parseable() -> None:
    ruby = shutil.which("ruby")
    assert ruby, "ruby with stdlib YAML is required to validate Kubernetes YAML in tests"
    paths = [
        *sorted((REPO_ROOT / "monitoring").rglob("*.yaml")),
        *sorted((REPO_ROOT / "platform" / "observability").rglob("*.yaml")),
    ]
    subprocess.run(
        [
            ruby,
            "-e",
            "require 'yaml'; ARGV.each { |p| YAML.load_stream(File.read(p)) }",
            *map(str, paths),
        ],
        check=True,
        cwd=REPO_ROOT,
    )


def test_blackbox_exporter_is_pinned_and_internal() -> None:
    release = (REPO_ROOT / "platform" / "observability" / "blackbox-exporter.yaml").read_text(
        encoding="utf-8"
    )
    values = (
        REPO_ROOT / "platform" / "observability" / "blackbox-exporter-values.yaml"
    ).read_text(encoding="utf-8")
    assert "kind: HelmRelease" in release
    assert "chart: prometheus-blackbox-exporter" in release
    assert re.search(r"(?m)^\s+version:\s+11\.15\.1\s*$", release)
    assert re.search(r"(?m)^\s+tag:\s+v0\.27\.0\s*$", values)
    assert re.search(r"(?m)^\s+type:\s+ClusterIP\s*$", values)
    assert re.search(r"(?m)^\s+ingress:\n\s+enabled:\s+false", values)


def test_probe_names_are_unique_and_have_release_label() -> None:
    names: list[str] = []
    for doc in _probe_docs():
        assert "kind: Probe" in doc
        name = _field(doc, "name")
        assert name
        names.append(name)
        assert re.search(r"(?m)^\s+release:\s+kube-prometheus-stack\s*$", doc), name
    assert len(names) == len(set(names))


def test_probes_have_bounded_canonical_labels_and_no_placeholder_targets() -> None:
    for doc in _probe_docs():
        name = _field(doc, "name") or "<unnamed>"
        for placeholder in PLACEHOLDERS:
            assert placeholder not in doc, f"{name} contains placeholder {placeholder}"
        app = _field(doc, "app")
        env = _field(doc, "environment")
        route = _field(doc, "route")
        criticality = _field(doc, "criticality")
        assert app in CANONICAL_APPS, name
        assert env in CANONICAL_ENVS, name
        assert route in {"root", "healthz", "livez", "config", "metadata"}, name
        assert criticality in {"critical", "warning"}, name
        assert not (route or "").startswith("http"), name


def test_expected_active_targets_and_documented_omissions() -> None:
    text = PROBE_FILE.read_text(encoding="utf-8")
    expected = {
        ("dspace", "staging", "root"),
        ("dspace", "staging", "config"),
        ("dspace", "staging", "healthz"),
        ("dspace", "staging", "livez"),
        ("dspace", "prod", "root"),
        ("tokenplace", "prod", "metadata"),
        ("danielsmith", "staging", "metadata"),
        ("jobbot3000", "staging", "root"),
    }
    for app, env, route in expected:
        assert f"app: {app}" in text and f"environment: {env}" in text and f"route: {route}" in text
    docs = (REPO_ROOT / "docs" / "observability-blackbox.md").read_text(encoding="utf-8")
    assert "jobbot3000 production is omitted" in docs
    assert "danielsmith.io `/resume.pdf` is omitted" in docs
