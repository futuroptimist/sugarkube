#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RELEASE="prometheus-blackbox-exporter"
BASE_RELEASE="kube-prometheus-stack"
NAMESPACE="monitoring"
CHART="prometheus-community/prometheus-blackbox-exporter"
REPOSITORY="https://prometheus-community.github.io/helm-charts"
VERSION_FILE="${ROOT}/platform/observability/helm/prometheus-blackbox-exporter.version"
VALUES="${ROOT}/clusters/staging/observability/prometheus-blackbox-exporter.values.yaml"
PROBES="${ROOT}/clusters/staging/observability/probes"
TIMEOUT="${SUGARKUBE_OBSERVABILITY_HELM_TIMEOUT:-20m}"

usage() { echo "Usage: $0 <render|install|upgrade|status|verify> env=staging" >&2; }
normalize_env() {
  local raw="${1:-}"; while [[ "${raw}" == env=* ]]; do raw="${raw#env=}"; done
  case "${raw}" in
    staging) printf staging ;;
    int) echo "WARNING: env name 'int' is deprecated; using env=staging." >&2; printf staging ;;
    ""|prod|production) echo "ERROR: production blackbox observability is unsupported; pass env=staging explicitly." >&2; exit 2 ;;
    *) echo "ERROR: unsupported blackbox observability env '${raw}'; supported env: staging." >&2; exit 2 ;;
  esac
}
require_tools() { local t; for t in "$@"; do command -v "${t}" >/dev/null || { echo "ERROR: required tool missing: ${t}" >&2; exit 127; }; done; }
version() { tr -d '[:space:]' <"${VERSION_FILE}"; }
context() { kubectl config current-context 2>/dev/null || true; }
print_resolved() { cat <<EOF
observability environment: staging
current Kubernetes context: $(context || true)
namespace: ${NAMESPACE}
release: ${RELEASE}
chart: ${CHART}
chart repository: ${REPOSITORY}
pinned version: $(version)
ordered values files:
  - ${VALUES}
Probe manifest path: ${PROBES}
EOF
}
assert_context() {
  local actual; actual="$(context)"
  [[ "${actual}" == sugar-staging ]] || { echo "ERROR: expected context 'sugar-staging', got '${actual:-<none>}' before mutation." >&2; exit 3; }
  python3 "${ROOT}/scripts/cluster_identity.py" assert --kubeconfig "${KUBECONFIG:-${HOME}/.kube/config}" --env staging >/dev/null
}
render_all() {
  local chart_out="$1" probes_out="$2"
  helm repo add prometheus-community "${REPOSITORY}" --force-update >/dev/null
  helm repo update prometheus-community >/dev/null
  helm template "${RELEASE}" "${CHART}" --namespace "${NAMESPACE}" --version "$(version)" -f "${VALUES}" >"${chart_out}"
  kubectl kustomize "${PROBES}" >"${probes_out}"
  [[ -s "${chart_out}" && -s "${probes_out}" ]] || { echo "ERROR: rendered lifecycle output is empty." >&2; exit 4; }
}
release_state() {
  local matches
  matches="$(helm list -n "${NAMESPACE}" --all --filter "^${RELEASE}$" --short)" || { echo "ERROR: Helm could not query release state; refusing to mutate." >&2; return 1; }
  [[ -z "${matches}" ]] && { printf absent; return; }
  [[ "${matches}" == "${RELEASE}" ]] && { printf present; return; }
  echo "ERROR: unexpected Helm release query result." >&2; return 1
}
preflight() {
  [[ "$(helm list -n "${NAMESPACE}" --all --filter "^${BASE_RELEASE}$" --short)" == "${BASE_RELEASE}" ]] || { echo "ERROR: required ${BASE_RELEASE} release is absent." >&2; exit 5; }
  kubectl get crd probes.monitoring.coreos.com servicemonitors.monitoring.coreos.com >/dev/null || { echo "ERROR: required Probe or ServiceMonitor CRD is absent." >&2; exit 5; }
  kubectl -n "${NAMESPACE}" get service "${BASE_RELEASE}-prometheus" >/dev/null || { echo "ERROR: required Prometheus service is absent." >&2; exit 5; }
}
with_render() {
  CHART_RENDER="$(mktemp -t sugarkube-blackbox-chart.XXXXXX.yaml)"
  PROBE_RENDER="$(mktemp -t sugarkube-blackbox-probes.XXXXXX.yaml)"
  trap 'rm -f "${CHART_RENDER:-}" "${PROBE_RENDER:-}"' EXIT
  render_all "${CHART_RENDER}" "${PROBE_RENDER}"
}
mutate() {
  local operation="$1" state
  require_tools helm kubectl python3; print_resolved; assert_context; with_render; preflight; state="$(release_state)"
  if [[ "${operation}" == install && "${state}" == present ]]; then echo "ERROR: exporter release exists; use observability-blackbox-upgrade." >&2; exit 6; fi
  if [[ "${operation}" == upgrade && "${state}" == absent ]]; then echo "ERROR: exporter release is absent; use observability-blackbox-install." >&2; exit 6; fi
  helm "${operation}" "${RELEASE}" "${CHART}" -n "${NAMESPACE}" --version "$(version)" -f "${VALUES}" --wait --timeout "${TIMEOUT}"
  kubectl apply -f "${PROBE_RENDER}"
}
status() {
  require_tools helm kubectl python3; print_resolved; assert_context
  helm -n "${NAMESPACE}" status "${RELEASE}"
  kubectl -n "${NAMESPACE}" get deployment,pods -l "app.kubernetes.io/instance=${RELEASE}"
  kubectl -n "${NAMESPACE}" get service "${RELEASE}"
  kubectl -n "${NAMESPACE}" get servicemonitor -l "app.kubernetes.io/instance=${RELEASE}"
  kubectl -n "${NAMESPACE}" get probes -l 'release=kube-prometheus-stack,environment=staging' -L app,route,criticality
}
verify_objects() {
  kubectl -n "${NAMESPACE}" get deployment "${RELEASE}" -o json | python3 -c 'import json,sys
d=json.load(sys.stdin); s=d.get("status",{}); desired=d.get("spec",{}).get("replicas")
assert desired == 1 and s.get("readyReplicas",0)==desired and s.get("availableReplicas",0)==desired, "ERROR: exporter Deployment is not fully ready."'
  [[ "$(kubectl -n "${NAMESPACE}" get service "${RELEASE}" -o jsonpath='{.spec.type}')" == ClusterIP ]] || { echo "ERROR: exporter Service must be ClusterIP." >&2; exit 7; }
  [[ -z "$(kubectl -n "${NAMESPACE}" get ingress -l "app.kubernetes.io/instance=${RELEASE}" -o name)" ]] || { echo "ERROR: exporter Ingress is forbidden." >&2; exit 7; }
  [[ -z "$(kubectl -n "${NAMESPACE}" get service -l "app.kubernetes.io/instance=${RELEASE}" -o jsonpath='{range .items[*].spec.ports[*]}{.nodePort}{"\n"}{end}')" ]] || { echo "ERROR: exporter NodePort is forbidden." >&2; exit 7; }
  kubectl -n "${NAMESPACE}" get servicemonitor "${RELEASE}" -o json | python3 -c 'import json,sys
d=json.load(sys.stdin); assert d.get("metadata",{}).get("labels",{}).get("release")=="kube-prometheus-stack", "ERROR: exporter ServiceMonitor discovery label is missing."'
  kubectl -n "${NAMESPACE}" get probes -o json | python3 -c 'import json,sys
live=json.load(sys.stdin)
routes={"dspace":("root","config","healthz","livez"),"tokenplace":("root","healthz","livez","metadata"),"danielsmith":("root","healthz","livez"),"jobbot3000":("root","healthz","livez","tracker","manifest")}
want={(f"blackbox-{app}-staging-{route}",app,route) for app,rs in routes.items() for route in rs}; owned=[]
for d in live.get("items",[]):
 labels=d.get("metadata",{}).get("labels",{}); name=d.get("metadata",{}).get("name","")
 if labels.get("release")=="kube-prometheus-stack" and name.startswith("blackbox-"):
  assert labels.get("environment") != "prod", "ERROR: lifecycle-owned production Probe exists."
  if labels.get("environment")=="staging": owned.append((name,labels.get("app"),labels.get("route")))
assert set(owned)==want and len(owned)==16, "ERROR: staging Probe name/app/route matrix differs from canonical manifests."'
}
verify_series() {
  local attempts="${SUGARKUBE_OBSERVABILITY_TARGET_HEALTH_ATTEMPTS:-20}" interval="${SUGARKUBE_OBSERVABILITY_TARGET_HEALTH_INTERVAL_SECONDS:-15}" endpoint response rc
  [[ "${attempts}" =~ ^[1-9][0-9]*$ && "${interval}" =~ ^[1-9][0-9]*$ ]] || { echo "ERROR: polling attempts and interval must be positive integers." >&2; exit 8; }
  endpoint="/api/v1/namespaces/${NAMESPACE}/services/http:${BASE_RELEASE}-prometheus:9090/proxy/api/v1/query"
  for ((attempt=1; attempt<=attempts; attempt++)); do
    response="$(kubectl get --request-timeout=14s --raw "${endpoint}?query=%7Benvironment%3D%22staging%22%7D")" || { echo "ERROR: Prometheus transport failure." >&2; exit 9; }
    rc=0
    FINAL="$((attempt==attempts))" python3 -c 'import json,os,sys
try: d=json.load(sys.stdin)
except Exception: raise SystemExit("ERROR: Prometheus response is malformed JSON.")
if not isinstance(d,dict) or d.get("status")!="success": raise SystemExit("ERROR: Prometheus API response was unsuccessful.")
r=d.get("data",{}).get("result");
if not isinstance(r,list): raise SystemExit("ERROR: Prometheus response has an invalid structure.")
expected={("dspace",x) for x in ("root","config","healthz","livez")} | {("tokenplace",x) for x in ("root","healthz","livez","metadata")} | {("danielsmith",x) for x in ("root","healthz","livez")} | {("jobbot3000",x) for x in ("root","healthz","livez","tracker","manifest")}
families={"probe_success","probe_duration_seconds","probe_http_status_code","probe_dns_lookup_time_seconds","probe_ssl_earliest_cert_expiry_seconds"}; seen={f:set() for f in families}; down=[]
for row in r:
 if not isinstance(row,dict) or not isinstance(row.get("metric"),dict): raise SystemExit("ERROR: Prometheus response has an invalid series.")
 m=row["metric"]; name=m.get("__name__"); pair=(m.get("app"),m.get("route"))
 if name in seen and pair in expected: seen[name].add(pair)
 if name=="probe_success" and pair in expected and (not isinstance(row.get("value"),list) or len(row["value"])!=2 or row["value"][1]!="1"): down.append(pair)
if all(seen[f]==expected for f in families) and not down: raise SystemExit(0)
if os.environ["FINAL"]=="1":
 print("ERROR: staging blackbox series did not converge before timeout.",file=sys.stderr)
 for app,route in sorted(expected-seen["probe_success"]): print(f"Probe diagnostic: app={app} environment=staging route={route} health=missing error=<redacted>",file=sys.stderr)
 for app,route in sorted(set(down)): print(f"Probe diagnostic: app={app} environment=staging route={route} health=down error=<redacted>",file=sys.stderr)
raise SystemExit(10)' <<<"${response}" || rc=$?
    [[ "${rc}" == 0 ]] && { echo "All 16 staging Probe series and required metric families are healthy."; return; }
    [[ "${rc}" == 10 ]] || exit "${rc}"
    ((attempt < attempts)) && sleep "${interval}"
  done
  exit 10
}
verify() { require_tools helm kubectl python3 ruby sleep; print_resolved; assert_context; with_render; verify_objects; verify_series; }
render() { require_tools helm kubectl; print_resolved; with_render; cat "${CHART_RENDER}"; cat "${PROBE_RENDER}"; }

cmd="${1:-}"; shift || true; [[ -n "${cmd}" ]] || { usage; exit 2; }; normalize_env "${1:-}" >/dev/null
case "${cmd}" in render) render;; install|upgrade) mutate "${cmd}";; status) status;; verify) verify;; *) usage; exit 2;; esac
