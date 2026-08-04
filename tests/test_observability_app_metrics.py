from __future__ import annotations
import json
from pathlib import Path
import pytest
from scripts import observability_app_metrics as m

ROOT = Path(__file__).resolve().parents[1]


def test_inventory_tokenplace_contract_is_strict():
    data = m.load()
    c = data["applications"]["tokenplace"]["environments"]["staging"]
    assert c["secret"] == {"name": "tokenplace-staging-metrics-token", "key": "token"}
    assert c["expectedTargetCount"] == 1
    assert c["endpoint"]["path"] == "/metrics"
    assert c["endpoint"]["expectedUnauthenticatedStatus"] == 401
    assert c["targetLabels"] == {
        "app": "tokenplace",
        "environment": "staging",
        "release": "tokenplace",
        "cluster": "sugarkube-int",
    }
    assert "tokenplace_build_info" in c["requiredMetricFamilies"]
    assert len(c["requiredMetricFamilies"]) == len(set(c["requiredMetricFamilies"]))


def test_inventory_rejects_unknown_and_duplicate(tmp_path):
    bad = {
        "applications": {
            "demo": {"environments": {"staging": dict(m.cfg("tokenplace", "staging"), extra=True)}}
        }
    }
    p = tmp_path / "bad.json"
    p.write_text(json.dumps(bad))
    with pytest.raises(m.Error, match="unknown"):
        m.load(p)
    bad["applications"]["demo"]["environments"]["staging"].pop("extra")
    bad["applications"]["demo"]["environments"]["staging"]["requiredMetricFamilies"] = ["x", "x"]
    p.write_text(json.dumps(bad))
    with pytest.raises(m.Error, match="duplicate"):
        m.load(p)


def test_verifier_source_has_no_tokenplace_branch():
    src = (ROOT / "scripts/observability_app_metrics.py").read_text()
    assert 'if app == "tokenplace"' not in src
    assert "if app == 'tokenplace'" not in src


def test_secret_install_refuses_env_and_nontty(monkeypatch):
    monkeypatch.setenv("METRICS_TOKEN", "redacted")
    with pytest.raises(m.Error, match="environment"):
        m.secret_install("tokenplace", "staging")
    monkeypatch.delenv("METRICS_TOKEN")
    monkeypatch.setattr(m.sys.stdin, "isatty", lambda: False)
    with pytest.raises(m.Error, match="terminal"):
        m.secret_install("tokenplace", "staging")


def test_cli_rejects_production(capsys):
    assert m.main(["verify", "--app", "tokenplace", "--env", "prod"]) == 2
    assert "production" in capsys.readouterr().err
