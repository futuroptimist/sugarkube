#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ACTIVE="${ROOT}/clusters/staging/ingress-ha"
ROLLBACK="${ACTIVE}/rollback"
TIMEOUT="${SUGARKUBE_INGRESS_HA_TIMEOUT:-180s}"
DNS_POD="sugarkube-ingress-ha-dns-check"

usage() { echo "Usage: $0 <render|plan|status|apply|verify|rollback> env=staging" >&2; }
env_name() {
  local value="${1:-}"; value="${value#env=}"
  [[ "${value}" == staging ]] || { echo "ERROR: this lifecycle is staging-only; pass env=staging." >&2; exit 2; }
}
need() { for tool in "$@"; do command -v "${tool}" >/dev/null || { echo "ERROR: required tool missing: ${tool}" >&2; exit 127; }; done; }
context() { kubectl config current-context 2>/dev/null || true; }
guard_mutation() {
  local current; current="$(context)"
  [[ "${current}" == sugar-staging ]] || {
    echo "ERROR: refusing staging mutation: expected context 'sugar-staging', got '${current:-<none>}'." >&2
    exit 3
  }
}
manifest() { cat "${ACTIVE}/coredns-helmchartconfig.yaml"; printf '\n---\n'; cat "${ACTIVE}/traefik-helmchartconfig.yaml"; }
rollout() {
  local expected="${1:-2}"
  kubectl -n kube-system rollout status deployment/coredns --timeout="${TIMEOUT}" || {
    echo "ERROR: CoreDNS did not converge within ${TIMEOUT}; inspect deployment events (sensitive values omitted)." >&2; return 10;
  }
  kubectl -n kube-system rollout status deployment/traefik --timeout="${TIMEOUT}" || {
    echo "ERROR: Traefik did not converge within ${TIMEOUT}; inspect deployment events (sensitive values omitted)." >&2; return 10;
  }
  for deployment in coredns traefik; do
    kubectl -n kube-system wait "deployment/${deployment}" \
      --for="jsonpath={.status.readyReplicas}=${expected}" --timeout="${TIMEOUT}" || {
      echo "ERROR: ${deployment} did not reach ${expected} ready replica(s) within ${TIMEOUT}." >&2
      return 10
    }
  done
}
check_workload() {
  local description="$1" selector="$2"
  kubectl get pods -A -l "${selector}" -o json | DESCRIPTION="${description}" python3 -c '
import json, os, sys
d=json.load(sys.stdin); ready=[]
for p in d.get("items", []):
  statuses=p.get("status", {}).get("containerStatuses") or []
  if p.get("status", {}).get("phase") == "Running" and statuses and all(c.get("ready") for c in statuses):
    ready.append(p)
nodes={p.get("spec", {}).get("nodeName") for p in ready if p.get("spec", {}).get("nodeName")}
if len(ready) < 2 or len(nodes) < 2:
  print(f"ERROR: {os.environ[\"DESCRIPTION\"]} requires >=2 ready pods on distinct nodes; found {len(ready)} ready on {len(nodes)} node(s).", file=sys.stderr)
  raise SystemExit(11)
print(f"OK: {os.environ[\"DESCRIPTION\"]}: {len(ready)} ready pods across {len(nodes)} nodes.")'
}
check_service() {
  local service="$1"
  kubectl -n kube-system get endpointslice -l "kubernetes.io/service-name=${service}" -o json | SERVICE="${service}" python3 -c '
import json, os, sys
d=json.load(sys.stdin); ready=sum(1 for s in d.get("items",[]) for e in s.get("endpoints",[]) if e.get("conditions",{}).get("ready") is not False)
if ready < 1:
  print(f"ERROR: Service {os.environ[\"SERVICE\"]} has no ready backends.", file=sys.stderr); raise SystemExit(12)
print(f"OK: Service {os.environ[\"SERVICE\"]} has {ready} ready backend(s).")'
}
verify() {
  need kubectl python3 curl
  check_workload CoreDNS 'k8s-app=kube-dns'
  check_workload Traefik 'app.kubernetes.io/name=traefik'
  # Discover the live Helm deployment by stable application labels, across namespaces.
  check_workload 'Cloudflare tunnel' 'app.kubernetes.io/name in (cloudflare-tunnel,cloudflared)'
  check_service kube-dns
  check_service traefik
  kubectl delete pod "${DNS_POD}" --ignore-not-found --wait=false >/dev/null 2>&1 || true
  trap 'kubectl delete pod "${DNS_POD}" --ignore-not-found --wait=false >/dev/null 2>&1 || true' EXIT
  kubectl run "${DNS_POD}" --image=busybox:1.36.1 --restart=Never --command -- nslookup kubernetes.default.svc.cluster.local >/dev/null
  if ! kubectl wait --for=jsonpath='{.status.phase}'=Succeeded "pod/${DNS_POD}" --timeout="${TIMEOUT}" >/dev/null; then
    echo "ERROR: bounded in-cluster DNS check failed; temporary pod output is intentionally not printed." >&2; return 13
  fi
  local urls
  urls="$(kubectl get probes.monitoring.coreos.com -A -l environment=staging,criticality=critical -o json | python3 -c '
import json,sys
for p in json.load(sys.stdin).get("items",[]):
  for u in p.get("spec",{}).get("targets",{}).get("staticConfig",{}).get("static",[]):
    if isinstance(u,str) and u.startswith("https://"): print(u)' | sort -u)"
  [[ -n "${urls}" ]] || { echo "ERROR: no critical public staging Probe targets were discovered." >&2; return 14; }
  while IFS= read -r url; do
    curl --fail --silent --show-error --location --max-time 15 --output /dev/null "${url}" || {
      echo "ERROR: a public staging health target was unreachable (target redacted)." >&2; return 15;
    }
  done <<<"${urls}"
  echo "OK: all discovered critical public staging health targets are reachable."
}

[[ $# -eq 2 ]] || { usage; exit 2; }
action="$1"; env_name "$2"
case "${action}" in
  render) manifest ;;
  plan) need kubectl; manifest | kubectl diff -f - || [[ $? -eq 1 ]] ;;
  status)
    need kubectl
    kubectl -n kube-system get helmchart,helmchartconfig coredns traefik
    kubectl get pods -A -l 'k8s-app=kube-dns' -o wide
    kubectl get pods -A -l 'app.kubernetes.io/name=traefik' -o wide
    kubectl get pods -A -l 'app.kubernetes.io/name in (cloudflare-tunnel,cloudflared)' -o wide
    ;;
  apply)
    need kubectl; guard_mutation
    kubectl apply -f "${ACTIVE}/coredns-helmchartconfig.yaml"
    kubectl -n kube-system wait deployment/coredns --for=jsonpath='{.status.readyReplicas}'=2 --timeout="${TIMEOUT}" || {
      echo "ERROR: CoreDNS HA did not converge within ${TIMEOUT}; Traefik was not changed." >&2; exit 10;
    }
    kubectl apply -f "${ACTIVE}/traefik-helmchartconfig.yaml"
    rollout 2
    ;;
  verify) guard_mutation; verify ;;
  rollback) need kubectl; guard_mutation; kubectl apply -f "${ROLLBACK}"; rollout 1 ;;
  *) usage; exit 2 ;;
esac
