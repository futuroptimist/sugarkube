#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RELEASE="prometheus-blackbox-exporter"
BASE_RELEASE="kube-prometheus-stack"
NAMESPACE="monitoring"
CHART="prometheus-community/prometheus-blackbox-exporter"
REPOSITORY="https://prometheus-community.github.io/helm-charts"
VERSION_FILE="${ROOT}/platform/observability/helm/prometheus-blackbox-exporter.version"
BASE_VERSION_FILE="${ROOT}/platform/observability/helm/kube-prometheus-stack.version"
BASE_COMMON_VALUES="${ROOT}/platform/observability/helm/kube-prometheus-stack.values.common.yaml"
BASE_ENV_VALUES=""
VALUES=""
PROBES=""
POLICIES=""
POLICY_SOURCE=""
ENVIRONMENT=""
EXPECTED_CONTEXT=""
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
usage() { echo "Usage: $0 <render|install|upgrade|status|verify> env=<staging|prod>" >&2; }
normalize_env() {
  local raw="${1:-}"; while [[ "${raw}" == env=* ]]; do raw="${raw#env=}"; done
  case "${raw}" in
    staging) printf staging ;;
    int) echo "WARNING: env name 'int' is deprecated; using env=staging." >&2; printf staging ;;
    prod|production) printf prod ;;
    "") echo "ERROR: blackbox observability environment is required; pass env=staging or env=prod." >&2; exit 2 ;;
    *) echo "ERROR: unsupported blackbox observability env '${raw}'; supported envs: staging, prod." >&2; exit 2 ;;
  esac
}
configure_env() {
  ENVIRONMENT="$1"
  BASE_ENV_VALUES="${ROOT}/clusters/${ENVIRONMENT}/observability/kube-prometheus-stack.values.yaml"
  VALUES="${ROOT}/clusters/${ENVIRONMENT}/observability/prometheus-blackbox-exporter.values.yaml"
  PROBES="${ROOT}/clusters/${ENVIRONMENT}/observability/probes"
  POLICIES="${ROOT}/clusters/${ENVIRONMENT}/observability/network-policies"
  POLICY_SOURCE="${POLICIES}/prometheus-to-blackbox-exporter.yaml"
  [[ "${ENVIRONMENT}" == staging ]] && EXPECTED_CONTEXT=sugar-staging || EXPECTED_CONTEXT=sugar-prod
}
require_tools() { local t; for t in "$@"; do command -v "$t" >/dev/null || { echo "ERROR: required tool missing: $t" >&2; exit 127; }; done; }
version() { tr -d '[:space:]' <"${VERSION_FILE}"; }
current_context() { kubectl config current-context 2>/dev/null || true; }
print_resolved() { local ctx; if (($#)); then ctx="$1"; else ctx="$(current_context)"; fi; cat <<EOT
blackbox environment: ${ENVIRONMENT}
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
  local ctx
  if [[ "${ENVIRONMENT}" == prod && -z "${KUBECONFIG:-}" ]]; then
    echo "ERROR: production live operations require an explicitly supplied KUBECONFIG." >&2; exit 3
  fi
  ctx="$(current_context)"
  [[ "${ctx}" == "${EXPECTED_CONTEXT}" ]] || { echo "ERROR: expected context '${EXPECTED_CONTEXT}', got '${ctx:-<none>}' before mutation or cluster access." >&2; exit 3; }
  python3 "${ROOT}/scripts/cluster_identity.py" assert --kubeconfig "${KUBECONFIG:-${HOME}/.kube/config}" --env "${ENVIRONMENT}" >/dev/null
}
render_to() {
  local base_out="$1" chart_out="$2" policy_out="$3" probe_out="$4" selectors_out="$5" base_json="$6" chart_json="$7" policy_json="$8" probes_json="$9"
  helm repo add prometheus-community "${REPOSITORY}" --force-update >/dev/null
  helm repo update prometheus-community >/dev/null
  helm template "${RELEASE}" "${CHART}" --namespace "${NAMESPACE}" --version "$(version)" -f "${VALUES}" >"${chart_out}"
  helm template "${BASE_RELEASE}" "prometheus-community/${BASE_RELEASE}" --namespace "${NAMESPACE}" --version "$(tr -d '[:space:]' <"${BASE_VERSION_FILE}")" -f "${BASE_COMMON_VALUES}" -f "${BASE_ENV_VALUES}" >"${base_out}"
  kubectl kustomize "${POLICIES}" >"${policy_out}"
  kubectl kustomize "${PROBES}" >"${probe_out}"
  [[ -s "${base_out}" && -s "${chart_out}" && -s "${policy_out}" && -s "${probe_out}" ]] || { echo "ERROR: prerequisite chart, exporter chart, NetworkPolicy, and Probe renders must all be non-empty." >&2; exit 4; }
  # Psych parses every rendered document locally, without Kubernetes discovery.
  ruby -ryaml -rjson - "${base_out}" "${base_json}" "${chart_out}" "${chart_json}" "${policy_out}" "${policy_json}" "${probe_out}" "${probes_json}" <<'RUBY'
begin
  ARGV.each_slice(2) do |source, destination|
    documents = YAML.load_stream(File.read(source))
    unless documents.all? { |document| document.nil? || document.is_a?(Hash) }
      raise ArgumentError, "render contains a non-object YAML document"
    end
    File.write(destination, JSON.generate({"items" => documents}))
  end
rescue Psych::Exception, JSON::GeneratorError, ArgumentError => error
  warn "ERROR: rendered YAML is malformed: #{error.message}"
  exit 4
end
RUBY
  python3 - "${base_json}" "${chart_json}" "${selectors_out}" <<'PY'
import json, sys
def items(path):
    value=json.load(open(path,encoding="utf-8"))
    return value["items"]
base=[d for d in items(sys.argv[1]) if isinstance(d,dict) and d.get("kind")=="Prometheus"]
exporter=[d for d in items(sys.argv[2]) if isinstance(d,dict) and d.get("kind")=="Deployment" and d.get("metadata",{}).get("name")=="prometheus-blackbox-exporter"]
monitors=[d for d in items(sys.argv[2]) if isinstance(d,dict) and d.get("kind")=="ServiceMonitor" and d.get("metadata",{}).get("name")=="prometheus-blackbox-exporter"]
if len(base)!=1 or not base[0].get("metadata",{}).get("name"): raise SystemExit("ERROR: pinned base chart must render exactly one named Prometheus object.")
if len(exporter) != 1 or exporter[0].get("spec",{}).get("replicas") != 1:
    raise SystemExit("ERROR: rendered exporter Deployment must have exactly one replica.")
if len(monitors) != 1 or monitors[0].get("metadata",{}).get("labels",{}).get("release") != "kube-prometheus-stack":
    raise SystemExit("ERROR: rendered exporter ServiceMonitor must carry the base release label.")
labels={}
for key in ("app.kubernetes.io/instance","app.kubernetes.io/name"):
    value=exporter[0].get("spec",{}).get("template",{}).get("metadata",{}).get("labels",{}).get(key)
    if not value: raise SystemExit(f"ERROR: exporter Deployment lacks required template label {key}.")
    labels[key]=value
# Helm renders the Prometheus CR; operator-created pods carry
# operator.prometheus.io/name=<CR name>, so the render supplies this value.
json.dump({"prometheus":{"operator.prometheus.io/name":base[0]["metadata"]["name"]},"exporter":labels},open(sys.argv[3],"w",encoding="utf-8"),sort_keys=True)
PY
  validate_policy_file "${policy_json}" "${selectors_out}"
  python3 "${ROOT}/scripts/verify_blackbox_prometheus.py" --env "${ENVIRONMENT}" --probes <"${probes_json}"
}
validate_policy_file() {
  python3 - "$2" "${POLICY_NAME}" "${NAMESPACE}" "$1" "${EXPECTED_POLICY_JSON}" <<'PY'
import json, sys
selectors=json.load(open(sys.argv[1],encoding="utf-8")); documents=json.load(open(sys.argv[4],encoding="utf-8"))["items"]
objects=[document for document in documents if document is not None]
if len(objects) != 1 or not isinstance(objects[0],dict):
    raise SystemExit("ERROR: lifecycle policy render must contain exactly one non-null Kubernetes object.")
policy=objects[0]
expected = {
    "podSelector": {"matchLabels": selectors["exporter"]},
    "policyTypes": ["Ingress"],
    "ingress": [{"from": [{"podSelector": {"matchLabels": selectors["prometheus"]}}], "ports": [{"protocol": "TCP", "port": 9115}]}],
}
required={"apiVersion": "networking.k8s.io/v1", "kind": "NetworkPolicy", "metadata": {"name": sys.argv[2], "namespace": sys.argv[3]}, "spec": expected}
policy.get("metadata",{}).pop("creationTimestamp",None)
if policy != required:
    raise SystemExit("ERROR: lifecycle NetworkPolicy must isolate only exporter ingress; Prometheus-selecting egress policies are forbidden.")
json.dump(required,open(sys.argv[5],"w",encoding="utf-8"),sort_keys=True)
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
  BASE_RENDER="$(mktemp -t sugarkube-prometheus-chart.XXXXXX.yaml)"
  CHART_RENDER="$(mktemp -t sugarkube-blackbox-chart.XXXXXX.yaml)"
  POLICY_RENDER="$(mktemp -t sugarkube-blackbox-policy.XXXXXX.yaml)"
  PROBE_RENDER="$(mktemp -t sugarkube-blackbox-probes.XXXXXX.yaml)"
  SELECTORS_RENDER="$(mktemp -t sugarkube-blackbox-selectors.XXXXXX.json)"
  BASE_RENDER_JSON="$(mktemp -t sugarkube-prometheus-chart.XXXXXX.json)"
  CHART_RENDER_JSON="$(mktemp -t sugarkube-blackbox-chart.XXXXXX.json)"
  POLICY_RENDER_JSON="$(mktemp -t sugarkube-blackbox-policy.XXXXXX.json)"
  PROBE_RENDER_JSON="$(mktemp -t sugarkube-blackbox-probes.XXXXXX.json)"
  LIVE_PROBES_JSON="$(mktemp -t sugarkube-blackbox-live-probes.XXXXXX.json)"
  STALE_PROBE_NAMES="$(mktemp -t sugarkube-blackbox-stale-probes.XXXXXX)"
  EXPECTED_POLICY_JSON="$(mktemp -t sugarkube-blackbox-policy.XXXXXX.json)"
  trap 'rm -f "${BASE_RENDER:-}" "${CHART_RENDER:-}" "${POLICY_RENDER:-}" "${PROBE_RENDER:-}" "${SELECTORS_RENDER:-}" "${BASE_RENDER_JSON:-}" "${CHART_RENDER_JSON:-}" "${POLICY_RENDER_JSON:-}" "${PROBE_RENDER_JSON:-}" "${LIVE_PROBES_JSON:-}" "${STALE_PROBE_NAMES:-}" "${EXPECTED_POLICY_JSON:-}"' EXIT
  render_to "${BASE_RENDER}" "${CHART_RENDER}" "${POLICY_RENDER}" "${PROBE_RENDER}" "${SELECTORS_RENDER}" "${BASE_RENDER_JSON}" "${CHART_RENDER_JSON}" "${POLICY_RENDER_JSON}" "${PROBE_RENDER_JSON}"
}
render() { require_tools helm kubectl python3 ruby; with_render; print_resolved "" >&2; cat "${CHART_RENDER}"; printf '\n---\n'; cat "${POLICY_RENDER}"; printf '\n---\n'; cat "${PROBE_RENDER}"; }
mutate() {
  local action="$1" state
  require_tools helm kubectl python3 ruby; with_render; assert_context; print_resolved "${EXPECTED_CONTEXT}"; preflight; state="$(release_state)"
  if [[ "${action}" == install && "${state}" == present ]]; then echo "ERROR: install requires an absent ${RELEASE} release; use upgrade." >&2; exit 6; fi
  if [[ "${action}" == upgrade && "${state}" == absent ]]; then echo "ERROR: upgrade requires an existing ${RELEASE} release; use install." >&2; exit 6; fi
  helm "${action}" "${RELEASE}" "${CHART}" --namespace "${NAMESPACE}" --version "$(version)" -f "${VALUES}" --wait --timeout "${TIMEOUT}"
  kubectl apply -f "${POLICY_RENDER}"
  kubectl apply -f "${PROBE_RENDER}"
  reconcile_probes
}
reconcile_probes() {
  local stale_names=() name
  kubectl -n "${NAMESPACE}" get probe \
    -l "release=${BASE_RELEASE},environment=${ENVIRONMENT}" -o json >"${LIVE_PROBES_JSON}" || {
    echo "ERROR: could not list lifecycle-owned Probes; refusing to prune." >&2
    exit 7
  }
  if ! python3 - "${PROBE_RENDER_JSON}" "${LIVE_PROBES_JSON}" "${ENVIRONMENT}" >"${STALE_PROBE_NAMES}" <<'PY'
import json
import sys

desired_document = json.load(open(sys.argv[1], encoding="utf-8"))
live = json.load(open(sys.argv[2], encoding="utf-8"))
environment = sys.argv[3]
if not isinstance(live, dict) or not isinstance(live.get("items"), list):
    raise SystemExit("ERROR: lifecycle-owned Probe response has an invalid structure.")
desired = {
    item["metadata"]["name"]
    for item in desired_document["items"]
    if isinstance(item, dict) and item.get("kind") == "Probe"
}
for item in live["items"]:
    metadata = item.get("metadata") if isinstance(item, dict) else None
    labels = metadata.get("labels") if isinstance(metadata, dict) else None
    name = metadata.get("name") if isinstance(metadata, dict) else None
    if not isinstance(labels, dict) or not isinstance(name, str):
        raise SystemExit("ERROR: lifecycle-owned Probe response contains an invalid object.")
    if labels.get("release") != "kube-prometheus-stack" or labels.get("environment") != environment:
        raise SystemExit("ERROR: Probe selector returned an object outside lifecycle ownership.")
    if name not in desired:
        print(name)
PY
  then
    echo "ERROR: could not compare lifecycle-owned Probes; refusing to prune." >&2
    exit 7
  fi
  while IFS= read -r name; do
    [[ -n "${name}" ]] && stale_names+=("${name}")
  done <"${STALE_PROBE_NAMES}"
  ((${#stale_names[@]} == 0)) || kubectl -n "${NAMESPACE}" delete probe "${stale_names[@]}" --ignore-not-found
  # These exact names are the production Probes formerly shipped in the mixed
  # staging matrix. Context validation above makes this cleanup staging-only.
  if [[ "${ENVIRONMENT}" == staging ]]; then
    kubectl -n "${NAMESPACE}" delete probe "${LEGACY_PROBES[@]}" --ignore-not-found
  fi
}
status() {
  require_tools helm kubectl python3 ruby; with_render; assert_context; print_resolved "${EXPECTED_CONTEXT}"
  helm -n "${NAMESPACE}" status "${RELEASE}"
  kubectl -n "${NAMESPACE}" get deployment,pods,service,servicemonitor -l "app.kubernetes.io/instance=${RELEASE}"
  kubectl -n "${NAMESPACE}" get networkpolicy "${POLICY_NAME}" -o yaml
  kubectl -n "${NAMESPACE}" get probe -l "release=kube-prometheus-stack,environment=${ENVIRONMENT}" -L app,route,criticality
}
validate_policy_live() {
  local policy
  policy="$(kubectl -n "${NAMESPACE}" get networkpolicy "${POLICY_NAME}" -o json)" || { echo "ERROR: required lifecycle NetworkPolicy is absent." >&2; exit 7; }
  python3 -c '
import json, sys
live=json.load(sys.stdin); expected=json.load(open(sys.argv[1]))
live={"apiVersion":live.get("apiVersion"),"kind":live.get("kind"),"metadata":{"name":live.get("metadata",{}).get("name"),"namespace":live.get("metadata",{}).get("namespace")},"spec":live.get("spec")}
if live != expected:
 raise SystemExit("ERROR: deployed lifecycle NetworkPolicy must isolate only exporter ingress; Prometheus-selecting egress policies are forbidden.")
' "${EXPECTED_POLICY_JSON}" <<<"${policy}" || exit 7
}
validate_resources() {
  kubectl -n "${NAMESPACE}" rollout status "deployment/${RELEASE}" --timeout="${TIMEOUT}"
  [[ "$(kubectl -n "${NAMESPACE}" get deployment "${RELEASE}" -o jsonpath='{.spec.replicas} {.status.readyReplicas} {.status.availableReplicas}')" == "1 1 1" ]] || { echo "ERROR: exporter Deployment desired, ready, and available replicas must all equal one." >&2; exit 7; }
  [[ "$(kubectl -n "${NAMESPACE}" get service "${RELEASE}" -o jsonpath='{.spec.type}')" == ClusterIP ]] || { echo "ERROR: exporter Service must be ClusterIP." >&2; exit 7; }
  [[ -z "$(kubectl -n "${NAMESPACE}" get ingress -l "app.kubernetes.io/instance=${RELEASE}" -o name)" ]] || { echo "ERROR: exporter Ingress is forbidden." >&2; exit 7; }
  [[ -z "$(kubectl -n "${NAMESPACE}" get service -l "app.kubernetes.io/instance=${RELEASE}" -o jsonpath='{range .items[*].spec.ports[*]}{.nodePort}{"\n"}{end}' | sed '/^$/d')" ]] || { echo "ERROR: exporter NodePort is forbidden." >&2; exit 7; }
  [[ "$(kubectl -n "${NAMESPACE}" get servicemonitor "${RELEASE}" -o jsonpath='{.metadata.labels.release}')" == "${BASE_RELEASE}" ]] || { echo "ERROR: exporter ServiceMonitor is absent or lacks release: ${BASE_RELEASE}." >&2; exit 7; }
  kubectl -n "${NAMESPACE}" get probe -l "release=kube-prometheus-stack,environment=${ENVIRONMENT}" -o json | python3 "${ROOT}/scripts/verify_blackbox_prometheus.py" --env "${ENVIRONMENT}" --probes
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
      printf -v encoded '%%7Benvironment%%3D%%22%s%%22%%7D' "${ENVIRONMENT}"
      output="$(prom_get "${family}" "/api/v1/query?query=${family}${encoded}")" || exit 9
      metrics="$(python3 -c 'import json,sys; d=json.loads(sys.argv[1]); d[sys.argv[2]]=json.loads(sys.stdin.read()); print(json.dumps(d,separators=(",",":")))' "${metrics}" "${family}" <<<"${output}")" || { echo "ERROR: Prometheus metric response is malformed JSON." >&2; exit 9; }
    done
    rc=0
    FINAL_ATTEMPT="$((attempt==attempts))" python3 "${ROOT}/scripts/verify_blackbox_prometheus.py" --env "${ENVIRONMENT}" <<<"$(printf '{"targets":%s,"metrics":%s}' "${targets}" "${metrics}")" || rc=$?
    case "${rc}" in 0) echo "All $(python3 -c 'import json,sys; print(len(json.load(open(sys.argv[1]))["items"]))' "${PROBE_RENDER_JSON}") ${ENVIRONMENT} blackbox targets and required metric families are healthy."; return;; 10) ((attempt<attempts)) && { echo "Blackbox targets are converging (attempt ${attempt}/${attempts}); retrying." >&2; sleep "${interval}"; };; *) exit "${rc}";; esac
  done
  exit 10
}
verify() { require_tools helm kubectl python3 ruby sleep; with_render; assert_context; print_resolved "${EXPECTED_CONTEXT}"; preflight; [[ "$(release_state)" == present ]] || { echo "ERROR: exporter release is absent." >&2; exit 7; }; validate_policy_live; validate_resources; verify_series; }

cmd="${1:-}"; shift || true; [[ -n "${cmd}" ]] || { usage; exit 2; }; ENVIRONMENT="$(normalize_env "${1:-}")"; configure_env "${ENVIRONMENT}"
case "${cmd}" in render) render;; install|upgrade) mutate "${cmd}";; status) status;; verify) verify;; *) usage; exit 2;; esac
