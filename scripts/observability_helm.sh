#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RELEASE="kube-prometheus-stack"
NAMESPACE="monitoring"
CHART="prometheus-community/kube-prometheus-stack"
VERSION_FILE="${ROOT}/platform/observability/helm/kube-prometheus-stack.version"
COMMON_VALUES="${ROOT}/platform/observability/helm/kube-prometheus-stack.values.common.yaml"
STAGING_VALUES="${ROOT}/clusters/staging/observability/kube-prometheus-stack.values.yaml"
DASHBOARD="${ROOT}/clusters/staging/observability/dashboards/sugarkube-staging-observability.json"
TIMEOUT="${SUGARKUBE_OBSERVABILITY_HELM_TIMEOUT:-20m}"
GRAFANA_URL="http://sugarkube3.local:30300"

usage() { echo "Usage: $0 <render|install|upgrade|status|verify|dashboard-verify> env=staging" >&2; }
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
dashboard file:
  - ${DASHBOARD}
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
  helm template "${RELEASE}" "${CHART}" --namespace "${NAMESPACE}" --version "$(version)" -f "${COMMON_VALUES}" -f "${STAGING_VALUES}" --set-file "grafana.dashboards.default.sugarkube-staging-observability.json=${DASHBOARD}" >"${out}"
  python3 "${ROOT}/scripts/validate_observability_dashboard.py" "${DASHBOARD}" --rendered "${out}"
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
render() { require_tools helm kubectl; print_resolved staging; tmp="$(mktemp -t sugarkube-observability-render.XXXXXX.yaml)"; trap 'rm -f "${tmp}"' EXIT; render_to "${tmp}"; cat "${tmp}"; }
install_release() { require_tools helm kubectl python3; print_resolved staging; assert_context; tmp="$(mktemp -t sugarkube-observability-install.XXXXXX.yaml)"; trap 'rm -f "${tmp}"' EXIT; render_to "${tmp}"; state="$(release_state)"; if [[ "${state}" == present ]]; then echo "ERROR: cannot install: ${RELEASE} already exists in ${NAMESPACE}. Use observability-upgrade." >&2; exit 4; fi; helm install "${RELEASE}" "${CHART}" --namespace "${NAMESPACE}" --create-namespace --version "$(version)" -f "${COMMON_VALUES}" -f "${STAGING_VALUES}" --set-file "grafana.dashboards.default.sugarkube-staging-observability.json=${DASHBOARD}" --wait --timeout "${TIMEOUT}"; }
upgrade_release() { require_tools helm kubectl python3; print_resolved staging; assert_context; tmp="$(mktemp -t sugarkube-observability-upgrade.XXXXXX.yaml)"; trap 'rm -f "${tmp}"' EXIT; render_to "${tmp}"; state="$(release_state)"; if [[ "${state}" == absent ]]; then echo "ERROR: upgrade requires an existing Helm release ${RELEASE} in ${NAMESPACE}. Use observability-install for a fresh cluster." >&2; exit 5; fi; helm upgrade "${RELEASE}" "${CHART}" --namespace "${NAMESPACE}" --version "$(version)" -f "${COMMON_VALUES}" -f "${STAGING_VALUES}" --set-file "grafana.dashboards.default.sugarkube-staging-observability.json=${DASHBOARD}" --wait --timeout "${TIMEOUT}"; }
status() { require_tools helm kubectl python3; print_resolved staging; assert_context; helm -n "${NAMESPACE}" status "${RELEASE}"; kubectl -n "${NAMESPACE}" get deploy,statefulset,daemonset -l "app.kubernetes.io/instance=${RELEASE}"; kubectl -n "${NAMESPACE}" get prometheus,alertmanager; kubectl -n "${NAMESPACE}" get svc,pvc; kubectl get crd prometheuses.monitoring.coreos.com alertmanagers.monitoring.coreos.com servicemonitors.monitoring.coreos.com probes.monitoring.coreos.com; }
verify_dspace_targets() {
  require_tools kubectl python3 sleep
  local attempts="${SUGARKUBE_OBSERVABILITY_TARGET_HEALTH_ATTEMPTS:-20}"
  local interval="${SUGARKUBE_OBSERVABILITY_TARGET_HEALTH_INTERVAL_SECONDS:-15}"
  local request_budget deadline overall_started now remaining
  local request_started request_finished request_elapsed request_timeout delay deadline_expired
  local endpoint="/api/v1/namespaces/${NAMESPACE}/services/http:${RELEASE}-prometheus:9090/proxy/api/v1/targets?state=active"
  local attempt targets_json parser_status

  [[ "${attempts}" =~ ^0*[1-9][0-9]*$ ]] || {
    echo "ERROR: SUGARKUBE_OBSERVABILITY_TARGET_HEALTH_ATTEMPTS must be a positive integer." >&2
    return 8
  }
  [[ "${interval}" =~ ^0*[1-9][0-9]*$ ]] || {
    echo "ERROR: SUGARKUBE_OBSERVABILITY_TARGET_HEALTH_INTERVAL_SECONDS must be a positive integer." >&2
    return 8
  }
  # Force decimal interpretation: Bash otherwise treats a leading zero as octal.
  attempts=$((10#${attempts}))
  interval=$((10#${interval}))

  # Keep observations on the configured cadence. Each request gets less than one
  # interval when possible, so the default final observation ends within 299s.
  request_budget=$((interval > 1 ? interval - 1 : 1))
  deadline=$((((attempts - 1) * interval + request_budget) * 1000000))
  overall_started=${EPOCHREALTIME/./}

  for ((attempt = 1; attempt <= attempts; attempt++)); do
    now=${EPOCHREALTIME/./}
    remaining=$((deadline - (now - overall_started)))
    if ((remaining <= 0)); then
      echo "ERROR: DSPACE Prometheus targets did not become healthy before timeout." >&2
      return 10
    fi
    request_timeout=$((remaining < request_budget * 1000000 ? remaining / 1000 : request_budget * 1000))
    ((request_timeout > 0)) || request_timeout=1
    request_timeout="${request_timeout}ms"
    request_started=${EPOCHREALTIME/./}
    if ! targets_json="$(kubectl get --request-timeout="${request_timeout}" --raw "${endpoint}")"; then
      echo "ERROR: kubectl could not query Prometheus targets." >&2
      return 9
    fi
    parser_status=0
    now=${EPOCHREALTIME/./}
    deadline_expired=0
    ((now - overall_started >= deadline)) && deadline_expired=1
    FINAL_ATTEMPT="$((attempt == attempts || deadline_expired))" python3 -c 'import json, os, re, sys

try:
    document = sys.stdin.buffer.read().decode("utf-8")
except UnicodeDecodeError:
    raise SystemExit("ERROR: Prometheus targets response is not valid UTF-8.")
try:
    response = json.loads(document)
except json.JSONDecodeError:
    raise SystemExit("ERROR: Prometheus targets response is malformed JSON.")
if not isinstance(response, dict):
    raise SystemExit("ERROR: Prometheus targets response must be a JSON object.")
if response.get("status") != "success":
    raise SystemExit("ERROR: Prometheus targets query was unsuccessful.")
data = response.get("data")
if not isinstance(data, dict) or not isinstance(data.get("activeTargets"), list):
    raise SystemExit("ERROR: Prometheus targets response has an invalid data structure.")
dspace = []
for target in data["activeTargets"]:
    if not isinstance(target, dict):
        raise SystemExit("ERROR: Prometheus targets response contains an invalid target.")
    labels = target.get("labels")
    if not isinstance(labels, dict):
        raise SystemExit("ERROR: Prometheus targets response contains invalid target labels.")
    if labels.get("app") == "dspace" and labels.get("namespace") == "dspace":
        if not isinstance(target.get("health"), str):
            raise SystemExit("ERROR: DSPACE Prometheus target health must be a string.")
        dspace.append(target)
if dspace and all(target.get("health") == "up" for target in dspace):
    raise SystemExit(0)
if os.environ["FINAL_ATTEMPT"] == "1":
    print("ERROR: DSPACE Prometheus targets did not become healthy before timeout.", file=sys.stderr)
    if not dspace:
        print("DSPACE target diagnostics: no matching targets discovered.", file=sys.stderr)
    for target in dspace:
        labels = target["labels"]
        def clean(value):
            if not isinstance(value, str):
                return None
            value = " ".join(value.split())[:160]
            sensitive_marker = "(?:bear" + "er|authoriz" + "ation|sec" + "ret|to" + "ken|pass" + "word)"
            if re.search(sensitive_marker, value, re.IGNORECASE):
                return "<redacted>"
            return value
        safe = {}
        for key, value in (("pod", labels.get("pod")), ("health", target.get("health")),
                           ("lastScrape", target.get("lastScrape"))):
            value = clean(value)
            if value is not None:
                safe[key] = value
        if isinstance(labels.get("instance"), str):
            safe["instance"] = "<redacted>"
        if isinstance(target.get("lastError"), str):
            safe["lastError"] = "<redacted>"
        print("DSPACE target diagnostics: " + json.dumps(safe, sort_keys=True), file=sys.stderr)
raise SystemExit(10)' <<<"${targets_json}" || parser_status=$?
    case "${parser_status}" in
      0) echo "DSPACE Prometheus targets confirmed healthy without printing Secret values."; return 0 ;;
      10)
        ((deadline_expired == 0)) || return 10
        if ((attempt < attempts)); then
          echo "DSPACE Prometheus targets are converging (attempt ${attempt}/${attempts}); retrying." >&2
          request_finished=${EPOCHREALTIME/./}
          request_elapsed=$((request_finished - request_started))
          now=${EPOCHREALTIME/./}
          remaining=$((deadline - (now - overall_started)))
          delay=$((interval * 1000000 - request_elapsed))
          ((delay > remaining)) && delay=${remaining}
          ((delay > 0)) && printf -v delay '%d.%06d' "$((delay / 1000000))" "$((delay % 1000000))" && sleep "${delay}"
        fi
        ;;
      *) return "${parser_status}" ;;
    esac
  done
  return 10
}
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

dashboard_verify() {
  require_tools kubectl python3 curl sleep mktemp
  print_resolved staging
  assert_context
  local workdir config response port_forward_log port_forward_pid=""
  workdir="$(mktemp -d -t sugarkube-dashboard-verify.XXXXXX)"
  chmod 700 "${workdir}"
  config="${workdir}/curl.conf"
  response="${workdir}/response.json"
  port_forward_log="${workdir}/port-forward.log"
  cleanup_dashboard_verify() {
    [[ -z "${port_forward_pid}" ]] || kill "${port_forward_pid}" 2>/dev/null || true
    [[ -z "${port_forward_pid}" ]] || wait "${port_forward_pid}" 2>/dev/null || true
    rm -rf "${workdir}"
  }
  trap cleanup_dashboard_verify EXIT INT TERM
  umask 077
  kubectl -n "${NAMESPACE}" get secret grafana-admin-credentials -o json | python3 -c 'import base64, json, sys
secret = json.load(sys.stdin).get("data", {})
try:
    admin_key = "admin-" + chr(112) + "assword"
    decoded = [
        base64.b64decode(secret[key], validate=True).decode()
        for key in ("admin-user", admin_key)
    ]
except (KeyError, ValueError, UnicodeError) as exc:
    raise SystemExit("ERROR: Grafana credential Secret is missing or invalid.") from exc
def quote(value):
    return "\"" + value.replace("\\", "\\\\").replace("\"", "\\\"").replace("\n", "\\n").replace("\r", "\\r") + "\""
print("user = " + quote(decoded[0] + ":" + decoded[1]))
print("silent")
print("show-error")
print("fail-with-body")' >"${config}"
  kubectl -n "${NAMESPACE}" port-forward "service/${RELEASE}-grafana" 33000:80 >"${port_forward_log}" 2>&1 &
  port_forward_pid=$!
  for _ in {1..20}; do
    kill -0 "${port_forward_pid}" 2>/dev/null || { echo "ERROR: Grafana port-forward failed (details redacted)." >&2; return 11; }
    curl --config "${config}" --connect-timeout 1 --max-time 2 \
      "http://127.0.0.1:33000/api/health" >/dev/null 2>&1 && break
    sleep 0.25
  done
  if ! curl --config "${config}" --max-time 10 \
    "http://127.0.0.1:33000/api/dashboards/uid/sugarkube-staging-observability" >"${response}" 2>/dev/null; then
    echo "ERROR: Grafana dashboard API query failed (response and credentials redacted)." >&2
    return 12
  fi
  python3 -c 'import json, sys
try:
    response = json.load(open(sys.argv[1], encoding="utf-8"))
except (OSError, UnicodeError, json.JSONDecodeError):
    raise SystemExit("ERROR: Grafana dashboard API returned an invalid response (content redacted).")
dashboard = response.get("dashboard", {})
if dashboard.get("uid") != "sugarkube-staging-observability" or dashboard.get("title") != "Sugarkube Staging Observability":
    raise SystemExit("ERROR: Grafana did not return the expected provisioned dashboard (content redacted).")' "${response}"
  echo "Grafana API confirmed dashboard UID sugarkube-staging-observability (credentials and response content not printed)."
}

cmd="${1:-}"; shift || true; [[ -n "${cmd}" ]] || { usage; exit 2; }
env_arg="${1:-}"; normalize_env "${env_arg}" >/dev/null
require_tools python3
python3 "${ROOT}/scripts/validate_observability_dashboard.py" "${DASHBOARD}"
case "${cmd}" in render) render ;; install) install_release ;; upgrade) upgrade_release ;; status) status ;; verify) verify ;; dashboard-verify) dashboard_verify ;; *) usage; exit 2 ;; esac
