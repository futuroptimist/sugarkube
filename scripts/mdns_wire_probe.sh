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
      if [ -z "${iface}" ]; then
        iface="$1"
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

mdns_query_secs="${MDNS_ACTIVE_QUERY_SECS:-5}"
case "${mdns_query_secs}" in
  ''|*[!0-9]*) mdns_query_secs=5 ;;
  0) mdns_query_secs=5 ;;
  *) : ;;
esac

# Attempt to confirm via D-Bus first.
dbus_summary=""
dbus_rc=127
if command -v gdbus >/dev/null 2>&1; then
  set +e
  dbus_summary="$({
    python3 - "${service_type}" <<'PY'
import ast
import json
import subprocess
import sys
import xml.etree.ElementTree as ET

SERVICE = "org.freedesktop.Avahi"
INTROSPECT_IFACE = "org.freedesktop.DBus.Introspectable"
ENTRY_IFACE = "org.freedesktop.Avahi.EntryGroup"
INTROSPECT_METHOD = f"{INTROSPECT_IFACE}.Introspect"

service_type = sys.argv[1]

def unwrap(value):
    if isinstance(value, tuple):
        if len(value) == 1:
            return unwrap(value[0])
        return [unwrap(item) for item in value]
    return value

def parse_output(text):
    text = text.strip()
    if not text:
        return ""
    try:
        value = ast.literal_eval(text)
    except Exception:
        return text
    return unwrap(value)

def call_gdbus(args):
    proc = subprocess.run(args, capture_output=True, text=True)
    if proc.returncode != 0:
        raise subprocess.CalledProcessError(proc.returncode, proc.args, proc.stdout, proc.stderr)
    return parse_output(proc.stdout)

def object_path(parent, name):
    if not name:
        return None
    if name.startswith("/"):
        return name
    if parent == "/":
        return f"/{name}"
    if parent.endswith("/"):
        return f"{parent}{name}"
    return f"{parent}/{name}"

def discover_entry_groups():
    from collections import deque

    queue = deque(["/"])
    seen = set()
    entry_groups = []

    while queue:
        path = queue.popleft()
        try:
            xml_text = call_gdbus([
                "gdbus",
                "call",
                "--system",
                "--dest",
                SERVICE,
                "--object-path",
                path,
                "--method",
                INTROSPECT_METHOD,
            ])
        except subprocess.CalledProcessError:
            continue
        if not xml_text:
            continue
        try:
            root = ET.fromstring(xml_text)
        except ET.ParseError:
            continue
        for node in root.findall("node"):
            name = node.get("name")
            child = object_path(path, name)
            if not child:
                continue
            if child in seen:
                continue
            seen.add(child)
            queue.append(child)
            if "EntryGroup" in child.split("/"):
                entry_groups.append(child)
    return entry_groups

def entry_group_state(path):
    value = call_gdbus([
        "gdbus",
        "call",
        "--system",
        "--dest",
        SERVICE,
        "--object-path",
        path,
        "--method",
        f"{ENTRY_IFACE}.GetState",
    ])
    if isinstance(value, (list, tuple)) and value:
        value = value[0]
    if isinstance(value, str):
        value = value.strip()
        try:
            value = int(value)
        except ValueError:
            pass
    if isinstance(value, (int, float)):
        return int(value)
    raise ValueError(f"Unexpected state response for {path}: {value!r}")

try:
    groups = discover_entry_groups()
except Exception as exc:  # pragma: no cover - defensive
    sys.stderr.write(f"mdns_wire_probe dbus discovery error: {exc}\n")
    sys.exit(1)

states = {}
errors = {}
for path in groups:
    try:
        state = entry_group_state(path)
    except Exception as exc:  # pragma: no cover - defensive
        errors[path] = str(exc)
        continue
    states[path] = state

result = {
    "service_type": service_type,
    "entry_groups": groups,
    "states": states,
    "errors": errors,
}
print(json.dumps(result, sort_keys=True))

if any(state == 2 for state in states.values()):
    sys.exit(0)
if states:
    sys.exit(2)
if groups:
    sys.exit(3)
sys.exit(4)
PY
  } 2>&1)"
  dbus_rc=$?
  set -e
else
  dbus_rc=127
fi

dbus_reason=""
case "${dbus_rc}" in
  0)
    status="established"
    answers="not_collected"
    printf 'event=mdns_wire_probe iface=%s service_type=%s status=%s answers=%s dbus_rc=%s' \
      "${iface}" "${service_type}" "${status}" "${answers}" "${dbus_rc}"
    if [ -n "${expected_ipv4}" ]; then
      printf ' expected_ipv4=%s' "${expected_ipv4}"
    fi
    if [ -n "${dbus_summary}" ]; then
      printf ' dbus_summary=%q' "${dbus_summary}"
    fi
    printf '\n'
    exit 0
    ;;
  2)
    status="not_established"
    answers="not_collected"
    printf 'event=mdns_wire_probe iface=%s service_type=%s status=%s answers=%s dbus_rc=%s' \
      "${iface}" "${service_type}" "${status}" "${answers}" "${dbus_rc}"
    if [ -n "${expected_ipv4}" ]; then
      printf ' expected_ipv4=%s' "${expected_ipv4}"
    fi
    if [ -n "${dbus_summary}" ]; then
      printf ' dbus_summary=%q' "${dbus_summary}"
    fi
    printf '\n'
    exit 0
    ;;
  3|4)
    status="no_entry_group"
    answers="not_collected"
    printf 'event=mdns_wire_probe iface=%s service_type=%s status=%s answers=%s dbus_rc=%s' \
      "${iface}" "${service_type}" "${status}" "${answers}" "${dbus_rc}"
    if [ -n "${expected_ipv4}" ]; then
      printf ' expected_ipv4=%s' "${expected_ipv4}"
    fi
    if [ -n "${dbus_summary}" ]; then
      printf ' dbus_summary=%q' "${dbus_summary}"
    fi
    printf '\n'
    exit 0
    ;;
  1)
    dbus_reason="error"
    ;;
  127)
    dbus_reason="gdbus_missing"
    ;;
  *)
    dbus_reason="unavailable"
    ;;
esac

# Fallback CLI path when D-Bus is unavailable.
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
      local base
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

have_tcpdump=0
if command -v tcpdump >/dev/null 2>&1; then
  have_tcpdump=1
fi
have_browse=0
if command -v avahi-browse >/dev/null 2>&1; then
  have_browse=1
fi

timeout_bin="$(command -v timeout || true)"

answers="not_collected"
tcpdump_rc=""
browse_rc=""
browse_output=""
reason="dbus_unavailable"

if [ -n "${dbus_reason}" ]; then
  reason="dbus_${dbus_reason}"
fi

if [ "${have_tcpdump}" -eq 1 ]; then
  tmp_file="$(mktemp "${TMPDIR:-/tmp}/mdns-wire-probe.XXXXXX")"
  cleanup() {
    rm -f "${tmp_file}"
    if [ -n "${timer_pid:-}" ]; then
      kill "${timer_pid}" >/dev/null 2>&1 || true
    fi
  }
  trap cleanup EXIT

  read -r -a tcpdump_expr <<<"udp port 5353"
  if [ -n "${expected_ipv4}" ]; then
    tcpdump_expr+=("and" "src" "host" "${expected_ipv4}")
  fi
  tcpdump_args=(tcpdump -i "${iface}" -n -vv -s0)
  tcpdump_args+=("${tcpdump_expr[@]}")

  set +e
  if [ -n "${timeout_bin}" ]; then
    "${timeout_bin}" "${mdns_query_secs}" "${tcpdump_args[@]}" >"${tmp_file}" 2>&1 &
    tcpdump_pid=$!
  else
    "${tcpdump_args[@]}" >"${tmp_file}" 2>&1 &
    tcpdump_pid=$!
    (
      sleep "${mdns_query_secs}"
      kill -TERM "${tcpdump_pid}" >/dev/null 2>&1 || true
    ) &
    timer_pid=$!
  fi
  set -e

  sleep 0.1 || true
else
  tmp_file=""
  tcpdump_pid=""
fi

if [ "${have_browse}" -eq 1 ]; then
  browse_cmd=(avahi-browse --parsable --ignore-local --terminate "${service_type}")
  if [ -n "${timeout_bin}" ]; then
    set +e
    browse_output="$("${timeout_bin}" "${mdns_query_secs}" "${browse_cmd[@]}" 2>&1)"
    browse_rc=$?
    set -e
  else
    browse_tmp="$(mktemp "${TMPDIR:-/tmp}/mdns-browse.XXXXXX")"
    set +e
    "${browse_cmd[@]}" >"${browse_tmp}" 2>&1 &
    browse_pid=$!
    (
      sleep "${mdns_query_secs}"
      kill -TERM "${browse_pid}" >/dev/null 2>&1 || true
    ) &
    browse_timer_pid=$!
    wait "${browse_pid}"
    browse_rc=$?
    kill "${browse_timer_pid}" >/dev/null 2>&1 || true
    browse_output="$(cat "${browse_tmp}" 2>/dev/null || true)"
    rm -f "${browse_tmp}" || true
    set -e
  fi
else
  browse_rc="127"
  browse_output="avahi-browse-missing"
fi

if [ -n "${tcpdump_pid}" ]; then
  set +e
  wait "${tcpdump_pid}"
  tcpdump_rc=$?
  set -e
else
  tcpdump_rc="127"
fi

if [ -n "${timer_pid:-}" ]; then
  kill "${timer_pid}" >/dev/null 2>&1 || true
fi

if [ "${have_tcpdump}" -eq 1 ] && [ -f "${tmp_file}" ]; then
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
fi

if [ -n "${tmp_file}" ]; then
  rm -f "${tmp_file}" || true
fi
trap - EXIT

if [ -z "${tcpdump_rc}" ]; then
  tcpdump_rc="0"
fi
if [ -z "${browse_rc}" ]; then
  browse_rc="0"
fi

printf 'event=mdns_wire_probe iface=%s service_type=%s status=indeterminate visibility=no_local_loop reason=%s answers=%s tcpdump_rc=%s browse_rc=%s' \
  "${iface}" "${service_type}" "${reason}" "${answers}" "${tcpdump_rc}" "${browse_rc}"
if [ -n "${expected_ipv4}" ]; then
  printf ' expected_ipv4=%s' "${expected_ipv4}"
fi
if [ -n "${dbus_summary}" ]; then
  printf ' dbus_summary=%q' "${dbus_summary}"
fi
if [ -n "${browse_output}" ]; then
  browse_flat="$(printf '%s' "${browse_output}" | tr '\n' ';')"
  printf ' browse_output=%q' "${browse_flat}"
fi
printf '\n'
