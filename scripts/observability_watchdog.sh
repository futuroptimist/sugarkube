#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
NAMESPACE=monitoring
SECRET=alertmanager-healthchecks-watchdog
KEY=ping-url
TTY="${SUGARKUBE_WATCHDOG_TTY:-/dev/tty}"
OWNER=sugarkube-observability-watchdog-drill

die() { printf 'ERROR: %s\n' "$1" >&2; exit "${2:-1}"; }
normalize_env() { local value="${1:-}"; while [[ "$value" == env=* ]]; do value="${value#env=}"; done; [[ "$value" == staging ]] || die 'env=staging is required; production and unknown environments are unsupported.' 2; }
require_tools() { local tool; for tool in "$@"; do command -v "$tool" >/dev/null || die "required tool is missing: $tool" 127; done; }
context_guard() {
  [[ "$(kubectl config current-context 2>/dev/null || true)" == sugar-staging ]] || die "staging context mismatch; run 'just kubeconfig-env env=staging'." 3
  python3 "$ROOT/scripts/cluster_identity.py" assert --kubeconfig "${KUBECONFIG:-$HOME/.kube/config}" --env staging >/dev/null || die 'staging cluster identity check failed.' 3
}
secret_contract() {
  local present
  if ! present="$(kubectl -n "$NAMESPACE" get secret "$SECRET" -o "go-template={{if index .data \"$KEY\"}}present{{end}}" 2>/dev/null)" || [[ "$present" != present ]]; then
    die "Secret $NAMESPACE/$SECRET must contain a nonempty $KEY (value not accessed or printed)." 15
  fi
  printf 'Watchdog Secret contract exists (value not accessed or printed).\n'
}
install_secret() {
  local value
  [[ $# -eq 0 ]] || die 'credentials in command arguments are refused.' 2
  [[ -z "${HEALTHCHECKS_PING_URL:-}${HEALTHCHECK_PING_URL:-}${PING_URL:-}${WATCHDOG_PING_URL:-}" ]] || die 'ping URLs in environment variables are refused.' 2
  context_guard; require_tools kubectl python3
  exec 3<"$TTY" || die 'a readable controlling terminal is required.'
  [[ "${SUGARKUBE_WATCHDOG_TEST_NONTTY:-0}" == 1 || -t 3 ]] || die 'a controlling terminal is required; piped input is refused.'
  printf 'Enter the Healthchecks watchdog ping URL (input hidden): ' >&2
  IFS= read -r -s value <&3 || die 'could not read the URL from the controlling terminal.'
  printf '\n' >&2
  [[ "$value" =~ ^https://hc-ping\.com/[0-9a-fA-F-]{36}$ && "$value" != *$'\n'* ]] || die 'ping URL is invalid (value redacted).'
  if ! printf '%s' "$value" | kubectl -n "$NAMESPACE" create secret generic "$SECRET" --from-file="$KEY=/dev/stdin" --dry-run=client -o yaml | kubectl apply -f - >/dev/null; then
    unset value; die 'watchdog Secret installation failed (credential redacted).'
  fi
  unset value
  printf 'Installed watchdog Secret contract in monitoring (credential redacted).\n'
}
verify_live() {
  context_guard; require_tools kubectl python3 ruby sleep; secret_contract
  local prom am cr config logs
  cr="$(mktemp -t watchdog-alertmanager-cr.XXXXXX)"; config="$(mktemp -t watchdog-alertmanager-config.XXXXXX)"; trap 'rm -f "$cr" "$config"' RETURN
  kubectl -n "$NAMESPACE" get alertmanager kube-prometheus-stack-alertmanager -o yaml >"$cr"
  kubectl -n "$NAMESPACE" get secret alertmanager-kube-prometheus-stack-alertmanager -o yaml >"$config"
  ruby "$ROOT/scripts/verify_observability_alertmanager.rb" live "$cr" "$config"
  prom="$(kubectl get --raw "/api/v1/namespaces/$NAMESPACE/services/http:kube-prometheus-stack-prometheus:9090/proxy/api/v1/rules?type=alert")"
  PROM_RESPONSE="$prom" python3 - <<'PY'
import json, os
r=json.loads(os.environ.pop("PROM_RESPONSE")); wanted={"alertname":"SugarkubeObservabilityWatchdog","environment":"staging","cluster":"sugarkube-int","purpose":"observability-watchdog"}
rules=[x for g in r.get("data",{}).get("groups",[]) for x in g.get("rules",[]) if x.get("name")==wanted["alertname"]]
if len(rules)!=1 or rules[0].get("query")!="vector(1)" or rules[0].get("state")!="firing" or any(rules[0].get("labels",{}).get(k)!=v for k,v in wanted.items() if k!="alertname"):
 raise SystemExit("ERROR: exact watchdog Prometheus rule is not firing (response redacted).")
PY
  am="$(kubectl get --raw "/api/v1/namespaces/$NAMESPACE/services/http:kube-prometheus-stack-alertmanager:9093/proxy/api/v2/alerts")"
  AM_RESPONSE="$am" python3 - <<'PY'
import json, os
alerts=json.loads(os.environ.pop("AM_RESPONSE")); wanted={"alertname":"SugarkubeObservabilityWatchdog","environment":"staging","cluster":"sugarkube-int","purpose":"observability-watchdog"}
if len([a for a in alerts if all(a.get("labels",{}).get(k)==v for k,v in wanted.items()) and a.get("status",{}).get("state")=="active"])!=1:
 raise SystemExit("ERROR: exact active watchdog alert is absent from Alertmanager (response redacted).")
PY
  sleep "${SUGARKUBE_WATCHDOG_OBSERVE_SECONDS:-10}"
  logs="$(kubectl -n "$NAMESPACE" logs statefulset/alertmanager-kube-prometheus-stack-alertmanager --since=2m 2>/dev/null || true)"
  if printf '%s' "$logs" | python3 -c 'import re,sys; s=sys.stdin.read(); raise SystemExit(0 if re.search(r"(?is)(watchdog|healthchecks).{0,200}(error|fail)|(?:error|fail).{0,200}(watchdog|healthchecks)",s) else 1)'; then
    die 'observed a watchdog delivery error (details redacted).' 18
  fi
  printf 'Live watchdog rule, alert, mounted receiver, and bounded delivery observation verified; credentials and responses redacted.\n'
}
port_forward() {
  PF_DIR="$(mktemp -d -t watchdog-alertmanager.XXXXXX)"; PF_PID=''; PF_PORT=''
  cleanup_pf() { [[ -z "$PF_PID" ]] || { kill "$PF_PID" 2>/dev/null || true; wait "$PF_PID" 2>/dev/null || true; }; rm -rf "$PF_DIR"; }
  trap cleanup_pf EXIT INT TERM
  kubectl -n "$NAMESPACE" port-forward --address=127.0.0.1 service/kube-prometheus-stack-alertmanager :9093 >"$PF_DIR/log" 2>&1 & PF_PID=$!
  for _ in {1..20}; do PF_PORT="$(sed -nE 's/^Forwarding from 127\.0\.0\.1:([0-9]+) -> 9093$/\1/p' "$PF_DIR/log" | head -1)"; [[ -n "$PF_PORT" ]] && break; kill -0 "$PF_PID" 2>/dev/null || break; sleep 1; done
  [[ -n "$PF_PORT" ]] || die 'Alertmanager loopback connection failed (diagnostics redacted).' 19
}
drill() {
  local action="$1" payload response
  context_guard; require_tools kubectl python3 curl; port_forward
  case "$action" in
    create)
      printf '\n*** MANUAL CHECKPOINT: confirm the Healthchecks check is healthy and PagerDuty is ready before continuing. ***\n' >&2
      [[ "${SUGARKUBE_WATCHDOG_DRILL_CONFIRM:-}" == confirmed ]] || die 'set SUGARKUBE_WATCHDOG_DRILL_CONFIRM=confirmed after completing the manual checkpoint; no disruption performed.' 20
      payload="$(python3 - <<'PY'
import datetime,json
now=datetime.datetime.now(datetime.timezone.utc); end=now+datetime.timedelta(minutes=8)
match=[{"name":k,"value":v,"isRegex":False} for k,v in {"alertname":"SugarkubeObservabilityWatchdog","environment":"staging","cluster":"sugarkube-int","purpose":"observability-watchdog"}.items()]
print(json.dumps({"matchers":match,"startsAt":now.isoformat(),"endsAt":end.isoformat(),"createdBy":"sugarkube-operator","comment":"sugarkube-observability-watchdog-drill"}))
PY
)"
      response="$(curl -fsS --max-time 10 -H 'Content-Type: application/json' --data-binary @- "http://127.0.0.1:$PF_PORT/api/v2/silences" <<<"$payload")" || die 'silence creation failed (response redacted).'
      RESPONSE="$response" python3 -c 'import json,os; assert isinstance(json.loads(os.environ.pop("RESPONSE")).get("silenceID"),str)' || die 'silence creation response was invalid (redacted).'
      printf 'Owned exact-label drill silence created with automatic eight-minute expiry. Confirm Healthchecks/PagerDuty transitions manually.\n' ;;
    status|clear)
      response="$(curl -fsS --max-time 10 "http://127.0.0.1:$PF_PORT/api/v2/silences")" || die 'silence query failed (response redacted).'
      IDS="$(RESPONSE="$response" python3 - <<'PY'
import json,os
want={"alertname":"SugarkubeObservabilityWatchdog","environment":"staging","cluster":"sugarkube-int","purpose":"observability-watchdog"}
out=[]
for s in json.loads(os.environ.pop("RESPONSE")):
 m={x.get("name"):x.get("value") for x in s.get("matchers",[]) if not x.get("isRegex")}
 if s.get("comment")=="sugarkube-observability-watchdog-drill" and m==want and s.get("status",{}).get("state") in ("active","pending"): out.append(s["id"])
print("\n".join(out))
PY
)"
      if [[ "$action" == clear ]]; then while IFS= read -r id; do [[ -z "$id" ]] || curl -fsS --max-time 10 -X DELETE "http://127.0.0.1:$PF_PORT/api/v2/silence/$id" >/dev/null || die 'owned silence removal failed (response redacted).'; done <<<"$IDS"; printf 'Removed only matching owned watchdog drill silence(s).\n'; else [[ -n "$IDS" ]] && printf 'Owned watchdog drill silence is active or pending.\n' || printf 'No owned active watchdog drill silence exists.\n'; fi ;;
  esac
}

[[ $# -ge 2 ]] || die "usage: $0 install|check|verify|drill-create|drill-status|drill-clear env=staging" 2
action="$1"; normalize_env "$2"; shift 2
case "$action" in install) install_secret "$@" ;; check) [[ $# -eq 0 ]] || die 'unexpected arguments.' 2; context_guard; secret_contract ;; verify) [[ $# -eq 0 ]] || die 'unexpected arguments.' 2; verify_live ;; drill-create) [[ $# -eq 0 ]] || die 'unexpected arguments.' 2; drill create ;; drill-status) [[ $# -eq 0 ]] || die 'unexpected arguments.' 2; drill status ;; drill-clear) [[ $# -eq 0 ]] || die 'unexpected arguments.' 2; drill clear ;; *) die 'unknown watchdog action.' 2 ;; esac
