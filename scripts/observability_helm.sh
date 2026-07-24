#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RELEASE="kube-prometheus-stack"
NAMESPACE="monitoring"
CHART="prometheus-community/kube-prometheus-stack"
VERSION_FILE="${ROOT_DIR}/platform/observability/helm/kube-prometheus-stack.version"
COMMON_VALUES="${ROOT_DIR}/platform/observability/helm/kube-prometheus-stack.values.common.yaml"
STAGING_VALUES="${ROOT_DIR}/clusters/staging/observability/kube-prometheus-stack.values.yaml"
TIMEOUT="20m"
LAN_URL="http://sugarkube3.local:30300"

usage() { echo "Usage: $0 render|install|upgrade|status|verify env=staging" >&2; }
normalize_env() {
  local raw="${1-}"; raw="${raw#env=}"
  case "$raw" in
    int) echo "WARNING: env name 'int' is deprecated; using env=staging." >&2; echo staging ;;
    staging) echo staging ;;
    "") echo "ERROR: env is required. Use env=staging. Production observability is not yet codified." >&2; return 2 ;;
    prod|production) echo "ERROR: production observability is not yet codified; refusing env=${raw}." >&2; return 2 ;;
    *) echo "ERROR: unsupported observability env '${raw}'. Currently only staging is codified; production observability is not yet codified." >&2; return 2 ;;
  esac
}
require_helm() { command -v helm >/dev/null || { echo "ERROR: helm is required." >&2; exit 1; }; }
require_kubectl() { command -v kubectl >/dev/null || { echo "ERROR: kubectl is required." >&2; exit 1; }; }
require_tools() { require_helm; require_kubectl; }
current_context() { kubectl config current-context 2>/dev/null || echo unknown; }
version() { sed -n '/^[[:space:]]*#/d; /^[[:space:]]*$/d; 1p' "$VERSION_FILE"; }
print_summary() {
  echo "environment: ${ENV_NAME}"
  echo "current context: $(current_context)"
  echo "namespace: ${NAMESPACE}"
  echo "release: ${RELEASE}"
  echo "chart: ${CHART}"
  echo "pinned version: $(version)"
  echo "ordered values files:"
  echo "  - ${COMMON_VALUES#${ROOT_DIR}/}"
  echo "  - ${STAGING_VALUES#${ROOT_DIR}/}"
}
assert_context() {
  local ctx; ctx="$(current_context)"
  if [ "$ctx" != "sugar-staging" ]; then
    echo "ERROR: expected Kubernetes context sugar-staging for staging observability, got '${ctx}'. Run just kubeconfig-env env=staging or set KUBECONFIG correctly." >&2
    exit 1
  fi
  python3 "${ROOT_DIR}/scripts/cluster_identity.py" assert --kubeconfig "${KUBECONFIG:-${HOME}/.kube/config}" --env staging >/dev/null
}
render_to() {
  local out="$1"
  helm template "$RELEASE" "$CHART" --namespace "$NAMESPACE" --create-namespace --version "$(version)" -f "$COMMON_VALUES" -f "$STAGING_VALUES" >"$out"
}
release_exists() { helm status "$RELEASE" --namespace "$NAMESPACE" >/dev/null 2>&1; }
read_only_header() { print_summary; echo "Grafana LAN URL: ${LAN_URL} (same NodePort is available through the other staging nodes)."; }

ACTION="${1-}"; ENV_ARG="${2-}"
[ -n "$ACTION" ] || { usage; exit 2; }
ENV_NAME="$(normalize_env "$ENV_ARG")" || exit $?
cd "$ROOT_DIR"
if [ "$ACTION" = render ]; then
  require_helm
else
  require_tools
fi
print_summary
case "$ACTION" in
  render)
    tmp="$(mktemp -t sugarkube-observability-render.XXXXXX.yaml)"; trap 'rm -f "$tmp"' EXIT
    render_to "$tmp"
    cat "$tmp"
    ;;
  install|upgrade)
    assert_context
    tmp="$(mktemp -t sugarkube-observability-render.XXXXXX.yaml)"; trap 'rm -f "$tmp"' EXIT
    echo "Rendering pinned chart before ${ACTION}..." >&2
    render_to "$tmp"
    if [ "$ACTION" = install ]; then
      if release_exists; then echo "ERROR: install requires release '${RELEASE}' to be absent in namespace '${NAMESPACE}'; use observability-upgrade for an existing release." >&2; exit 1; fi
      helm install "$RELEASE" "$CHART" --namespace "$NAMESPACE" --create-namespace --version "$(version)" -f "$COMMON_VALUES" -f "$STAGING_VALUES" --wait --timeout "$TIMEOUT"
    else
      if ! release_exists; then echo "ERROR: upgrade requires existing release '${RELEASE}' in namespace '${NAMESPACE}'; use observability-install for a fresh cluster." >&2; exit 1; fi
      helm upgrade "$RELEASE" "$CHART" --namespace "$NAMESPACE" --version "$(version)" -f "$COMMON_VALUES" -f "$STAGING_VALUES" --wait --timeout "$TIMEOUT"
    fi
    ;;
  status)
    read_only_header
    helm status "$RELEASE" --namespace "$NAMESPACE" || true
    kubectl -n "$NAMESPACE" get deploy,statefulset,daemonset,pods -l "release=${RELEASE}" -o wide || true
    kubectl -n "$NAMESPACE" get prometheus,alertmanager,svc,pvc || true
    kubectl get crd prometheuses.monitoring.coreos.com alertmanagers.monitoring.coreos.com servicemonitors.monitoring.coreos.com probes.monitoring.coreos.com || true
    ;;
  verify)
    read_only_header
    kubectl get crd prometheuses.monitoring.coreos.com alertmanagers.monitoring.coreos.com servicemonitors.monitoring.coreos.com probes.monitoring.coreos.com >/dev/null
    kubectl -n "$NAMESPACE" wait --for=condition=available deploy/kube-prometheus-stack-operator deploy/kube-prometheus-stack-grafana deploy/kube-prometheus-stack-kube-state-metrics --timeout=5s
    kubectl -n "$NAMESPACE" rollout status daemonset/kube-prometheus-stack-prometheus-node-exporter --timeout=5s
    [ "$(kubectl -n "$NAMESPACE" get pods -l app.kubernetes.io/name=prometheus-node-exporter -o jsonpath='{range .items[?(@.status.phase=="Running")]}{.metadata.name}{"\n"}{end}' | sed '/^$/d' | wc -l | tr -d ' ')" = 3 ]
    kubectl -n "$NAMESPACE" get pvc -o jsonpath='{range .items[?(@.metadata.name=="prometheus-kube-prometheus-stack-prometheus-db-prometheus-kube-prometheus-stack-prometheus-0")]}{.status.phase}{" "}{.spec.storageClassName}{"\n"}{end}' | grep -qx 'Bound local-path'
    [ "$(kubectl -n "$NAMESPACE" get prometheus kube-prometheus-stack-prometheus -o jsonpath='{.spec.replicas}')" = 1 ]
    [ "$(kubectl -n "$NAMESPACE" get alertmanager kube-prometheus-stack-alertmanager -o jsonpath='{.spec.replicas}')" = 1 ]
    ! kubectl -n "$NAMESPACE" get ingress kube-prometheus-stack-grafana >/dev/null 2>&1
    [ "$(kubectl -n "$NAMESPACE" get svc kube-prometheus-stack-grafana -o jsonpath='{.spec.type} {.spec.ports[0].nodePort}')" = 'NodePort 30300' ]
    kubectl -n dspace get servicemonitor -l release=kube-prometheus-stack >/dev/null
    secret_name="$(kubectl -n dspace get servicemonitor -l release=kube-prometheus-stack -o jsonpath='{.items[0].spec.endpoints[0].bearerTokenSecret.name}')"
    [ -n "$secret_name" ] && kubectl -n dspace get secret "$secret_name" >/dev/null
    echo "DSPACE ServiceMonitor references existing Secret '${secret_name}' (value not printed)."
    if kubectl -n "$NAMESPACE" get svc prometheus-operated >/dev/null 2>&1; then
      echo "Prometheus is reachable in-cluster; inspect /api/v1/targets via a local port-forward if operator policy permits."
    fi
    ;;
  *) usage; exit 2 ;;
esac
