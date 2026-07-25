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
POLICY_KUSTOMIZATION="${ROOT}/clusters/staging/observability/network-policies"
POLICY_SOURCE="${POLICY_KUSTOMIZATION}/prometheus-to-blackbox-exporter.yaml"
POLICY_NAME="allow-kube-prometheus-stack-to-blackbox-exporter"
TIMEOUT="${SUGARKUBE_OBSERVABILITY_HELM_TIMEOUT:-20m}"
PROMETHEUS_SERVICE="kube-prometheus-stack-prometheus"
LEGACY_PROBES=(
  blackbox-dspace-prod-root blackbox-dspace-prod-config
  blackbox-dspace-prod-healthz blackbox-dspace-prod-livez
  blackbox-tokenplace-prod-root blackbox-tokenplace-prod-healthz
  blackbox-tokenplace-prod-livez blackbox-tokenplace-prod-metadata
  blackbox-danielsmith-prod-root blackbox-danielsmith-prod-healthz
  blackbox-danielsmith-prod-livez
)

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
NetworkPolicy manifest path: ${POLICY_SOURCE}
EOT
}
assert_context() {
  local ctx; ctx="$(current_context)"
  [[ "${ctx}" == sugar-staging ]] || { echo "ERROR: expected context 'sugar-staging', got '${ctx:-<none>}' before mutation or cluster access." >&2; exit 3; }
  python3 "${ROOT}/scripts/cluster_identity.py" assert --kubeconfig "${KUBECONFIG:-${HOME}/.kube/config}" --env staging >/dev/null
}
render_to() {
  local chart_out="$1" policy_out="$2" probe_out="$3"
  helm repo add prometheus-community "${REPOSITORY}" --force-update >/dev/null
  helm repo update prometheus-community >/dev/null
  helm template "${RELEASE}" "${CHART}" --namespace "${NAMESPACE}" --version "$(version)" -f "${VALUES}" >"${chart_out}"
  kubectl kustomize "${POLICY_KUSTOMIZATION}" >"${policy_out}"
  kubectl kustomize "${PROBES}" >"${probe_out}"
  [[ -s "${chart_out}" && -s "${policy_out}" && -s "${probe_out}" ]] || { echo "ERROR: chart, NetworkPolicy, and Probe renders must all be non-empty." >&2; exit 4; }
  python3 - "${chart_out}" "${policy_out}" <<'PY'
import re, sys
text = open(sys.argv[1], encoding="utf-8").read()
docs = text.split("\n---")
deployments = [d for d in docs if re.search(r"(?m)^kind: Deployment$", d) and re.search(r"(?m)^  name: prometheus-blackbox-exporter$", d)]
monitors = [d for d in docs if re.search(r"(?m)^kind: ServiceMonitor$", d) and re.search(r"(?m)^  name: prometheus-blackbox-exporter$", d)]
if len(deployments) != 1 or not re.search(r"(?m)^  replicas: 1$", deployments[0]):
    raise SystemExit("ERROR: rendered exporter Deployment must have exactly one replica.")
for label in (
    r"(?m)^        app\.kubernetes\.io/instance: prometheus-blackbox-exporter$",
    r"(?m)^        app\.kubernetes\.io/name: prometheus-blackbox-exporter$",
):
    if not re.search(label, deployments[0]):
        raise SystemExit("ERROR: rendered exporter pod labels do not match the NetworkPolicy selector.")
if len(monitors) != 1 or not re.search(r"(?m)^    release: kube-prometheus-stack$", monitors[0]):
    raise SystemExit("ERROR: rendered exporter ServiceMonitor must carry the base release label.")
policy = open(sys.argv[2], encoding="utf-8").read()
required = [
    r"(?m)^kind: NetworkPolicy$",
    r"(?m)^  name: allow-kube-prometheus-stack-to-blackbox-exporter$",
    r"(?m)^  namespace: monitoring$",
    r"(?m)^\s+- Egress$",
    r"(?m)^      app\.kubernetes\.io/instance: kube-prometheus-stack$",
    r"(?m)^      app\.kubernetes\.io/name: prometheus$",
    r"(?m)^              app\.kubernetes\.io/instance: prometheus-blackbox-exporter$",
    r"(?m)^              app\.kubernetes\.io/name: prometheus-blackbox-exporter$",
    r"(?m)^\s+-?\s*port: 9115$",
    r"(?m)^\s+-?\s*protocol: TCP$",
]
if any(not re.search(pattern, policy) for pattern in required) or policy.count("kind: NetworkPolicy") != 1:
    raise SystemExit("ERROR: rendered NetworkPolicy does not match the lifecycle contract.")
for forbidden in ("namespaceSelector:", "ipBlock:", "ingress:", "podSelector: {}"):
    if forbidden in policy:
        raise SystemExit("ERROR: rendered NetworkPolicy contains forbidden broad behavior.")
PY
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
  POLICY_RENDER="$(mktemp -t sugarkube-blackbox-policy.XXXXXX.yaml)"
  PROBE_RENDER="$(mktemp -t sugarkube-blackbox-probes.XXXXXX.yaml)"
  trap 'rm -f "${CHART_RENDER:-}" "${POLICY_RENDER:-}" "${PROBE_RENDER:-}"' EXIT
  render_to "${CHART_RENDER}" "${POLICY_RENDER}" "${PROBE_RENDER}"
}
render() {
  require_tools helm kubectl python3
  print_resolved
  with_render
  cat "${CHART_RENDER}"
  printf '\n---\n'
  cat "${POLICY_RENDER}"
  printf '\n---\n'
  cat "${PROBE_RENDER}"
}
mutate() {
  local action="$1" state
  require_tools helm kubectl python3; print_resolved; with_render; assert_context; preflight; state="$(release_state)"
  if [[ "${action}" == install && "${state}" == present ]]; then echo "ERROR: install requires an absent ${RELEASE} release; use upgrade." >&2; exit 6; fi
  if [[ "${action}" == upgrade && "${state}" == absent ]]; then echo "ERROR: upgrade requires an existing ${RELEASE} release; use install." >&2; exit 6; fi
  helm "${action}" "${RELEASE}" "${CHART}" --namespace "${NAMESPACE}" --version "$(version)" -f "${VALUES}" --wait --timeout "${TIMEOUT}"
  kubectl apply -f "${POLICY_RENDER}"
  # Remove only the production Probes left by the former mixed staging matrix.
  kubectl -n "${NAMESPACE}" delete probe "${LEGACY_PROBES[@]}" --ignore-not-found
  kubectl apply -f "${PROBE_RENDER}"
}
status() {
  require_tools helm kubectl python3; print_resolved; with_render; assert_context
  helm -n "${NAMESPACE}" status "${RELEASE}"
  kubectl -n "${NAMESPACE}" get deployment,pods,service,servicemonitor -l "app.kubernetes.io/instance=${RELEASE}"
  kubectl -n "${NAMESPACE}" get networkpolicy "${POLICY_NAME}" -o yaml
  kubectl -n "${NAMESPACE}" get probe -l 'release=kube-prometheus-stack,environment=staging' -L app,route,criticality
}
validate_policy() {
  local deployed
  deployed="$(mktemp -t sugarkube-blackbox-deployed-policy.XXXXXX.json)"
  kubectl -n "${NAMESPACE}" get networkpolicy "${POLICY_NAME}" -o json >"${deployed}" || { rm -f "${deployed}"; echo "ERROR: lifecycle NetworkPolicy is absent." >&2; return 7; }
  python3 - "${deployed}" <<'PY' || { local rc=$?; rm -f "${deployed}"; return "${rc}"; }
import json, sys

try:
    with open(sys.argv[1], encoding="utf-8") as stream:
        actual = json.load(stream)
except (json.JSONDecodeError, UnicodeDecodeError):
    raise SystemExit("ERROR: lifecycle NetworkPolicy response is malformed JSON.")
expected = {
    "podSelector": {"matchLabels": {
        "app.kubernetes.io/instance": "kube-prometheus-stack",
        "app.kubernetes.io/name": "prometheus",
    }},
    "policyTypes": ["Egress"],
    "egress": [{
        "to": [{"podSelector": {"matchLabels": {
            "app.kubernetes.io/instance": "prometheus-blackbox-exporter",
            "app.kubernetes.io/name": "prometheus-blackbox-exporter",
        }}}],
        "ports": [{"protocol": "TCP", "port": 9115}],
    }],
}
if not isinstance(actual, dict) or actual.get("spec") != expected:
    raise SystemExit("ERROR: deployed lifecycle NetworkPolicy is absent, broad, or differs from the required contract.")
PY
  rm -f "${deployed}"
}
validate_resources() {
  kubectl -n "${NAMESPACE}" rollout status "deployment/${RELEASE}" --timeout="${TIMEOUT}"
  [[ "$(kubectl -n "${NAMESPACE}" get deployment "${RELEASE}" -o jsonpath='{.spec.replicas} {.status.readyReplicas} {.status.availableReplicas}')" == "1 1 1" ]] || { echo "ERROR: exporter Deployment desired, ready, and available replicas must all equal one." >&2; exit 7; }
  [[ "$(kubectl -n "${NAMESPACE}" get service "${RELEASE}" -o jsonpath='{.spec.type}')" == ClusterIP ]] || { echo "ERROR: exporter Service must be ClusterIP." >&2; exit 7; }
  [[ -z "$(kubectl -n "${NAMESPACE}" get ingress -l "app.kubernetes.io/instance=${RELEASE}" -o name)" ]] || { echo "ERROR: exporter Ingress is forbidden." >&2; exit 7; }
  [[ -z "$(kubectl -n "${NAMESPACE}" get service -l "app.kubernetes.io/instance=${RELEASE}" -o jsonpath='{range .items[*].spec.ports[*]}{.nodePort}{"\n"}{end}' | sed '/^$/d')" ]] || { echo "ERROR: exporter NodePort is forbidden." >&2; exit 7; }
  [[ "$(kubectl -n "${NAMESPACE}" get servicemonitor "${RELEASE}" -o jsonpath='{.metadata.labels.release}')" == "${BASE_RELEASE}" ]] || { echo "ERROR: exporter ServiceMonitor is absent or lacks release: ${BASE_RELEASE}." >&2; exit 7; }
  kubectl -n "${NAMESPACE}" get probe -l 'release=kube-prometheus-stack' -o json | python3 "${ROOT}/scripts/verify_blackbox_prometheus.py" --probes
}
prom_get() {
  local operation="$1" path="$2" error_file output rc category
  error_file="$(mktemp -t sugarkube-blackbox-prometheus.XXXXXX)"
  if output="$(kubectl get --request-timeout="${SUGARKUBE_BLACKBOX_REQUEST_TIMEOUT:-14s}" --raw "/api/v1/namespaces/${NAMESPACE}/services/http:${PROMETHEUS_SERVICE}:9090/proxy${path}" 2>"${error_file}")"; then
    rm -f "${error_file}"
    printf '%s' "${output}"
    return
  else
    rc=$?
  fi
  if grep -Eqi 'unauthenticated|unauthorized|authentication|credential|token' "${error_file}"; then
    category=authentication
  elif grep -Eqi 'forbidden|authorization|permission denied|access denied' "${error_file}"; then
    category=authorization
  elif grep -Eqi 'timed out|timeout|deadline exceeded' "${error_file}"; then
    category=timeout
  elif grep -Eqi 'connection|unable to connect|no route to host|tls handshake|x509' "${error_file}"; then
    category=connection
  elif grep -Eqi 'not found|status[=: ]+404|http 404' "${error_file}"; then
    category=not_found
  else
    category=other
  fi
  rm -f "${error_file}"
  printf 'ERROR: Prometheus transport operation=%s category=%s status=%d error=<redacted>\n' "${operation}" "${category}" "${rc}" >&2
  return "${rc}"
}
verify_series() {
  local attempts="${SUGARKUBE_BLACKBOX_VERIFY_ATTEMPTS:-20}" interval="${SUGARKUBE_BLACKBOX_VERIFY_INTERVAL_SECONDS:-15}" attempt targets metrics family encoded output rc
  [[ "${attempts}" =~ ^[1-9][0-9]*$ && "${interval}" =~ ^[1-9][0-9]*$ ]] || { echo "ERROR: verification attempts and interval must be positive integers." >&2; exit 8; }
  for ((attempt=1; attempt<=attempts; attempt++)); do
    targets="$(prom_get targets '/api/v1/targets?state=active')" || exit 9
    metrics='{}'
    for family in probe_success probe_duration_seconds probe_http_status_code probe_dns_lookup_time_seconds probe_ssl_earliest_cert_expiry; do
      printf -v encoded '%%7Benvironment%%3D%%22staging%%22%%7D'
      output="$(prom_get "${family}" "/api/v1/query?query=${family}${encoded}")" || exit 9
      metrics="$(python3 -c 'import json,sys; d=json.loads(sys.argv[1]); d[sys.argv[2]]=json.loads(sys.stdin.read()); print(json.dumps(d,separators=(",",":")))' "${metrics}" "${family}" <<<"${output}")" || { echo "ERROR: Prometheus metric response is malformed JSON." >&2; exit 9; }
    done
    rc=0
    FINAL_ATTEMPT="$((attempt==attempts))" python3 "${ROOT}/scripts/verify_blackbox_prometheus.py" <<<"$(printf '{"targets":%s,"metrics":%s}' "${targets}" "${metrics}")" || rc=$?
    case "${rc}" in 0) echo "All 16 staging blackbox targets and required metric families are healthy."; return;; 10) ((attempt<attempts)) && { echo "Blackbox targets are converging (attempt ${attempt}/${attempts}); retrying." >&2; sleep "${interval}"; };; *) exit "${rc}";; esac
  done
  exit 10
}
verify() { require_tools helm kubectl python3 sleep; print_resolved; with_render; assert_context; preflight; [[ "$(release_state)" == present ]] || { echo "ERROR: exporter release is absent." >&2; exit 7; }; validate_policy || exit 7; validate_resources; verify_series; }

cmd="${1:-}"; shift || true; [[ -n "${cmd}" ]] || { usage; exit 2; }; normalize_env "${1:-}" >/dev/null
case "${cmd}" in render) render;; install|upgrade) mutate "${cmd}";; status) status;; verify) verify;; *) usage; exit 2;; esac
