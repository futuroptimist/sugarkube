#!/usr/bin/env bash

set -Eeuo pipefail

hash_token() {
  local token="$1"
  printf '%s' "${salt}${token}" | sha256sum | awk '{print substr($1, 1, 6)}'
}

ipv4_pattern='((25[0-5]|2[0-4][0-9]|1[0-9]{2}|[1-9]?[0-9])\.){3}'\
'(25[0-5]|2[0-4][0-9]|1[0-9]{2}|[1-9]?[0-9])'
ipv6_pattern='([0-9a-fA-F]{0,4}:){2,7}[0-9a-fA-F]{0,4}'
mac_pattern='([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}'
jq_kube_filter='..|objects|select(has("name") and (.name|startswith("KUBE-")))'

escape_sed() {
  printf '%s' "$1" | sed -e 's/[\&/]/\\&/g'
}

mask_ipv4_token() {
  local ip="$1"
  if [ "${ip}" = "0.0.0.0" ]; then
    printf '%s\n' "0.0.0.0"
    return 0
  fi
  case "${ip}" in
    127.*)
      printf '%s\n' "127.0.0.1"
      return 0
      ;;
    10.*)
      printf '10.%s\n' "$(hash_token "${ip}")"
      return 0
      ;;
    172.1[6-9].*|172.2[0-9].*|172.3[0-1].*)
      printf '172.%s\n' "$(hash_token "${ip}")"
      return 0
      ;;
    192.168.*)
      printf '192.168.%s\n' "$(hash_token "${ip}")"
      return 0
      ;;
  esac
  printf 'PUBLIC-%s\n' "$(hash_token "${ip}")"
}

mask_ipv4() {
  local text="$1"
  local ips
  ips="$(
    printf '%s\n' "${text}" |
      grep -Eo "${ipv4_pattern}" |
      sort -u || true
  )"
  if [ -z "${ips}" ]; then
    printf '%s\n' "${text}"
    return 0
  fi
  local ip replacement escaped
  for ip in ${ips}; do
    replacement="$(mask_ipv4_token "${ip}")" || continue
    escaped="$(escape_sed "${ip}")"
    text="$(printf '%s\n' "${text}" | sed "s/${escaped}/${replacement}/g")"
  done
  printf '%s\n' "${text}"
}

mask_ipv6() {
  local text="$1"
  local ips
  ips="$(
    printf '%s\n' "${text}" |
      grep -Eo "${ipv6_pattern}" |
      sort -u || true
  )"
  if [ -z "${ips}" ]; then
    printf '%s\n' "${text}"
    return 0
  fi
  local ip replacement escaped
  for ip in ${ips}; do
    replacement="IPv6-$(hash_token "${ip}")"
    escaped="$(escape_sed "${ip}")"
    text="$(printf '%s\n' "${text}" | sed "s/${escaped}/${replacement}/g")"
  done
  printf '%s\n' "${text}"
}

mask_mac() {
  local text="$1"
  local macs
  macs="$(
    printf '%s\n' "${text}" |
      grep -Eo "${mac_pattern}" |
      sort -u || true
  )"
  if [ -z "${macs}" ]; then
    printf '%s\n' "${text}"
    return 0
  fi
  local mac replacement escaped
  for mac in ${macs}; do
    replacement="MAC-$(hash_token "${mac}")"
    escaped="$(escape_sed "${mac}")"
    text="$(printf '%s\n' "${text}" | sed "s/${escaped}/${replacement}/g")"
  done
  printf '%s\n' "${text}"
}

mask_host_tokens() {
  local text="$1"
  local hosts
  hosts="$(printf '%s\n' "${text}" | grep -Eo '([A-Za-z0-9_.-]{3,})' | sort -u || true)"
  if [ -z "${hosts}" ]; then
    printf '%s\n' "${text}"
    return 0
  fi
  local host replacement escaped
  for host in ${hosts}; do
    if printf '%s' "${host}" | grep -Eq '^sugarkube[0-9]+(\.local)?$'; then
      continue
    fi
    if printf '%s' "${host}" | grep -Eq '^(host|PUBLIC|IPv6|MAC|10|172|192\.168)'; then
      continue
    fi
    if ! printf '%s' "${host}" | grep -Eq '[0-9.-]'; then
      continue
    fi
    replacement="host-$(hash_token "${host}")"
    escaped="$(escape_sed "${host}")"
    text="$(printf '%s\n' "${text}" | sed "s/${escaped}/${replacement}/g")"
  done
  printf '%s\n' "${text}"
}

redact_tokens() {
  local text="$1"
  text="$(printf '%s\n' "${text}" | sed -E 's/(Bearer|bearer) [^[:space:]]+/\1 [REDACTED]/g')"
  text="$(printf '%s\n' "${text}" | sed -E 's/[Tt]oken:[^[:space:]]+/token:[REDACTED]/g')"
  text="$(printf '%s\n' "${text}" | sed -E 's/(Authorization:)[[:space:]]+.*/\1 [REDACTED]/Ig')"
  printf '%s\n' "${text}"
}

sanitize_text() {
  local text="$1"
  text="$(redact_tokens "${text}")"
  text="$(mask_mac "${text}")"
  text="$(mask_ipv6 "${text}")"
  text="$(mask_ipv4 "${text}")"
  text="$(mask_host_tokens "${text}")"
  printf '%s\n' "${text}"
}

verify_ipv4_sanitized() {
  local text="$1"
  local matches
  matches="$(
    printf '%s\n' "${text}" |
      grep -Eo "${ipv4_pattern}" |
      sort -u || true
  )"
  if [ -z "${matches}" ]; then
    return 0
  fi
  local ip
  for ip in ${matches}; do
    case "${ip}" in
      127.0.0.1|0.0.0.0)
        continue
        ;;
      *)
        return 1
        ;;
    esac
  done
  return 0
}

sanitize_block() {
  local block="$1"
  local sanitized
  sanitized="$(sanitize_text "${block}")"
  if ! verify_ipv4_sanitized "${sanitized}"; then
    printf ''
    return 1
  fi
  printf '%s\n' "${sanitized}"
}

append_appendix() {
  local title="$1"
  local content="$2"
  APPENDIX_ENTRIES+=$(printf '\n[%s]\n%s\n' "${title}" "${content}")
}

timeout_run() {
  if [ -n "${TIME_BUDGET_REMAINING:-}" ] && [ "${TIME_BUDGET_REMAINING}" -le 0 ]; then
    return 1
  fi
  timeout 3 "$@"
}

update_budget() {
  local now
  now="$(date +%s)"
  TIME_BUDGET_REMAINING=$((TOTAL_TIME_BUDGET - (now - START_TIME)))
}

check_budget() {
  update_budget
  if [ "${TIME_BUDGET_REMAINING}" -le 0 ]; then
    return 1
  fi
  return 0
}

collect_interfaces() {
  if ! check_budget; then
    return
  fi
  if ! output="$(timeout_run ip -o link show up 2>&1 || true)"; then
    output=""
  fi
  local sanitized
  sanitized="$(sanitize_block "${output}")" || sanitized=""
  append_appendix 'ip -o link show up' "${sanitized}"
  local ifaces
  ifaces="$(
    printf '%s\n' "${output}" |
      awk -F': ' '{print $2}' |
      awk '{print $1}' |
      paste -sd',' - || true
  )"
  printf '%s\n' "${ifaces}"
}

collect_ipv4_addrs() {
  if ! check_budget; then
    return
  fi
  if ! output="$(timeout_run ip -4 -o addr show scope global 2>&1 || true)"; then
    output=""
  fi
  local sanitized
  sanitized="$(sanitize_block "${output}")" || sanitized=""
  append_appendix 'ip -4 -o addr show scope global' "${sanitized}"
  printf '%s\n' "${sanitized}"
}

collect_default_route() {
  if ! check_budget; then
    printf ';\n'
    return
  fi
  if ! output="$(timeout_run ip route show default 2>&1 || true)"; then
    output=""
  fi
  local sanitized
  sanitized="$(sanitize_block "${output}")" || sanitized=""
  append_appendix 'ip route show default' "${sanitized}"
  local iface=""
  local gw=""
  if [ -n "${output}" ]; then
    iface="$(
      printf '%s' "${output}" |
        awk '/default/ {for (i=1;i<=NF;i++) if ($i=="dev") {print $(i+1); exit}}'
    )"
    gw_raw="$(
      printf '%s' "${output}" |
        awk '/default/ {for (i=1;i<=NF;i++) if ($i=="via") {print $(i+1); exit}}'
    )"
    if [ -n "${gw_raw}" ]; then
      gw="$(mask_ipv4_token "${gw_raw}")"
    fi
  fi
  printf '%s;%s\n' "${iface}" "${gw}"
}

collect_dns() {
  if ! check_budget; then
    printf '0;unknown\n'
    return
  fi
  local servers=""
  local families=""
  local output=""
  if command -v resolvectl >/dev/null 2>&1; then
    output="$(timeout_run resolvectl dns 2>&1 || true)"
    if [ -z "${output}" ]; then
      output="$(timeout_run resolvectl status 2>&1 || true)"
    fi
  fi
  if [ -z "${output}" ] && [ -f /etc/resolv.conf ]; then
    output="$(cat /etc/resolv.conf 2>/dev/null || true)"
  fi
  local sanitized
  sanitized="$(sanitize_block "${output}")" || sanitized=""
  append_appendix 'dns config' "${sanitized}"
  if [ -n "${output}" ]; then
    servers="$(
      printf '%s\n' "${output}" |
        grep -Eo "${ipv4_pattern}" |
        wc -l |
        tr -d ' '
    )"
    families=""
    if printf '%s\n' "${output}" | grep -Eq '([0-9a-fA-F]{0,4}:){2,7}[0-9a-fA-F]{0,4}'; then
      if [ -n "${servers}" ] && [ "${servers}" -ne 0 ]; then
        families="IPv4/IPv6"
      else
        families="IPv6"
      fi
    else
      if [ -n "${servers}" ] && [ "${servers}" -ne 0 ]; then
        families="IPv4"
      fi
    fi
    if [ -z "${servers}" ]; then
      servers=0
    fi
    if [ -z "${families}" ]; then
      families="unknown"
    fi
  else
    servers=0
    families="unknown"
  fi
  printf '%s;%s\n' "${servers}" "${families}"
}

collect_mdns_status() {
  if ! check_budget; then
    printf 'no;0;;no;:0\n'
    return
  fi
  local active="no"
  local services_count=0
  local browse_output=""
  local mdns_names=""
  if command -v systemctl >/dev/null 2>&1; then
    if timeout_run systemctl is-active avahi-daemon >/dev/null 2>&1; then
      active="yes"
    fi
  fi

  if command -v avahi-browse >/dev/null 2>&1; then
    browse_output="$(timeout_run avahi-browse -rt _k3s-sugar-dev._tcp 2>&1 || true)"
    local sanitized
    sanitized="$(sanitize_block "${browse_output}")" || sanitized=""
    append_appendix 'avahi-browse -rt _k3s-sugar-dev._tcp' "${sanitized}"
    if [ -n "${browse_output}" ]; then
      services_count="$(
        printf '%s\n' "${browse_output}" |
          awk -F';' 'BEGIN{count=0} /^=/{count++} END{print count}'
      )"
      mdns_names="$(
        printf '%s\n' "${browse_output}" |
          awk -F';' 'NF>=4 && $1 ~ /^=/{print $4}' |
          sort -u |
          paste -sd',' - || true
      )"
    fi
  fi

  local resolve_status="no"
  local resolve_addr=""
  local resolve_rtt=""
  if command -v avahi-resolve >/dev/null 2>&1; then
    local start
    start="$(date +%s%3N)"
    local resolve_output
    resolve_output="$(timeout_run avahi-resolve -n sugarkube0.local 2>&1 || true)"
    local end
    end="$(date +%s%3N)"
    local elapsed
    elapsed=$((end - start))
    local sanitized
    sanitized="$(sanitize_block "${resolve_output}")" || sanitized=""
    append_appendix 'avahi-resolve -n sugarkube0.local' "${sanitized}"
    if printf '%s' "${resolve_output}" | grep -q 'sugarkube0'; then
      resolve_status="yes"
      resolve_addr="$(printf '%s' "${resolve_output}" | awk '{print $2}' | head -n1)"
      if [ -n "${resolve_addr}" ]; then
        resolve_addr="$(mask_ipv4_token "${resolve_addr}")"
      fi
      resolve_rtt="$elapsed"
    fi
  fi

  printf '%s;%s;%s;%s;%s\n' \
    "${active}" \
    "${services_count}" \
    "${mdns_names}" \
    "${resolve_status}" \
    "${resolve_addr}:${resolve_rtt}"
}

collect_mdns_journal() {
  if ! check_budget; then
    return
  fi
  local journal_output=""
  if command -v journalctl >/dev/null 2>&1; then
    journal_output="$(timeout_run journalctl -u avahi-daemon -n 50 --no-pager 2>&1 || true)"
  fi
  local sanitized
  sanitized="$(sanitize_block "${journal_output}")" || sanitized=""
  append_appendix 'journalctl -u avahi-daemon -n 50' "${sanitized}"
}

collect_listeners() {
  if ! check_budget; then
    printf 'no;no;no;no\n'
    return
  fi
  local ss_output=""
  if command -v ss >/dev/null 2>&1; then
    ss_output="$(timeout_run ss -lntu 2>&1 || true)"
    ss_output="$(printf '%s\n' "${ss_output}" | grep -E ':(6443|2379|2380|10250)\s' || true)"
  fi
  local sanitized
  sanitized="$(sanitize_block "${ss_output}")" || sanitized=""
  append_appendix 'ss -lntu (filtered)' "${sanitized}"
  local kube="no" etcd="no" etcd_peer="no" kubelet="no"
  if printf '%s' "${ss_output}" | grep -q ':6443'; then kube="yes"; fi
  if printf '%s' "${ss_output}" | grep -q ':2379'; then etcd="yes"; fi
  if printf '%s' "${ss_output}" | grep -q ':2380'; then etcd_peer="yes"; fi
  if printf '%s' "${ss_output}" | grep -q ':10250'; then kubelet="yes"; fi
  printf '%s;%s;%s;%s\n' "${kube}" "${etcd}" "${etcd_peer}" "${kubelet}"
}

collect_firewall() {
  if ! check_budget; then
    printf 'unknown\n'
    return
  fi
  local dataplane="unknown"
  if command -v nft >/dev/null 2>&1; then
    if nft list tables >/dev/null 2>&1; then
      dataplane="nftables"
      local nft_output
      nft_output="$(timeout_run nft -j list ruleset 2>/dev/null || true)"
      if [ -n "${nft_output}" ] && command -v jq >/dev/null 2>&1; then
        local filtered
        filtered="$(
          printf '%s' "${nft_output}" |
            jq -r "${jq_kube_filter}" 2>/dev/null || true
        )"
        local sanitized
        sanitized="$(sanitize_block "${filtered}")" || sanitized=""
        append_appendix 'nft -j list ruleset (KUBE-*)' "${sanitized}"
      fi
    fi
  fi
  if [ "${dataplane}" = "unknown" ]; then
    if command -v iptables >/dev/null 2>&1; then
      dataplane="iptables"
      local ipt_output ip6_output
      ipt_output="$(timeout_run iptables -S 2>&1 || true)"
      ip6_output="$(timeout_run ip6tables -S 2>&1 || true)"
      ipt_output="$(printf '%s\n' "${ipt_output}" | grep -Ev '([0-9]{1,3}\.){3}[0-9]{1,3}' || true)"
      ip6_output="$(
        printf '%s\n' "${ip6_output}" |
          grep -Ev '([0-9a-fA-F]{0,4}:){2,7}[0-9a-fA-F]{0,4}' || true
      )"
      local sanitized
      sanitized="$(sanitize_block "${ipt_output}\n${ip6_output}")" || sanitized=""
      append_appendix 'iptables/ip6tables -S (sanitized)' "${sanitized}"
    fi
  fi
  printf '%s\n' "${dataplane}"
}

collect_stage_label() {
  local stage="$1"
  if [ -n "${stage}" ]; then
    printf 'stage: %s\n' "${stage}"
  fi
}

main() {
  local stage=""
  if [ $# -gt 0 ]; then
    stage="$1"
  fi

  salt="${LOG_SALT:-$(head -c 16 /dev/urandom | xxd -p)}"

  START_TIME="$(date +%s)"
  TOTAL_TIME_BUDGET=15
  TIME_BUDGET_REMAINING=${TOTAL_TIME_BUDGET}

  local timestamp
  timestamp="$(date -u +%Y%m%dT%H%M%SZ)"

  APPENDIX_ENTRIES=""

  printf '# net_debug v1 (privacy-safe)\n'
  printf 'run_id: %s\n' "${timestamp}"
  printf 'pseudonymization: per-run-salt\n'
  collect_stage_label "${stage}"

  collect_mdns_journal
  local mdns_data
  mdns_data="$(collect_mdns_status)"
  local mdns_active mdns_services mdns_names mdns_resolve mdns_addr_rtt
  IFS=';' read -r mdns_active mdns_services mdns_names mdns_resolve mdns_addr_rtt <<EOF
${mdns_data}
EOF
  local resolve_addr="" resolve_rtt=""
  resolve_addr="${mdns_addr_rtt%%:*}"
  resolve_rtt="${mdns_addr_rtt##*:}"

  printf 'mdns.active: %s\n' "${mdns_active:-no}"
  printf 'mdns.services._k3s-sugar-dev._tcp.count: %s\n' "${mdns_services:-0}"
  printf 'mdns.sugarkube0.resolve: %s addr: %s rtt_ms: %s\n' \
    "${mdns_resolve:-no}" \
    "${resolve_addr:-unknown}" \
    "${resolve_rtt:-}"

  local iface_list
  iface_list="$(collect_interfaces)"
  iface_list="${iface_list%,}"
  printf 'iface.up: %s\n' "${iface_list:-none}"

  local addr_output
  addr_output="$(collect_ipv4_addrs)"
  if [ -n "${addr_output}" ]; then
    printf 'iface.addr.global: %s\n' "${addr_output}" | sed 's/  */ /g'
  fi

  local route_info
  route_info="$(collect_default_route)"
  local route_iface route_gw
  route_iface="${route_info%%;*}"
  route_gw="${route_info##*;}"
  printf 'route.default.iface: %s\n' "${route_iface:-none}"
  if [ -n "${route_gw}" ]; then
    printf 'route.default.gateway: %s\n' "${route_gw}"
  fi

  local dns_info
  dns_info="$(collect_dns)"
  local dns_count dns_fam
  dns_count="${dns_info%%;*}"
  dns_fam="${dns_info##*;}"
  printf 'dns.servers.count: %s families: %s\n' "${dns_count:-0}" "${dns_fam:-unknown}"

  local listener_info
  listener_info="$(collect_listeners)"
  local kube_api etcd etcd_peer kubelet
  IFS=';' read -r kube_api etcd etcd_peer kubelet <<EOF
${listener_info}
EOF
  printf 'kube.api.6443.listen: %s\n' "${kube_api:-no}"
  printf 'etcd.2379.listen: %s\n' "${etcd:-no}"
  printf 'etcd.2380.listen: %s\n' "${etcd_peer:-no}"
  printf 'kubelet.10250.listen: %s\n' "${kubelet:-no}"

  local dataplane
  dataplane="$(collect_firewall)"
  printf 'dataplane: %s\n' "${dataplane:-unknown}"

  if [ -n "${mdns_names}" ]; then
    local sanitized_names
    sanitized_names="$(sanitize_block "${mdns_names}")" || sanitized_names=""
    printf 'mdns.services._k3s-sugar-dev._tcp.instances: %s\n' "${sanitized_names}"
  fi

  printf '\n# sanitized appendix\n'
  printf '%s\n' "${APPENDIX_ENTRIES#\n}"
}

main "$@"
