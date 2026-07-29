import json
import os
import pathlib
import subprocess

ROOT = pathlib.Path(__file__).parents[1]
SCRIPT = ROOT / "scripts/staging_ingress_ha.sh"


def test_sources_encode_two_replicas_and_required_hostname_spread():
    manifest = (ROOT / "clusters/staging/ingress-ha/traefik-helmchartconfig.yaml").read_text()
    script = SCRIPT.read_text()
    assert "replicas: 2" in manifest
    assert "requiredDuringSchedulingIgnoredDuringExecution" in manifest
    assert "topologyKey: kubernetes.io/hostname" in manifest
    assert 'd["spec"]["replicas"]=2' in script
    assert '"k8s-app":"kube-dns"' in script
    assert '"topologyKey":"kubernetes.io/hostname"' in script


def _stub(tmp_path, pods=None, context="sugar-staging"):
    calls = tmp_path / "calls"
    kubectl = tmp_path / "kubectl"
    pods = pods or []
    deployment = {
        "apiVersion": "apps/v1",
        "kind": "Deployment",
        "metadata": {"name": "coredns"},
        "spec": {
            "replicas": 1,
            "selector": {"matchLabels": {"k8s-app": "kube-dns"}},
            "template": {
                "metadata": {"labels": {"k8s-app": "kube-dns"}},
                "spec": {
                    "serviceAccountName": "coredns",
                    "containers": [{"name": "coredns", "image": "example.invalid/coredns"}],
                },
            },
        },
    }
    kubectl.write_text(f"""#!/bin/sh
echo "$*" >>"{calls}"
case "$*" in
"config current-context") echo "{context}";;
"-n kube-system get deployment coredns -o json") cat <<'JSON'
{json.dumps(deployment)}
JSON
;;
"get pods -A -o json") cat <<'JSON'
{json.dumps({'items': pods})}
JSON
;;
*"get endpoints "*" -o json") echo '{{"subsets":[{{"addresses":[{{"ip":"10.0.0.1"}}]}}]}}';;
*) :;;
esac
""")
    kubectl.chmod(0o755)
    curl = tmp_path / "curl"
    curl.write_text("#!/bin/sh\nexit 0\n")
    curl.chmod(0o755)
    return {
        **os.environ,
        "PATH": f"{tmp_path}:{os.environ['PATH']}",
        "SUGARKUBE_STAGING_HEALTH_URLS": "https://example.invalid/healthz",
    }, calls


def _pod(label, node):
    return {
        "metadata": {"labels": label},
        "spec": {"nodeName": node},
        "status": {"phase": "Running", "containerStatuses": [{"ready": True}]},
    }


def test_mutation_guards_wrong_environment_and_context(tmp_path):
    env, calls = _stub(tmp_path, context="not-staging")
    result = subprocess.run([SCRIPT, "apply", "prod"], env=env, text=True, capture_output=True)
    assert result.returncode and "staging-only" in result.stderr
    assert not calls.exists()
    result = subprocess.run([SCRIPT, "apply", "staging"], env=env, text=True, capture_output=True)
    assert result.returncode and "exactly sugar-staging" in result.stderr
    assert "apply -f" not in calls.read_text()


def test_apply_is_idempotent_ordered_and_rollback_owned_only(tmp_path):
    env, calls = _stub(tmp_path)
    for _ in range(2):
        assert subprocess.run([SCRIPT, "apply", "staging"], env=env).returncode == 0
    text = calls.read_text()
    assert text.count("apply -f") == 4
    assert text.index("deployment/coredns-ha") < text.index("traefik-helmchartconfig.yaml")
    assert subprocess.run([SCRIPT, "rollback", "staging"], env=env).returncode == 0
    text = calls.read_text()
    assert "delete deployment coredns-ha --ignore-not-found=true" in text
    assert "delete deployment coredns --ignore-not-found" not in text


def test_verify_rejects_singleton_and_same_node_and_cleans_up(tmp_path):
    labels = [
        {"k8s-app": "kube-dns"},
        {"app.kubernetes.io/name": "traefik"},
        {"app.kubernetes.io/name": "cloudflare-tunnel"},
    ]
    pods = [_pod(label, "sugarkube4") for label in labels for _ in range(2)]
    env, calls = _stub(tmp_path, pods)
    result = subprocess.run([SCRIPT, "verify", "staging"], env=env, text=True, capture_output=True)
    assert result.returncode and "fewer than two" in result.stderr
    assert "delete pod sugarkube-ingress-ha-verify-" in calls.read_text()


def test_status_is_read_only_and_errors_do_not_expose_credentials(tmp_path):
    env, calls = _stub(tmp_path)
    assert subprocess.run([SCRIPT, "status", "staging"], env=env).returncode == 0
    text = calls.read_text()
    assert all(word not in text for word in ("apply", "patch", "delete", "secret"))
    source = SCRIPT.read_text().lower()
    assert "get secret" not in source and "logs" not in source
