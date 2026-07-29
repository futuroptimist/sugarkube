import json
import os
import pathlib
import subprocess

ROOT = pathlib.Path(__file__).parents[1]
SCRIPT = ROOT / "scripts/staging_ingress_ha.sh"
SUMMARY = ROOT / "scripts/endpoint_slice_summary.py"
OWNER = "sugarkube.dev/managed-by"

DEPLOYMENT = {
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
                "containers": [{
                    "name": "coredns", "image": "registry.invalid/coredns:v1",
                    "args": ["-conf", "/etc/coredns/Corefile"],
                    "readinessProbe": {"httpGet": {"path": "/ready", "port": 8181}},
                    "livenessProbe": {"httpGet": {"path": "/health", "port": 8080}},
                    "volumeMounts": [{"name": "config-volume", "mountPath": "/etc/coredns"}],
                }],
                "volumes": [{"name": "config-volume", "configMap": {"name": "coredns"}}],
            },
        },
    },
}


def _pod(node):
    return {"metadata": {}, "spec": {"nodeName": node}, "status": {
        "phase": "Running", "containerStatuses": [{"ready": True}]
    }}


def _stub(tmp_path, *, context="sugar-staging", nodes="node1,node2", workload_nodes=None, tunnels=1,
          owner="staging-ingress-ha", probes=True, probe_mode="canonical", endpoint_nodes="node1,node2",
          endpoint_slices=None,
          resource_absent=False, lookup_error=False, fail_wait="", fail_curl=False,
          fail_reconcile=False):
    calls = tmp_path / "calls"
    kubectl = tmp_path / "kubectl"
    kubectl.write_text(f'''#!/usr/bin/env python3
import json, os, sys
args=sys.argv[1:]
with open({str(calls)!r}, "a") as f: f.write(" ".join(args)+"\\n")
joined=" ".join(args)
if args == ["config", "current-context"]: print(os.environ["FAKE_CONTEXT"])
elif joined == "-n kube-system get deployment coredns -o json": print(os.environ["DEPLOYMENT"])
elif joined.endswith("get deployment/coredns-ha -o json") or joined.endswith("get helmchartconfig/traefik -o json"):
    if os.environ["RESOURCE_ABSENT"] == "1":
        print('Error from server (NotFound): resource not found', file=sys.stderr); sys.exit(1)
    if os.environ["LOOKUP_ERROR"] == "1":
        print('forbidden live-value-secret', file=sys.stderr); sys.exit(1)
    print(json.dumps({{"metadata":{{"labels":{{"sugarkube.dev/managed-by":os.environ.get("OWNER", "")}}}}}}))
elif "get pods" in joined and "-o json" in joined:
    key = "TUNNEL_NODES" if "cloudflare-tunnel" in joined else ("TRAEFIK_NODES" if "traefik" in joined else "COREDNS_NODES")
    print(json.dumps({{"items":[{{"metadata":{{}},"spec":{{"nodeName":n}},"status":{{"phase":"Running","containerStatuses":[{{"ready":True}}]}}}} for n in os.environ[key].split(",") if n]}}))
elif joined == "get deployment -A -l app.kubernetes.io/name=cloudflare-tunnel -o json":
    print(json.dumps({{"items":[{{"metadata":{{"namespace":f"tunnel-{{i}}"}}}} for i in range(int(os.environ["TUNNELS"]))]}}))
elif joined == "get probes -A -l environment=staging,criticality=critical -o json":
    if os.environ["PROBES"] != "1": items=[]
    elif os.environ["PROBE_MODE"] == "legacy": items=[{{"spec":{{"url":"https://legacy.example/health"}}}}]
    else: items=[{{"spec":{{"targets":{{"staticConfig":{{"static":["https://private.example/health", "http://ignored.example", "https://private.example/health"]}}}}}}}}]
    print(json.dumps({{"items":items}}))
elif "get endpointslices.discovery.k8s.io" in joined and "-o json" in joined:
    if os.environ.get("ENDPOINT_SLICES"): print(os.environ["ENDPOINT_SLICES"])
    else:
        nodes=os.environ["ENDPOINT_NODES"].split(",") if "service-name=kube-dns" in joined else ["node1"]
        print(json.dumps({{"items":[{{"endpoints":[{{"addresses":[f"10.0.0.{{i+1}}"],"nodeName":n,"conditions":{{"ready":True,"serving":True,"terminating":False}},"targetRef":{{"kind":"Pod","namespace":"kube-system","name":f"pod-{{i}}"}}}} for i,n in enumerate(nodes) if n]}}]}}))
elif "wait" in args:
    if os.environ.get("FAIL_WAIT") and os.environ["FAIL_WAIT"] in joined: sys.exit(1)
    if "deployment/traefik" in joined and "jsonpath={{.spec.replicas}}" in joined:
        if os.environ["FAIL_RECONCILE"] == "1": sys.exit(1)
        calls=open({str(calls)!r}).read()
        expected = "=2" if "=2" in joined else "=1"
        prerequisite = "apply -f" if expected == "=2" else "delete -f"
        if prerequisite not in calls: sys.exit(1)
    elif "pod/sugarkube" not in joined: sys.exit(1)
elif "rollout status" in joined and os.environ.get("FAIL_WAIT") and os.environ["FAIL_WAIT"] in joined: sys.exit(1)
''')
    kubectl.chmod(0o755)
    curl = tmp_path / "curl"
    curl.write_text('#!/bin/sh\necho "$*" >>"$CALLS"\necho "sensitive-url-output" >&2\nexit "${FAIL_CURL:-0}"\n')
    curl.chmod(0o755)
    return {
        **os.environ, "PATH": f"{tmp_path}:{os.environ['PATH']}", "CALLS": str(calls),
        "FAKE_CONTEXT": context, "DEPLOYMENT": json.dumps(DEPLOYMENT),
        "COREDNS_NODES": (workload_nodes or {}).get("CoreDNS", nodes),
        "TRAEFIK_NODES": (workload_nodes or {}).get("Traefik", nodes),
        "TUNNEL_NODES": (workload_nodes or {}).get("Cloudflare tunnel", nodes),
        "TUNNELS": str(tunnels), "OWNER": owner, "PROBES": "1" if probes else "0",
        "PROBE_MODE": probe_mode, "ENDPOINT_NODES": endpoint_nodes,
        "ENDPOINT_SLICES": "" if endpoint_slices is None else endpoint_slices,
        "RESOURCE_ABSENT": "1" if resource_absent else "0", "LOOKUP_ERROR": "1" if lookup_error else "0",
        "FAIL_WAIT": fail_wait, "FAIL_CURL": "1" if fail_curl else "0",
        "FAIL_RECONCILE": "1" if fail_reconcile else "0",
    }, calls


def _run(env, action, stage="staging"):
    return subprocess.run([SCRIPT, action, stage], env=env, text=True, capture_output=True)


def _summarize(document, service="kube-dns", minimum=1, nodes=0):
    return subprocess.run(
        [SUMMARY, "--service", service, "--min-healthy", str(minimum), "--min-nodes", str(nodes)],
        input=document if isinstance(document, str) else json.dumps(document), text=True,
        capture_output=True,
    )


def _slice(*endpoints):
    return {"endpoints": list(endpoints)}


def _endpoint(addresses, node=None, conditions=None, target="pod"):
    value = {"addresses": addresses}
    if node is not None:
        value["nodeName"] = node
    if conditions is not None:
        value["conditions"] = conditions
    if target is not None:
        value["targetRef"] = {"kind": "Pod", "namespace": "kube-system", "name": target}
    return value


def test_rendered_contracts_and_coredns_clone(tmp_path):
    env, _ = _stub(tmp_path)
    result = _run(env, "render")
    assert result.returncode == 0, result.stderr
    traefik_text, coredns_text = result.stdout.split("\n---\n")
    # Parse the small manifest into its semantically relevant key/value records
    # rather than merely searching the complete source for disconnected strings.
    records = {}
    path = []
    for raw in traefik_text.splitlines():
        if not raw.strip() or raw.lstrip().startswith("-") or raw.strip().endswith("|-"):
            continue
        indent = len(raw) - len(raw.lstrip())
        key, _, value = raw.strip().partition(":")
        while path and path[-1][0] >= indent:
            path.pop()
        if value.strip():
            records[tuple(x[1] for x in path) + (key,)] = value.strip()
        else:
            path.append((indent, key))
    assert records[("metadata", "name")] == "traefik"
    assert records[("metadata", "labels", OWNER)] == "staging-ingress-ha"
    assert records[("spec", "deployment", "replicas")] == "2"
    assert records[("spec", "affinity", "podAntiAffinity", "requiredDuringSchedulingIgnoredDuringExecution", "topologyKey")] == "kubernetes.io/hostname"
    coredns = json.loads(coredns_text)
    assert coredns["spec"]["replicas"] == 2
    assert coredns["metadata"]["labels"][OWNER] == "staging-ingress-ha"
    assert coredns["spec"]["template"]["spec"] == DEPLOYMENT["spec"]["template"]["spec"] | {"affinity": coredns["spec"]["template"]["spec"]["affinity"]}
    term = coredns["spec"]["template"]["spec"]["affinity"]["podAntiAffinity"]["requiredDuringSchedulingIgnoredDuringExecution"][0]
    assert term["topologyKey"] == "kubernetes.io/hostname"
    assert term["labelSelector"]["matchLabels"] == {"k8s-app": "kube-dns"}


def test_every_mutation_guard_precedes_cluster_operations(tmp_path):
    for action in ("apply", "upgrade", "verify", "rollback"):
        case = tmp_path / action; case.mkdir()
        env, calls = _stub(case, context="production")
        assert "staging-only" in _run(env, action, "prod").stderr
        assert not calls.exists()
        result = _run(env, action)
        assert result.returncode and "exactly sugar-staging" in result.stderr
        text = calls.read_text()
        assert all(word not in text for word in ("apply", " run ", "delete"))


def test_status_is_read_only_and_optional_companion_may_be_absent(tmp_path):
    env, calls = _stub(tmp_path)
    assert _run(env, "status").returncode == 0
    text = calls.read_text()
    assert "get deploy coredns traefik -o wide" in text
    assert "get deploy coredns-ha -o wide --ignore-not-found=true" in text
    assert all(word not in text for word in ("apply", "patch", "delete", " run "))


def test_apply_idempotent_ordered_and_owned_rollback(tmp_path):
    env, calls = _stub(tmp_path)
    for _ in range(2): assert _run(env, "apply").returncode == 0
    text = calls.read_text()
    assert text.count("apply -f") == 4
    assert text.index("deployment/coredns-ha") < text.index("traefik-helmchartconfig.yaml")
    assert _run(env, "rollback").returncode == 0
    text = calls.read_text()
    assert "delete deployment coredns-ha" in text
    assert "delete deployment coredns " not in text

    absent = tmp_path / "absent"; absent.mkdir()
    env, _ = _stub(absent, resource_absent=True)
    assert _run(env, "apply").returncode == 0


def test_traefik_reconciliation_precedes_rollout_and_fails_closed(tmp_path):
    env, calls = _stub(tmp_path)
    assert _run(env, "apply").returncode == 0
    text = calls.read_text()
    apply_pos = text.rindex("apply -f", 0, text.index("traefik-helmchartconfig.yaml") + 1)
    apply_wait = text.index("jsonpath={.spec.replicas}=2")
    apply_rollout = text.index("rollout status deployment/traefik")
    assert apply_pos < apply_wait < apply_rollout

    calls.write_text("")
    assert _run(env, "rollback").returncode == 0
    text = calls.read_text()
    delete_pos = text.index("delete -f")
    rollback_wait = text.index("jsonpath={.spec.replicas}=1")
    rollback_rollout = text.index("rollout status deployment/traefik")
    assert delete_pos < rollback_wait < rollback_rollout

    for action in ("apply", "rollback"):
        case = tmp_path / f"never-{action}"; case.mkdir()
        failed_env, failed_calls = _stub(case, fail_reconcile=True)
        result = _run(failed_env, action)
        assert result.returncode and "reconcile" in result.stderr
        assert "resource details redacted" in result.stderr
        text = failed_calls.read_text()
        assert "rollout status deployment/traefik" not in text


def test_unowned_resources_are_never_modified_or_disclosed(tmp_path):
    for action in ("apply", "rollback"):
        case = tmp_path / action; case.mkdir()
        env, calls = _stub(case, owner="someone-else")
        result = _run(env, action)
        assert result.returncode and "not owned" in result.stderr
        assert "someone-else" not in result.stdout + result.stderr
        assert all(word not in calls.read_text() for word in ("apply -f", "delete"))
    failed = tmp_path / "lookup"; failed.mkdir()
    env, calls = _stub(failed, lookup_error=True)
    result = _run(env, "apply")
    assert result.returncode and "unable to inspect ownership" in result.stderr
    assert "live-value-secret" not in result.stdout + result.stderr
    assert "apply -f" not in calls.read_text()


def test_each_pod_workload_rejects_singleton_and_same_node(tmp_path):
    for nodes in ("node1", "node1,node1"):
        for expected in ("Traefik", "Cloudflare tunnel"):
            case = tmp_path / f"{nodes.replace(',', '-')}-{expected.split()[0]}"; case.mkdir()
            env, calls = _stub(case, workload_nodes={expected: nodes})
            result = _run(env, "verify")
            assert result.returncode
            assert f"hostname-spread {expected} pods" in result.stderr
            assert "delete pod sugarkube-ingress-ha-verify-" in calls.read_text()


def test_coredns_requires_two_ready_endpoints_on_distinct_nodes(tmp_path):
    for i, nodes in enumerate(("node1", "node1,node1")):
        case = tmp_path / str(i); case.mkdir()
        env, calls = _stub(case, endpoint_nodes=nodes)
        result = _run(env, "verify")
        assert result.returncode and "hostname-spread CoreDNS endpoints" in result.stderr
        assert "delete pod sugarkube-ingress-ha-verify-" in calls.read_text()
    healthy = tmp_path / "healthy"; healthy.mkdir()
    env, _ = _stub(healthy, endpoint_nodes="node1,node2")
    assert _run(env, "verify").returncode == 0


def test_endpoint_slices_aggregate_deduplicate_and_sort_deterministically():
    duplicate = _endpoint(["2001:db8::2", "10.0.0.2"], "node2", {}, "dns-b")
    document = {"items": [
        _slice(duplicate, _endpoint(["10.0.0.1"], "node1", {}, "dns-a")),
        _slice(duplicate),
    ]}
    first = _summarize(document, minimum=2, nodes=2)
    second = _summarize({"items": list(reversed(document["items"]))}, minimum=2, nodes=2)
    assert first.returncode == 0, first.stderr
    assert first.stdout == second.stdout
    assert "healthy endpoints=2 nodes=['node1', 'node2']" in first.stdout
    assert "addresses=10.0.0.2,2001:db8::2" in first.stdout
    assert first.stdout.index("node=node1") < first.stdout.index("node=node2")


def test_endpoint_slice_health_contract_and_diagnostics():
    document = {"items": [_slice(
        _endpoint(["10.0.0.1"], "node1", {"ready": True, "serving": True,
                                                    "terminating": False}, "healthy"),
        _endpoint(["10.0.0.2"], "node2", {"ready": False, "serving": True}, "not-ready"),
        _endpoint(["10.0.0.3"], "node3", {"ready": True, "serving": True,
                                                    "terminating": True}, "terminating"),
        _endpoint(["10.0.0.4"], "node4", {"ready": True, "serving": False}, "not-serving"),
        _endpoint(["2001:db8::5"], conditions={}, target=None),
    )]}
    result = _summarize(document, minimum=2, nodes=1)
    assert result.returncode == 0, result.stderr
    assert "healthy endpoints=2 nodes=['node1']" in result.stdout
    assert result.stdout.count("  unhealthy ") == 3
    assert "node=- addresses=2001:db8::5 ready=true serving=true terminating=false targetRef=-" in result.stdout


def test_endpoint_slice_empty_and_malformed_data_fail_safely():
    invalid = [
        "not json", {"items": []}, {"items": [_slice({"addresses": []})]},
        {"items": [{"endpoints": "wrong"}]},
        {"items": [_slice(_endpoint(["10.0.0.1"], conditions={"ready": "yes"}))]},
        {"items": [_slice({"addresses": ["10.0.0.1"], "targetRef": "pod"})]},
    ]
    for document in invalid:
        result = _summarize(document)
        assert result.returncode == 2
        assert "ERROR: invalid EndpointSlice data" in result.stderr


def test_verify_rejects_unhealthy_duplicate_endpoint_nodes_and_no_slices(tmp_path):
    cases = [
        {"items": [_slice(
            _endpoint(["10.0.0.1"], "node1", {"ready": True, "serving": True}),
            _endpoint(["10.0.0.2"], "node1", {"ready": True, "serving": True}),
        )]},
        {"items": [_slice(
            _endpoint(["10.0.0.1"], "node1", {"ready": True, "serving": True}),
            _endpoint(["10.0.0.2"], "node2", {"ready": True, "serving": True,
                                                    "terminating": True}),
        )]},
        {"items": []},
    ]
    for index, slices in enumerate(cases):
        case = tmp_path / str(index); case.mkdir()
        env, calls = _stub(case, endpoint_slices=json.dumps(slices))
        result = _run(env, "verify")
        assert result.returncode and "hostname-spread CoreDNS endpoints" in result.stderr
        assert "delete pod sugarkube-ingress-ha-verify-" in calls.read_text()


def test_healthy_verify_and_unique_tunnel_discovery(tmp_path):
    env, calls = _stub(tmp_path)
    result = _run(env, "verify")
    assert result.returncode == 0, result.stderr
    text = calls.read_text()
    assert "get deployment -A -l app.kubernetes.io/name=cloudflare-tunnel -o json" in text
    assert "-n tunnel-0 get pods -l app.kubernetes.io/name=cloudflare-tunnel" in text
    assert "delete pod sugarkube-ingress-ha-verify-" in text


def test_zero_or_multiple_tunnel_deployments_fail_and_cleanup(tmp_path):
    for count in (0, 2):
        case = tmp_path / str(count); case.mkdir()
        env, calls = _stub(case, tunnels=count)
        result = _run(env, "verify")
        assert result.returncode and f"found {count}" in result.stderr
        assert "delete pod sugarkube-ingress-ha-verify-" in calls.read_text()


def test_probe_discovery_required_and_curl_failure_redacted(tmp_path):
    none = tmp_path / "none"; none.mkdir(); env, calls = _stub(none, probes=False)
    result = _run(env, "verify")
    assert result.returncode and "no critical staging HTTPS Probe targets" in result.stderr
    assert "delete pod sugarkube-ingress-ha-verify-" in calls.read_text()
    failed = tmp_path / "failed"; failed.mkdir(); env, calls = _stub(failed, fail_curl=True)
    result = _run(env, "verify")
    assert result.returncode and "target redacted" in result.stderr
    assert "private.example" not in result.stdout + result.stderr
    assert "sensitive-url-output" not in result.stdout + result.stderr
    legacy = tmp_path / "legacy"; legacy.mkdir(); env, calls = _stub(legacy, probe_mode="legacy")
    result = _run(env, "verify")
    assert result.returncode and "no critical staging HTTPS Probe targets" in result.stderr
    assert "legacy.example" not in calls.read_text()
    assert "delete pod sugarkube-ingress-ha-verify-" in calls.read_text()


def test_rollout_and_dns_probe_timeouts_cleanup(tmp_path):
    rollout = tmp_path / "rollout"; rollout.mkdir(); env, _ = _stub(rollout, fail_wait="deployment/coredns-ha")
    assert "rollout timed out" in _run(env, "apply").stderr
    dns = tmp_path / "dns"; dns.mkdir(); env, calls = _stub(dns, fail_wait="pod/sugarkube")
    result = _run(env, "verify")
    assert result.returncode and "DNS probe failed" in result.stderr
    assert "delete pod sugarkube-ingress-ha-verify-" in calls.read_text()
