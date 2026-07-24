#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RELEASE="kube-prometheus-stack"
NAMESPACE="monitoring"
CHART="prometheus-community/kube-prometheus-stack"
VERSION_FILE="${ROOT}/platform/observability/helm/kube-prometheus-stack.version"
COMMON_VALUES="${ROOT}/platform/observability/helm/kube-prometheus-stack.values.common.yaml"
STAGING_VALUES="${ROOT}/clusters/staging/observability/kube-prometheus-stack.values.yaml"
TIMEOUT="${SUGARKUBE_OBSERVABILITY_HELM_TIMEOUT:-15m}"
GRAFANA_URL="http://sugarkube3.local:30300"

usage(){ echo "Usage: $0 render|install|upgrade|status|verify env=staging" >&2; }
normalize_env(){
  local raw="${1:-}"
  raw="${raw#env=}"
  if [ -z "$raw" ]; then
    echo "ERROR: env is required; use env=staging. Production observability is not yet codified." >&2; exit 2
  fi
  if [ "$raw" = int ]; then raw=staging; fi
  case "$raw" in
    staging) printf '%s' staging ;;
    prod|production) echo "ERROR: production observability is not yet codified; refusing env=${raw}." >&2; exit 2 ;;
    *) echo "ERROR: unsupported observability env '${raw}'. Only env=staging is implemented; production observability is not yet codified." >&2; exit 2 ;;
  esac
}
version(){ sed -e 's/#.*$//' -e '/^[[:space:]]*$/d' "$VERSION_FILE" | head -n1 | tr -d '[:space:]'; }
ensure_tools(){ command -v helm >/dev/null || { echo "ERROR: helm is required." >&2; exit 127; }; command -v kubectl >/dev/null || { echo "ERROR: kubectl is required." >&2; exit 127; }; }
setup_kubeconfig(){
  if [ -z "${KUBECONFIG:-}" ]; then export KUBECONFIG="${HOME}/.kube/config"; fi
  if [ ! -r "$KUBECONFIG" ] && [ -x "${ROOT}/scripts/ensure_user_kubeconfig.sh" ]; then "${ROOT}/scripts/ensure_user_kubeconfig.sh" || true; fi
  [ -r "$KUBECONFIG" ] || { echo "ERROR: kubeconfig is not readable at ${KUBECONFIG}. Run: just kubeconfig-env env=staging" >&2; exit 2; }
}
current_context(){ kubectl --kubeconfig "$KUBECONFIG" config current-context 2>/dev/null || echo unknown; }
assert_context(){ python3 "${ROOT}/scripts/cluster_identity.py" assert --kubeconfig "$KUBECONFIG" --env staging >/dev/null; }
summary(){
  echo "environment: staging"; echo "current context: $(current_context)"; echo "namespace: ${NAMESPACE}"; echo "release: ${RELEASE}"; echo "chart: ${CHART}"; echo "pinned version: $(version)"; echo "ordered values files:"; echo "  - ${COMMON_VALUES#${ROOT}/}"; echo "  - ${STAGING_VALUES#${ROOT}/}"; echo "Grafana LAN URL: ${GRAFANA_URL} (same NodePort is available through the other staging nodes)"
}
ensure_chart_repo(){ helm repo add prometheus-community https://prometheus-community.github.io/helm-charts --force-update >/dev/null; helm repo update prometheus-community >/dev/null; }
helm_template(){ ensure_chart_repo; helm template "$RELEASE" "$CHART" --namespace "$NAMESPACE" --version "$(version)" -f "$COMMON_VALUES" -f "$STAGING_VALUES"; }
render_to_temp(){ local out="$1"; helm_template >"$out"; }
release_exists(){ helm -n "$NAMESPACE" status "$RELEASE" >/dev/null 2>&1; }
cmd_render(){ ensure_tools; setup_kubeconfig; summary; helm_template; }
cmd_install(){ ensure_tools; setup_kubeconfig; assert_context; summary; if release_exists; then echo "ERROR: Helm release ${RELEASE} already exists in ${NAMESPACE}; use observability-upgrade for an existing release." >&2; exit 3; fi; tmp="$(mktemp -t sugarkube-observability-render.XXXXXX.yaml)"; trap 'rm -f "$tmp"' EXIT; render_to_temp "$tmp"; helm install "$RELEASE" "$CHART" --namespace "$NAMESPACE" --create-namespace --version "$(version)" -f "$COMMON_VALUES" -f "$STAGING_VALUES" --wait --timeout "$TIMEOUT"; }
cmd_upgrade(){ ensure_tools; setup_kubeconfig; assert_context; summary; if ! release_exists; then echo "ERROR: Helm release ${RELEASE} does not exist in ${NAMESPACE}; use observability-install for a fresh cluster." >&2; exit 3; fi; tmp="$(mktemp -t sugarkube-observability-render.XXXXXX.yaml)"; trap 'rm -f "$tmp"' EXIT; render_to_temp "$tmp"; helm upgrade "$RELEASE" "$CHART" --namespace "$NAMESPACE" --version "$(version)" -f "$COMMON_VALUES" -f "$STAGING_VALUES" --wait --timeout "$TIMEOUT"; }
cmd_status(){ ensure_tools; setup_kubeconfig; summary; helm -n "$NAMESPACE" status "$RELEASE" || true; kubectl -n "$NAMESPACE" get deploy,statefulset,daemonset -l 'app.kubernetes.io/instance=kube-prometheus-stack' || true; kubectl -n "$NAMESPACE" get prometheus,alertmanager || true; kubectl -n "$NAMESPACE" get svc,pvc || true; kubectl get crd prometheuses.monitoring.coreos.com alertmanagers.monitoring.coreos.com servicemonitors.monitoring.coreos.com probes.monitoring.coreos.com || true; }
ready(){ kubectl -n "$NAMESPACE" rollout status "$1" --timeout=1s >/dev/null; }
ready_node_exporters(){ [ "$(kubectl -n "$NAMESPACE" get pods -l app.kubernetes.io/name=prometheus-node-exporter -o jsonpath='{range .items[?(@.status.phase=="Running")]}{range .status.conditions[?(@.type=="Ready")]}{.status}{"\n"}{end}{end}' | grep -cx True)" = 3 ]; }
cmd_verify(){ ensure_tools; setup_kubeconfig; summary; kubectl get crd prometheuses.monitoring.coreos.com alertmanagers.monitoring.coreos.com servicemonitors.monitoring.coreos.com probes.monitoring.coreos.com >/dev/null; ready deploy/kube-prometheus-stack-operator; ready deploy/kube-prometheus-stack-grafana; ready deploy/kube-prometheus-stack-kube-state-metrics; ready statefulset/prometheus-kube-prometheus-stack-prometheus; ready statefulset/alertmanager-kube-prometheus-stack-alertmanager; ready_node_exporters; [ "$(kubectl -n "$NAMESPACE" get prometheus kube-prometheus-stack-prometheus -o jsonpath='{.spec.replicas}')" = 1 ]; [ "$(kubectl -n "$NAMESPACE" get alertmanager kube-prometheus-stack-alertmanager -o jsonpath='{.spec.replicas}')" = 1 ]; [ -z "$(kubectl -n "$NAMESPACE" get ingress -l app.kubernetes.io/name=grafana -o name)" ]; [ "$(kubectl -n "$NAMESPACE" get svc kube-prometheus-stack-grafana -o jsonpath='{.spec.type}:{.spec.ports[0].nodePort}')" = NodePort:30300 ]; kubectl -n "$NAMESPACE" get pvc -l app.kubernetes.io/name=prometheus -o jsonpath='{range .items[*]}{.status.phase}:{.spec.storageClassName}{"\n"}{end}' | grep -qx 'Bound:local-path'; kubectl -n dspace get servicemonitor -l release=kube-prometheus-stack >/dev/null; secret_name="$(kubectl -n dspace get servicemonitor -l release=kube-prometheus-stack -o jsonpath='{.items[0].spec.endpoints[0].bearerTokenSecret.name}' 2>/dev/null || true)"; [ -n "$secret_name" ] && kubectl -n dspace get secret "$secret_name" >/dev/null; echo "DSPACE ServiceMonitor references existing Secret '${secret_name}' (value not printed)."; echo "DSPACE Prometheus target health: check Prometheus /api/v1/targets via port-forward when reachable; no credentials printed."; }
cmd="${1:-}"; shift || true; envname="$(normalize_env "${1:-}")"; [ "$envname" = staging ] || exit 2
case "$cmd" in render) cmd_render;; install) cmd_install;; upgrade) cmd_upgrade;; status) cmd_status;; verify) cmd_verify;; *) usage; exit 2;; esac
