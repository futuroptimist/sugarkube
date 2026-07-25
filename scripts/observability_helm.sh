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
TARGET_HEALTH_ATTEMPTS="${SUGARKUBE_OBSERVABILITY_TARGET_HEALTH_ATTEMPTS:-20}"
TARGET_HEALTH_INTERVAL_SECONDS="${SUGARKUBE_OBSERVABILITY_TARGET_HEALTH_INTERVAL_SECONDS:-15}"

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
release_state() {
  local matches
  # Do not infer absence from `helm status`: transport and authorization errors
  # must remain fatal. `helm list` exits nonzero on those errors.
  if ! matches="$(helm list --namespace "${NAMESPACE}" --all --filter "^${RELEASE}$" --short)"; then
    echo "ERROR: Helm could not query release state; refusing to mutate the cluster." >&2
    return 1
  fi
  if [[ "${matches}" == "${RELEASE}" ]]; then
    printf 'present'
  elif [[ -z "${matches}" ]]; then
    printf 'absent'
  else
    echo "ERROR: unexpected Helm release query result: ${matches}" >&2
    return 1
  fi
}
verify_dspace_targets() {
  local attempts="${TARGET_HEALTH_ATTEMPTS}" interval="${TARGET_HEALTH_INTERVAL_SECONDS}"
  local attempt targets_json observation rc
  [[ "${attempts}" =~ ^[0-9]+$ && "${attempts}" -gt 0 ]] || {
    echo "ERROR: SUGARKUBE_OBSERVABILITY_TARGET_HEALTH_ATTEMPTS must be a positive integer." >&2
    return 8
  }
  [[ "${interval}" =~ ^[0-9]+$ && "${interval}" -gt 0 ]] || {
    echo "ERROR: SUGARKUBE_OBSERVABILITY_TARGET_HEALTH_INTERVAL_SECONDS must be a positive integer." >&2
    return 8
  }

  for ((attempt = 1; attempt <= attempts; attempt++)); do
    if ! targets_json="$(kubectl get --raw "/api/v1/namespaces/${NAMESPACE}/services/http:${RELEASE}-prometheus:9090/proxy/api/v1/targets?state=active" 2>/dev/null)"; then
      echo "ERROR: Prometheus targets query transport failed." >&2
      return 9
    fi
    set +e
    observation="$(python3 -c 'import json, sys
try:
    response = json.load(sys.stdin)
    if not isinstance(response, dict) or response.get("status") != "success":
        raise ValueError("Prometheus API status was not success")
    data = response.get("data")
    if not isinstance(data, dict) or not isinstance(data.get("activeTargets"), list):
        raise TypeError("required Prometheus target structure is missing")
    matches = []
    for target in data["activeTargets"]:
        if not isinstance(target, dict) or not isinstance(target.get("labels"), dict):
            raise TypeError("target labels cannot be parsed safely")
        labels = target["labels"]
        if labels.get("app") == "dspace" and labels.get("namespace") == "dspace":
            if not isinstance(target.get("health"), str):
                raise TypeError("target health cannot be parsed safely")
            matches.append(target)
    if matches and all(target["health"] == "up" for target in matches):
        raise SystemExit(0)
    safe = [{key: target.get(key) for key in ("health", "lastError", "lastScrape")}
            | {key: target["labels"].get(key) for key in ("pod", "instance")}
            for target in matches]
    print(json.dumps(safe, separators=(",", ":")))
    raise SystemExit(10)
except (json.JSONDecodeError, TypeError, ValueError) as error:
    print("ERROR: invalid Prometheus targets response: " + str(error), file=sys.stderr)
    raise SystemExit(2)' <<<"${targets_json}")"
    rc=$?
    set -e
    case "${rc}" in
      0) echo "DSPACE Prometheus targets confirmed healthy without printing Secret values."; return 0 ;;
      10)
        if (( attempt < attempts )); then
          echo "DSPACE Prometheus targets not yet healthy (attempt ${attempt}/${attempts}); retrying." >&2
          sleep "${interval}"
        else
          echo "ERROR: DSPACE Prometheus targets did not become healthy after ${attempts} attempts." >&2
          echo "Safe target diagnostics: ${observation}" >&2
          return 10
        fi
        ;;
      *) return "${rc}" ;;
    esac
  done
}
render() { require_tools helm kubectl; print_resolved staging; tmp="$(mktemp -t sugarkube-observability-render.XXXXXX.yaml)"; trap 'rm -f "${tmp}"' EXIT; render_to "${tmp}"; cat "${tmp}"; }
install_release() { require_tools helm kubectl python3; print_resolved staging; assert_context; tmp="$(mktemp -t sugarkube-observability-install.XXXXXX.yaml)"; trap 'rm -f "${tmp}"' EXIT; render_to "${tmp}"; state="$(release_state)"; if [[ "${state}" == present ]]; then echo "ERROR: cannot install: ${RELEASE} already exists in ${NAMESPACE}. Use observability-upgrade." >&2; exit 4; fi; helm install "${RELEASE}" "${CHART}" --namespace "${NAMESPACE}" --create-namespace --version "$(version)" -f "${COMMON_VALUES}" -f "${STAGING_VALUES}" --wait --timeout "${TIMEOUT}"; }
upgrade_release() { require_tools helm kubectl python3; print_resolved staging; assert_context; tmp="$(mktemp -t sugarkube-observability-upgrade.XXXXXX.yaml)"; trap 'rm -f "${tmp}"' EXIT; render_to "${tmp}"; state="$(release_state)"; if [[ "${state}" == absent ]]; then echo "ERROR: upgrade requires an existing Helm release ${RELEASE} in ${NAMESPACE}. Use observability-install for a fresh cluster." >&2; exit 5; fi; helm upgrade "${RELEASE}" "${CHART}" --namespace "${NAMESPACE}" --version "$(version)" -f "${COMMON_VALUES}" -f "${STAGING_VALUES}" --wait --timeout "${TIMEOUT}"; }
status() { require_tools helm kubectl python3; print_resolved staging; assert_context; helm -n "${NAMESPACE}" status "${RELEASE}"; kubectl -n "${NAMESPACE}" get deploy,statefulset,daemonset -l "app.kubernetes.io/instance=${RELEASE}"; kubectl -n "${NAMESPACE}" get prometheus,alertmanager; kubectl -n "${NAMESPACE}" get svc,pvc; kubectl get crd prometheuses.monitoring.coreos.com alertmanagers.monitoring.coreos.com servicemonitors.monitoring.coreos.com probes.monitoring.coreos.com; }
verify() {
  require_tools kubectl python3
  print_resolved staging
  assert_context
  kubectl get crd prometheuses.monitoring.coreos.com alertmanagers.monitoring.coreos.com servicemonitors.monitoring.coreos.com probes.monitoring.coreos.com >/dev/null
  for workload in \
    deploy/kube-prometheus-stack-operator \
    deploy/kube-prometheus-stack-grafana \
    deploy/kube-prometheus-stack-kube-state-metrics \
    statefulset/prometheus-kube-prometheus-stack-prometheus \
    statefulset/alertmanager-kube-prometheus-stack-alertmanager; do
    kubectl -n "${NAMESPACE}" rollout status "${workload}" --timeout="${TIMEOUT}"
  done

  read -r desired_ne ready_ne < <(kubectl -n "${NAMESPACE}" get daemonset kube-prometheus-stack-prometheus-node-exporter -o jsonpath='{.status.desiredNumberScheduled}{" "}{.status.numberReady}{"\n"}')
  [[ "${desired_ne}" == 3 && "${ready_ne}" == 3 ]] || {
    echo "ERROR: node-exporter daemonset has ${ready_ne:-0}/${desired_ne:-0} ready pods." >&2
    exit 6
  }
  kubectl -n "${NAMESPACE}" get pvc -o json | python3 -c 'import json, sys
items = json.load(sys.stdin).get("items", [])
claims = [item for item in items if item.get("metadata", {}).get("labels", {}).get("app.kubernetes.io/name") == "prometheus"]
if len(claims) != 1 or claims[0].get("status", {}).get("phase") != "Bound" or claims[0].get("spec", {}).get("storageClassName") != "local-path":
    raise SystemExit("ERROR: expected one Bound local-path Prometheus PVC.")'
  [[ "$(kubectl -n "${NAMESPACE}" get prometheus kube-prometheus-stack-prometheus -o jsonpath='{.spec.replicas}')" == 1 ]]
  [[ "$(kubectl -n "${NAMESPACE}" get alertmanager kube-prometheus-stack-alertmanager -o jsonpath='{.spec.replicas}')" == 1 ]]
  [[ -z "$(kubectl -n "${NAMESPACE}" get ingress -l app.kubernetes.io/name=grafana -o name 2>/dev/null)" ]]
  [[ "$(kubectl -n "${NAMESPACE}" get svc kube-prometheus-stack-grafana -o jsonpath='{.spec.ports[?(@.port==80)].nodePort}')" == 30300 ]]
  monitor_release="$(kubectl -n dspace get servicemonitor dspace -o jsonpath='{.metadata.labels.release}')"
  [[ "${monitor_release}" == "${RELEASE}" ]] || { echo "ERROR: dspace ServiceMonitor must have release: ${RELEASE}." >&2; exit 7; }
  secret_name="$(kubectl -n dspace get servicemonitor dspace -o jsonpath='{.spec.endpoints[0].bearerTokenSecret.name}')"
  [[ -n "${secret_name}" ]] || { echo "ERROR: dspace ServiceMonitor has no bearerTokenSecret.name." >&2; exit 7; }
  kubectl -n dspace get secret "${secret_name}" -o name >/dev/null
  echo "DSPACE ServiceMonitor secret reference exists (value intentionally not printed)."

  verify_dspace_targets
  echo "Grafana LAN URL: ${GRAFANA_URL} (same NodePort is available through the other staging nodes)"
}

cmd="${1:-}"; shift || true; [[ -n "${cmd}" ]] || { usage; exit 2; }
env_arg="${1:-}"; normalize_env "${env_arg}" >/dev/null
case "${cmd}" in render) render ;; install) install_release ;; upgrade) upgrade_release ;; status) status ;; verify) verify ;; *) usage; exit 2 ;; esac
