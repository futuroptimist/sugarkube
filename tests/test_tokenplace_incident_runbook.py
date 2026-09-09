import json
from pathlib import Path

from scripts import tokenplace_incident_runbook as runbook


def coords(tmp_path, **changes):
    kubeconfig = tmp_path / "config"
    kubeconfig.write_text("test-only", encoding="utf-8")
    values = dict(
        host="staging.token.place",
        kubeconfig=kubeconfig,
        context="sugar-staging",
        environment="staging",
        namespace="tokenplace",
        deployment="tokenplace",
        container="relay",
        image="ghcr.io/example/relay@sha256:" + "a" * 64,
        replicas=1,
        memory_limit="512Mi",
        service_monitor="tokenplace-staging",
        root_probe="blackbox-tokenplace-staging-root",
        metadata_probe="blackbox-tokenplace-staging-metadata",
        livez_probe="blackbox-tokenplace-staging-livez",
        healthz_probe="blackbox-tokenplace-staging-healthz",
        drill_id="drill-20260908-a",
    )
    values.update(changes)
    return runbook.Coordinates(**values)


def test_metrics_pauses_only_service_monitor_and_preserves_all_probes(tmp_path):
    result = runbook.plan("metrics-oom", coords(tmp_path))
    assert result["pause"] == ["servicemonitor/tokenplace-staging"]
    assert result["preserved"] == [
        "probe/blackbox-tokenplace-staging-livez",
        "probe/blackbox-tokenplace-staging-healthz",
    ]
    assert not any("root" in value or "metadata" in value for value in result["pause"])


def test_quota_pauses_root_and_metadata_only_and_restores_in_order(tmp_path):
    result = runbook.plan("quota-exhaustion", coords(tmp_path))
    assert result["pause"] == [
        "probe/blackbox-tokenplace-staging-root",
        "probe/blackbox-tokenplace-staging-metadata",
    ]
    gates = result["mandatoryGates"]
    assert (
        gates.index("restore-root")
        < gates.index("restore-metadata")
        < gates.index("restore-metrics")
    )
    assert "compute-register" in gates and "compute-poll" in gates and "encrypted-e2e" in gates


def test_oom_requires_authoritative_reason_and_exit_code_not_readiness():
    assert runbook.authoritative_oom("OOMKilled", 137)
    assert not runbook.authoritative_oom("OOMKilled", 1)
    assert not runbook.authoritative_oom(None, 137)


def test_mismatches_fail_closed_before_runner_is_called(tmp_path, capsys):
    calls = []
    args = arguments(coords(tmp_path, context="sugar-prod"), "metrics-oom")
    assert runbook.main(args, runner=lambda *a, **k: calls.append(a)) == 2
    assert calls == []
    assert "sugar-prod" not in capsys.readouterr().err


def test_missing_and_ambiguous_targets_fail_closed(tmp_path):
    for change in (
        {"service_monitor": ""},
        {"root_probe": "blackbox-tokenplace-staging-livez"},
        {"image": "mutable:latest"},
    ):
        try:
            runbook.plan("metrics-oom", coords(tmp_path, **change))
        except runbook.GuardError:
            pass
        else:
            raise AssertionError("unsafe coordinates accepted")


def test_evidence_is_privacy_safe_and_models_emptydir_state_loss(tmp_path):
    result = runbook.plan("metrics-oom", coords(tmp_path))
    encoded = json.dumps(result)
    for private in ("staging.token.place", str(tmp_path), "ghcr.io", "identity", "ciphertext"):
        assert private not in encoded
    assert "pod emptyDir multiprocess metric files" in result["replacementStateLoss"]


def arguments(c, mode):
    result = ["--mode", mode]
    for key, value in vars(c).items():
        result.extend(["--" + key.replace("_", "-"), str(value)])
    return result
