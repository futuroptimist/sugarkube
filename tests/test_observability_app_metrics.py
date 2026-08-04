import copy
import json
from pathlib import Path

import pytest

import scripts.observability_app_metrics as appm

ROOT = Path(__file__).resolve().parents[1]


def load():
    return json.loads((ROOT / "platform/observability/app-metrics.json").read_text())


def test_inventory_is_strict_and_tokenplace_contract_is_declared():
    data = load()
    appm.validate_inventory(data)
    cfg = data["applications"]["tokenplace"]["environments"]["staging"]
    assert cfg["metricsSecret"] == {"name": "tokenplace-staging-metrics-token", "key": "token"}
    assert cfg["expectedTargetCount"] == 1
    assert cfg["endpoint"] == {"path": "/metrics", "interval": "30s", "scrapeTimeout": "10s"}
    assert cfg["publicMetrics"]["expectedUnauthenticatedStatus"] == 401
    assert cfg["targetLabels"] == {
        "app": "tokenplace",
        "environment": "staging",
        "release": "tokenplace",
        "cluster": "sugarkube-int",
    }
    assert len(cfg["requiredMetricFamilies"]) == len(set(cfg["requiredMetricFamilies"]))


def test_inventory_rejects_unknown_keys_duplicates_bad_status_and_enums():
    data = load()
    cfg = data["applications"]["tokenplace"]["environments"]["staging"]
    bad = copy.deepcopy(data)
    bad["extra"] = True
    with pytest.raises(SystemExit):
        appm.validate_inventory(bad)
    bad = copy.deepcopy(data)
    bad["applications"]["tokenplace"]["environments"]["staging"]["publicMetrics"][
        "expectedUnauthenticatedStatus"
    ] = 200
    with pytest.raises(SystemExit):
        appm.validate_inventory(bad)
    bad = copy.deepcopy(data)
    bad["applications"]["tokenplace"]["environments"]["staging"]["requiredMetricFamilies"].append(
        cfg["requiredMetricFamilies"][0]
    )
    with pytest.raises(SystemExit):
        appm.validate_inventory(bad)
    bad = copy.deepcopy(data)
    bad["applications"]["tokenplace"]["environments"]["staging"]["allowedApplicationLabels"][
        "bad_label"
    ] = []
    with pytest.raises(SystemExit):
        appm.validate_inventory(bad)


def test_verifier_source_is_application_agnostic():
    source = (ROOT / "scripts/observability_app_metrics.py").read_text()
    assert 'if app == "tokenplace"' not in source
    assert "elif app ==" not in source


class CP:
    def __init__(self, out, rc=0):
        self.stdout = out if isinstance(out, bytes) else out.encode()
        self.stderr = b""
        self.returncode = rc


def test_secret_check_does_not_decode_or_print_value(monkeypatch, capsys):
    cfg = load()["applications"]["tokenplace"]["environments"]["staging"]
    calls = []

    def fake(cmd, input_bytes=None):
        calls.append(cmd)
        if cmd[:3] == ["kubectl", "config", "current-context"]:
            return CP("sugar-staging\n")
        return CP("present")

    monkeypatch.setattr(appm, "run", fake)
    appm.secret_check(cfg)
    out = capsys.readouterr().out
    assert "intentionally not read or printed" in out
    assert all("decode" not in " ".join(c) for c in calls)
    assert "tokenplace-staging-metrics-token" in out and "present" not in out


def test_public_401_accepts_only_expected_status(monkeypatch):
    cfg = load()["applications"]["tokenplace"]["environments"]["staging"]

    class E(Exception):
        code = 401

    monkeypatch.setattr(appm.urllib.request, "urlopen", lambda *a, **k: (_ for _ in ()).throw(E()))
    monkeypatch.setattr(appm.urllib.error, "HTTPError", E)
    appm.public_401(cfg)
