#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONFIG_DIR="${ROOT}/clusters/staging/ingress-ha"
TIMEOUT="${SUGARKUBE_STAGING_HA_TIMEOUT:-5m}"
OWNER="sugarkube-staging-ingress-ha"

usage() { echo "Usage: $0 <render|status|apply|verify|rollback> env=staging" >&2; }
normalize_env() {
  local value="${1:-}"
  while [[ "${value}" == env=* ]]; do value="${value#env=}"; done
  [[ "${value}" == staging ]] || { echo "ERROR: staging ingress HA only supports explicit env=staging." >&2; exit 2; }
}
require_tools() { for tool in "$@"; do command -v "${tool}" >/dev/null || { echo "ERROR: required tool missing: ${tool}" >&2; exit 127; }; done; }
context() { kubectl config current-context 2>/dev/null || true; }
guard() {
  local current; current="$(context)"
  [[ "${current}" == sugar-staging ]] || {
    echo "ERROR: expected Kubernetes context 'sugar-staging', got '${current:-<none>}'; refusing cluster access." >&2
    exit 3
  }
  python3 "${ROOT}/scripts/cluster_identity.py" assert --kubeconfig "${KUBECONFIG:-${HOME}/.kube/config}" --env staging >/dev/null
}
render() { require_tools kubectl; kubectl kustomize "${CONFIG_DIR}"; echo "---"; echo "# CoreDNS is rendered from the active packaged Deployment during apply; preview with status."; }
assert_owned_or_absent() {
  local name owner
  name="$1"
  owner="$(kubectl -n kube-system get helmchartconfig "${name}" -o jsonpath='{.metadata.labels.app\.kubernetes\.io/managed-by}' 2>/dev/null || true)"
  if kubectl -n kube-system get helmchartconfig "${name}" >/dev/null 2>&1 && [[ "${owner}" != "${OWNER}" ]]; then
    echo "ERROR: kube-system/${name} already exists outside this lifecycle; refusing to overwrite current custom values." >&2
    echo "Merge its redacted values into ${CONFIG_DIR} before retrying." >&2
    exit 4
  fi
}
status() {
  require_tools kubectl python3; guard
  kubectl -n kube-system get helmchartconfig k3s-traefik --ignore-not-found
  kubectl -n kube-system get deployment coredns coredns-ha -o wide
  kubectl -n kube-system get deploy,pod,svc,endpoints -l 'k8s-app=kube-dns' -o wide
  kubectl -n kube-system get deploy,pod,svc,endpoints -l 'app.kubernetes.io/name=traefik' -o wide
  discover_cloudflare get
}
discover_cloudflare() {
  local verb="$1" inventory namespace name
  inventory="$(kubectl get deployments --all-namespaces -l 'app.kubernetes.io/name=cloudflare-tunnel' -o json)"
  read -r namespace name < <(python3 -c 'import json,sys
d=json.load(sys.stdin); items=d.get("items",[])
if len(items)!=1: raise SystemExit("ERROR: expected exactly one active Cloudflare tunnel Deployment discovered by stable label")
print(items[0]["metadata"]["namespace"],items[0]["metadata"]["name"])' <<<"${inventory}")
  if [[ "${verb}" == get ]]; then kubectl -n "${namespace}" get deploy "${name}"; kubectl -n "${namespace}" get pods -l 'app.kubernetes.io/name=cloudflare-tunnel' -o wide; else printf '%s %s\n' "${namespace}" "${name}"; fi
}
apply_config() {
  require_tools kubectl python3; guard
  assert_owned_or_absent k3s-traefik
  render >/dev/null
  kubectl -n kube-system get deployment coredns -o json | python3 "${ROOT}/scripts/render_coredns_ha.py" | kubectl apply -f -
  kubectl apply -k "${CONFIG_DIR}"
  kubectl -n kube-system rollout status deployment/coredns-ha --timeout="${TIMEOUT}" || { echo "ERROR: supplemental CoreDNS rollout timed out; packaged CoreDNS remains active." >&2; exit 5; }
  kubectl -n kube-system rollout status deployment/traefik --timeout="${TIMEOUT}" || { echo "ERROR: Traefik rollout timed out; inspect deployment events (credentials are never printed)." >&2; exit 5; }
}
verify() {
  require_tools kubectl python3; guard
  local cf_namespace cf_name tmp pod rc=0
  read -r cf_namespace cf_name < <(discover_cloudflare identify)
  tmp="$(mktemp -d -t sugarkube-staging-ha.XXXXXX)"; pod="sugarkube-dns-check-$RANDOM"
  trap 'kubectl -n default delete pod "${pod}" --ignore-not-found --wait=false >/dev/null 2>&1 || true; rm -rf "${tmp}"' EXIT
  kubectl -n kube-system get pods -l k8s-app=kube-dns -o json >"${tmp}/coredns"
  kubectl -n kube-system get pods -l app.kubernetes.io/name=traefik -o json >"${tmp}/traefik"
  kubectl -n "${cf_namespace}" get pods -l app.kubernetes.io/name=cloudflare-tunnel -o json >"${tmp}/cloudflare"
  kubectl -n kube-system get endpoints kube-dns -o json >"${tmp}/dns_endpoints"
  kubectl -n kube-system get endpoints traefik -o json >"${tmp}/traefik_endpoints"
  python3 - "${tmp}" <<'PY' | python3 "${ROOT}/scripts/staging_ingress_ha_verify.py"
import json, pathlib, sys
root=pathlib.Path(sys.argv[1]); print(json.dumps({p.name:json.loads(p.read_text()) for p in root.iterdir()}))
PY
  kubectl -n default run "${pod}" --image="${SUGARKUBE_DNS_TEST_IMAGE:-busybox:1.36}" --restart=Never --command -- nslookup kubernetes.default.svc.cluster.local
  kubectl -n default wait --for=jsonpath='{.status.phase}'=Succeeded "pod/${pod}" --timeout="${TIMEOUT}" || { echo "ERROR: bounded in-cluster DNS check failed; test pod will be removed." >&2; rc=6; }
  if ((rc == 0)); then
    kubectl -n monitoring get probes -l environment=staging -o json | python3 -c 'import json,subprocess,sys
items=json.load(sys.stdin).get("items",[])
urls=[target for item in items for target in item.get("spec",{}).get("targets",{}).get("staticConfig",{}).get("static",[])]
if not urls: raise SystemExit("ERROR: no labeled public staging health Probe targets discovered")
for url in urls:
 r=subprocess.run(["curl","--fail","--silent","--show-error","--max-time","10","--output","/dev/null",url])
 if r.returncode: raise SystemExit("ERROR: a public staging health endpoint was unreachable (URL redacted)")
print(f"public staging health: {len(urls)} endpoints reachable")' || rc=7
  fi
  return "${rc}"
}
rollback() {
  require_tools kubectl python3; guard
  assert_owned_or_absent k3s-traefik
  kubectl -n kube-system delete deployment coredns-ha --ignore-not-found
  kubectl -n kube-system delete helmchartconfig k3s-traefik --ignore-not-found
  kubectl -n kube-system rollout status deployment/coredns --timeout="${TIMEOUT}"
  kubectl -n kube-system rollout status deployment/traefik --timeout="${TIMEOUT}"
  echo "Rollback complete: supplemental CoreDNS is removed and K3s packaged chart defaults are restored."
}

[[ $# -eq 2 ]] || { usage; exit 2; }
normalize_env "$2"
case "$1" in render) render;; status) status;; apply) apply_config;; verify) verify;; rollback) rollback;; *) usage; exit 2;; esac
