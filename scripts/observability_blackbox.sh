#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RELEASE="prometheus-blackbox-exporter"
BASE_RELEASE="kube-prometheus-stack"
NAMESPACE="monitoring"
CHART="prometheus-community/prometheus-blackbox-exporter"
REPOSITORY="https://prometheus-community.github.io/helm-charts"
VERSION_FILE="${ROOT}/platform/observability/helm/prometheus-blackbox-exporter.version"
VALUES_FILE="${ROOT}/clusters/staging/observability/prometheus-blackbox-exporter.values.yaml"
PROBES_PATH="${ROOT}/clusters/staging/observability/probes"
TIMEOUT="${SUGARKUBE_OBSERVABILITY_HELM_TIMEOUT:-20m}"
PROMETHEUS_SERVICE="kube-prometheus-stack-prometheus"

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
require_tools() { local t; for t in "$@"; do command -v "$t" >/dev/null || { echo "ERROR: required tool missing: $t" >&2; exit 127; }; done; }
version() { tr -d '[:space:]' <"${VERSION_FILE}"; }
current_context() { kubectl config current-context 2>/dev/null || true; }
print_resolved() { cat <<EOT
blackbox environment: staging
current Kubernetes context: $(current_context || true)
namespace: ${NAMESPACE}
release: ${RELEASE}
chart: ${CHART}
chart repository: ${REPOSITORY}
pinned version: $(version)
ordered values files:
  - ${VALUES_FILE}
Probe manifest path: ${PROBES_PATH}
EOT
}
assert_context() {
  local ctx; ctx="$(current_context)"
  [[ "${ctx}" == sugar-staging ]] || { echo "ERROR: expected context 'sugar-staging', got '${ctx:-<none>}' before mutation." >&2; exit 3; }
  python3 "${ROOT}/scripts/cluster_identity.py" assert --kubeconfig "${KUBECONFIG:-${HOME}/.kube/config}" --env staging >/dev/null
}
render_chart() {
  local out="$1"
  helm repo add prometheus-community "${REPOSITORY}" --force-update >/dev/null
  helm repo update prometheus-community >/dev/null
  helm template "${RELEASE}" "${CHART}" --namespace "${NAMESPACE}" --version "$(version)" -f "${VALUES_FILE}" >"${out}"
}
render_probes() { kubectl kustomize "${PROBES_PATH}" >"$1"; }
release_state() {
  local matches
  matches="$(helm list --namespace "${NAMESPACE}" --all --filter "^${RELEASE}$" --short)" || { echo "ERROR: Helm could not query exporter release state; refusing mutation." >&2; return 1; }
  case "${matches}" in "${RELEASE}") printf present;; "") printf absent;; *) echo "ERROR: unexpected Helm release query result." >&2; return 1;; esac
}
preflight() {
  [[ "$(helm list -n "${NAMESPACE}" --all --filter "^${BASE_RELEASE}$" --short)" == "${BASE_RELEASE}" ]] || { echo "ERROR: canonical ${BASE_RELEASE} release is required." >&2; exit 6; }
  kubectl get crd probes.monitoring.coreos.com servicemonitors.monitoring.coreos.com >/dev/null || { echo "ERROR: required Probe and ServiceMonitor CRDs are missing." >&2; exit 6; }
  kubectl -n "${NAMESPACE}" get service "${PROMETHEUS_SERVICE}" >/dev/null || { echo "ERROR: Prometheus service ${PROMETHEUS_SERVICE} is required." >&2; exit 6; }
}
render() { local c p; c="$(mktemp -t sugarkube-blackbox-chart.XXXXXX.yaml)"; p="$(mktemp -t sugarkube-blackbox-probes.XXXXXX.yaml)"; trap 'rm -f "${c}" "${p}"' EXIT; print_resolved; render_chart "${c}"; render_probes "${p}"; cat "${c}"; echo '---'; cat "${p}"; }
mutate() {
  local mode="$1" chart_render probe_render state
  chart_render="$(mktemp -t sugarkube-blackbox-chart.XXXXXX.yaml)"; probe_render="$(mktemp -t sugarkube-blackbox-probes.XXXXXX.yaml)"; trap 'rm -f "${chart_render}" "${probe_render}"' EXIT
  print_resolved; assert_context
  # Render both committed inputs before any cluster state query.
  render_chart "${chart_render}"; render_probes "${probe_render}"
  preflight; state="$(release_state)"
  if [[ "${mode}" == install ]]; then
    [[ "${state}" == absent ]] || { echo "ERROR: exporter release already exists; use observability-blackbox-upgrade." >&2; exit 4; }
    helm install "${RELEASE}" "${CHART}" -n "${NAMESPACE}" --version "$(version)" -f "${VALUES_FILE}" --wait --timeout "${TIMEOUT}"
  else
    [[ "${state}" == present ]] || { echo "ERROR: exporter release is absent; use observability-blackbox-install." >&2; exit 5; }
    helm upgrade "${RELEASE}" "${CHART}" -n "${NAMESPACE}" --version "$(version)" -f "${VALUES_FILE}" --wait --timeout "${TIMEOUT}"
  fi
  kubectl apply -f "${probe_render}"
}
status() {
  print_resolved; assert_context
  helm -n "${NAMESPACE}" status "${RELEASE}"
  kubectl -n "${NAMESPACE}" get deployment,pod,service -l "app.kubernetes.io/instance=${RELEASE}"
  kubectl -n "${NAMESPACE}" get servicemonitor -l "app.kubernetes.io/instance=${RELEASE}"
  kubectl -n "${NAMESPACE}" get probe -l 'release=kube-prometheus-stack,environment=staging' -L app,environment,route,criticality
}
validate_runtime_objects() {
  kubectl -n "${NAMESPACE}" get deployment "${RELEASE}" -o json | python3 -c 'import json,sys
o=json.load(sys.stdin); s=o.get("status",{}); desired=o.get("spec",{}).get("replicas",0)
if desired != 1 or s.get("availableReplicas",0) != desired or s.get("readyReplicas",0) != desired: raise SystemExit("ERROR: exporter Deployment is not fully ready (expected 1/1).")'
  kubectl -n "${NAMESPACE}" get service "${RELEASE}" -o json | python3 -c 'import json,sys
o=json.load(sys.stdin); s=o.get("spec",{})
if s.get("type") != "ClusterIP" or any("nodePort" in p for p in s.get("ports",[])): raise SystemExit("ERROR: exporter Service must be ClusterIP-only.")'
  [[ -z "$(kubectl -n "${NAMESPACE}" get ingress -l "app.kubernetes.io/instance=${RELEASE}" -o name)" ]] || { echo "ERROR: exporter Ingress is forbidden." >&2; exit 7; }
  kubectl -n "${NAMESPACE}" get servicemonitor "${RELEASE}" -o json | python3 -c 'import json,sys
o=json.load(sys.stdin)
if o.get("metadata",{}).get("labels",{}).get("release") != "kube-prometheus-stack": raise SystemExit("ERROR: exporter ServiceMonitor has the wrong discovery label.")'
  kubectl -n "${NAMESPACE}" get probes -l release=kube-prometheus-stack -o json | python3 -c 'import json,sys
expected={"dspace":{"root","config","healthz","livez"},"tokenplace":{"root","healthz","livez","metadata"},"danielsmith":{"root","healthz","livez"},"jobbot3000":{"root","healthz","livez","tracker","manifest"}}
o=json.load(sys.stdin); seen=set()
for item in o.get("items",[]):
 l=item.get("metadata",{}).get("labels",{})
 if l.get("environment") == "prod" and item.get("metadata",{}).get("name","").startswith("blackbox-"): raise SystemExit("ERROR: lifecycle-owned production Probe exists.")
 if l.get("environment") == "staging": seen.add((l.get("app"),l.get("route")))
want={(a,r) for a,rs in expected.items() for r in rs}
if seen != want: raise SystemExit("ERROR: staging Probe app/route matrix differs (missing or unexpected resources).")'
}
prom_query() { local query="$1" encoded; encoded="$(python3 -c 'import sys,urllib.parse; print(urllib.parse.quote(sys.argv[1],safe=""))' "${query}")"; kubectl get --request-timeout=14s --raw "/api/v1/namespaces/${NAMESPACE}/services/http:${PROMETHEUS_SERVICE}:9090/proxy/api/v1/query?query=${encoded}"; }
check_series() {
  local metric="$1" response
  response="$(prom_query "${metric}{environment=\"staging\"}")" || { echo "ERROR: Prometheus transport failure while checking ${metric}." >&2; return 9; }
  local parser_status=0
  METRIC="${metric}" python3 -c 'import json,os,sys
try: o=json.load(sys.stdin)
except (json.JSONDecodeError,UnicodeDecodeError):
 print("ERROR: malformed Prometheus response.",file=sys.stderr); raise SystemExit(9)
if not isinstance(o,dict) or o.get("status") != "success" or not isinstance(o.get("data"),dict) or not isinstance(o["data"].get("result"),list):
 print("ERROR: unsuccessful or invalid Prometheus API response.",file=sys.stderr); raise SystemExit(9)
want={"dspace":{"root","config","healthz","livez"},"tokenplace":{"root","healthz","livez","metadata"},"danielsmith":{"root","healthz","livez"},"jobbot3000":{"root","healthz","livez","tracker","manifest"}}
expected={(a,r) for a,rs in want.items() for r in rs}; got=set()
for x in o["data"]["result"]:
 m=x.get("metric",{}); pair=(m.get("app"),m.get("route"))
 if m.get("environment")=="staging": got.add(pair)
 if os.environ["METRIC"]=="probe_success" and pair in expected and (not isinstance(x.get("value"),list) or len(x["value"])!=2 or x["value"][1] != "1"): print("ERROR: probe_success is not 1 for app=%s route=%s."%pair,file=sys.stderr); raise SystemExit(11)
if got != expected:
 print("ERROR: required staging series are not yet complete for %s."%os.environ["METRIC"],file=sys.stderr); raise SystemExit(10)' <<<"${response}" || parser_status=$?
  return "${parser_status}"
}
verify_metrics() {
  local attempts="${SUGARKUBE_BLACKBOX_VERIFY_ATTEMPTS:-20}" interval="${SUGARKUBE_BLACKBOX_VERIFY_INTERVAL_SECONDS:-15}" i rc=0
  [[ "${attempts}" =~ ^[1-9][0-9]*$ && "${interval}" =~ ^[1-9][0-9]*$ ]] || { echo "ERROR: verification attempts and interval must be positive integers." >&2; exit 8; }
  for ((i=1;i<=attempts;i++)); do
    rc=0; check_series probe_success || rc=$?
    if ((rc==0)); then for metric in probe_duration_seconds probe_http_status_code probe_dns_lookup_time_seconds probe_ssl_earliest_cert_expiry_seconds; do check_series "${metric}" || return $?; done; return 0; fi
    ((rc==9 || rc==11)) && return "${rc}"
    ((i<attempts)) && { echo "Staging Probe series are converging (attempt ${i}/${attempts})." >&2; sleep "${interval}"; }
  done
  echo "ERROR: staging Probe series did not converge; diagnostics limited to expected app/environment/route labels." >&2; return 10
}
verify() { print_resolved; assert_context; validate_runtime_objects; verify_metrics; echo "All 16 staging Probe series and required metric families are healthy."; }

cmd="${1:-}"; shift || true; [[ -n "${cmd}" ]] || { usage; exit 2; }
env="$(normalize_env "${1:-}")"; [[ "${env}" == staging ]]
require_tools helm kubectl python3
case "${cmd}" in render) render;; install|upgrade) mutate "${cmd}";; status) status;; verify) verify;; *) usage; exit 2;; esac
