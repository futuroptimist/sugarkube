import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/observability_blackbox.sh"


def run(args, tmp_path):
    bindir = tmp_path / "bin"
    bindir.mkdir(parents=True)
    for tool in ("helm", "kubectl"):
        (bindir / tool).write_text(
            '#!/bin/sh\necho CALLED >>"$LOG"\n'
            "[ \"$1 $2\" = 'config current-context' ] && echo sugar-staging\n"
        )
        (bindir / tool).chmod(0o755)
    env = {**os.environ, "PATH": f"{bindir}:{os.environ['PATH']}", "LOG": str(tmp_path / "log")}
    return subprocess.run([str(SCRIPT), *args], cwd=ROOT, env=env, text=True, capture_output=True)


def test_missing_and_production_envs_fail_before_cluster_access(tmp_path):
    cases = [
        ([], "empty"),
        (["render"], "missing"),
        (["render", "prod"], "prod"),
        (["render", "production"], "production"),
        (["render", "dev"], "dev"),
    ]
    for args, dirname in cases:
        run_dir = tmp_path / dirname
        result = run(args, run_dir)
        assert result.returncode == 2
        assert not (run_dir / "log").exists()


def test_helper_has_guarded_complete_lifecycle():
    text = SCRIPT.read_text()
    assert "https://prometheus-community.github.io/helm-charts" in text
    assert '--version "$(version)" -f "${VALUES}" --wait --timeout "${TIMEOUT}"' in text
    assert "--reuse-values" not in text
    assert text.index('helm "${action}"') < text.index('kubectl apply -f "${PROBE_RENDER}"')
    assert 'delete probe "${LEGACY_PROBES[@]}" --ignore-not-found' in text
    assert " -l " not in text[text.index("delete probe") : text.index("kubectl apply")]
    assert "2>/dev/null" not in text[text.index("prom_get()") : text.index("verify_series()")]
    assert "cluster_identity.py" in text and "sugar-staging" in text
    status = text[text.index("status()") : text.index("validate_resources()")]
    assert " apply " not in status and "helm install" not in status and "helm upgrade" not in status


def expected_names():
    text = (ROOT / "clusters/staging/observability/probes/public-apps.yaml").read_text()
    return [
        line.strip().split(": ", 1)[1]
        for line in text.splitlines()
        if line.startswith("  name: blackbox-")
    ]


def verifier_bundle(health="up", success="1"):
    names = expected_names()
    pairs = [(name, name.removeprefix("blackbox-").split("-staging-")) for name in names]
    targets = [
        {
            "labels": {
                "job": f"probe/monitoring/{name}",
                "app": pair[0],
                "route": pair[1],
                "environment": "staging",
            },
            "health": health,
        }
        for name, pair in pairs
    ]
    families = [
        "probe_success",
        "probe_duration_seconds",
        "probe_http_status_code",
        "probe_dns_lookup_time_seconds",
        "probe_ssl_earliest_cert_expiry",
    ]
    metrics = {}
    for family in families:
        metrics[family] = {
            "status": "success",
            "data": {
                "resultType": "vector",
                "result": [
                    {
                        "metric": {
                            "job": f"probe/monitoring/{name}",
                            "app": pair[0],
                            "route": pair[1],
                        },
                        "value": [1, success if family == "probe_success" else "2"],
                    }
                    for name, pair in pairs
                ],
            },
        }
    return {
        "targets": {"status": "success", "data": {"activeTargets": targets}},
        "metrics": metrics,
    }


def verify(payload, final=False, *args):
    import json

    env = {**os.environ, "FINAL_ATTEMPT": "1" if final else "0"}
    return subprocess.run(
        [str(ROOT / "scripts/verify_blackbox_prometheus.py"), *args],
        input=json.dumps(payload) if not isinstance(payload, str) else payload,
        text=True,
        capture_output=True,
        env=env,
    )


def test_prometheus_verifier_accepts_exact_lifecycle_jobs_and_ignores_unrelated():
    payload = verifier_bundle()
    payload["targets"]["data"]["activeTargets"].append(
        {"labels": {"job": "probe/monitoring/unrelated"}, "health": "down"}
    )
    assert verify(payload).returncode == 0


def test_prometheus_verifier_converges_then_reports_bounded_diagnostics():
    for change in ("missing", "down", "probe_failure", "family"):
        payload = verifier_bundle()
        if change == "missing":
            payload["targets"]["data"]["activeTargets"].pop()
        elif change == "down":
            payload["targets"]["data"]["activeTargets"][0]["health"] = "down"
        elif change == "probe_failure":
            payload["metrics"]["probe_success"]["data"]["result"][0]["value"][1] = "0"
        else:
            payload["metrics"].pop("probe_duration_seconds")
        result = verify(payload, change != "family")
        assert result.returncode in {9, 10}
        assert "https://" not in result.stderr
        assert len(result.stderr.splitlines()) <= 18


def test_prometheus_verifier_fails_immediately_on_bad_responses():
    bad = [
        "not-json",
        [],
        {"targets": {}, "metrics": {}},
        {
            **verifier_bundle(),
            "targets": {"status": "error", "data": {}},
        },
    ]
    for payload in bad:
        assert verify(payload).returncode == 9


def test_probe_validator_requires_exact_names_and_mappings():
    import json

    docs = subprocess.run(
        [
            "ruby",
            "-ryaml",
            "-rjson",
            "-e",
            "puts JSON.generate(YAML.load_stream(File.read(ARGV[0])))",
            str(ROOT / "clusters/staging/observability/probes/public-apps.yaml"),
        ],
        check=True,
        text=True,
        capture_output=True,
    )
    items = {"items": json.loads(docs.stdout)}
    assert verify(items, False, "--probes").returncode == 0
    items["items"][0]["metadata"]["labels"]["route"] = "wrong"
    assert verify(items, False, "--probes").returncode == 7
