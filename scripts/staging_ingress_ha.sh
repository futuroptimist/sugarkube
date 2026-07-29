#!/usr/bin/env bash
set -Eeuo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TRAEFIK_CONFIG="${ROOT}/clusters/staging/ingress-ha/traefik-helmchartconfig.yaml"
ENDPOINT_SLICE_HEALTH="${ROOT}/scripts/endpoint_slice_health.py"
TIMEOUT="${SUGARKUBE_INGRESS_HA_TIMEOUT:-180s}"
EXPECTED_CONTEXT=sugar-staging
OWNER_LABEL='sugarkube.dev/managed-by'
OWNER_VALUE='staging-ingress-ha'
die() { printf 'ERROR: %s\n' "$*" >&2; exit 2; }
need() { command -v "$1" >/dev/null 2>&1 || die "required command '$1' was not found"; }
normalize_env() { local value="${1#env=}"; [[ "$value" == staging ]] || die "this lifecycle is staging-only; use env=staging"; }
context() { kubectl config current-context 2>/dev/null || true; }
guard() { normalize_env "$1"; [[ "$(context)" == "$EXPECTED_CONTEXT" ]] || die "refusing mutation: current context must be exactly ${EXPECTED_CONTEXT}"; }
render_coredns() {
  kubectl -n kube-system get deployment coredns -o json | python3 -c '
import json,sys
d=json.load(sys.stdin); d["metadata"]={"name":"coredns-ha","namespace":"kube-system","labels":{"sugarkube.dev/managed-by":"staging-ingress-ha"}}
d["spec"]["replicas"]=2
d["spec"]["selector"]["matchLabels"]["sugarkube.dev/component"]="coredns-ha"
t=d["spec"]["template"]; t["metadata"].setdefault("labels",{})["sugarkube.dev/component"]="coredns-ha"
t["spec"]["affinity"]={"podAntiAffinity":{"requiredDuringSchedulingIgnoredDuringExecution":[{"labelSelector":{"matchLabels":{"k8s-app":"kube-dns"}},"topologyKey":"kubernetes.io/hostname"}]}}
for k in ("creationTimestamp","resourceVersion","uid","generation","managedFields","annotations"): d["metadata"].pop(k,None)
d.pop("status",None); print(json.dumps(d,sort_keys=True,indent=2))'
}
render() { normalize_env "$1"; need kubectl; need python3; cat "$TRAEFIK_CONFIG"; printf '%s\n' '---'; render_coredns; }
endpoint_slices() {
  local service="$1"
  shift
  kubectl -n kube-system get endpointslices.discovery.k8s.io -l "kubernetes.io/service-name=${service}" -o json |
    python3 "$ENDPOINT_SLICE_HEALTH" "$service" "$@"
}
status() {
  normalize_env "$1"; need kubectl; need python3
  printf 'Context: %s (read-only)\n' "$(context)"
  kubectl -n kube-system get deploy coredns traefik -o wide
  kubectl -n kube-system get deploy coredns-ha -o wide --ignore-not-found=true
  endpoint_slices kube-dns
  endpoint_slices traefik
  kubectl get deployment -A -l app.kubernetes.io/name=cloudflare-tunnel -o wide
}
assert_owned_or_absent() {
  local kind="$1" name="$2" value error_file resource_file
  error_file="$(mktemp -t sugarkube-ownership.XXXXXX)"
  resource_file="$(mktemp -t sugarkube-resource.XXXXXX.json)"
  if ! kubectl -n kube-system get "${kind}/${name}" -o json >"$resource_file" 2>"$error_file"; then
    if grep -q '(NotFound)' "$error_file"; then
      rm -f "$error_file" "$resource_file"
      return 0
    fi
    rm -f "$error_file" "$resource_file"
    die "unable to inspect ownership of ${kind}/${name}"
  fi
  if ! value="$(python3 -c 'import json,sys; print(json.load(sys.stdin).get("metadata",{}).get("labels",{}).get(sys.argv[1], ""), end="")' "$OWNER_LABEL" <"$resource_file" 2>/dev/null)"; then
    rm -f "$error_file" "$resource_file"
    die "unable to inspect ownership of ${kind}/${name}"
  fi
  rm -f "$error_file" "$resource_file"
  [[ "$value" == "$OWNER_VALUE" ]] || die "refusing to modify existing ${kind}/${name}: resource is not owned by this lifecycle"
}
apply() {
  guard "$1"; need kubectl; need python3
  assert_owned_or_absent deployment coredns-ha
  assert_owned_or_absent helmchartconfig traefik
  local tmp; tmp="$(mktemp -t sugarkube-coredns-ha.XXXXXX.json)"; trap 'rm -f "${tmp:-}"' EXIT
  render_coredns >"$tmp"
  kubectl apply -f "$tmp"
  kubectl -n kube-system rollout status deployment/coredns-ha --timeout="$TIMEOUT" || die "CoreDNS HA rollout timed out; run staging-ingress-ha-status (no credentials are logged)"
  kubectl apply -f "$TRAEFIK_CONFIG"
  kubectl -n kube-system wait --for=jsonpath='{.spec.replicas}'=2 deployment/traefik --timeout="$TIMEOUT" || die "Traefik did not reconcile to the expected two-replica specification before timeout (resource details redacted)"
  kubectl -n kube-system rollout status deployment/traefik --timeout="$TIMEOUT" || die "Traefik rollout timed out; run staging-ingress-ha-status"
}
rollback() {
  guard "$1"; need kubectl
  assert_owned_or_absent deployment coredns-ha
  assert_owned_or_absent helmchartconfig traefik
  kubectl delete -f "$TRAEFIK_CONFIG" --ignore-not-found=true
  kubectl -n kube-system wait --for=jsonpath='{.spec.replicas}'=1 deployment/traefik --timeout="$TIMEOUT" || die "packaged Traefik did not reconcile to the expected one-replica specification before timeout (resource details redacted)"
  kubectl -n kube-system delete deployment coredns-ha --ignore-not-found=true
  kubectl -n kube-system rollout status deployment/coredns --timeout="$TIMEOUT" || die "packaged CoreDNS did not become ready during rollback"
  kubectl -n kube-system rollout status deployment/traefik --timeout="$TIMEOUT" || die "packaged Traefik did not become ready during rollback"
}
verify() {
  guard "$1"; need kubectl; need python3; need curl
  probe="sugarkube-ingress-ha-verify-$$"
  cleanup() { kubectl -n default delete pod "$probe" --ignore-not-found=true --wait=false >/dev/null 2>&1 || true; }
  trap cleanup EXIT INT TERM
  check_spread() {
    local name="$1"
    python3 -c '
import json,sys
pods=json.load(sys.stdin)["items"]
def ready(p): return p.get("status",{}).get("phase")=="Running" and bool(p.get("status",{}).get("containerStatuses")) and all(c.get("ready") for c in p["status"]["containerStatuses"])
nodes={p.get("spec",{}).get("nodeName") for p in pods if ready(p)}-{None}
print(f"{sys.argv[1]}: ready nodes={sorted(nodes)}")
if len(nodes)<2: raise SystemExit(f"ERROR: fewer than two ready, hostname-spread {sys.argv[1]} pods")' "$name"
  }
  endpoint_slices kube-dns --minimum-healthy 2 --minimum-nodes 2
  kubectl -n kube-system get pods -l app.kubernetes.io/name=traefik -o json | check_spread Traefik
  local tunnel_namespace
  tunnel_namespace="$(kubectl get deployment -A -l app.kubernetes.io/name=cloudflare-tunnel -o json | python3 -c '
import json,sys
items=json.load(sys.stdin)["items"]
if len(items) != 1: raise SystemExit(f"ERROR: expected exactly one Cloudflare tunnel Deployment; found {len(items)}")
print(items[0]["metadata"]["namespace"])')"
  kubectl -n "$tunnel_namespace" get pods -l app.kubernetes.io/name=cloudflare-tunnel -o json | check_spread 'Cloudflare tunnel'
  endpoint_slices traefik --minimum-healthy 2 --minimum-nodes 2
  kubectl -n default run "$probe" --image="${SUGARKUBE_DNS_TEST_IMAGE:-busybox:1.36}" --restart=Never --command -- nslookup kubernetes.default.svc.cluster.local >/dev/null
  kubectl -n default wait --for=jsonpath='{.status.phase}'=Succeeded "pod/$probe" --timeout="$TIMEOUT" || die "bounded in-cluster DNS probe failed"
  local targets url
  targets="$(kubectl get probes -A -l environment=staging,criticality=critical -o json | python3 -c '
import json,sys
items=json.load(sys.stdin)["items"]
urls={url for item in items for url in item.get("spec",{}).get("targets",{}).get("staticConfig",{}).get("static",[]) if isinstance(url,str) and url.startswith("https://")}
if not urls: raise SystemExit("ERROR: no critical staging HTTPS Probe targets found")
print("\n".join(sorted(urls)))')"
  while IFS= read -r url; do
    curl --fail --silent --max-time 15 --retry 2 --output /dev/null "$url" 2>/dev/null || die "critical staging HTTPS Probe target failed (target redacted)"
  done <<<"$targets"
  printf 'PASS: staging DNS/ingress HA baseline is healthy.\n'
}
cmd="${1:-}"; env_name="${2:-}"
case "$cmd" in render) render "$env_name";; status) status "$env_name";; apply|upgrade) apply "$env_name";; verify) verify "$env_name";; rollback) rollback "$env_name";; *) die "usage: $0 render|status|apply|upgrade|verify|rollback staging";; esac
