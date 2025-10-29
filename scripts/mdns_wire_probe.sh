#!/usr/bin/env bash
set -euo pipefail

iface=""
while [ "$#" -gt 0 ]; do
  case "$1" in
    --iface)
      if [ "$#" -lt 2 ]; then
        echo "event=mdns_wire_probe answers=0 status=skipped reason=missing_iface" >&2
        exit 2
      fi
      iface="$2"
      shift 2
      ;;
    --)
      shift
      break
      ;;
    *)
      # treat first non-flag as iface for convenience
      if [ -z "${iface}" ]; then
        iface="$1"
      else
        # ignore unknown parameters to remain forward compatible
        :
      fi
      shift
      ;;
  esac
done

cluster="${SUGARKUBE_CLUSTER:-sugar}"
environment="${SUGARKUBE_ENV:-dev}"
expected_ipv4="${EXPECTED_IPV4:-${SUGARKUBE_EXPECTED_IPV4:-}}"
expected_host="${SUGARKUBE_EXPECTED_HOST:-}"
if [ -z "${iface}" ]; then
  iface="${SUGARKUBE_MDNS_INTERFACE:-}"
fi
if [ -z "${iface}" ]; then
  iface="eth0"
fi
if [ -z "${expected_host}" ]; then
  expected_host="$(hostname -f 2>/dev/null || hostname 2>/dev/null || true)"
fi
if [ -z "${expected_host}" ]; then
  expected_host=""
fi

service_type="_k3s-${cluster}-${environment}._tcp"
service_suffix=".${service_type}.local"
service_suffix_lc="$(printf '%s' "${service_suffix}" | tr '[:upper:]' '[:lower:]')"

if ! command -v tcpdump >/dev/null 2>&1; then
  printf 'event=mdns_wire_probe status=skipped reason=tcpdump_missing iface=%s answers=0\n' "${iface}"
  exit 0
fi
if ! command -v avahi-browse >/dev/null 2>&1; then
  printf 'event=mdns_wire_probe status=skipped reason=avahi_browse_missing iface=%s answers=0\n' "${iface}"
  exit 0
fi

host_variants=()
add_host_variant() {
  local raw="$1"
  [ -n "${raw}" ] || return 0
  local lowered
  lowered="$(printf '%s' "${raw}" | tr '[:upper:]' '[:lower:]')"
  lowered="${lowered%.}"
  [ -n "${lowered}" ] || return 0
  host_variants+=("${lowered}")
  case "${lowered}" in
    *.local)
      base="${lowered%.local}"
      if [ -n "${base}" ]; then
        host_variants+=("${base}")
      fi
      ;;
    *)
      host_variants+=("${lowered}.local")
      ;;
  esac
}

add_host_variant "${expected_host}"
add_host_variant "${HOSTNAME:-}"
add_host_variant "$(hostname 2>/dev/null || true)"
add_host_variant "$(hostname -s 2>/dev/null || true)"
add_host_variant "$(hostname -f 2>/dev/null || true)"

unique_hosts=()
for candidate in "${host_variants[@]}"; do
  [ -n "${candidate}" ] || continue
  skip=0
  for existing in "${unique_hosts[@]}"; do
    if [ "${existing}" = "${candidate}" ]; then
      skip=1
      break
    fi
  done
  if [ "${skip}" -eq 0 ]; then
    unique_hosts+=("${candidate}")
  fi
done
host_variants=("${unique_hosts[@]}")

# Build tcpdump command
read -r -a tcpdump_expr <<<"udp port 5353"
if [ -n "${expected_ipv4}" ]; then
  tcpdump_expr+=("and" "src" "host" "${expected_ipv4}")
fi

tcpdump_args=(tcpdump -i "${iface}" -n -vv -s0)
tcpdump_args+=("${tcpdump_expr[@]}")

timeout_bin="$(command -v timeout || true)"

tmp_file="$(mktemp "${TMPDIR:-/tmp}/mdns-wire-probe.XXXXXX")"
cleanup() {
  rm -f "${tmp_file}"
  if [ -n "${timer_pid:-}" ]; then
    kill "${timer_pid}" >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT

set +e
if [ -n "${timeout_bin}" ]; then
  "${timeout_bin}" 5 "${tcpdump_args[@]}" >"${tmp_file}" 2>&1 &
  tcpdump_pid=$!
else
  "${tcpdump_args[@]}" >"${tmp_file}" 2>&1 &
  tcpdump_pid=$!
  (
    sleep 5
    kill -TERM "${tcpdump_pid}" >/dev/null 2>&1 || true
  ) &
  timer_pid=$!
fi
set -e

# Give tcpdump a brief moment to attach before sending query
sleep 0.1

set +e
browse_output="$(avahi-browse --terminate "${service_type}" 2>&1)"
browse_rc=$?
set -e

set +e
wait "${tcpdump_pid}"
tcpdump_rc=$?
set -e

if [ -n "${timer_pid:-}" ]; then
  kill "${timer_pid}" >/dev/null 2>&1 || true
fi

host_csv=""
for candidate in "${host_variants[@]}"; do
  [ -n "${candidate}" ] || continue
  if [ -n "${host_csv}" ]; then
    host_csv="${host_csv},${candidate}"
  else
    host_csv="${candidate}"
  fi
done

answers="$({
  python3 - "$tmp_file" "${service_suffix_lc}" "${host_csv}" <<'PY'
import collections
import sys

dump_path = sys.argv[1]
service_suffix = sys.argv[2]
raw_hosts = sys.argv[3]
if raw_hosts:
    hosts = {h.strip() for h in raw_hosts.split(',') if h.strip()}
else:
    hosts = set()

records = collections.defaultdict(lambda: {"ptr": False, "srv": False})

try:
    with open(dump_path, "r", encoding="utf-8", errors="replace") as fh:
        lines = fh.readlines()
except FileNotFoundError:
    lines = []

for line in lines:
    line_stripped = line.strip()
    if not line_stripped:
        continue
    lower = line_stripped.lower()
    if service_suffix not in lower:
        continue
    idx = lower.find(service_suffix)
    prefix = line_stripped[:idx].rstrip(" .,:")
    tokens = prefix.split()
    instance = tokens[-1] if tokens else ""
    if not instance:
        continue
    entry = records[instance]
    if " ptr" in lower:
        entry["ptr"] = True
    if " srv" in lower:
        if hosts:
            if any(host in lower for host in hosts):
                entry["srv"] = True
        else:
            entry["srv"] = True

count = sum(1 for entry in records.values() if entry["ptr"] and entry["srv"])
print(count)
PY
} 2>/dev/null)"
if [ -z "${answers}" ]; then
  answers="0"
fi

status="absent"
if [ "${answers}" != "0" ]; then
  status="present"
fi

printf 'event=mdns_wire_probe iface=%s service_type=%s answers=%s status=%s tcpdump_rc=%s browse_rc=%s' \
  "${iface}" "${service_type}" "${answers}" "${status}" "${tcpdump_rc}" "${browse_rc}"
if [ -n "${expected_ipv4}" ]; then
  printf ' expected_ipv4=%s' "${expected_ipv4}"
fi
if [ -n "${browse_output}" ]; then
  browse_flat="$(printf '%s' "${browse_output}" | tr '\n' ';')"
  printf ' browse_output=%q' "${browse_flat}"
fi
printf '\n'
