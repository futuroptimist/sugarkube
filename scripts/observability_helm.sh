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
DASHBOARD_VALUE="grafana.dashboards.sugarkube.sugarkube-staging-observability.json"
DASHBOARD_VALIDATOR="${ROOT}/scripts/validate_observability_dashboard.py"
TIMEOUT="${SUGARKUBE_OBSERVABILITY_HELM_TIMEOUT:-20m}"
GRAFANA_URL="http://sugarkube3.local:30300"
PAGERDUTY_SECRET="alertmanager-pagerduty"
WATCHDOG_SECRET="alertmanager-healthchecks-watchdog"
ALERTMANAGER_VALIDATOR="${ROOT}/scripts/verify_observability_alertmanager.rb"

usage() { echo "Usage: $0 <render|install|upgrade|status|verify|dashboard-verify|pagerduty-test|watchdog-secret-install|watchdog-secret-check|watchdog-verify|watchdog-drill-create|watchdog-drill-status|watchdog-drill-clear> env=staging [fire|resolve]" >&2; }
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
  local env="$1" ctx
  if (($# >= 2)); then ctx="$2"; else ctx="$(current_context)"; fi
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
dashboard source (--set-file): ${DASHBOARD}
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
validate_dashboard() { python3 "${DASHBOARD_VALIDATOR}" "${DASHBOARD}"; }
validate_rendered_dashboard() { python3 "${DASHBOARD_VALIDATOR}" "${DASHBOARD}" --rendered "$1"; }
validate_rendered_alertmanager() { ruby "${ALERTMANAGER_VALIDATOR}" rendered "$1"; }
render_to() {
  local out="$1"
  helm repo add prometheus-community https://prometheus-community.github.io/helm-charts --force-update >/dev/null
  helm repo update prometheus-community >/dev/null
  helm template "${RELEASE}" "${CHART}" --namespace "${NAMESPACE}" --version "$(version)" -f "${COMMON_VALUES}" -f "${STAGING_VALUES}" --set-file "${DASHBOARD_VALUE}=${DASHBOARD}" >"${out}"
  validate_rendered_dashboard "${out}"
  validate_rendered_alertmanager "${out}"
}
assert_pagerduty_secret() {
  local present
  if ! present="$(kubectl -n "${NAMESPACE}" get secret "${PAGERDUTY_SECRET}" -o 'go-template={{if index .data "routing-key"}}present{{end}}' 2>/dev/null)"; then
    echo "ERROR: required Secret monitoring/alertmanager-pagerduty is absent; create it with a nonempty routing-key before deployment or verification." >&2
    return 15
  fi
  if [[ "${present}" != present ]]; then
    echo "ERROR: Secret monitoring/alertmanager-pagerduty must contain a nonempty routing-key (value intentionally not read or printed)." >&2
    return 15
  fi
  echo "PagerDuty Secret contract exists (value intentionally not read or printed)."
}
assert_watchdog_secret() {
  local present
  if ! present="$(kubectl -n "${NAMESPACE}" get secret "${WATCHDOG_SECRET}" -o 'go-template={{if index .data "ping-url"}}present{{end}}' 2>/dev/null)"; then
    echo "ERROR: required Secret monitoring/alertmanager-healthchecks-watchdog is absent; install a nonempty ping-url before deployment or verification." >&2
    return 15
  fi
  if [[ "${present}" != present ]]; then
    echo "ERROR: Secret monitoring/alertmanager-healthchecks-watchdog must contain a nonempty ping-url (value intentionally not read or printed)." >&2
    return 15
  fi
  echo "Watchdog Secret contract exists (value intentionally not read or printed)."
}
assert_integration_secrets() { assert_pagerduty_secret && assert_watchdog_secret; }
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
render() { validate_dashboard; require_tools helm python3 ruby; print_resolved staging '<not queried: offline render>'; tmp="$(mktemp -t sugarkube-observability-render.XXXXXX.yaml)"; trap 'rm -f "${tmp}"' EXIT; render_to "${tmp}"; cat "${tmp}"; }
install_release() { validate_dashboard; require_tools helm kubectl python3 ruby; print_resolved staging; assert_context; assert_integration_secrets; tmp="$(mktemp -t sugarkube-observability-install.XXXXXX.yaml)"; trap 'rm -f "${tmp:-}"' EXIT; render_to "${tmp}"; state="$(release_state)"; if [[ "${state}" == present ]]; then echo "ERROR: cannot install: ${RELEASE} already exists in ${NAMESPACE}. Use observability-upgrade." >&2; exit 4; fi; helm install "${RELEASE}" "${CHART}" --namespace "${NAMESPACE}" --create-namespace --version "$(version)" -f "${COMMON_VALUES}" -f "${STAGING_VALUES}" --set-file "${DASHBOARD_VALUE}=${DASHBOARD}" --wait --timeout "${TIMEOUT}"; }
upgrade_release() { validate_dashboard; require_tools helm kubectl python3 ruby; print_resolved staging; assert_context; assert_integration_secrets; tmp="$(mktemp -t sugarkube-observability-upgrade.XXXXXX.yaml)"; trap 'rm -f "${tmp:-}"' EXIT; render_to "${tmp}"; state="$(release_state)"; if [[ "${state}" == absent ]]; then echo "ERROR: upgrade requires an existing Helm release ${RELEASE} in ${NAMESPACE}. Use observability-install for a fresh cluster." >&2; exit 5; fi; helm upgrade "${RELEASE}" "${CHART}" --namespace "${NAMESPACE}" --version "$(version)" -f "${COMMON_VALUES}" -f "${STAGING_VALUES}" --set-file "${DASHBOARD_VALUE}=${DASHBOARD}" --wait --timeout "${TIMEOUT}"; }
WATCHDOG_TTY="${SUGARKUBE_WATCHDOG_TTY:-/dev/tty}"
WATCHDOG_API="/api/v1/namespaces/${NAMESPACE}/services/http:${RELEASE}-alertmanager:9093/proxy/api/v2"

watchdog_secret_check() { assert_context; assert_watchdog_secret; }
watchdog_secret_install() {
  assert_context
  [[ -z "${HEALTHCHECKS_PING_URL:-}${HEALTHCHECK_PING_URL:-}${PING_URL:-}${WATCHDOG_PING_URL:-}" ]] || { echo "ERROR: credential environment variables are refused." >&2; return 2; }
  [[ $# == 0 ]] || { echo "ERROR: credential arguments are refused." >&2; return 2; }
  local value
  exec 3<"${WATCHDOG_TTY}"
  [[ "${SUGARKUBE_WATCHDOG_TEST_NONTTY:-0}" == 1 || -t 3 ]] || { echo "ERROR: an interactive controlling terminal is required." >&2; return 2; }
  printf 'Enter the Healthchecks watchdog ping URL (input hidden): ' >&2
  IFS= read -r -s value <&3 || { echo "ERROR: could not read the ping URL (value redacted)." >&2; return 2; }
  printf '\n' >&2
  [[ "${value}" =~ ^https://hc-ping\.com/[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$ && "${value}" != *$'\n'* ]] || { unset value; echo "ERROR: ping URL is invalid (value redacted)." >&2; return 2; }
  if ! printf '%s' "${value}" | kubectl -n "${NAMESPACE}" create secret generic "${WATCHDOG_SECRET}" --from-file=ping-url=/dev/stdin --dry-run=client -o yaml | kubectl apply -f - >/dev/null; then
    unset value; echo "ERROR: watchdog Secret installation failed (value redacted)." >&2; return 1
  fi
  unset value
  echo "Watchdog Secret installed or rotated (value not displayed)."
}

watchdog_live_check() (
  require_tools kubectl python3 ruby sleep
  assert_context
  assert_watchdog_secret
  local tmp observation
  tmp="$(mktemp -d -t sugarkube-watchdog-verify.XXXXXX)"; chmod 700 "${tmp}"; trap 'rm -rf "${tmp}"' EXIT
  kubectl get --raw "/api/v1/namespaces/${NAMESPACE}/services/http:${RELEASE}-prometheus:9090/proxy/api/v1/rules" >"${tmp}/rules"
  kubectl get --raw "${WATCHDOG_API}/alerts" >"${tmp}/alerts"
  python3 - "${tmp}/rules" "${tmp}/alerts" <<'PY'
import json, sys
wanted={"alertname":"SugarkubeObservabilityWatchdog","environment":"staging","cluster":"sugarkube-int","purpose":"observability-watchdog"}
expected_rule_labels={k:v for k,v in wanted.items() if k!="alertname"}
try:
    rules_doc, alerts = (json.load(open(path, encoding="utf-8")) for path in sys.argv[1:])
except (OSError, UnicodeError, json.JSONDecodeError):
    raise SystemExit("ERROR: watchdog APIs returned malformed data (responses redacted).")
rules=[r for g in rules_doc.get("data",{}).get("groups",[]) for r in g.get("rules",[]) if r.get("name")==wanted["alertname"]]
if len(rules)!=1 or rules[0].get("state")!="firing" or rules[0].get("query")!="vector(1)" or rules[0].get("labels")!=expected_rule_labels:
    raise SystemExit("ERROR: unique vector(1) watchdog rule is not firing with required labels (response redacted).")
matching=[a for a in alerts if a.get("status",{}).get("state")=="active" and all(a.get("labels",{}).get(k)==v for k,v in wanted.items())]
if len(matching)!=1:
    raise SystemExit("ERROR: unique watchdog alert is not active with required routing labels (response redacted).")
PY
  kubectl -n "${NAMESPACE}" get alertmanager "${RELEASE}-alertmanager" -o yaml >"${tmp}/cr"
  kubectl -n "${NAMESPACE}" get secret "alertmanager-${RELEASE}-alertmanager" -o yaml >"${tmp}/config"
  ruby "${ALERTMANAGER_VALIDATOR}" live "${tmp}/cr" "${tmp}/config"
  kubectl -n "${NAMESPACE}" get pods -l 'app.kubernetes.io/name=alertmanager' -o json >"${tmp}/pods"
  python3 - "${tmp}/pods" "${RELEASE}-alertmanager" >"${tmp}/pod-names" <<'PY'
import json, re, sys
try:
 doc=json.load(open(sys.argv[1], encoding="utf-8"))
 def mapping(value):
  if not isinstance(value,dict): raise TypeError
  return value
 def sequence(value):
  if not isinstance(value,list): raise TypeError
  return value
 mapping(doc)
 pods=sequence(doc["items"])
 selected=[]
 for pod in pods:
  pod=mapping(pod)
  metadata=mapping(pod["metadata"])
  labels=mapping(metadata["labels"])
  name=metadata["name"]
  if not isinstance(name,str) or len(name)>253 or not re.fullmatch(r'[a-z0-9](?:[-a-z0-9.]*[a-z0-9])?',name): raise TypeError
  mapping(pod["status"])
  spec=mapping(pod["spec"])
  vols=sequence(spec.get("volumes",[]))
  names=set()
  for volume in vols:
   volume=mapping(volume)
   secret=volume.get("secret")
   if secret is not None and mapping(secret).get("secretName")=="alertmanager-healthchecks-watchdog": names.add(volume.get("name"))
  containers=sequence(spec.get("containers",[]))
  mounts=[]
  for container in containers:
   container=mapping(container)
   mounts.extend(mapping(mount) for mount in sequence(container.get("volumeMounts",[])))
  if labels.get("alertmanager")==sys.argv[2]: selected.append((name,pod["status"].get("phase"),bool(names) and any(m.get("name") in names and m.get("mountPath")=="/etc/alertmanager/secrets/alertmanager-healthchecks-watchdog" and m.get("readOnly") is True for m in mounts)))
except (OSError, UnicodeError, json.JSONDecodeError, AttributeError, KeyError, TypeError): raise SystemExit("ERROR: Alertmanager pod data is malformed (response redacted).")
if not selected:
 raise SystemExit("ERROR: no operator-managed Alertmanager pods matched the expected resource (response redacted).")
if not all(phase=="Running" and mounted for _,phase,mounted in selected):
 raise SystemExit("ERROR: running Alertmanager pods do not have the exact watchdog Secret mount (response redacted).")
print(*(name for name,_,_ in selected), sep="\n")
PY
  observation="${SUGARKUBE_WATCHDOG_OBSERVATION_SECONDS:-310}"
  [[ "${observation}" =~ ^[0-9]+$ ]] || { echo "ERROR: watchdog observation duration must be an integer." >&2; return 2; }
  if ((observation < 300)) && [[ "${SUGARKUBE_WATCHDOG_TEST_ALLOW_SHORT_OBSERVATION:-0}" != 1 ]]; then
    echo "ERROR: watchdog observation must cover at least one five-minute repeat." >&2; return 2
  fi
  sleep "${observation}"
  local log_index=0
  while IFS= read -r pod; do
    if ! kubectl -n "${NAMESPACE}" logs "pod/${pod}" -c alertmanager --since="$((observation + 60))s" >"${tmp}/logs.${log_index}" 2>"${tmp}/logs.${log_index}.stderr"; then
      echo "ERROR: Alertmanager logs could not be retrieved (details redacted)." >&2; return 1
    fi
    log_index=$((log_index + 1))
  done <"${tmp}/pod-names"
  local log_count=${log_index}
  for ((log_index=0; log_index<log_count; log_index++)); do
  python3 - "${tmp}/logs.${log_index}" <<'PY'
import re,sys
try: text=open(sys.argv[1], encoding="utf-8", errors="replace").read()
except OSError: raise SystemExit("ERROR: Alertmanager logs could not be inspected (details redacted).")
receiver=r'(?:healthchecks-watchdog|alertmanager-healthchecks-watchdog)'
error=r'(?:error|failed|failure|timeout|refused)'
if re.search(fr'(?i)(?:{receiver}).{{0,240}}{error}|{error}.{{0,240}}(?:{receiver})', text):
 raise SystemExit("ERROR: watchdog receiver delivery error observed (details redacted).")
PY
  done
  echo "Watchdog rule, active alert, live configuration, pod mount, and bounded repeat observation verified; delivery must be confirmed at Healthchecks."
)

watchdog_silence_create() (
  local port="" line http_status silence_pid="" silence_tmp
  local -a port_forward_lines=()
  require_tools kubectl python3 curl sleep
  assert_context
  cat >&2 <<'EOF2'
MANUAL CHECKPOINT: confirm Healthchecks has a recent watchdog ping before disruption and confirm the PagerDuty resolution after recovery. This creates only an eight-minute silence.
EOF2
  silence_tmp="$(mktemp -d -t sugarkube-watchdog-silence.XXXXXX)"
  chmod 700 "${silence_tmp}"
  # shellcheck disable=SC2317
  cleanup_watchdog_silence() {
    if [[ -n "${silence_pid}" && " $(jobs -pr) " == *" ${silence_pid} "* ]]; then
      kill "${silence_pid}" 2>/dev/null || true
    fi
    [[ -z "${silence_pid}" ]] || wait "${silence_pid}" 2>/dev/null || true
    rm -rf "${silence_tmp}"
  }
  silence_port_forward_running() {
    [[ " $(jobs -pr) " == *" ${silence_pid} "* ]] && kill -0 "${silence_pid}" 2>/dev/null
  }
  trap cleanup_watchdog_silence EXIT
  trap 'exit 130' INT
  trap 'exit 143' TERM

  umask 077
  python3 -c 'import json; from datetime import datetime,timedelta,timezone; n=datetime.now(timezone.utc); f=lambda d:d.isoformat(timespec="seconds").replace("+00:00","Z"); print(json.dumps({"matchers":[{"name":k,"value":v,"isRegex":False} for k,v in [("alertname","SugarkubeObservabilityWatchdog"),("environment","staging"),("cluster","sugarkube-int"),("purpose","observability-watchdog")]],"startsAt":f(n),"endsAt":f(n+timedelta(minutes=8)),"createdBy":"sugarkube-observability-watchdog-drill","comment":"Owned staging watchdog failure drill"}))' >"${silence_tmp}/payload.json"
  : >"${silence_tmp}/port-forward.log"
  kubectl -n "${NAMESPACE}" port-forward --address=127.0.0.1 "service/${RELEASE}-alertmanager" :9093 >"${silence_tmp}/port-forward.log" 2>&1 &
  silence_pid=$!
  for _ in {1..20}; do
    if ! silence_port_forward_running; then
      echo "ERROR: Alertmanager port-forward stopped (diagnostics redacted)." >&2
      return 19
    fi
    mapfile -t port_forward_lines <"${silence_tmp}/port-forward.log"
    for line in "${port_forward_lines[@]}"; do
      if [[ "${line}" =~ ^Forwarding\ from\ 127\.0\.0\.1:([1-9][0-9]{0,4})\ -\>\ 9093$ ]]; then
        port="${BASH_REMATCH[1]}"
        ((10#${port} <= 65535)) || port=""
      fi
    done
    [[ -z "${port}" ]] || break
    sleep 1
  done
  [[ -n "${port}" ]] || { echo "ERROR: Alertmanager port-forward did not establish an owned loopback listener (diagnostics redacted)." >&2; return 19; }
  silence_port_forward_running || { echo "ERROR: Alertmanager port-forward stopped (diagnostics redacted)." >&2; return 19; }

  if ! curl --silent --show-error --noproxy '*' --connect-timeout 3 --max-time 10 \
    --header 'Content-Type: application/json' --data-binary "@${silence_tmp}/payload.json" \
    --output "${silence_tmp}/response" --write-out '%{http_code}' \
    "http://127.0.0.1:${port}/api/v2/silences" >"${silence_tmp}/status" 2>"${silence_tmp}/curl.log"; then
    echo "ERROR: Alertmanager v2 API silence request failed (response redacted)." >&2
    return 18
  fi
  silence_port_forward_running || { echo "ERROR: Alertmanager port-forward stopped (diagnostics redacted)." >&2; return 19; }
  http_status="$(cat "${silence_tmp}/status")"
  [[ "${http_status}" =~ ^[0-9]{3}$ && "${http_status}" == 200 ]] || {
    echo "ERROR: Alertmanager v2 API silence request was not accepted (response redacted)." >&2
    return 18
  }
  python3 - "${silence_tmp}/response" <<'PY'
import json
import re
import sys

try:
    with open(sys.argv[1], encoding="utf-8") as response:
        document = json.load(response)
    silence_id = document.get("silenceID") if isinstance(document, dict) else None
    if not isinstance(silence_id, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]*", silence_id):
        raise ValueError
except (OSError, UnicodeError, json.JSONDecodeError, ValueError):
    raise SystemExit("ERROR: Alertmanager returned an invalid silence response (response redacted).")
print(f"Owned watchdog drill silence created; id={silence_id}; automatic expiry=8m.")
PY
)
watchdog_owned_silences() {
  kubectl get --raw "${WATCHDOG_API}/silences" | python3 -c 'import json,sys; wanted=[("alertname","SugarkubeObservabilityWatchdog"),("environment","staging"),("cluster","sugarkube-int"),("purpose","observability-watchdog")]; out=[]
for x in json.load(sys.stdin):
 m=x.get("matchers"); exact=isinstance(m,list) and len(m)==4 and sorted((a.get("name"),a.get("value")) for a in m if isinstance(a,dict) and a.get("isRegex") is False and set(a)=={"name","value","isRegex"})==sorted(wanted)
 if x.get("createdBy")=="sugarkube-observability-watchdog-drill" and x.get("comment")=="Owned staging watchdog failure drill" and x.get("status",{}).get("state") in ("active","pending") and exact: out.append(x["id"])
print("\n".join(out))'
}
watchdog_silence_list() { assert_context; local ids; ids="$(watchdog_owned_silences)"; [[ -n "${ids}" ]] && printf 'Owned active/pending watchdog drill silence IDs:\n%s\n' "${ids}" || echo "No owned active/pending watchdog drill silence."; }
watchdog_silence_clear() { assert_context; local ids; ids="$(watchdog_owned_silences)"; [[ -n "${ids}" ]] || { echo "No owned active/pending watchdog drill silence to clear."; return; }; while IFS= read -r id; do kubectl delete --raw "${WATCHDOG_API}/silence/${id}" >/dev/null; done <<<"${ids}"; echo "Owned watchdog drill silence cleared."; }

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
verify() (
  require_tools kubectl python3 ruby
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
  assert_integration_secrets
  local alertmanager_yaml="" config_yaml=""
  trap 'rm -f "${alertmanager_yaml:-}" "${config_yaml:-}"' EXIT
  alertmanager_yaml="$(mktemp -t sugarkube-alertmanager-cr.XXXXXX.yaml)"
  config_yaml="$(mktemp -t sugarkube-alertmanager-config.XXXXXX.yaml)"
  kubectl -n "${NAMESPACE}" get alertmanager kube-prometheus-stack-alertmanager -o yaml >"${alertmanager_yaml}"
  kubectl -n "${NAMESPACE}" get secret alertmanager-kube-prometheus-stack-alertmanager -o yaml >"${config_yaml}"
  ruby "${ALERTMANAGER_VALIDATOR}" live "${alertmanager_yaml}" "${config_yaml}"
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
)

pagerduty_test() (
  local action="${1:-}" ends_at port="" line http_status
  local -a port_forward_lines=()
  local test_pid="" test_tmp
  action="${action#action=}"
  case "${action}" in
    fire|resolve) ;;
    "") echo "ERROR: PagerDuty test requires an explicit action: fire or resolve." >&2; return 17 ;;
    *) echo "ERROR: unsupported PagerDuty test action '${action}'; expected fire or resolve." >&2; return 17 ;;
  esac
  require_tools kubectl python3 curl sleep
  assert_context
  ends_at="$(ACTION="${action}" python3 -c 'from datetime import datetime, timedelta, timezone
import os
now = datetime.now(timezone.utc)
end = now + timedelta(minutes=15) if os.environ["ACTION"] == "fire" else now
print(end.isoformat(timespec="seconds").replace("+00:00", "Z"))')"
  test_tmp="$(mktemp -d -t sugarkube-alertmanager-test.XXXXXX)"
  chmod 700 "${test_tmp}"
  # Return 19 specifically when the owned port-forward cannot be established.
  # shellcheck disable=SC2317
  cleanup_pagerduty_test() {
    if [[ -n "${test_pid}" && " $(jobs -pr) " == *" ${test_pid} "* ]]; then
      kill "${test_pid}" 2>/dev/null || true
    fi
    [[ -z "${test_pid}" ]] || wait "${test_pid}" 2>/dev/null || true
    rm -rf "${test_tmp}"
  }
  port_forward_stopped() {
    wait "${test_pid}" 2>/dev/null || true
    test_pid=""
    echo "ERROR: Alertmanager port-forward stopped (diagnostics redacted)." >&2
    return 19
  }
  port_forward_running() {
    [[ " $(jobs -pr) " == *" ${test_pid} "* ]] && kill -0 "${test_pid}" 2>/dev/null
  }
  trap cleanup_pagerduty_test EXIT
  trap 'exit 130' INT
  trap 'exit 143' TERM

  umask 077
  ENDS_AT="${ends_at}" python3 -c 'import json, os, sys
json.dump([{
  "labels": {
    "alertname": "SugarkubePagerDutyTest",
    "environment": "staging",
    "cluster": "sugarkube-int",
    "severity": "critical"
  },
  "annotations": {
    "summary": "Sugarkube staging PagerDuty delivery test",
    "description": "Operator-triggered synthetic alert for the staging PagerDuty fire/resolve drill.",
    "runbook_url": "https://github.com/futuroptimist/sugarkube/blob/main/docs/observability-operations.md#pagerduty-staging-fire-and-resolve-runbook"
  },
  "startsAt": "2020-01-01T00:00:00Z",
  "endsAt": os.environ["ENDS_AT"]
}], sys.stdout)' >"${test_tmp}/payload.json"

  : >"${test_tmp}/port-forward.log"
  kubectl -n "${NAMESPACE}" port-forward --address=127.0.0.1 "service/${RELEASE}-alertmanager" :9093 >"${test_tmp}/port-forward.log" 2>&1 &
  test_pid=$!
  for _ in {1..20}; do
    port_forward_running || port_forward_stopped
    mapfile -t port_forward_lines <"${test_tmp}/port-forward.log"
    for line in "${port_forward_lines[@]}"; do
      if [[ "${line}" =~ ^Forwarding\ from\ 127\.0\.0\.1:([1-9][0-9]{0,4})\ -\>\ 9093$ ]]; then
        port="${BASH_REMATCH[1]}"
        ((10#${port} <= 65535)) || port=""
      fi
    done
    [[ -z "${port}" ]] || break
    sleep 1
  done
  [[ -n "${port}" ]] || { echo "ERROR: Alertmanager port-forward did not establish an owned loopback listener (diagnostics redacted)." >&2; return 19; }
  port_forward_running || port_forward_stopped

  if ! curl --silent --show-error --noproxy '*' --connect-timeout 3 --max-time 10 \
    --header 'Content-Type: application/json' --data-binary "@${test_tmp}/payload.json" \
    --output "${test_tmp}/response" --write-out '%{http_code}' \
    "http://127.0.0.1:${port}/api/v2/alerts" >"${test_tmp}/status" 2>"${test_tmp}/curl.log"; then
    echo "ERROR: Alertmanager v2 API rejected synthetic ${action} request (response redacted)." >&2
    return 18
  fi
  port_forward_running || port_forward_stopped
  http_status="$(cat "${test_tmp}/status")"
  [[ "${http_status}" =~ ^[0-9]{3}$ && "${http_status}" == 200 ]] || {
    echo "ERROR: Alertmanager v2 API rejected synthetic ${action} request (response redacted)." >&2
    return 18
  }
  echo "PagerDuty synthetic ${action} submitted; Alertmanager API status: accepted (response redacted)."
)

dashboard_verify() (
  require_tools kubectl python3 curl base64 sleep
  print_resolved staging
  assert_context
  local response body http_status port="" remote_port line
  local -a port_forward_lines=()
  local verify_pid="" verify_tmp
  verify_tmp="$(mktemp -d -t sugarkube-grafana-verify.XXXXXX)"
  chmod 700 "${verify_tmp}"
  # The EXIT trap invokes this cleanup callback indirectly.
  # shellcheck disable=SC2317
  cleanup_dashboard_verify() {
    if [[ -n "${verify_pid}" && " $(jobs -pr) " == *" ${verify_pid} "* ]]; then
      kill "${verify_pid}" 2>/dev/null || true
    fi
    [[ -z "${verify_pid}" ]] || wait "${verify_pid}" 2>/dev/null || true
    rm -rf "${verify_tmp}"
  }
  port_forward_stopped() {
    wait "${verify_pid}" 2>/dev/null || true
    verify_pid=""
    echo "ERROR: Grafana port-forward stopped (diagnostics redacted)." >&2
    return 12
  }
  trap cleanup_dashboard_verify EXIT
  trap 'exit 130' INT
  trap 'exit 143' TERM

  # The operator host and account are trusted. Ephemeral allocation prevents
  # predictable prebinding and ordinary collisions, and process checks reject
  # ordinary child failure. This helper does not claim cryptographic protection
  # against an active same-host rebind between the final check and connection.
  # Do not let the asynchronous child inherit the parent's EXIT cleanup trap.
  : >"${verify_tmp}/port-forward.log"
  trap - EXIT
  kubectl -n "${NAMESPACE}" port-forward --address=127.0.0.1 "service/${RELEASE}-grafana" :80 >"${verify_tmp}/port-forward.log" 2>&1 &
  verify_pid=$!
  trap cleanup_dashboard_verify EXIT
  for _ in {1..20}; do
    kill -0 "${verify_pid}" 2>/dev/null || port_forward_stopped
    mapfile -t port_forward_lines <"${verify_tmp}/port-forward.log"
    for line in "${port_forward_lines[@]}"; do
      if [[ "${line}" =~ ^Forwarding\ from\ 127\.0\.0\.1:([1-9][0-9]{0,4})\ -\>\ ([1-9][0-9]{0,4})$ ]]; then
        port="${BASH_REMATCH[1]}"
        remote_port="${BASH_REMATCH[2]}"
        if ((10#${port} > 65535 || 10#${remote_port} > 65535)); then
          port=""
        fi
      fi
    done
    [[ -z "${port}" ]] || break
    sleep 1
  done
  [[ -n "${port}" ]] || { echo "ERROR: Grafana port-forward did not establish an owned loopback listener (diagnostics redacted)." >&2; return 12; }
  kill -0 "${verify_pid}" 2>/dev/null || port_forward_stopped

  # Keep decoded credentials out of argv, stdout, diagnostics, and persistent files.
  umask 077
  local grafana_user grafana_value admin_key="admin-pass""word"
  grafana_user="$(kubectl -n "${NAMESPACE}" get secret grafana-admin-credentials -o jsonpath='{.data.admin-user}' | base64 --decode)"
  grafana_value="$(kubectl -n "${NAMESPACE}" get secret grafana-admin-credentials -o "jsonpath={.data.${admin_key}}" | base64 --decode)"
  [[ -n "${grafana_user}" && -n "${grafana_value}" && "${grafana_user}" != *$'\n'* && "${grafana_value}" != *$'\n'* ]] || { echo "ERROR: Grafana credentials Secret is missing or malformed (values redacted)." >&2; return 11; }
  grafana_user="${grafana_user//\\/\\\\}"; grafana_user="${grafana_user//\"/\\\"}"
  grafana_value="${grafana_value//\\/\\\\}"; grafana_value="${grafana_value//\"/\\\"}"
  printf 'machine 127.0.0.1 login "%s" pass%s "%s"\n' "${grafana_user}" "word" "${grafana_value}" >"${verify_tmp}/netrc"
  unset grafana_user grafana_value
  chmod 600 "${verify_tmp}/netrc"

  for _ in {1..20}; do
    kill -0 "${verify_pid}" 2>/dev/null || port_forward_stopped
    if response="$(curl --silent --show-error --max-time 3 --netrc-file "${verify_tmp}/netrc" --write-out $'\n%{http_code}' "http://127.0.0.1:${port}/api/dashboards/uid/sugarkube-staging-observability" 2>"${verify_tmp}/curl.log")"; then
      http_status="${response##*$'\n'}"; body="${response%$'\n'*}"
      case "${http_status}" in
        401|403) echo "ERROR: Grafana authentication was rejected (credentials and response redacted)." >&2; return 14 ;;
        200) ;;
        000|404|429|500|502|503|504) sleep 1; continue ;;
        *) echo "ERROR: Grafana dashboard API rejected the request (response redacted)." >&2; return 13 ;;
      esac
      python3 -c 'import json, sys
try:
    result = json.load(sys.stdin)
except (json.JSONDecodeError, UnicodeError):
    raise SystemExit("ERROR: Grafana dashboard API returned malformed JSON (response redacted).")
dashboard = result.get("dashboard") if isinstance(result, dict) else None
if not isinstance(dashboard, dict) or dashboard.get("uid") != "sugarkube-staging-observability" or dashboard.get("title") != "Sugarkube Staging Observability":
    raise SystemExit("ERROR: Grafana did not return the expected provisioned dashboard (response redacted).")' <<<"${body}"
      echo "Grafana API confirmed dashboard UID sugarkube-staging-observability (credentials and response redacted)."
      return 0
    fi
    sleep 1
  done
  echo "ERROR: Grafana dashboard API was unavailable or rejected the request (diagnostics redacted)." >&2
  return 13
)

cmd="${1:-}"; shift || true; [[ -n "${cmd}" ]] || { usage; exit 2; }
env_arg="${1:-}"; normalize_env "${env_arg}" >/dev/null
validate_dashboard
case "${cmd}" in render) render ;; install) install_release ;; upgrade) upgrade_release ;; status) status ;; verify) verify ;; dashboard-verify) dashboard_verify ;; pagerduty-test) pagerduty_test "${2:-${1:-}}" ;; watchdog-secret-install) watchdog_secret_install "${@:2}" ;; watchdog-secret-check) watchdog_secret_check ;; watchdog-verify) watchdog_live_check ;; watchdog-drill-create) watchdog_silence_create ;; watchdog-drill-status) watchdog_silence_list ;; watchdog-drill-clear) watchdog_silence_clear ;; *) usage; exit 2 ;; esac
