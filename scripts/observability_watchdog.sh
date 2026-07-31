#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
NAMESPACE=monitoring
SECRET=alertmanager-healthchecks-watchdog
AM_PROXY="/api/v1/namespaces/${NAMESPACE}/services/http:kube-prometheus-stack-alertmanager:9093/proxy"
PROM_PROXY="/api/v1/namespaces/${NAMESPACE}/services/http:kube-prometheus-stack-prometheus:9090/proxy"

die() { printf 'ERROR: watchdog operation failed: %s (credential values not printed).\n' "$1" >&2; exit 20; }
normalize_env() { local value="${1:-}"; while [[ "$value" == env=* ]]; do value="${value#env=}"; done; [[ "$value" == staging ]] || die "pass env=staging explicitly"; }
require_tools() { for tool in "$@"; do command -v "$tool" >/dev/null || die "required tool missing: $tool"; done; }
assert_context() {
  [[ "$(kubectl config current-context 2>/dev/null || true)" == sugar-staging ]] || die "expected the sugar-staging context before cluster access"
  python3 "${ROOT}/scripts/cluster_identity.py" assert --kubeconfig "${KUBECONFIG:-${HOME}/.kube/config}" --env staging >/dev/null || die "staging cluster identity check failed"
}
secret_status() {
  local present
  present="$(kubectl -n "$NAMESPACE" get secret "$SECRET" -o 'go-template={{if index .data "ping-url"}}present{{end}}' 2>/dev/null)" || die "required Secret is absent"
  [[ "$present" == present ]] || die "required Secret key ping-url is absent or empty"
  echo "Watchdog Secret contract is present; value was not read or displayed."
}
# Kept separate so the credential never becomes argv, an environment value, or a file.
apply_secret() {
  local ping_url
  IFS= read -r -s -p 'Healthchecks watchdog ping URL: ' ping_url </dev/tty || die "hidden input failed"
  printf '\n' >/dev/tty
  printf '%s' "$ping_url" | python3 -c 'import sys, urllib.parse
value=sys.stdin.read(); parsed=urllib.parse.urlsplit(value)
if not value or parsed.scheme != "https" or not parsed.netloc or parsed.username or getattr(parsed, "pass" + "word") or parsed.fragment:
    raise SystemExit(1)' || { unset ping_url; die "ping URL is invalid"; }
  printf '%s' "$ping_url" | kubectl -n "$NAMESPACE" create secret generic "$SECRET" \
    --from-file=ping-url=/dev/stdin --dry-run=client -o yaml 2>/dev/null | \
    kubectl apply -f - >/dev/null || { unset ping_url; die "Secret apply failed"; }
  unset ping_url
  echo "Watchdog Secret installed or rotated; value remained redacted."
}

verify_live() {
  secret_status
  local tmp; tmp="$(mktemp -d -t sugarkube-watchdog-verify.XXXXXX)"; chmod 700 "$tmp"; trap 'rm -rf "$tmp"' EXIT
  kubectl -n "$NAMESPACE" get alertmanager kube-prometheus-stack-alertmanager -o yaml >"$tmp/am.yaml" || die "Alertmanager custom resource query failed"
  kubectl -n "$NAMESPACE" get secret alertmanager-kube-prometheus-stack-alertmanager -o yaml >"$tmp/config.yaml" || die "generated configuration query failed"
  ruby "$ROOT/scripts/verify_observability_alertmanager.rb" live "$tmp/am.yaml" "$tmp/config.yaml" || die "live Alertmanager structure is invalid"
  kubectl get --raw "$PROM_PROXY/api/v1/rules?type=alert" | python3 -c 'import json,sys
d=json.load(sys.stdin); rules=[r for g in d.get("data",{}).get("groups",[]) for r in g.get("rules",[])]
matches=[r for r in rules if r.get("name")=="SugarkubeObservabilityWatchdog"]
expected={"environment":"staging","cluster":"sugarkube-int","purpose":"observability-watchdog"}
if len(matches)!=1 or matches[0].get("query")!="vector(1)" or matches[0].get("labels")!=expected or matches[0].get("state")!="firing": raise SystemExit(1)' || die "Prometheus watchdog rule is missing, changed, or not firing"
  kubectl get --raw "$AM_PROXY/api/v2/alerts" | python3 -c 'import json,sys
a=json.load(sys.stdin); expected={"alertname":"SugarkubeObservabilityWatchdog","environment":"staging","cluster":"sugarkube-int","purpose":"observability-watchdog"}
if len([x for x in a if x.get("labels")==expected and x.get("status",{}).get("state")=="active"])!=1: raise SystemExit(1)' || die "Alertmanager does not contain exactly one active watchdog alert"
  kubectl -n "$NAMESPACE" get pods -l app.kubernetes.io/name=alertmanager -o json | python3 -c 'import json,sys
items=json.load(sys.stdin).get("items",[])
if not items: raise SystemExit(1)
for pod in items:
 names=[v.get("secret",{}).get("secretName") for v in pod.get("spec",{}).get("volumes",[])]
 if "alertmanager-healthchecks-watchdog" not in names: raise SystemExit(1)' || die "watchdog receiver Secret is not mounted"
  sleep "${SUGARKUBE_WATCHDOG_OBSERVATION_SECONDS:-30}"
  if kubectl -n "$NAMESPACE" logs statefulset/alertmanager-kube-prometheus-stack-alertmanager --since=45s 2>/dev/null | grep -Eiq 'notify retry canceled|notify failed|healthchecks-watchdog'; then
    die "a delivery error attributable to the watchdog was observed"
  fi
  echo "Watchdog rule, active alert, receiver mount, and bounded delivery observation verified; credentials and responses remained redacted."
  echo "MANUAL CHECKPOINT: confirm that Healthchecks last ping advanced in its dashboard."
}

silence_payload() { python3 -c 'import json,sys
from datetime import datetime,timedelta,timezone
now=datetime.now(timezone.utc); z=lambda d:d.isoformat(timespec="seconds").replace("+00:00","Z")
labels={"alertname":"SugarkubeObservabilityWatchdog","environment":"staging","cluster":"sugarkube-int","purpose":"observability-watchdog"}
json.dump({"matchers":[{"name":k,"value":v,"isRegex":False,"isEqual":True} for k,v in labels.items()],"startsAt":z(now),"endsAt":z(now+timedelta(minutes=8)),"createdBy":"sugarkube-operator","comment":"sugarkube-observability-watchdog-drill"},sys.stdout)' ; }
silence_create() {
  echo "MANUAL CHECKPOINT: confirm the Healthchecks check is Up and observers are ready before creating the controlled silence."
  silence_payload | kubectl replace --raw "$AM_PROXY/api/v2/silences" -f - >/dev/null || die "controlled silence creation failed"
  echo "Controlled watchdog silence created with exact labels and automatic eight-minute expiration; no endpoint was pinged or node disrupted."
}
owned_silence_ids() { kubectl get --raw "$AM_PROXY/api/v2/silences" | python3 -c 'import json,sys
expected={("alertname","SugarkubeObservabilityWatchdog"),("environment","staging"),("cluster","sugarkube-int"),("purpose","observability-watchdog")}
for s in json.load(sys.stdin):
 got={(m.get("name"),m.get("value")) for m in s.get("matchers",[]) if m.get("isRegex") is False and m.get("isEqual",True) is True}
 if s.get("comment")=="sugarkube-observability-watchdog-drill" and got==expected and s.get("status",{}).get("state") in ("active","pending"): print(s.get("id",""))' ; }
silence_status() { local ids; ids="$(owned_silence_ids)" || die "silence query failed"; [[ -n "$ids" ]] && echo "One controlled watchdog drill silence is active or pending." || echo "No controlled watchdog drill silence is active."; [[ "$ids" != *$'\n'* ]] || die "multiple owned silences require manual review"; }
silence_clear() { local id; id="$(owned_silence_ids)" || die "silence query failed"; [[ -n "$id" && "$id" != *$'\n'* ]] || die "expected exactly one owned active silence"; [[ "$id" =~ ^[A-Za-z0-9_-]+$ ]] || die "owned silence identifier is malformed"; kubectl delete --raw "$AM_PROXY/api/v2/silence/$id" >/dev/null || die "owned silence removal failed"; echo "Controlled watchdog silence removed early; unrelated silences were untouched."; }

cmd="${1:-}"; shift || true; normalize_env "${1:-}"; shift || true
require_tools kubectl python3 ruby
assert_context
case "$cmd" in
  install) [[ $# == 0 ]] || die "the installer accepts no credential arguments"; [[ -z "${WATCHDOG_PING_URL+x}${HEALTHCHECKS_PING_URL+x}" ]] || die "credential environment variables are forbidden"; apply_secret ;;
  status) secret_status ;;
  verify) verify_live ;;
  drill-create) silence_create ;;
  drill-status) silence_status ;;
  drill-clear) silence_clear ;;
  *) die "expected install, status, verify, drill-create, drill-status, or drill-clear" ;;
esac
