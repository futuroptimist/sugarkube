#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CHART="prometheus-community/kube-prometheus-stack"
RELEASE="kube-prometheus-stack"
NAMESPACE="monitoring"
VERSION_FILE="platform/observability/helm/kube-prometheus-stack.version"
COMMON_VALUES="platform/observability/helm/kube-prometheus-stack.values.common.yaml"
STAGING_VALUES="clusters/staging/observability/kube-prometheus-stack.values.yaml"
TIMEOUT="${SUGARKUBE_OBSERVABILITY_HELM_TIMEOUT:-15m}"
GRAFANA_URL="http://sugarkube3.local:30300"

usage() { echo "Usage: $0 render|install|upgrade|status|verify env=staging" >&2; }
normalize_env() {
  local value="${1:-}"
  while [[ "${value}" == env=* ]]; do value="${value#env=}"; done
  value="$(printf '%s' "${value}" | xargs | tr '[:upper:]' '[:lower:]')"
  [ "${value}" = "int" ] && value="staging"
  printf '%s' "${value}"
}

ACTION="${1:-}"; shift || true
ENV_ARG="${1:-${SUGARKUBE_ENV:-}}"
ENV_NAME="$(normalize_env "${ENV_ARG}")"
if [ -z "${ACTION}" ] || [ -z "${ENV_NAME}" ]; then
  usage; echo "ERROR: explicit env=staging is required; production observability is not yet codified." >&2; exit 2
fi
if [ "${ENV_NAME}" != "staging" ]; then
  echo "ERROR: unsupported env='${ENV_NAME}'. Only staging observability is codified; production observability is not yet codified." >&2
  exit 2
fi
cd "${ROOT}"
VERSION="$(sed -e 's/#.*$//' -e '/^[[:space:]]*$/d' "${VERSION_FILE}" | head -n1 | tr -d '[:space:]')"
VALUES=("${COMMON_VALUES}" "${STAGING_VALUES}")
for f in "${VALUES[@]}"; do [ -f "${f}" ] || { echo "ERROR: missing values file: ${f}" >&2; exit 2; }; done
[ "${VERSION}" = "87.19.0" ] || { echo "ERROR: expected chart version 87.19.0, got '${VERSION}' from ${VERSION_FILE}" >&2; exit 2; }

ensure_kubeconfig() {
  scripts/ensure_user_kubeconfig.sh || true
  export KUBECONFIG="${KUBECONFIG:-${HOME}/.kube/config}"
  [ -r "${KUBECONFIG}" ] || { echo "ERROR: kubeconfig is not readable at ${KUBECONFIG}. Run: just kubeconfig-env env=staging" >&2; exit 2; }
}
current_context() { kubectl config current-context 2>/dev/null || printf '<unknown>'; }
print_summary() {
  echo "environment: ${ENV_NAME}"
  echo "current context: $(current_context)"
  echo "namespace: ${NAMESPACE}"
  echo "release: ${RELEASE}"
  echo "chart: ${CHART}"
  echo "pinned version: ${VERSION}"
  echo "ordered values files: ${VALUES[*]}"
}
helm_value_args() { local f; for f in "${VALUES[@]}"; do printf '%s\0%s\0' -f "${f}"; done; }
render_chart() {
  tmp="$(mktemp -t sugarkube-observability-render.XXXXXX.yaml)"
  trap 'rm -f "${tmp:-}"' RETURN
  helm template "${RELEASE}" "${CHART}" --namespace "${NAMESPACE}" --version "${VERSION}" $(printf -- '-f %q ' "${VALUES[@]}") >"${tmp}"
  cat "${tmp}"
}
release_exists() { helm -n "${NAMESPACE}" status "${RELEASE}" >/dev/null 2>&1; }
assert_staging_context() { python3 scripts/cluster_identity.py assert --kubeconfig "${KUBECONFIG}" --env "${ENV_NAME}" >/dev/null; }

case "${ACTION}" in
  render)
    ensure_kubeconfig; print_summary; render_chart ;;
  install|upgrade)
    ensure_kubeconfig; print_summary; assert_staging_context
    echo "Rendering pinned chart before ${ACTION}; aborting without mutation if rendering fails..." >&2
    render_chart >/dev/null
    if [ "${ACTION}" = install ]; then
      if release_exists; then echo "ERROR: Helm release ${RELEASE} already exists in ${NAMESPACE}; use observability-upgrade for an existing release." >&2; exit 1; fi
      helm install "${RELEASE}" "${CHART}" --namespace "${NAMESPACE}" --create-namespace --version "${VERSION}" -f "${VALUES[0]}" -f "${VALUES[1]}" --wait --timeout "${TIMEOUT}"
    else
      if ! release_exists; then echo "ERROR: Helm release ${RELEASE} does not exist in ${NAMESPACE}; use observability-install for a fresh cluster." >&2; exit 1; fi
      helm upgrade "${RELEASE}" "${CHART}" --namespace "${NAMESPACE}" --version "${VERSION}" -f "${VALUES[0]}" -f "${VALUES[1]}" --wait --timeout "${TIMEOUT}"
    fi ;;
  status)
    ensure_kubeconfig; print_summary
    helm -n "${NAMESPACE}" status "${RELEASE}" || true
    kubectl -n "${NAMESPACE}" get deploy,statefulset,daemonset -l 'app.kubernetes.io/instance=kube-prometheus-stack' -o wide || true
    kubectl -n "${NAMESPACE}" get prometheus,alertmanager || true
    kubectl -n "${NAMESPACE}" get svc,pvc || true
    kubectl get crd prometheuses.monitoring.coreos.com alertmanagers.monitoring.coreos.com servicemonitors.monitoring.coreos.com probes.monitoring.coreos.com || true
    echo "Grafana LAN URL: ${GRAFANA_URL} (same NodePort is available through the other staging nodes)." ;;
  verify)
    ensure_kubeconfig; print_summary
    fail=0; check(){ echo "+ $*"; "$@" || fail=1; }
    check kubectl get crd prometheuses.monitoring.coreos.com alertmanagers.monitoring.coreos.com servicemonitors.monitoring.coreos.com probes.monitoring.coreos.com
    check kubectl -n "${NAMESPACE}" rollout status deploy/kube-prometheus-stack-operator --timeout=120s
    check kubectl -n "${NAMESPACE}" rollout status deploy/kube-prometheus-stack-grafana --timeout=120s
    check kubectl -n "${NAMESPACE}" rollout status statefulset/prometheus-kube-prometheus-stack-prometheus --timeout=120s
    check kubectl -n "${NAMESPACE}" rollout status statefulset/alertmanager-kube-prometheus-stack-alertmanager --timeout=120s
    check kubectl -n "${NAMESPACE}" rollout status deploy/kube-prometheus-stack-kube-state-metrics --timeout=120s
    ready_ne="$(kubectl -n "${NAMESPACE}" get pods -l app.kubernetes.io/name=prometheus-node-exporter -o jsonpath='{range .items[?(@.status.containerStatuses[0].ready==true)]}{.metadata.name}{"\n"}{end}' | wc -l | tr -d ' ')"; [ "${ready_ne}" = 3 ] || { echo "ERROR: expected exactly 3 ready node-exporter pods, got ${ready_ne}" >&2; fail=1; }
    pvc_json="$(kubectl -n "${NAMESPACE}" get pvc -l app.kubernetes.io/name=prometheus -o jsonpath='{.items[0].status.phase} {.items[0].spec.storageClassName}')"; [ "${pvc_json}" = "Bound local-path" ] || { echo "ERROR: expected Prometheus PVC to be Bound local-path; got ${pvc_json}" >&2; fail=1; }
    [ "$(kubectl -n "${NAMESPACE}" get prometheus kube-prometheus-stack-prometheus -o jsonpath='{.spec.replicas}')" = 1 ] || { echo "ERROR: Prometheus replica count is not 1" >&2; fail=1; }
    [ "$(kubectl -n "${NAMESPACE}" get alertmanager kube-prometheus-stack-alertmanager -o jsonpath='{.spec.replicas}')" = 1 ] || { echo "ERROR: Alertmanager replica count is not 1" >&2; fail=1; }
    [ -z "$(kubectl -n "${NAMESPACE}" get ingress -l app.kubernetes.io/name=grafana -o name 2>/dev/null)" ] || { echo "ERROR: Grafana Ingress exists" >&2; fail=1; }
    [ "$(kubectl -n "${NAMESPACE}" get svc kube-prometheus-stack-grafana -o jsonpath='{.spec.type} {.spec.ports[0].nodePort}')" = "NodePort 30300" ] || { echo "ERROR: Grafana service is not NodePort 30300" >&2; fail=1; }
    sm="$(kubectl get servicemonitor -A -l release=kube-prometheus-stack -o jsonpath='{range .items[?(@.metadata.name=="dspace")]}{.metadata.namespace}/{.metadata.name}{"\n"}{end}' 2>/dev/null || true)"; [ -n "${sm}" ] || { echo "ERROR: DSPACE ServiceMonitor with release=kube-prometheus-stack was not found" >&2; fail=1; }
    kubectl get secret -n dspace dspace-staging-metrics-token >/dev/null 2>&1 || { echo "ERROR: DSPACE metrics Secret reference is missing (value not printed)." >&2; fail=1; }
    echo "DSPACE Prometheus targets: inspectable through Prometheus API when Prometheus is reachable; no credentials printed."
    echo "Grafana LAN URL: ${GRAFANA_URL} (same NodePort is available through the other staging nodes)."
    exit "${fail}" ;;
  *) usage; exit 2 ;;
esac
