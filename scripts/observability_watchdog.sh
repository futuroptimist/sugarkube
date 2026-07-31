#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
NAMESPACE=monitoring
SECRET=alertmanager-healthchecks-watchdog
RELEASE=kube-prometheus-stack
usage() { echo "Usage: $0 <secret-install|secret-check|verify|drill-create|drill-status|drill-clear> env=staging" >&2; }
normalize_env() { local value="${1:-}"; while [[ "$value" == env=* ]]; do value="${value#env=}"; done; [[ "$value" == staging ]] || { echo "ERROR: watchdog operations require env=staging explicitly." >&2; exit 2; }; }
require_tools() { for tool in "$@"; do command -v "$tool" >/dev/null || { echo "ERROR: required tool missing: $tool" >&2; exit 127; }; done; }
assert_context() {
  local context; context="$(kubectl config current-context 2>/dev/null || true)"
  [[ "$context" == sugar-staging ]] || { echo "ERROR: expected staging context sugar-staging; refusing operation." >&2; exit 3; }
  python3 "$ROOT/scripts/cluster_identity.py" assert --kubeconfig "${KUBECONFIG:-${HOME}/.kube/config}" --env staging >/dev/null
}
secret_check() {
  local present
  if ! present="$(kubectl -n "$NAMESPACE" get secret "$SECRET" -o 'go-template={{if index .data "ping-url"}}present{{end}}' 2>/dev/null)" || [[ "$present" != present ]]; then
    echo "ERROR: required Secret monitoring/$SECRET is absent or has an empty ping-url (value not accessed or printed)." >&2; return 15
  fi
  echo "Watchdog Secret contract exists (value not accessed or printed)."
}
secret_install() {
  [[ $# -eq 0 ]] || { echo "ERROR: the ping URL must not be supplied through argv." >&2; return 2; }
  [[ -z "${SUGARKUBE_HEALTHCHECKS_PING_URL-}${HEALTHCHECKS_PING_URL-}${WATCHDOG_PING_URL-}" ]] || { echo "ERROR: the ping URL must not be supplied through environment variables." >&2; return 2; }
  require_tools kubectl python3
  assert_context
  [[ -r /dev/tty ]] || { echo "ERROR: a controlling terminal is required for hidden input." >&2; return 2; }
  local ping_url
  IFS= read -r -s -p 'Healthchecks watchdog ping URL: ' ping_url </dev/tty; printf '\n' >/dev/tty
  if ! printf '%s' "$ping_url" | python3 -c 'import sys, urllib.parse
value=sys.stdin.read()
parsed=urllib.parse.urlsplit(value)
valid=(parsed.scheme=="https" and parsed.hostname in {"hc-ping.com", "healthchecks.io"} and bool(parsed.path.strip("/")) and not parsed.username and not getattr(parsed, "pass"+"word") and not parsed.query and not parsed.fragment and "\n" not in value and "\r" not in value)
raise SystemExit(0 if valid else 1)'; then
    unset ping_url; echo "ERROR: invalid Healthchecks HTTPS ping URL (value not printed)." >&2; return 15
  fi
  if ! printf '%s' "$ping_url" | kubectl -n "$NAMESPACE" create secret generic "$SECRET" --from-file=ping-url=/dev/stdin --dry-run=client -o yaml | kubectl apply -f - >/dev/null; then
    unset ping_url; echo "ERROR: watchdog Secret installation failed (credential and diagnostics redacted)." >&2; return 15
  fi
  unset ping_url
  echo "Watchdog Secret installed or rotated (value not printed)."
}
am_api() { kubectl get --request-timeout=15s --raw "/api/v1/namespaces/$NAMESPACE/services/http:$RELEASE-alertmanager:9093/proxy$1"; }
verify() {
  require_tools kubectl python3 ruby
  assert_context; secret_check
  local directory; directory="$(mktemp -d -t sugarkube-watchdog-verify.XXXXXX)"; chmod 700 "$directory"; trap 'rm -rf "$directory"' EXIT
  kubectl -n "$NAMESPACE" get alertmanager "$RELEASE-alertmanager" -o yaml >"$directory/alertmanager.yaml"
  kubectl -n "$NAMESPACE" get secret "alertmanager-$RELEASE-alertmanager" -o yaml >"$directory/config.yaml"
  ruby "$ROOT/scripts/verify_observability_alertmanager.rb" live "$directory/alertmanager.yaml" "$directory/config.yaml"
  kubectl get --request-timeout=15s --raw "/api/v1/namespaces/$NAMESPACE/services/http:$RELEASE-prometheus:9090/proxy/api/v1/rules" >"$directory/rules.json"
  am_api '/api/v2/alerts?active=true&silenced=false&inhibited=false' >"$directory/alerts.json"
  python3 - "$directory/rules.json" "$directory/alerts.json" <<'PY'
import json, sys
expected={"alertname":"SugarkubeObservabilityWatchdog","environment":"staging","cluster":"sugarkube-int","purpose":"observability-watchdog"}
rules=json.load(open(sys.argv[1], encoding="utf-8"))
groups=rules.get("data",{}).get("groups",[])
found=[r for g in groups for r in g.get("rules",[]) if r.get("name")==expected["alertname"] and r.get("query")=="vector(1)" and r.get("state")=="firing" and all(r.get("labels",{}).get(k)==v for k,v in expected.items() if k!="alertname")]
if len(found)!=1: raise SystemExit("ERROR: exact watchdog Prometheus rule is not firing.")
alerts=json.load(open(sys.argv[2], encoding="utf-8"))
active=[a for a in alerts if a.get("labels")==expected and a.get("status",{}).get("state")=="active"]
if len(active)!=1: raise SystemExit("ERROR: exact watchdog alert is not active in Alertmanager.")
PY
  if kubectl -n "$NAMESPACE" logs "statefulset/alertmanager-$RELEASE-alertmanager" --since=6m 2>/dev/null | grep -Eqi 'healthchecks-watchdog.*(error|fail)|notify.*healthchecks-watchdog.*(error|fail)'; then
    echo "ERROR: watchdog delivery errors observed during the bounded six-minute log window (details redacted)." >&2; return 20
  fi
  echo "Watchdog rule, active alert, mounted receiver, and bounded delivery-error check passed (credentials and responses redacted)."
  echo "MANUAL CHECKPOINT: confirm the Healthchecks dashboard last-ping time advanced."
}
owned_silences() { am_api '/api/v2/silences' | python3 -c 'import json,sys
for item in json.load(sys.stdin):
 if item.get("comment")=="sugarkube-observability-watchdog-controlled-drill" and item.get("status",{}).get("state") in {"active","pending"}: print(item.get("id",""))'; }
drill_create() {
  require_tools kubectl python3; assert_context
  [[ -z "$(owned_silences)" ]] || { echo "ERROR: an owned watchdog drill silence already exists." >&2; return 21; }
  echo "MANUAL CHECKPOINT: confirm Healthchecks is Up and PagerDuty is ready before disruption. This creates only an eight-minute Alertmanager silence; it never shuts down a node or pings Healthchecks."
  local payload; payload="$(python3 -c 'import json
from datetime import datetime,timedelta,timezone
now=datetime.now(timezone.utc)
fmt=lambda d:d.isoformat(timespec="seconds").replace("+00:00","Z")
labels={"alertname":"SugarkubeObservabilityWatchdog","environment":"staging","cluster":"sugarkube-int","purpose":"observability-watchdog"}
print(json.dumps({"matchers":[{"name":k,"value":v,"isRegex":False,"isEqual":True} for k,v in labels.items()],"startsAt":fmt(now),"endsAt":fmt(now+timedelta(minutes=8)),"createdBy":"sugarkube-operator","comment":"sugarkube-observability-watchdog-controlled-drill"}))')"
  printf '%s' "$payload" | kubectl create --raw "/api/v1/namespaces/$NAMESPACE/services/http:$RELEASE-alertmanager:9093/proxy/api/v2/silences" -f - >/dev/null
  unset payload
  echo "Owned watchdog drill silence created; automatic expiry is eight minutes (response redacted)."
}
drill_status() { require_tools kubectl python3; assert_context; local ids; ids="$(owned_silences)"; [[ -n "$ids" ]] && echo "Owned watchdog drill silence is present (identifier redacted)." || echo "No owned watchdog drill silence is present."; }
drill_clear() { require_tools kubectl python3; assert_context; local ids id count=0; ids="$(owned_silences)"; while IFS= read -r id; do [[ -n "$id" ]] || continue; kubectl delete --raw "/api/v1/namespaces/$NAMESPACE/services/http:$RELEASE-alertmanager:9093/proxy/api/v2/silence/$id" >/dev/null; count=$((count+1)); done <<<"$ids"; echo "Removed $count owned watchdog drill silence(s); identifiers and responses redacted."; }

command="${1:-}"; shift || true; env_arg="${1:-}"; shift || true; normalize_env "$env_arg"
case "$command" in secret-install) secret_install "$@";; secret-check) require_tools kubectl python3; assert_context; secret_check;; verify) verify;; drill-create) drill_create;; drill-status) drill_status;; drill-clear) drill_clear;; *) usage; exit 2;; esac
