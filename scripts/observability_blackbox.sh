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
print_resolved() { local ctx; ctx="$(current_context)"; cat <<EOT
blackbox environment: staging
current Kubernetes context: ${ctx:-<unknown>}
namespace: ${NAMESPACE}
release: ${RELEASE}
chart: ${CHART}
chart repository: ${REPOSITORY}
pinned version: $(version)
ordered values files:
  - ${VALUES}
Probe manifest path: ${PROBES}
EOT
}
assert_context() {
  local ctx; ctx="$(current_context)"
  [[ "${ctx}" == sugar-staging ]] || { echo "ERROR: expected context 'sugar-staging', got '${ctx:-<none>}' before mutation or cluster access." >&2; exit 3; }
  python3 "${ROOT}/scripts/cluster_identity.py" assert --kubeconfig "${KUBECONFIG:-${HOME}/.kube/config}" --env staging >/dev/null
}
render_to() {
  local chart_out="$1" probe_out="$2"
  helm repo add prometheus-community "${REPOSITORY}" --force-update >/dev/null
  helm repo update prometheus-community >/dev/null
  helm template "${RELEASE}" "${CHART}" --namespace "${NAMESPACE}" --version "$(version)" -f "${VALUES}" >"${chart_out}"
  kubectl kustomize "${PROBES}" >"${probe_out}"
  [[ -s "${chart_out}" && -s "${probe_out}" ]] || { echo "ERROR: chart and Probe renders must both be non-empty." >&2; exit 4; }
}
release_state() {
  local matches
  matches="$(helm list --namespace "${NAMESPACE}" --all --filter "^${RELEASE}$" --short)" || { echo "ERROR: Helm could not query exporter release state; refusing to mutate." >&2; return 1; }
  [[ "${matches}" == "${RELEASE}" ]] && { printf present; return; }
  [[ -z "${matches}" ]] && { printf absent; return; }
  echo "ERROR: unexpected Helm release query result." >&2; return 1
}
preflight() {
  [[ "$(helm list --namespace "${NAMESPACE}" --all --filter "^${BASE_RELEASE}$" --short)" == "${BASE_RELEASE}" ]] || { echo "ERROR: required ${BASE_RELEASE} release is absent." >&2; exit 5; }
  kubectl get crd probes.monitoring.coreos.com servicemonitors.monitoring.coreos.com >/dev/null || { echo "ERROR: required Probe or ServiceMonitor CRD is absent." >&2; exit 5; }
  kubectl -n "${NAMESPACE}" get service "${PROMETHEUS_SERVICE}" >/dev/null || { echo "ERROR: required Prometheus service is absent." >&2; exit 5; }
}
with_render() {
  CHART_RENDER="$(mktemp -t sugarkube-blackbox-chart.XXXXXX.yaml)"
  PROBE_RENDER="$(mktemp -t sugarkube-blackbox-probes.XXXXXX.yaml)"
  trap 'rm -f "${CHART_RENDER:-}" "${PROBE_RENDER:-}"' EXIT
  render_to "${CHART_RENDER}" "${PROBE_RENDER}"
}
render() { require_tools helm kubectl; print_resolved; with_render; cat "${CHART_RENDER}" "${PROBE_RENDER}"; }
mutate() {
  local action="$1" state
  require_tools helm kubectl python3; print_resolved; assert_context; with_render; preflight; state="$(release_state)"
  if [[ "${action}" == install && "${state}" == present ]]; then echo "ERROR: install requires an absent ${RELEASE} release; use upgrade." >&2; exit 6; fi
  if [[ "${action}" == upgrade && "${state}" == absent ]]; then echo "ERROR: upgrade requires an existing ${RELEASE} release; use install." >&2; exit 6; fi
  helm "${action}" "${RELEASE}" "${CHART}" --namespace "${NAMESPACE}" --version "$(version)" -f "${VALUES}" --wait --timeout "${TIMEOUT}"
  kubectl apply -f "${PROBE_RENDER}"
  # Remove production Probes left by the former mixed-environment staging overlay.
  # The staging identity guard above makes this cleanup safe; production retains
  # its own Flux-owned Probe manifests under clusters/prod/observability/probes.
  kubectl -n "${NAMESPACE}" delete probe \
    -l "release=${BASE_RELEASE},environment=prod" --ignore-not-found
}
status() {
  require_tools helm kubectl python3; print_resolved; assert_context; with_render
  helm -n "${NAMESPACE}" status "${RELEASE}"
  kubectl -n "${NAMESPACE}" get deployment,pods,service,servicemonitor -l "app.kubernetes.io/instance=${RELEASE}"
  kubectl -n "${NAMESPACE}" get probe -l 'release=kube-prometheus-stack,environment=staging' -L app,route,criticality
}
validate_resources() {
  kubectl -n "${NAMESPACE}" rollout status "deployment/${RELEASE}" --timeout="${TIMEOUT}"
  [[ "$(kubectl -n "${NAMESPACE}" get service "${RELEASE}" -o jsonpath='{.spec.type}')" == ClusterIP ]] || { echo "ERROR: exporter Service must be ClusterIP." >&2; exit 7; }
  [[ -z "$(kubectl -n "${NAMESPACE}" get ingress -l "app.kubernetes.io/instance=${RELEASE}" -o name)" ]] || { echo "ERROR: exporter Ingress is forbidden." >&2; exit 7; }
  [[ -z "$(kubectl -n "${NAMESPACE}" get service -l "app.kubernetes.io/instance=${RELEASE}" -o jsonpath='{range .items[*].spec.ports[*]}{.nodePort}{"\n"}{end}' | sed '/^$/d')" ]] || { echo "ERROR: exporter NodePort is forbidden." >&2; exit 7; }
  [[ "$(kubectl -n "${NAMESPACE}" get servicemonitor "${RELEASE}" -o jsonpath='{.metadata.labels.release}')" == "${BASE_RELEASE}" ]] || { echo "ERROR: exporter ServiceMonitor is absent or lacks release: ${BASE_RELEASE}." >&2; exit 7; }
  kubectl -n "${NAMESPACE}" get probe -l 'release=kube-prometheus-stack' -o json | python3 -c 'import json,sys
expected={
("dspace","root"),("dspace","config"),("dspace","healthz"),("dspace","livez"),
("tokenplace","root"),("tokenplace","healthz"),("tokenplace","livez"),("tokenplace","metadata"),
("danielsmith","root"),("danielsmith","healthz"),("danielsmith","livez"),
("jobbot3000","root"),("jobbot3000","healthz"),("jobbot3000","livez"),("jobbot3000","tracker"),("jobbot3000","manifest")}
d=json.load(sys.stdin); items=d.get("items") if isinstance(d,dict) else None
if not isinstance(items,list): raise SystemExit("ERROR: invalid Probe response structure.")
owned=[]
for x in items:
 m=x.get("metadata",{}); labels=m.get("labels",{})
 if m.get("name","").startswith("blackbox-"):
  if labels.get("environment")!="staging": raise SystemExit("ERROR: lifecycle-owned non-staging Probe exists.")
  owned.append((labels.get("app"),labels.get("route")))
if len(owned)!=16 or set(owned)!=expected: raise SystemExit("ERROR: staging Probe app/route matrix is missing, unexpected, or mislabelled.")'
}
prom_get() { kubectl get --request-timeout="${SUGARKUBE_BLACKBOX_REQUEST_TIMEOUT:-14s}" --raw "/api/v1/namespaces/${NAMESPACE}/services/http:${PROMETHEUS_SERVICE}:9090/proxy$1"; }
verify_series() {
  local attempts="${SUGARKUBE_BLACKBOX_VERIFY_ATTEMPTS:-20}" interval="${SUGARKUBE_BLACKBOX_VERIFY_INTERVAL_SECONDS:-15}" attempt targets metrics family encoded output rc
  [[ "${attempts}" =~ ^[1-9][0-9]*$ && "${interval}" =~ ^[1-9][0-9]*$ ]] || { echo "ERROR: verification attempts and interval must be positive integers." >&2; exit 8; }
  for ((attempt=1; attempt<=attempts; attempt++)); do
    targets="$(prom_get '/api/v1/targets?state=active')" || { echo "ERROR: Prometheus target transport failed." >&2; exit 9; }
    metrics='{}'
    for family in probe_success probe_duration_seconds probe_http_status_code probe_dns_lookup_time_seconds probe_ssl_earliest_cert_expiry_seconds; do
      printf -v encoded '%%7Benvironment%%3D%%22staging%%22%%7D'
      output="$(prom_get "/api/v1/query?query=${family}${encoded}")" || { echo "ERROR: Prometheus metric transport failed." >&2; exit 9; }
      metrics="$(python3 -c 'import json,sys; d=json.loads(sys.argv[1]); d[sys.argv[2]]=json.loads(sys.stdin.read()); print(json.dumps(d,separators=(",",":")))' "${metrics}" "${family}" <<<"${output}")" || { echo "ERROR: Prometheus metric response is malformed JSON." >&2; exit 9; }
    done
    rc=0
    FINAL_ATTEMPT="$((attempt==attempts))" python3 "${ROOT}/scripts/verify_blackbox_prometheus.py" <<<"$(printf '{"targets":%s,"metrics":%s}' "${targets}" "${metrics}")" || rc=$?
    case "${rc}" in 0) echo "All 16 staging blackbox targets and required metric families are healthy."; return;; 10) ((attempt<attempts)) && { echo "Blackbox targets are converging (attempt ${attempt}/${attempts}); retrying." >&2; sleep "${interval}"; };; *) exit "${rc}";; esac
  done
  exit 10
}
verify() { require_tools helm kubectl python3 sleep; print_resolved; assert_context; with_render; preflight; [[ "$(release_state)" == present ]] || { echo "ERROR: exporter release is absent." >&2; exit 7; }; validate_resources; verify_series; }

cmd="${1:-}"; shift || true; [[ -n "${cmd}" ]] || { usage; exit 2; }; normalize_env "${1:-}" >/dev/null
case "${cmd}" in render) render;; install|upgrade) mutate "${cmd}";; status) status;; verify) verify;; *) usage; exit 2;; esac
