#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HOSTNAMECTL_BIN="${ENSURE_HOSTNAMECTL_BIN:-hostnamectl}"
HOSTNAME_FILE="${ENSURE_HOSTNAME_FILE:-/etc/hostname}"
SYSTEMD_DIR="${ENSURE_SYSTEMD_DIR:-/etc/systemd/system}"
DROPIN_NAME="${ENSURE_NODE_ID_DROPIN:-20-node-id.conf}"
HOSTNAME_CMD="${ENSURE_HOSTNAME_CMD:-hostname}"
LOG_PREFIX="ensure_unique_hostname"

log_info() {
  local msg="$1"
  shift || true
  printf '%s %s' "${LOG_PREFIX}" "${msg}" >&2
  if [ "$#" -gt 0 ]; then
    printf ' %s' "$@" >&2
  fi
  printf '\n' >&2
}

log_warn() {
  log_info "WARN:$1" "${@:2}"
}

collect_collision_decision() {
  local current="$1"
  local mdns_hosts_env="${ENSURE_UNIQUE_HOSTNAME_MDNS_HOSTS:-}"
  PYTHONPATH="${SCRIPT_DIR}" CURRENT_HOST="${current}" \
    SUGARKUBE_CLUSTER="${SUGARKUBE_CLUSTER:-sugar}" \
    SUGARKUBE_ENV="${SUGARKUBE_ENV:-dev}" \
    ENSURE_UNIQUE_HOSTNAME_MDNS_HOSTS="${mdns_hosts_env}" \
    python3 - <<'PY'
import os
import secrets
import string
import subprocess
import sys
from typing import Set

alphabet = string.ascii_lowercase + string.digits
cluster = os.environ.get("SUGARKUBE_CLUSTER", "sugar")
environment = os.environ.get("SUGARKUBE_ENV", "dev")
current = os.environ.get("CURRENT_HOST", "").strip()
manual_hosts = os.environ.get("ENSURE_UNIQUE_HOSTNAME_MDNS_HOSTS", "")

try:
    from mdns_helpers import normalize_hostname
except Exception as exc:  # pragma: no cover - defensive fallback
    print(f"mdns_helpers import failed: {exc}", file=sys.stderr)
    normalize_hostname = lambda value: value.strip().lower().rstrip('.')  # type: ignore

hosts: Set[str] = set()


def add_host(value: str) -> None:
    if not value:
        return
    norm = normalize_hostname(value)
    if not norm:
        return
    hosts.add(norm)
    short = norm.split('.')[0]
    if short:
        hosts.add(short)


def load_mdns() -> None:
    if manual_hosts:
        for line in manual_hosts.splitlines():
            add_host(line.strip())
        return
    try:
        from k3s_mdns_query import query_mdns
    except Exception as exc:  # pragma: no cover - defensive fallback
        print(f"k3s_mdns_query import failed: {exc}", file=sys.stderr)
        return
    for mode in ("server-hosts", "bootstrap-hosts"):
        try:
            for host in query_mdns(mode, cluster, environment):
                add_host(host)
        except Exception as exc:  # pragma: no cover - diagnostic logging only
            print(f"mdns query {mode} failed: {exc}", file=sys.stderr)


def load_kubectl() -> None:
    candidates = (
        ("kubectl",),
        ("k3s", "kubectl"),
    )
    for base in candidates:
        try:
            result = subprocess.run(
                base
                + (
                    "get",
                    "nodes",
                    "-o",
                    "jsonpath={range .items[*]}{.metadata.name}{\"\\n\"}{end}",
                    "--request-timeout=5s",
                ),
                check=True,
                capture_output=True,
                text=True,
                timeout=10,
            )
        except FileNotFoundError:
            continue
        except subprocess.SubprocessError as exc:  # pragma: no cover - best effort only
            print(f"kubectl {' '.join(base)} failed: {exc}", file=sys.stderr)
            continue
        for line in result.stdout.splitlines():
            add_host(line.strip())
        break


load_mdns()
load_kubectl()

if not current:
    sys.exit(0)

current_norm = normalize_hostname(current)
if current_norm in hosts:
    for attempt in range(32):
        suffix = ''.join(secrets.choice(alphabet) for _ in range(4))
        candidate = f"{current}-{suffix}"
        candidate_norm = normalize_hostname(candidate)
        if candidate_norm not in hosts and candidate_norm.split('.')[0] not in hosts:
            print(candidate)
            sys.exit(20)
    print("unable to generate unique hostname", file=sys.stderr)
    sys.exit(21)

if current_norm.split('.')[0] in hosts:
    for attempt in range(32):
        suffix = ''.join(secrets.choice(alphabet) for _ in range(4))
        candidate = f"{current}-{suffix}"
        candidate_norm = normalize_hostname(candidate)
        if candidate_norm not in hosts and candidate_norm.split('.')[0] not in hosts:
            print(candidate)
            sys.exit(20)
    print("unable to generate unique hostname", file=sys.stderr)
    sys.exit(21)

sys.exit(0)
PY
}

write_dropin() {
  local unit="$1"
  local dir="${SYSTEMD_DIR}/${unit}.d"
  local dest="${dir}/${DROPIN_NAME}"
  mkdir -p "${dir}"
  local tmp
  tmp="$(mktemp "${dir}/${DROPIN_NAME}.XXXXXX")"
  {
    printf '[Service]\n'
    printf 'Environment=K3S_WITH_NODE_ID=true\n'
  } >"${tmp}"
  local changed=1
  if [ -f "${dest}" ] && cmp -s "${tmp}" "${dest}"; then
    changed=0
  fi
  if [ "${changed}" -eq 1 ]; then
    mv "${tmp}" "${dest}"
    log_info "enabled --with-node-id drop-in" "unit=${unit}" "path=${dest}"
  else
    rm -f "${tmp}"
  fi
}

enable_with_node_id() {
  write_dropin "k3s.service"
  write_dropin "k3s-agent.service"
  if command -v systemctl >/dev/null 2>&1; then
    systemctl daemon-reload >/dev/null 2>&1 || true
  fi
}

set_hostname() {
  local new_host="$1"
  local success=1
  if [ -n "${HOSTNAMECTL_BIN}" ] && command -v "${HOSTNAMECTL_BIN}" >/dev/null 2>&1; then
    if "${HOSTNAMECTL_BIN}" set-hostname "${new_host}" >/dev/null 2>&1; then
      success=0
    fi
  fi
  if [ "${success}" -ne 0 ]; then
    if [ "${HOSTNAME_FILE}" != "/etc/hostname" ]; then
      mkdir -p "$(dirname "${HOSTNAME_FILE}")"
    fi
    if printf '%s\n' "${new_host}" >"${HOSTNAME_FILE}"; then
      success=0
    fi
  fi
  if [ "${success}" -ne 0 ]; then
    return 1
  fi
  if command -v "${HOSTNAME_CMD}" >/dev/null 2>&1; then
    "${HOSTNAME_CMD}" "${new_host}" >/dev/null 2>&1 || true
  fi
  return 0
}

main() {
  if ! command -v python3 >/dev/null 2>&1; then
    log_warn "python3 not available; skipping hostname uniqueness check"
    return 0
  fi

  local current_host
  if command -v "${HOSTNAME_CMD}" >/dev/null 2>&1; then
    if current_host="$(${HOSTNAME_CMD} -s 2>/dev/null)" && [ -n "${current_host}" ]; then
      :
    else
      current_host="$(${HOSTNAME_CMD} 2>/dev/null || true)"
    fi
  else
    log_warn "hostname command unavailable; skipping"
    return 0
  fi

  current_host="${current_host%%.*}"
  current_host="${current_host,,}"
  if [ -z "${current_host}" ]; then
    log_warn "unable to determine current hostname"
    return 0
  fi

  local decision
  local status
  if decision="$(collect_collision_decision "${current_host}")"; then
    status=0
  else
    status=$?
  fi

  if [ "${status}" -eq 0 ]; then
    log_info "hostname is already unique" "hostname=${current_host}"
    return 0
  fi

  if [ "${status}" -eq 20 ]; then
    local new_host
    new_host="${decision%%$'\n'*}"
    if [ -z "${new_host}" ]; then
      log_warn "collision detected but no candidate generated"
      enable_with_node_id
      return 0
    fi
    log_info "detected hostname collision" "current=${current_host}" "candidate=${new_host}"
    if set_hostname "${new_host}"; then
      log_info "hostname updated" "new=${new_host}"
      return 0
    fi
    log_warn "failed to update hostname" "new=${new_host}" "fallback=with-node-id"
    enable_with_node_id
    return 0
  fi

  log_warn "unable to evaluate hostname uniqueness" "status=${status}" "fallback=with-node-id"
  enable_with_node_id
  return 0
}

main "$@"
