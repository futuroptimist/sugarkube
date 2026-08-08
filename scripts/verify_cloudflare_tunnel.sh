#!/usr/bin/env bash
# Read-only staging verification for the non-Flux cloudflare-tunnel Helm release.
set -Eeuo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
KUBECONFIG=${KUBECONFIG:-$HOME/.kube/config}
export KUBECONFIG

python3 "$ROOT/scripts/cluster_identity.py" assert --kubeconfig "$KUBECONFIG" --env staging

release_json=$(helm -n cloudflare list --filter '^cloudflare-tunnel$' --output json)
python3 -c 'import json,sys
x=json.load(sys.stdin)
assert len(x)==1, f"expected one cloudflare-tunnel Helm release, found {len(x)}"
assert x[0]["chart"]=="cloudflare-tunnel-0.3.2", x[0]["chart"]' <<<"$release_json"

deployment=$(kubectl -n cloudflare get deployment cloudflare-tunnel -o json)
python3 -c 'import json,sys
d=json.load(sys.stdin); s=d["spec"]; p=s["template"]["spec"]; c=p["containers"][0]
expected="cloudflare/cloudflared:2026.7.3@sha256:e39ee8da81ad5e05d77f38d2f51c60ca51bf2a8450ac3abab50c17fdb91d91bf"
assert s["replicas"]==2
assert c["image"]==expected
assert "livenessProbe" not in c
assert c["readinessProbe"]["httpGet"]=={"path":"/ready","port":2000}
assert s["strategy"]["rollingUpdate"]=={"maxSurge":1,"maxUnavailable":0}
ref=c["env"][0]["valueFrom"]["secretKeyRef"]
assert ref=={"name":"tunnel-token","key":"token"}
assert c["command"]==["cloudflared","tunnel","--no-autoupdate","--metrics","0.0.0.0:2000","run"]' <<<"$deployment"

pods=$(kubectl -n cloudflare get pods -l app.kubernetes.io/name=cloudflare-tunnel,app.kubernetes.io/instance=cloudflare-tunnel -o json)
python3 -c 'import json,sys
x=json.load(sys.stdin)["items"]
assert len(x)==2, f"expected two connectors, found {len(x)}"
nodes={p["spec"].get("nodeName") for p in x}
assert None not in nodes and len(nodes)==2, f"connectors are not on separate nodes: {nodes}"' <<<"$pods"

kubectl -n cloudflare get poddisruptionbudget cloudflare-tunnel -o jsonpath='{.spec.minAvailable}' | grep -qx 1
kubectl -n cloudflare get service cloudflare-tunnel-metrics -o json | python3 -c 'import json,sys
x=json.load(sys.stdin)["spec"]
assert x["type"]=="ClusterIP"
assert x["selector"]=={"app.kubernetes.io/name":"cloudflare-tunnel","app.kubernetes.io/instance":"cloudflare-tunnel"}
assert x["ports"][0]["name"]=="metrics" and x["ports"][0]["targetPort"]==2000'
kubectl -n cloudflare get servicemonitor cloudflare-tunnel -o json | python3 -c 'import json,sys
x=json.load(sys.stdin); assert x["metadata"]["labels"]["release"]=="kube-prometheus-stack"
assert x["spec"]["selector"]["matchLabels"]=={"app.kubernetes.io/name":"cloudflare-tunnel","app.kubernetes.io/instance":"cloudflare-tunnel"}'

prom=/api/v1/namespaces/monitoring/services/http:kube-prometheus-stack-prometheus:9090/proxy
targets=$(kubectl get --raw "$prom/api/v1/query?query=count(up%7Bnamespace%3D%22cloudflare%22%2Cservice%3D%22cloudflare-tunnel-metrics%22%7D%3D%3D1)")
connections=$(kubectl get --raw "$prom/api/v1/query?query=count(cloudflared_tunnel_ha_connections%7Bnamespace%3D%22cloudflare%22%2Cservice%3D%22cloudflare-tunnel-metrics%22%7D%3E%3D4)")
alerts=$(kubectl get --raw "$prom/api/v1/rules")
python3 - "$targets" "$connections" "$alerts" <<'PY'
import json, sys
def scalar(raw):
    result=json.loads(raw)["data"]["result"]
    return float(result[0]["value"][1]) if result else 0
assert scalar(sys.argv[1]) == 2, "Prometheus does not see two healthy targets"
assert scalar(sys.argv[2]) == 2, "not every connector reports at least four HA connections"
rules=json.loads(sys.argv[3])["data"]["groups"]
wanted={"CloudflareTunnelNoHealthyConnections","CloudflareTunnelConnectionsDegraded","CloudflareTunnelMetricsTargetsDown"}
loaded={r["name"] for g in rules for r in g.get("rules",[]) if r.get("health")=="ok"}
assert wanted <= loaded, f"healthy tunnel alerts missing: {wanted-loaded}"
PY

echo "Cloudflare Tunnel staging verification passed."
