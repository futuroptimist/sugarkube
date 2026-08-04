import json
import subprocess
from pathlib import Path
import pytest
from scripts import observability_app_metrics as m

ROOT = Path(__file__).resolve().parents[1]
INV = ROOT / "docs/observability-app-metrics.json"


def test_inventory_accepts_tokenplace_contract():
    data = m.load_inventory(INV)
    cfg = data["applications"]["tokenplace"]["staging"]
    assert cfg["secret"] == {"name": "tokenplace-staging-metrics-token", "key": "token"}
    assert cfg["expectedTargetCount"] == 1
    assert cfg["publicMetrics"]["expectedUnauthenticatedStatus"] == 401
    assert "tokenplace_relay_queue_depth" in cfg["requiredMetricFamilies"]
    assert "user_id" in cfg["forbiddenApplicationLabels"]


def test_inventory_rejects_unknown_keys_and_duplicates(tmp_path):
    data = json.loads(INV.read_text())
    data["applications"]["tokenplace"]["staging"]["surprise"] = True
    p = tmp_path / "bad.json"
    p.write_text(json.dumps(data))
    with pytest.raises(m.ConfigError, match="unknown"):
        m.load_inventory(p)
    data = json.loads(INV.read_text())
    fam = data["applications"]["tokenplace"]["staging"]["requiredMetricFamilies"]
    fam.append(fam[0])
    p.write_text(json.dumps(data))
    with pytest.raises(m.ConfigError, match="duplicate"):
        m.load_inventory(p)


def test_inventory_rejects_production_and_invalid_enums(tmp_path):
    data = json.loads(INV.read_text())
    data["applications"]["tokenplace"]["prod"] = data["applications"]["tokenplace"].pop("staging")
    p = tmp_path / "bad.json"
    p.write_text(json.dumps(data))
    with pytest.raises(m.ConfigError, match="staging-only"):
        m.load_inventory(p)
    data = json.loads(INV.read_text())
    data["applications"]["tokenplace"]["staging"]["allowedApplicationLabels"]["outcome"] = []
    p.write_text(json.dumps(data))
    with pytest.raises(m.ConfigError, match="must not be empty"):
        m.load_inventory(p)


def test_verifier_source_has_no_tokenplace_branch():
    text = (ROOT / "scripts/observability_app_metrics.py").read_text()
    assert 'if app == "tokenplace"' not in text
    assert "if app == 'tokenplace'" not in text


def test_redaction_for_malformed_prometheus(monkeypatch):
    def fake(args, **kwargs):
        if args[:3] == ["kubectl", "config", "current-context"]:
            return subprocess.CompletedProcess(args, 0, "sugar-staging", "")
        return subprocess.CompletedProcess(args, 0, b"{bad-secret-url-http://10.0.0.1}", b"")

    monkeypatch.setattr(m.subprocess, "run", fake)
    cfg = m.load_inventory(INV)["applications"]["tokenplace"]["staging"]
    with pytest.raises(m.VerifyError, match="redacted"):
        m.verify_kubectl_contract("anything", cfg)
