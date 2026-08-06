import importlib.util
import json
import re
import stat
import subprocess
import sys
import time
from pathlib import Path

from test_observability_helm import yaml_load

ROOT = Path(__file__).parents[1]
VALUES = ROOT / "clusters/staging/observability/kube-prometheus-stack.values.yaml"
RULES = ROOT / "platform/observability/rules/dspace-release-integrity.yaml"
STAGING = ROOT / "deployment-evidence/dspace/staging/main-018687f-20260805T035722Z.json"
PROD = ROOT / "deployment-evidence/dspace/prod/main-1a31a56-20260801T093443Z.json"
PRODUCER = ROOT / "scripts/dspace_chat_synthetic_metrics.py"
NAMES = {
    "DspaceBuildRevisionMismatch",
    "DspaceMixedBuildRevisions",
    "DspaceDeploymentImagePinMismatch",
    "DspaceChatSyntheticFailed",
    "DspaceMetricsTargetDown",
}
RUNBOOK = (
    "https://github.com/futuroptimist/sugarkube/blob/main/docs/"
    "observability-dspace-release-integrity.md"
)


def rules():
    return yaml_load(RULES)["groups"][0]["rules"]


def render_alert_contracts(canonical_rules, environment, cluster, evidence):
    """Render non-installable alert metadata from finalized release evidence."""
    if evidence.get("recordType") != "final" or evidence.get("environment") != environment:
        raise ValueError("alert contracts require finalized evidence for their environment")
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,62}", cluster):
        raise ValueError("cluster contract must be a bounded identifier")

    coordinates = {
        "application_version": evidence["applicationVersion"],
        "source_revision": evidence["sourceRevision"],
        "runtime_revision": evidence["runtimeSourceRevision"],
        "image_tag": evidence["imageTag"],
        "image_digest": evidence["imageDigest"],
        "chart_version": evidence["chartVersion"],
        "chart_digest": evidence["chartDigest"],
        "helm_revision": evidence["helmRevision"],
        "provider": evidence["expectedDefaultChatProvider"],
    }
    contracts = []
    for rule in canonical_rules:
        if "alert" not in rule:
            continue
        labels = dict(rule["labels"])
        labels.update(
            environment=environment,
            cluster=cluster,
            expected_revision=evidence["sourceRevision"],
        )
        contracts.append(
            {
                "alert": rule["alert"],
                "labels": labels,
                "annotations": dict(rule["annotations"]),
                "coordinates": dict(coordinates),
            }
        )
    return contracts


def test_canonical_rules_equal_helm_representation_and_evidence():
    values = yaml_load(VALUES)
    assert (
        values["additionalPrometheusRulesMap"]["dspace-release-integrity"]["groups"]
        == yaml_load(RULES)["groups"]
    )
    approved = next(x for x in rules() if x.get("record") == "dspace_release_approved_info")[
        "labels"
    ]
    evidence = json.loads(STAGING.read_text())
    assert (
        approved["revision"],
        approved["image"],
        approved["image_digest"],
        approved["evidence"],
    ) == (
        evidence["sourceRevision"],
        evidence["imageTag"],
        evidence["imageDigest"],
        str(STAGING.relative_to(ROOT)),
    )
    prod = json.loads(PROD.read_text())
    assert (
        prod["sourceRevision"] == "1a31a569aff2dbeb238e8c2688b9e85140d2077d"
        and prod["helmRevision"] == 9
    )
    assert (
        evidence["semanticTag"] not in RULES.read_text()
        and prod["semanticTag"] not in RULES.read_text()
    )


def test_staging_alert_contracts_agree_with_canonical_rules():
    evidence = json.loads(STAGING.read_text())
    canonical_alerts = [rule for rule in rules() if "alert" in rule]
    contracts = render_alert_contracts(canonical_alerts, "staging", "sugarkube-int", evidence)

    assert {contract["alert"] for contract in contracts} == NAMES
    assert [contract["labels"] for contract in contracts] == [
        rule["labels"] for rule in canonical_alerts
    ]
    assert [contract["annotations"] for contract in contracts] == [
        rule["annotations"] for rule in canonical_alerts
    ]


def test_production_alert_contracts_derive_from_finalized_evidence_only():
    evidence = json.loads(PROD.read_text())
    contracts = render_alert_contracts(rules(), "prod", "sugarkube-prod", evidence)
    expected_coordinates = {
        "application_version": evidence["applicationVersion"],
        "source_revision": evidence["sourceRevision"],
        "runtime_revision": evidence["runtimeSourceRevision"],
        "image_tag": evidence["imageTag"],
        "image_digest": evidence["imageDigest"],
        "chart_version": evidence["chartVersion"],
        "chart_digest": evidence["chartDigest"],
        "helm_revision": evidence["helmRevision"],
        "provider": evidence["expectedDefaultChatProvider"],
    }

    assert {contract["alert"] for contract in contracts} == NAMES
    assert len(contracts) == 5
    for contract in contracts:
        assert contract["labels"] == {
            "application": "dspace",
            "environment": "prod",
            "cluster": "sugarkube-prod",
            "severity": "critical",
            "expected_revision": evidence["sourceRevision"],
        }
        assert contract["coordinates"] == expected_coordinates
        annotations = contract["annotations"]
        assert all(
            annotations[field]
            for field in (
                "summary",
                "description",
                "current_revision",
                "remediation",
                "runbook_url",
            )
        )
        assert annotations["runbook_url"].startswith(f"{RUNBOOK}#dspace")

    rendered = json.dumps(contracts, sort_keys=True)
    assert "semanticTag" not in rendered
    assert evidence["semanticTag"] not in rendered


def test_alert_contract_cardinality_and_promql_states():
    alerts = {x["alert"]: x for x in rules() if "alert" in x}
    assert set(alerts) == NAMES
    forbidden = ("prompt", "response", "user", "session", "request_id", "error=", "url=")
    for name, rule in alerts.items():
        assert rule["labels"].keys() >= {
            "application",
            "environment",
            "cluster",
            "severity",
            "expected_revision",
        }
        assert rule["annotations"].keys() >= {
            "summary",
            "description",
            "current_revision",
            "remediation",
            "runbook_url",
        }
        assert rule["annotations"]["runbook_url"].startswith(
            "https://github.com/futuroptimist/sugarkube/blob/main/docs/"
        )
        assert not any(x in str(rule).lower() for x in forbidden)
    assert "count(count by (revision)" in alerts["DspaceMixedBuildRevisions"]["expr"]
    image = alerts["DspaceDeploymentImagePinMismatch"]["expr"]
    assert 'image_id=~"^(docker-pullable://)?' in image and "image_spec=" in image
    assert "kube_pod_deletion_timestamp" in image and 'phase="Running"' in image
    synthetic = alerts["DspaceChatSyntheticFailed"]["expr"]
    assert all(state in synthetic for state in ("executed_failure", "stale", "missing"))
    target = alerts["DspaceMetricsTargetDown"]["expr"]
    assert "up{" in target and "== 0" in target and "unless on (namespace, pod)" in target


def result(rev, **overrides):
    value = {
        "schemaVersion": 1,
        "journey": "/chat",
        "passed": True,
        "executedAt": int(time.time()),
        "runnerRevision": rev,
        "transport": "intercepted",
        "mutationEnabled": False,
    }
    value.update(overrides)
    return value


def run(tmp_path, value, revision="a" * 40, environment="staging"):
    inp = tmp_path / "result.json"
    out = tmp_path / "metric.prom"
    inp.write_text(json.dumps(value))
    proc = subprocess.run(
        [
            sys.executable,
            str(PRODUCER),
            "--result",
            str(inp),
            "--output",
            str(out),
            "--runner-revision",
            revision,
            "--environment",
            environment,
        ],
        text=True,
        capture_output=True,
    )
    return proc, out


def test_synthetic_consumer_pass_fail_and_fail_closed(tmp_path):
    rev = "a" * 40
    proc, out = run(tmp_path, result(rev))
    assert proc.returncode == 0
    assert "_success{" in out.read_text() and "} 1\n" in out.read_text()
    assert stat.S_IMODE(out.stat().st_mode) == 0o644
    proc, out = run(tmp_path, result(rev, passed=False))
    assert proc.returncode == 0
    assert "} 0\n" in out.read_text()
    before = out.read_text()
    proc, _ = run(tmp_path, result(rev, transport="live"))
    assert proc.returncode != 0 and out.read_text() == before


def test_synthetic_consumer_rejects_mutation_unpinned_and_production(tmp_path):
    rev = "b" * 40
    for value, revision, env in [
        (result(rev, mutationEnabled=True), rev, "staging"),
        (result(rev), "main", "staging"),
        (result(rev), rev, "prod"),
    ]:
        proc, out = run(tmp_path, value, revision, env)
        assert proc.returncode != 0
        assert not out.exists()


def test_synthetic_consumer_rejects_future_timestamp_without_replacing_output(tmp_path):
    rev = "c" * 40
    proc, out = run(tmp_path, result(rev, executedAt=int(time.time())), revision=rev)
    assert proc.returncode == 0
    before = out.read_text()
    proc, _ = run(tmp_path, result(rev, executedAt=int(time.time()) + 61), revision=rev)
    assert proc.returncode != 0
    assert "allowed clock skew" in proc.stderr
    assert out.read_text() == before


def test_parse_result_uses_injected_clock_and_accepts_old_results(tmp_path):
    spec = importlib.util.spec_from_file_location("dspace_metrics", PRODUCER)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader
    spec.loader.exec_module(module)
    rev = "d" * 40
    source = tmp_path / "result.json"
    source.write_text(json.dumps(result(rev, executedAt=1)))
    assert module.parse_result(source, rev, now=1000) == (1, 1)
    source.write_text(json.dumps(result(rev, executedAt=1060)))
    assert module.parse_result(source, rev, now=1000) == (1, 1060)
    source.write_text(json.dumps(result(rev, executedAt=1061)))
    try:
        module.parse_result(source, rev, now=1000)
    except ValueError as error:
        assert "clock skew" in str(error)
    else:
        raise AssertionError("future result was accepted")


def test_synthetic_consumer_rejects_extra_fields_without_replacing_output(tmp_path):
    rev = "e" * 40
    proc, out = run(tmp_path, result(rev, executedAt=1), revision=rev)
    assert proc.returncode == 0
    before = out.read_text()
    for extra in ({"loginField": False}, {"unexpected": False}):
        proc, _ = run(tmp_path, result(rev, executedAt=1, **extra), revision=rev)
        assert proc.returncode != 0
        assert "exact bounded schema" in proc.stderr
        assert out.read_text() == before
