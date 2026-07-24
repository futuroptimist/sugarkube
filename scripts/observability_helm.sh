#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RELEASE="kube-prometheus-stack"
NAMESPACE="monitoring"
CHART="prometheus-community/kube-prometheus-stack"
VERSION_FILE="${ROOT}/platform/observability/helm/kube-prometheus-stack.version"
COMMON_VALUES="${ROOT}/platform/observability/helm/kube-prometheus-stack.values.common.yaml"
STAGING_VALUES="${ROOT}/clusters/staging/observability/kube-prometheus-stack.values.yaml"
TIMEOUT="${SUGARKUBE_OBSERVABILITY_HELM_TIMEOUT:-20m}"
GRAFANA_URL="http://sugarkube3.local:30300"

usage() { echo "Usage: $0 <render|install|upgrade|status|verify> env=staging" >&2; }
normalize_env() {
  local raw="${1:-}"
  while [[ "${raw}" == env=* ]]; do raw="${raw#env=}"; done
  case "${raw}" in
    int) echo "WARNING: env name 'int' is deprecated; using env=staging." >&2; printf staging ;;
    staging) printf staging ;;
    ""|prod|production) echo "ERROR: production observability is not yet codified; pass env=staging explicitly." >&2; exit 2 ;;
    *) echo "ERROR: unsupported observability env '${raw}'. Production observability is not yet codified; supported env: staging." >&2; exit 2 ;;
  esac
}
require_tools() { for t in "$@"; do command -v "$t" >/dev/null 2>&1 || { echo "ERROR: required tool missing: $t" >&2; exit 127; }; done; }
current_context() { kubectl config current-context 2>/dev/null || true; }
print_resolved() {
  local env="$1" ctx; ctx="$(current_context)"
  cat <<EOT
observability environment: ${env}
current Kubernetes context: ${ctx:-<unknown>}
namespace: ${NAMESPACE}
release: ${RELEASE}
chart: ${CHART}
pinned version: $(cat "${VERSION_FILE}")
ordered values files:
  - ${COMMON_VALUES}
  - ${STAGING_VALUES}
Grafana LAN URL: ${GRAFANA_URL} (same NodePort is available through the other staging nodes)
EOT
}
assert_context() {
  local ctx; ctx="$(current_context)"
  if [[ "${ctx}" != "sugar-staging" ]]; then
    echo "ERROR: context mismatch for staging observability: expected 'sugar-staging', got '${ctx:-<none>}' before mutation." >&2
    echo "Run: just kubeconfig-env env=staging" >&2
    exit 3
  fi
  python3 "${ROOT}/scripts/cluster_identity.py" assert --kubeconfig "${KUBECONFIG:-${HOME}/.kube/config}" --env staging >/dev/null
}
version() { tr -d '[:space:]' < "${VERSION_FILE}"; }
render_to() {
  local out="$1"
  helm repo add prometheus-community https://prometheus-community.github.io/helm-charts --force-update >/dev/null
  helm repo update prometheus-community >/dev/null
  helm template "${RELEASE}" "${CHART}" --namespace "${NAMESPACE}" --version "$(version)" -f "${COMMON_VALUES}" -f "${STAGING_VALUES}" >"${out}"
}
release_exists() { helm -n "${NAMESPACE}" status "${RELEASE}" >/dev/null 2>&1; }
render() { require_tools helm kubectl; print_resolved staging; tmp="$(mktemp -t sugarkube-observability-render.XXXXXX.yaml)"; trap 'rm -f "${tmp}"' EXIT; render_to "${tmp}"; cat "${tmp}"; }
install_release() { require_tools helm kubectl python3; print_resolved staging; assert_context; tmp="$(mktemp -t sugarkube-observability-install.XXXXXX.yaml)"; trap 'rm -f "${tmp}"' EXIT; render_to "${tmp}"; if release_exists; then echo "ERROR: install requires missing release; ${RELEASE} already exists in ${NAMESPACE}. Use observability-upgrade." >&2; exit 4; fi; helm install "${RELEASE}" "${CHART}" --namespace "${NAMESPACE}" --create-namespace --version "$(version)" -f "${COMMON_VALUES}" -f "${STAGING_VALUES}" --wait --timeout "${TIMEOUT}"; }
upgrade_release() { require_tools helm kubectl python3; print_resolved staging; assert_context; tmp="$(mktemp -t sugarkube-observability-upgrade.XXXXXX.yaml)"; trap 'rm -f "${tmp}"' EXIT; render_to "${tmp}"; if ! release_exists; then echo "ERROR: upgrade requires an existing Helm release ${RELEASE} in ${NAMESPACE}. Use observability-install for a fresh cluster." >&2; exit 5; fi; helm upgrade "${RELEASE}" "${CHART}" --namespace "${NAMESPACE}" --version "$(version)" -f "${COMMON_VALUES}" -f "${STAGING_VALUES}" --wait --timeout "${TIMEOUT}"; }
status() { require_tools helm kubectl; print_resolved staging; helm -n "${NAMESPACE}" status "${RELEASE}" || true; kubectl -n "${NAMESPACE}" get deploy,statefulset,daemonset -l "app.kubernetes.io/instance=${RELEASE}"; kubectl -n "${NAMESPACE}" get prometheus,alertmanager; kubectl -n "${NAMESPACE}" get svc,pvc; kubectl get crd prometheuses.monitoring.coreos.com alertmanagers.monitoring.coreos.com servicemonitors.monitoring.coreos.com probes.monitoring.coreos.com; }
verify() { require_tools kubectl; print_resolved staging; kubectl get crd prometheuses.monitoring.coreos.com alertmanagers.monitoring.coreos.com servicemonitors.monitoring.coreos.com probes.monitoring.coreos.com >/dev/null; kubectl -n "${NAMESPACE}" rollout status deploy/kube-prometheus-stack-operator --timeout=5s; kubectl -n "${NAMESPACE}" rollout status deploy/kube-prometheus-stack-grafana --timeout=5s; kubectl -n "${NAMESPACE}" rollout status deploy/kube-prometheus-stack-kube-state-metrics --timeout=5s; kubectl -n "${NAMESPACE}" rollout status statefulset/prometheus-kube-prometheus-stack-prometheus --timeout=5s; kubectl -n "${NAMESPACE}" rollout status statefulset/alertmanager-kube-prometheus-stack-alertmanager --timeout=5s; ready_ne="$(kubectl -n "${NAMESPACE}" get pods -l app.kubernetes.io/name=prometheus-node-exporter -o jsonpath='{range .items[*]}{.status.containerStatuses[0].ready}{"\n"}{end}' | awk '$1=="true"{c++} END{print c+0}')"; [[ "${ready_ne}" == 3 ]] || { echo "ERROR: expected exactly 3 ready node-exporter pods, got ${ready_ne}." >&2; exit 6; }; kubectl -n "${NAMESPACE}" get pvc -o jsonpath='{range .items[?(@.metadata.name=="prometheus-kube-prometheus-stack-prometheus-db-prometheus-kube-prometheus-stack-prometheus-0")]}{.status.phase}{" "}{.spec.storageClassName}{"\n"}{end}' | grep -qx 'Bound local-path'; [[ "$(kubectl -n "${NAMESPACE}" get prometheus kube-prometheus-stack-prometheus -o jsonpath='{.spec.replicas}')" == 1 ]]; [[ "$(kubectl -n "${NAMESPACE}" get alertmanager kube-prometheus-stack-alertmanager -o jsonpath='{.spec.replicas}')" == 1 ]]; [[ -z "$(kubectl -n "${NAMESPACE}" get ingress -l app.kubernetes.io/name=grafana -o name 2>/dev/null)" ]]; [[ "$(kubectl -n "${NAMESPACE}" get svc kube-prometheus-stack-grafana -o jsonpath='{.spec.ports[?(@.port==80)].nodePort}')" == 30300 ]]; kubectl -n dspace get servicemonitor -l release=kube-prometheus-stack >/dev/null; secret_name="$(kubectl -n dspace get servicemonitor -l release=kube-prometheus-stack -o jsonpath='{.items[0].spec.endpoints[0].bearerTokenSecret.name}')"; [[ -n "${secret_name}" ]]; kubectl -n dspace get secret "${secret_name}" >/dev/null; echo "DSPACE ServiceMonitor secret reference exists (value intentionally not printed)."; if kubectl -n "${NAMESPACE}" get svc kube-prometheus-stack-prometheus >/dev/null 2>&1; then targets_json="$(kubectl -n "${NAMESPACE}" exec statefulset/prometheus-kube-prometheus-stack-prometheus -- wget -qO- "http://127.0.0.1:9090/api/v1/targets?state=active" 2>/dev/null || true)"; if [[ -n "${targets_json}" ]]; then grep -q "dspace" <<<"${targets_json}" && grep -q '"health":"up"' <<<"${targets_json}" || { echo "ERROR: Prometheus was reachable but healthy DSPACE targets were not confirmed." >&2; exit 7; }; echo "DSPACE Prometheus targets confirmed healthy without printing Secret values."; else echo "WARNING: Prometheus service exists but the local read-only targets query was not reachable; skipping DSPACE target health confirmation." >&2; fi; fi; echo "Grafana LAN URL: ${GRAFANA_URL} (same NodePort is available through the other staging nodes)"; }

cmd="${1:-}"; shift || true; [[ -n "${cmd}" ]] || { usage; exit 2; }
env_arg="${1:-}"; env_name="$(normalize_env "${env_arg}")"
case "${cmd}" in render) render ;; install) install_release ;; upgrade) upgrade_release ;; status) status ;; verify) verify ;; *) usage; exit 2 ;; esac
