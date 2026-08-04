import json
from pathlib import Path

import pytest

from scripts import observability_app_metrics as m

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "platform/observability/app-metrics.json"
SCRIPT = ROOT / "scripts/observability_app_metrics.py"


def test_inventory_tokenplace_contract_is_strict_and_complete():
    doc = json.loads(CONFIG.read_text())
    m.validate_inventory(doc)
    cfg = doc["applications"]["tokenplace"]["environments"]["staging"]
    assert cfg["namespace"] == "tokenplace"
    assert cfg["serviceMonitorName"] == "tokenplace"
    assert cfg["expectedTargetCount"] == 1
    assert cfg["secret"] == {"name": "tokenplace-staging-metrics-token", "key": "token"}
    assert cfg["serviceMonitor"]["path"] == "/metrics"
    assert cfg["serviceMonitor"]["interval"] == "30s"
    assert cfg["serviceMonitor"]["scrapeTimeout"] == "10s"
    assert cfg["targetLabels"] == {
        "app": "tokenplace",
        "environment": "staging",
        "release": "tokenplace",
        "cluster": "sugarkube-int",
        "namespace": "tokenplace",
    }
    assert cfg["publicMetrics"]["expectedUnauthenticatedStatus"] == 401
    assert "tokenplace_build_info" in cfg["requiredMetricFamilies"]
    assert "token" in cfg["forbiddenApplicationLabels"]


def test_inventory_rejects_unknown_keys_duplicates_and_bad_status():
    doc = json.loads(CONFIG.read_text())
    cfg = doc["applications"]["tokenplace"]["environments"]["staging"]
    cfg["extra"] = True
    with pytest.raises(SystemExit):
        m.validate_inventory(doc)
    doc = json.loads(CONFIG.read_text())
    metrics = doc["applications"]["tokenplace"]["environments"]["staging"]["requiredMetricFamilies"]
    metrics.append(metrics[0])
    with pytest.raises(SystemExit):
        m.validate_inventory(doc)
    doc = json.loads(CONFIG.read_text())
    doc["applications"]["tokenplace"]["environments"]["staging"]["publicMetrics"][
        "expectedUnauthenticatedStatus"
    ] = 99
    with pytest.raises(SystemExit):
        m.validate_inventory(doc)


def test_inventory_rejects_non_object_selector_match_labels():
    doc = json.loads(CONFIG.read_text())
    doc["applications"]["tokenplace"]["environments"]["staging"]["serviceMonitor"][
        "selectorMatchLabels"
    ] = []
    with pytest.raises(SystemExit) as excinfo:
        m.validate_inventory(doc)
    assert "selectorMatchLabels must be a nonempty object" in str(excinfo.value)


def test_standard_scrape_labels_are_not_forbidden_application_labels():
    cfg = json.loads(CONFIG.read_text())["applications"]["tokenplace"]["environments"]["staging"]
    m.validate_metric_labels(
        cfg,
        {
            "__name__": "tokenplace_build_info",
            "instance": "10.42.0.10:8080",
            "pod": "tokenplace-abc123",
            "app": "tokenplace",
            "environment": "staging",
            "version": "0.1.4",
        },
    )
    with pytest.raises(SystemExit) as excinfo:
        m.validate_metric_labels(cfg, {"customer_email": "fixture@example.invalid"})
    assert "unbounded application metric label" in str(excinfo.value)


def test_verifier_has_no_tokenplace_specific_branch():
    text = SCRIPT.read_text()
    assert 'if app == "tokenplace"' not in text
    assert 'elif app == "tokenplace"' not in text
    assert text.count("tokenplace") == 0
