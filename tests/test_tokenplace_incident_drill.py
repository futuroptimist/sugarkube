import json
from pathlib import Path

from scripts import tokenplace_incident_drill as drill

DIGEST = "registry.invalid/tokenplace@sha256:" + "a" * 64


def argv(tmp_path: Path, incident="metrics-oom"):
    return [
        "--incident",
        incident,
        "--host",
        "staging.invalid",
        "--kubeconfig",
        "/private/config",
        "--context",
        "sugar-staging",
        "--environment",
        "staging",
        "--namespace",
        "tokenplace",
        "--deployment",
        "tokenplace",
        "--container",
        "relay",
        "--image",
        DIGEST,
        "--replacement-image",
        DIGEST.replace("a" * 64, "b" * 64),
        "--rollback-image",
        DIGEST,
        "--replicas",
        "1",
        "--memory-limit",
        "512Mi",
        "--monitor-namespace",
        "monitoring",
        "--service-monitor",
        "tokenplace",
        "--root-probe",
        "blackbox-tokenplace-staging-root",
        "--metadata-probe",
        "blackbox-tokenplace-staging-metadata",
        "--livez-probe",
        "blackbox-tokenplace-staging-livez",
        "--healthz-probe",
        "blackbox-tokenplace-staging-healthz",
        "--evidence-dir",
        str(tmp_path / "private-evidence"),
    ]


def snapshot(tmp_path: Path, *, oom=True):
    names = ["root", "metadata", "livez", "healthz"]
    data = {
        "deployment": {
            "metadata": {"name": "tokenplace", "namespace": "tokenplace"},
            "spec": {
                "replicas": 1,
                "template": {
                    "spec": {
                        "containers": [
                            {
                                "name": "relay",
                                "image": DIGEST,
                                "resources": {"limits": {"memory": "512Mi"}},
                            }
                        ]
                    }
                },
            },
        },
        "monitoring": {
            "items": [{"kind": "ServiceMonitor", "metadata": {"name": "tokenplace"}}]
            + [
                {"kind": "Probe", "metadata": {"name": f"blackbox-tokenplace-staging-{x}"}}
                for x in names
            ]
        },
        "terminations": (
            [{"container": "relay", "reason": "OOMKilled", "exitCode": 137}] if oom else []
        ),
    }
    path = tmp_path / "snapshot.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def parse_plan(tmp_path, capsys, incident="metrics-oom"):
    args = argv(tmp_path, incident) + ["--snapshot", str(snapshot(tmp_path))]
    assert drill.main(args) == 0
    return json.loads(capsys.readouterr().out)


def test_metrics_oom_selects_only_service_monitor_and_requires_authoritative_oom(tmp_path, capsys):
    result = parse_plan(tmp_path, capsys)
    mutations = [x for x in result["actions"] if "do" in x]
    assert mutations[0]["stage"] == "pause-metrics"
    assert "servicemonitor" in mutations[0]["do"]
    assert not any("probe" in x["do"] for x in mutations)
    args = argv(tmp_path) + ["--snapshot", str(snapshot(tmp_path, oom=False))]
    assert drill.main(args) == 2


def test_quota_selects_root_and_metadata_only_and_restores_in_order(tmp_path, capsys):
    result = parse_plan(tmp_path, capsys, "quota-exhaustion")
    stages = result["summary"]["stages"]
    assert stages[:2] == ["pause-root", "pause-metadata"]
    assert stages.index("restore-root") < stages.index("restore-metadata")
    commands = "\n".join(" ".join(x.get("do", [])) for x in result["actions"])
    assert "staging-livez" not in commands and "staging-healthz" not in commands
    assert "servicemonitor" not in commands


def test_mismatch_fails_before_runner_mutation(tmp_path):
    calls = []
    args = argv(tmp_path) + ["--snapshot", str(snapshot(tmp_path))]
    args[args.index("--replicas") + 1] = "2"
    assert drill.main(args, lambda *a, **k: calls.append(a)) == 2
    assert calls == []


def test_plan_encodes_state_loss_compute_e2e_rollback_and_privacy(tmp_path, capsys):
    result = parse_plan(tmp_path, capsys)
    stages = result["summary"]["stages"]
    assert stages[1:4] == ["replace", "readiness-and-identity", "compute-register-and-poll"]
    assert "encrypted-request-response-retrieval-decryption" in stages
    assert all("rollback" in x for x in result["actions"] if "do" in x)
    emitted = json.dumps(result)
    for private in ("staging.invalid", "/private/config", "private-evidence"):
        assert private not in emitted


def test_production_and_non_digest_are_rejected(tmp_path):
    args = argv(tmp_path) + ["--snapshot", str(snapshot(tmp_path))]
    args[args.index("--context") + 1] = "production"
    assert drill.main(args) == 2
    args = argv(tmp_path) + ["--snapshot", str(snapshot(tmp_path))]
    args[args.index("--image") + 1] = "latest"
    assert drill.main(args) == 2
