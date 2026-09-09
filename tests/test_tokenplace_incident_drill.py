import json
import subprocess

import pytest

from scripts import tokenplace_incident_drill as drill

DIGEST_A = "registry.example/tokenplace@sha256:" + "a" * 64
DIGEST_B = "registry.example/tokenplace@sha256:" + "b" * 64


def arguments(tmp_path, incident="metrics-oom"):
    values = {
        "incident": incident,
        "host": "staging.example",
        "kubeconfig": "/safe/kubeconfig",
        "context": "sugarkube-staging",
        "environment": "staging",
        "namespace": "tokenplace",
        "deployment": "tokenplace",
        "container": "relay",
        "image": DIGEST_A,
        "rollback_image": DIGEST_B,
        "replicas": 1,
        "memory_limit": "512Mi",
        "service_monitor": "tokenplace",
        "root_probe": "blackbox-tokenplace-staging-root",
        "metadata_probe": "blackbox-tokenplace-staging-metadata",
        "livez_probe": "blackbox-tokenplace-staging-livez",
        "healthz_probe": "blackbox-tokenplace-staging-healthz",
    }
    snapshot = {
        "matches": {
            "host": values["host"],
            "context": values["context"],
            "environment": values["environment"],
            "namespace": values["namespace"],
            "deployment": values["deployment"],
            "container": values["container"],
            "image": values["rollback_image"],
            "replicas": values["replicas"],
            "memory_limit": values["memory_limit"],
            "service_monitor": values["service_monitor"],
            "probes": [
                values[x] for x in ("root_probe", "metadata_probe", "livez_probe", "healthz_probe")
            ],
        },
        "target_counts": {
            name: 1
            for name in (
                "deployment",
                "container",
                "service_monitor",
                "root_probe",
                "metadata_probe",
                "livez_probe",
                "healthz_probe",
            )
        },
        "health_probe_labels": {values["livez_probe"]: True, values["healthz_probe"]: True},
        "oom": {"reason": "OOMKilled", "exit_code": 137},
        "quota_contract_valid": True,
        "degraded_metrics_supported": False,
    }
    path = tmp_path / "snapshot.json"
    path.write_text(json.dumps(snapshot), encoding="utf-8")
    values["snapshot"] = path
    values.update(
        execute=False,
        authorize_state_loss=False,
        confirm_compute_registration=False,
        confirm_compute_polling=False,
        confirm_encrypted_e2e=False,
        confirm_observation_gates=False,
        evidence_summary=None,
    )
    return drill.argparse.Namespace(**values), snapshot


def test_mismatch_and_non_authoritative_oom_fail_before_mutation(tmp_path):
    args, snapshot = arguments(tmp_path)
    c = drill.coordinates(args)
    snapshot["matches"]["replicas"] = 2
    with pytest.raises(drill.GuardError, match="mismatched"):
        drill.validate(args, c, snapshot)
    snapshot["matches"]["replicas"] = 1
    snapshot["oom"] = {"reason": "Error", "exit_code": 137}
    with pytest.raises(drill.GuardError, match="OOMKilled/137"):
        drill.validate(args, c, snapshot)


@pytest.mark.parametrize(
    "bad_context,bad_host", [("production", "staging.example"), ("staging", "token.place")]
)
def test_production_is_rejected(tmp_path, bad_context, bad_host):
    args, snapshot = arguments(tmp_path)
    args.context, args.host = bad_context, bad_host
    snapshot["matches"]["context"], snapshot["matches"]["host"] = bad_context, bad_host
    with pytest.raises(drill.GuardError, match="non-production"):
        drill.validate(args, drill.coordinates(args), snapshot)


def test_metrics_plan_only_pauses_exact_service_monitor_and_restores_it_last(tmp_path):
    args, snapshot = arguments(tmp_path)
    plan = drill.build_plan(args, drill.coordinates(args), snapshot)
    mutations = [" ".join(x["command"]) for x in plan if "command" in x]
    assert "servicemonitor tokenplace release-" in mutations[0]
    assert all("probe" not in command for command in mutations)
    assert plan[-2]["stage"] == "restore-metrics-last"
    assert [x["stage"] for x in plan][2:6] == [
        "workload-ready-and-image",
        "compute-registration",
        "compute-polling",
        "encrypted-e2e",
    ]


def test_feature_detected_degraded_mode_keeps_exact_pause_fallback(tmp_path):
    args, snapshot = arguments(tmp_path)
    snapshot["degraded_metrics_supported"] = True
    plan = drill.build_plan(args, drill.coordinates(args), snapshot)
    assert [x["stage"] for x in plan[:2]] == ["pause-metrics", "enable-degraded-metrics"]
    assert "TOKENPLACE_METRICS_MODE=degraded" in plan[1]["command"]


def test_quota_order_and_rollbacks_never_select_health_probes(tmp_path):
    args, snapshot = arguments(tmp_path, "quota-exhaustion")
    drill.validate(args, drill.coordinates(args), snapshot)
    plan = drill.build_plan(args, drill.coordinates(args), snapshot)
    stages = [x["stage"] for x in plan]
    assert (
        stages.index("restore-root")
        < stages.index("restore-metadata")
        < stages.index("metrics-confirmed-active-last")
    )
    rendered = json.dumps(plan)
    assert args.root_probe in rendered and args.metadata_probe in rendered
    assert args.livez_probe not in rendered and args.healthz_probe not in rendered
    assert "servicemonitor" not in rendered
    root = next(x for x in plan if x["stage"] == "restore-root")
    metadata = next(x for x in plan if x["stage"] == "restore-metadata")
    assert "release-" in root["rollback"] and "release-" in metadata["rollback"]


def test_execute_prints_rollback_before_each_mutation(tmp_path, capsys):
    args, snapshot = arguments(tmp_path)
    plan = drill.build_plan(args, drill.coordinates(args), snapshot)
    calls = []

    def runner(command, check):
        calls.append(command)
        return subprocess.CompletedProcess(command, 0)

    drill.execute(plan, runner)
    output = capsys.readouterr().out.splitlines()
    assert len(output) == len(calls)
    assert all(line.startswith("ROLLBACK kubectl ") for line in output)


def test_dry_run_summary_is_private_and_claims_no_live_drill(tmp_path, capsys):
    args, _ = arguments(tmp_path, "quota-exhaustion")
    argv = []
    for key, value in vars(args).items():
        if key in {
            "execute",
            "authorize_state_loss",
            "confirm_compute_registration",
            "confirm_compute_polling",
            "confirm_encrypted_e2e",
            "confirm_observation_gates",
            "evidence_summary",
        }:
            continue
        argv.extend(("--" + key.replace("_", "-"), str(value)))
    assert drill.main(argv) == 0
    output = capsys.readouterr().out
    assert args.host not in output
    assert args.kubeconfig not in output
    assert 'live_drill_passed": false' in output


def test_execute_requires_all_state_loss_and_recovery_confirmations(tmp_path, capsys):
    args, _ = arguments(tmp_path)
    args.execute = True
    summary = drill.safe_summary(args, [])
    assert summary["state"] == {
        "cluster_changed": True,
        "production_changed": False,
        "repository_changed": False,
        "external_changed": False,
    }
    # CLI validation happens before execute(), so missing gates cannot invoke a runner.
    argv = ["--incident", args.incident]
    for key in ("host", *drill.Coordinates.__dataclass_fields__):
        argv.extend(("--" + key.replace("_", "-"), str(getattr(args, key))))
    argv.extend(("--snapshot", str(args.snapshot), "--execute"))
    assert drill.main(argv) == 2
    assert "all recovery gates" in capsys.readouterr().err
