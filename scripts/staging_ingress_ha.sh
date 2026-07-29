#!/usr/bin/env bash
set -Eeuo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TRAEFIK_CONFIG="${ROOT}/clusters/staging/ingress-ha/traefik-helmchartconfig.yaml"
TIMEOUT="${SUGARKUBE_INGRESS_HA_TIMEOUT:-180s}"
EXPECTED_CONTEXT=sugar-staging
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
status() { normalize_env "$1"; need kubectl; printf 'Context: %s (read-only)\n' "$(context)"; kubectl -n kube-system get deploy coredns traefik -o wide; kubectl -n kube-system get deploy coredns-ha -o wide --ignore-not-found=true; kubectl -n kube-system get endpoints kube-dns traefik; kubectl get deployment -A -l app.kubernetes.io/name=cloudflare-tunnel -o wide; }
apply() {
  guard "$1"; need kubectl; need python3
  local tmp; tmp="$(mktemp -t sugarkube-coredns-ha.XXXXXX.json)"; trap 'rm -f "${tmp:-}"' EXIT
  render_coredns >"$tmp"
  kubectl apply -f "$tmp"
  kubectl -n kube-system rollout status deployment/coredns-ha --timeout="$TIMEOUT" || die "CoreDNS HA rollout timed out; run staging-ingress-ha-status (no credentials are logged)"
  kubectl apply -f "$TRAEFIK_CONFIG"
  kubectl -n kube-system rollout status deployment/traefik --timeout="$TIMEOUT" || die "Traefik rollout timed out; run staging-ingress-ha-status"
}
rollback() {
  guard "$1"; need kubectl
  kubectl delete -f "$TRAEFIK_CONFIG" --ignore-not-found=true
  kubectl -n kube-system delete deployment coredns-ha --ignore-not-found=true
  kubectl -n kube-system rollout status deployment/coredns --timeout="$TIMEOUT" || die "packaged CoreDNS did not become ready during rollback"
  kubectl -n kube-system rollout status deployment/traefik --timeout="$TIMEOUT" || die "packaged Traefik did not become ready during rollback"
}
verify() {
  guard "$1"; need kubectl; need python3; need curl
  probe="sugarkube-ingress-ha-verify-$$"
  cleanup() { kubectl -n default delete pod "$probe" --ignore-not-found=true --wait=false >/dev/null 2>&1 || true; }
  trap cleanup EXIT INT TERM
  kubectl get pods -A -o json | python3 -c '
import json,sys
pods=json.load(sys.stdin)["items"]
def ready(p): return p.get("status",{}).get("phase")=="Running" and bool(p.get("status",{}).get("containerStatuses")) and all(c.get("ready") for c in p["status"]["containerStatuses"])
def nodes(pred): return {p.get("spec",{}).get("nodeName") for p in pods if pred(p) and ready(p)}-{None}
checks={"CoreDNS":nodes(lambda p:p["metadata"].get("labels",{}).get("k8s-app")=="kube-dns"),"Traefik":nodes(lambda p:p["metadata"].get("labels",{}).get("app.kubernetes.io/name")=="traefik"),"Cloudflare tunnel":nodes(lambda p:p["metadata"].get("labels",{}).get("app.kubernetes.io/name")=="cloudflare-tunnel")}
bad=[]
for name,ns in checks.items(): print(f"{name}: ready nodes={sorted(ns)}"); bad += [name] if len(ns)<2 else []
if bad: raise SystemExit("ERROR: fewer than two ready, hostname-spread pods: "+", ".join(bad))'
  for svc in kube-dns traefik; do kubectl -n kube-system get endpoints "$svc" -o json | python3 -c 'import json,sys; e=json.load(sys.stdin); assert any(x.get("addresses") for x in e.get("subsets",[])), "ERROR: Service has no ready backend"'; done
  kubectl -n default run "$probe" --image="${SUGARKUBE_DNS_TEST_IMAGE:-busybox:1.36}" --restart=Never --command -- nslookup kubernetes.default.svc.cluster.local >/dev/null
  kubectl -n default wait --for=jsonpath='{.status.phase}'=Succeeded "pod/$probe" --timeout="$TIMEOUT" || die "bounded in-cluster DNS probe failed"
  local urls="${SUGARKUBE_STAGING_HEALTH_URLS:-https://staging.token.place/healthz https://staging.democratized.space/healthz}"
  local url; for url in $urls; do curl --fail --silent --show-error --max-time 15 --retry 2 --output /dev/null "$url" || die "public staging health check failed for ${url}"; done
  printf 'PASS: staging DNS/ingress HA baseline is healthy.\n'
}
cmd="${1:-}"; env_name="${2:-}"
case "$cmd" in render) render "$env_name";; status) status "$env_name";; apply|upgrade) apply "$env_name";; verify) verify "$env_name";; rollback) rollback "$env_name";; *) die "usage: $0 render|status|apply|upgrade|verify|rollback staging";; esac
