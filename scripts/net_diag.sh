#!/usr/bin/env bash
set -euo pipefail

iface=""
reason="mdns_selfcheck_failure"
attempt=""
declare -a tags=()

while [ "$#" -gt 0 ]; do
  case "$1" in
    --iface)
      if [ "$#" -lt 2 ]; then
        echo "--iface requires a value" >&2
        exit 2
      fi
      iface="$2"
      shift 2
      ;;
    --reason)
      if [ "$#" -lt 2 ]; then
        echo "--reason requires a value" >&2
        exit 2
      fi
      reason="$2"
      shift 2
      ;;
    --attempt)
      if [ "$#" -lt 2 ]; then
        echo "--attempt requires a value" >&2
        exit 2
      fi
      attempt="$2"
      shift 2
      ;;
    --tag)
      if [ "$#" -lt 2 ]; then
        echo "--tag requires a value" >&2
        exit 2
      fi
      tags+=("$2")
      shift 2
      ;;
    --)
      shift
      break
      ;;
    *)
      tags+=("$1")
      shift
      ;;
  esac
done

if [ -z "${iface}" ]; then
  iface="${SUGARKUBE_MDNS_INTERFACE:-}"
fi
if [ -z "${iface}" ]; then
  iface="eth0"
fi

reason="${reason// /_}"
if [ -n "${attempt}" ]; then
  case "${attempt}" in
    ''|*[!0-9]*) attempt="" ;;
  esac
fi

emit_line() {
  local check="$1"
  local exit_code="$2"
  local output="$3"
  shift 3 || true

  printf 'event=net_diag check=%s' "${check}"
  printf ' reason=%s' "${reason}"
  if [ -n "${attempt}" ]; then
    printf ' attempt=%s' "${attempt}"
  fi
  local tag
  for tag in "${tags[@]}"; do
    if [ -n "${tag}" ]; then
      printf ' %s' "${tag}"
    fi
  done
  while [ "$#" -gt 0 ]; do
    if [ -n "$1" ]; then
      printf ' %s' "$1"
    fi
    shift
  done
  if [ -n "${exit_code}" ]; then
    printf ' exit_code=%s' "${exit_code}"
  fi
  printf ' output=%q\n' "${output}"
}

systemctl_status="command_missing"
systemctl_rc=""
if command -v systemctl >/dev/null 2>&1; then
  set +e
  systemctl_status="$(systemctl is-active avahi-daemon 2>&1)"
  systemctl_rc="$?"
  set -e
else
  systemctl_status="systemctl_missing"
  systemctl_rc="127"
fi
emit_line "systemctl_is_active_avahi" "${systemctl_rc}" "${systemctl_status}"

avahi_version="unavailable"
avahi_rc=""
if command -v avahi-daemon >/dev/null 2>&1; then
  set +e
  avahi_version="$(avahi-daemon --version 2>&1)"
  avahi_rc="$?"
  set -e
elif command -v systemctl >/dev/null 2>&1; then
  set +e
  avahi_version="$(systemctl status avahi-daemon 2>&1 | head -n1)"
  avahi_rc="$?"
  set -e
else
  avahi_version="avahi_daemon_missing"
  avahi_rc="127"
fi
emit_line "avahi_daemon_version" "${avahi_rc}" "${avahi_version}"

udp_summary=""
udp_rc=""
udp_source=""
if command -v lsof >/dev/null 2>&1; then
  set +e
  lsof_output="$(LC_ALL=C lsof -nP -i UDP:5353 2>&1)"
  lsof_rc="$?"
  set -e
  if [ "${lsof_rc}" = "0" ]; then
    udp_summary="$(
      printf '%s\n' "${lsof_output}" \
        | awk 'NR>1 {print $1":"$2":"$9}' \
        | paste -sd',' -
    )"
    if [ -z "${udp_summary}" ]; then
      udp_summary="none"
    fi
  else
    if [ -z "${lsof_output}" ]; then
      udp_summary="none"
    else
      udp_summary="${lsof_output}" 
    fi
  fi
  udp_rc="${lsof_rc}"
  udp_source="lsof"
elif command -v ss >/dev/null 2>&1; then
  set +e
  ss_output="$(ss -ulpn 'sport = 5353' 2>&1)"
  ss_rc="$?"
  set -e
  if [ "${ss_rc}" = "0" ]; then
    udp_summary="$(
      printf '%s\n' "${ss_output}" \
        | tail -n +2 \
        | sed -E 's/^\s+//'
    )"
    udp_summary="$(printf '%s' "${udp_summary}" | tr '\n' ';')"
    if [ -z "${udp_summary}" ]; then
      udp_summary="none"
    fi
  else
    udp_summary="${ss_output}"
  fi
  udp_rc="${ss_rc}"
  udp_source="ss"
else
  udp_summary="no_lsof_or_ss"
  udp_rc="127"
  udp_source="missing"
fi
emit_line "udp_5353_processes" "${udp_rc}" "${udp_summary}" "source=${udp_source}"

ip_addr_output=""
ip_addr_rc=""
if command -v ip >/dev/null 2>&1; then
  set +e
  ip_addr_output="$(ip -br addr 2>/dev/null | grep -E 'UP' || true)"
  ip_addr_rc="$?"
  set -e
else
  ip_addr_output="ip_command_missing"
  ip_addr_rc="127"
fi
if [ -z "${ip_addr_output}" ]; then
  ip_addr_output=""
fi
ip_addr_output="$(printf '%s' "${ip_addr_output}" | tr '\n' ';')"
emit_line "ip_brief_up" "${ip_addr_rc}" "${ip_addr_output}" "iface=${iface}"

ip_route_output=""
ip_route_rc=""
if command -v ip >/dev/null 2>&1; then
  set +e
  ip_route_output="$(ip route 2>/dev/null | head -n 20)"
  ip_route_rc="$?"
  set -e
else
  ip_route_output="ip_command_missing"
  ip_route_rc="127"
fi
ip_route_output="$(printf '%s' "${ip_route_output}" | tr '\n' ';')"
emit_line \
  "ip_route" \
  "${ip_route_rc}" \
  "${ip_route_output}" \
  "iface=${iface}"

tcpdump_summary="tcpdump_not_run"
tcpdump_rc=""
tcpdump_matches="0"
if command -v tcpdump >/dev/null 2>&1; then
  set +e
  tcpdump_raw="$(
    timeout 4 tcpdump -n -l -i "${iface}" udp port 5353 -c 12 2>&1
  )"
  tcpdump_rc="$?"
  set -e
  tcpdump_filtered="$(
    printf '%s\n' "${tcpdump_raw}" \
      | grep -E '_k3s-|_services._dns-sd._udp' \
      || true
  )"
  if [ -n "${tcpdump_filtered}" ]; then
    tcpdump_matches="$(printf '%s\n' "${tcpdump_filtered}" | wc -l | tr -d ' ')"
    tcpdump_summary="$(printf '%s' "${tcpdump_filtered}" | tr '\n' ';')"
  else
    tcpdump_summary="$(printf '%s' "${tcpdump_raw}" | tr '\n' ';')"
  fi
else
  tcpdump_summary="tcpdump_missing"
  tcpdump_rc="127"
fi
emit_line \
  "tcpdump_5353" \
  "${tcpdump_rc}" \
  "${tcpdump_summary}" \
  "iface=${iface}" \
  "matches=${tcpdump_matches}"
