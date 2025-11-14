#!/usr/bin/env bash
set -euo pipefail

command_timeout() {
  if command -v timeout >/dev/null 2>&1; then
    timeout --signal=TERM 3 "$@"
  else
    "$@"
  fi
}

salt="${LOG_SALT:-}"
if [ -z "${salt}" ]; then
  salt="$(head -c 16 /dev/urandom | xxd -p)"
fi

hash_token() {
  printf '%s' "${salt}:$1" | sha256sum | awk '{print substr($1,1,6)}'
}

mask_ipv4_value() {
  local ip="$1"
  case "${ip}" in
    127.0.0.1|0.0.0.0)
      printf '%s' "${ip}"
      return 0
      ;;
    10.*)
      printf '10.%s' "$(hash_token "${ip}")"
      return 0
      ;;
    172.*)
      local second
      IFS='.' read -r _ second _ _ <<<"${ip}"
      if [ -n "${second}" ] && [ "${second}" -ge 16 ] && [ "${second}" -le 31 ]; then
        printf '172.%s' "$(hash_token "${ip}")"
        return 0
      fi
      ;;
    192.168.*)
      printf '192.168.%s' "$(hash_token "${ip}")"
      return 0
      ;;
  esac
  printf 'PUBLIC-%s' "$(hash_token "${ip}")"
}

mask_ipv6_value() {
  printf 'IPv6-%s' "$(hash_token "$1")"
}

mask_mac_value() {
  printf 'MAC-%s' "$(hash_token "$1")"
}

mask_host_value() {
  local host="$1"
  if printf '%s' "${host}" | grep -Eq '^sugarkube[0-9]+(\.local)?$'; then
    printf '%s' "${host}"
  else
    printf 'host-%s' "$(hash_token "${host}")"
  fi
}

escape_sed_pattern() {
  printf '%s' "$1" | sed -e 's/[\&/]/\\&/g'
}

sanitize_tokens() {
  sed -E \
    -e 's/(Authorization:)[[:space:]]*(Bearer[[:space:]]*)?[^[:space:]]+/\1 \2[REDACTED]/Ig' \
    -e 's/([Bb]earer[[:space:]]+)[^[:space:]]+/\1[REDACTED]/g' \
    -e 's/([Tt]oken[:=])[[:space:]]*[^[:space:]]+/\1[REDACTED]/g'
}

apply_mask_ipv4() {
  local data
  data="$(cat)"
  local ip replacement escaped_ip escaped_repl
  while IFS= read -r ip; do
    [ -n "${ip}" ] || continue
    replacement="$(mask_ipv4_value "${ip}")"
    escaped_ip="$(escape_sed_pattern "${ip}")"
    escaped_repl="$(escape_sed_pattern "${replacement}")"
    data="$(printf '%s' "${data}" | sed "s/${escaped_ip}/${escaped_repl}/g")"
  done < <(printf '%s' "${data}" | grep -Eo '([0-9]{1,3}\.){3}[0-9]{1,3}' | sort -u)
  printf '%s' "${data}"
}

apply_mask_ipv6() {
  local data
  data="$(cat)"
  local token replacement escaped_token escaped_repl
  while IFS= read -r token; do
    [ -n "${token}" ] || continue
    replacement="$(mask_ipv6_value "${token}")"
    escaped_token="$(escape_sed_pattern "${token}")"
    escaped_repl="$(escape_sed_pattern "${replacement}")"
    data="$(printf '%s' "${data}" | sed "s/${escaped_token}/${escaped_repl}/g")"
  done < <(printf '%s' "${data}" | grep -Eio '([0-9a-f]{0,4}:){2,7}[0-9a-f]{0,4}' | sort -u)
  printf '%s' "${data}"
}

apply_mask_mac() {
  local data
  data="$(cat)"
  local mac replacement escaped_mac escaped_repl
  while IFS= read -r mac; do
    [ -n "${mac}" ] || continue
    replacement="$(mask_mac_value "${mac}")"
    escaped_mac="$(escape_sed_pattern "${mac}")"
    escaped_repl="$(escape_sed_pattern "${replacement}")"
    data="$(printf '%s' "${data}" | sed "s/${escaped_mac}/${escaped_repl}/g")"
  done < <(printf '%s' "${data}" | grep -Eio '([0-9a-f]{2}:){5}[0-9a-f]{2}' | sort -u)
  printf '%s' "${data}"
}

apply_mask_hosts() {
  local data
  data="$(cat)"
  local host replacement escaped_host escaped_repl
  while IFS= read -r host; do
    [ -n "${host}" ] || continue
    if printf '%s' "${host}" | grep -Eq '^sugarkube[0-9]+(\.local)?$'; then
      continue
    fi
    replacement="$(mask_host_value "${host}")"
    escaped_host="$(escape_sed_pattern "${host}")"
    escaped_repl="$(escape_sed_pattern "${replacement}")"
    data="$(printf '%s' "${data}" | sed "s/${escaped_host}/${escaped_repl}/g")"
  done < <(printf '%s' "${data}" | grep -Eo '([[:alnum:]-]+\.)+[[:alnum:]-]+' | sort -u)
  printf '%s' "${data}"
}

sanitize_block() {
  sanitize_tokens | apply_mask_ipv4 | apply_mask_mac | apply_mask_ipv6 | apply_mask_hosts
}

appendix_data=""
append_command_output() {
  local title="$1"
  local content="$2"
  if [ -z "${appendix_data}" ]; then
    appendix_data=$'# sanitized appendix\n'
  fi
  appendix_data+="command: ${title}\n"
  if [ -n "${content}" ]; then
    appendix_data+="${content}\n"
  else
    appendix_data+="(no output)\n"
  fi
}

port_label() {
  case "$1" in
    6443) printf 'kube.api.6443' ;;
    2379) printf 'etcd.2379' ;;
    2380) printf 'etcd.2380' ;;
    10250) printf 'kubelet.10250' ;;
    *) printf 'port.%s' "$1" ;;
  esac
}

run_id="$(date -u +%Y%m%dT%H%M%SZ)"

printf '# net_debug v1 (privacy-safe)\n'
printf 'run_id: %s\n' "${run_id}"
printf 'salt_notice: per-run random salt applied\n'

iface_list=""
if command -v ip >/dev/null 2>&1; then
  if raw_ip_link="$(command_timeout ip -o link show up 2>/dev/null)"; then
    sanitized_link="$(printf '%s' "${raw_ip_link}" | sanitize_block)"
    append_command_output 'ip -o link show up' "${sanitized_link}"
    while IFS= read -r line; do
      [ -n "${line}" ] || continue
      name="$(printf '%s' "${line}" | awk -F': ' '{print $2}' | awk '{print $1}')"
      [ -n "${name}" ] || continue
      mtu="$(printf '%s' "${line}" | sed -n 's/.*mtu \([0-9]\+\).*/\1/p')"
      if printf '%s' "${line}" | grep -q 'state[[:space:]]\+UP'; then
        state="up"
      else
        state="unknown"
      fi
      entry="${name}(${state},mtu${mtu:-na})"
      if [ -n "${iface_list}" ]; then
        iface_list+="${entry},"
      else
        iface_list="${entry},"
      fi
    done <<<"${raw_ip_link}"
  fi
fi
iface_list="${iface_list%,}"
if [ -n "${iface_list}" ]; then
  printf 'iface.up: %s\n' "${iface_list}"
else
  printf 'iface.up: none\n'
fi

addr_summary=""
if command -v ip >/dev/null 2>&1; then
  if raw_ip_addr="$(command_timeout ip -4 -o addr show scope global 2>/dev/null)"; then
    sanitized_addr="$(printf '%s' "${raw_ip_addr}" | sanitize_block)"
    append_command_output 'ip -4 -o addr show scope global' "${sanitized_addr}"
    while IFS= read -r line; do
      [ -n "${line}" ] || continue
      set -- ${line}
      iface="${2:-}"
      inet="${4:-}"
      if [ -z "${iface}" ] || [ -z "${inet}" ]; then
        continue
      fi
      cidr="${inet##*/}"
      ip_value="${inet%%/*}"
      masked="$(mask_ipv4_value "${ip_value}")"
      addr_summary+="${iface}=${masked}/${cidr} "
    done <<<"${raw_ip_addr}"
  fi
fi
addr_summary="${addr_summary%% }"
if [ -n "${addr_summary}" ]; then
  printf 'addr.v4: %s\n' "${addr_summary}"
else
  printf 'addr.v4: none\n'
fi

route_iface=""
if command -v ip >/dev/null 2>&1; then
  if raw_route="$(command_timeout ip route show default 2>/dev/null)"; then
    sanitized_route="$(printf '%s' "${raw_route}" | sanitize_block)"
    append_command_output 'ip route show default' "${sanitized_route}"
    first_line="$(printf '%s' "${raw_route}" | head -n1)"
    if printf '%s' "${first_line}" | grep -q ' dev '; then
      route_iface="$(printf '%s' "${first_line}" | sed -n 's/.* dev \([^[:space:]]\+\).*/\1/p')"
    fi
    if printf '%s' "${first_line}" | grep -q ' via '; then
      gw="$(printf '%s' "${first_line}" | sed -n 's/.* via \([^[:space:]]\+\).*/\1/p')"
      if [ -n "${gw}" ]; then
        gw_masked="$(mask_ipv4_value "${gw}")"
        printf 'route.default.gateway: %s\n' "${gw_masked}"
      fi
    fi
  fi
fi
if [ -n "${route_iface}" ]; then
  printf 'route.default.iface: %s\n' "${route_iface}"
else
  printf 'route.default.iface: none\n'
fi

print_dns_summary() {
  local total="$1"
  local families="$2"
  printf 'dns.servers.count: %s families: %s\n' "${total}" "${families:-none}"
}

dns_printed=0
if command -v resolvectl >/dev/null 2>&1; then
  if raw_resolve="$(command_timeout resolvectl dns 2>/dev/null)"; then
    sanitized_resolve="$(printf '%s' "${raw_resolve}" | sanitize_block)"
    append_command_output 'resolvectl dns' "${sanitized_resolve}"
    v4_count=0
    v6_count=0
    while IFS= read -r token; do
      case "${token}" in
        *.*)
          v4_count=$((v4_count + 1))
          ;;
        *:*)
          v6_count=$((v6_count + 1))
          ;;
      esac
    done < <(printf '%s' "${raw_resolve}" | grep -Eo '([0-9]{1,3}\.){3}[0-9]{1,3}|([0-9a-fA-F]{0,4}:){2,7}[0-9a-fA-F]{0,4}')
    families=""
    if [ "${v4_count}" -gt 0 ]; then
      families="IPv4"
    fi
    if [ "${v6_count}" -gt 0 ]; then
      if [ -n "${families}" ]; then
        families+="/"
      fi
      families+="IPv6"
    fi
    total=$((v4_count + v6_count))
    print_dns_summary "${total}" "${families}"
    dns_printed=1
  fi
fi
if [ "${dns_printed}" -eq 0 ]; then
  resolv_conf="/etc/resolv.conf"
  if [ -r "${resolv_conf}" ]; then
    raw_conf="$(cat "${resolv_conf}")"
    sanitized_conf="$(printf '%s' "${raw_conf}" | sanitize_block)"
    append_command_output '/etc/resolv.conf' "${sanitized_conf}"
    v4_count=$(printf '%s' "${raw_conf}" | grep -E '^nameserver[[:space:]]+([0-9]{1,3}\.){3}[0-9]{1,3}' | wc -l | tr -d ' ')
    v6_count=$(printf '%s' "${raw_conf}" | grep -E '^nameserver[[:space:]]+([0-9a-fA-F]{0,4}:){2,7}[0-9a-fA-F]{0,4}' | wc -l | tr -d ' ')
    families=""
    if [ "${v4_count}" -gt 0 ]; then
      families="IPv4"
    fi
    if [ "${v6_count}" -gt 0 ]; then
      if [ -n "${families}" ]; then
        families+="/"
      fi
      families+="IPv6"
    fi
    total=$((v4_count + v6_count))
    print_dns_summary "${total}" "${families}"
  else
    print_dns_summary 0 none
  fi
fi

mdns_active="no"
if command -v systemctl >/dev/null 2>&1; then
  if command_timeout systemctl is-active --quiet avahi-daemon 2>/dev/null; then
    mdns_active="yes"
  else
    mdns_active="no"
  fi
fi
printf 'mdns.active: %s\n' "${mdns_active}"

if command -v journalctl >/dev/null 2>&1; then
  if journal_output="$(command_timeout journalctl -u avahi-daemon -n 50 2>/dev/null)"; then
    sanitized_journal="$(printf '%s' "${journal_output}" | sanitize_block | sed '/ TXT /d')"
    append_command_output 'journalctl -u avahi-daemon -n 50' "${sanitized_journal}"
  fi
fi

service_count=0
if command -v avahi-browse >/dev/null 2>&1; then
  if browse_output="$(command_timeout avahi-browse -rt _k3s-sugar-dev._tcp 2>/dev/null)"; then
    sanitized_browse="$(printf '%s' "${browse_output}" | sanitize_block)"
    append_command_output 'avahi-browse -rt _k3s-sugar-dev._tcp' "${sanitized_browse}"
    service_count=$(printf '%s' "${browse_output}" | grep -E '^=' | wc -l | tr -d ' ')
  fi
fi
printf 'mdns.services._k3s-sugar-dev._tcp.count: %s\n' "${service_count}"

resolve_status="no"
resolve_addr="na"
resolve_rtt="na"
if command -v avahi-resolve >/dev/null 2>&1; then
  start_ms="$(date +%s%3N 2>/dev/null || python3 - <<'PY'
import time
print(int(time.time()*1000))
PY
)"
  if resolve_output="$(command_timeout avahi-resolve -n sugarkube0.local 2>/dev/null)"; then
    end_ms="$(date +%s%3N 2>/dev/null || python3 - <<'PY'
import time
print(int(time.time()*1000))
PY
)"
    resolve_status="yes"
    addr_token="$(printf '%s' "${resolve_output}" | awk '{print $NF}')"
    if printf '%s' "${addr_token}" | grep -Eq '^([0-9]{1,3}\.){3}[0-9]{1,3}$'; then
      resolve_addr="$(mask_ipv4_value "${addr_token}")"
    else
      resolve_addr="$(mask_ipv6_value "${addr_token}")"
    fi
    if [ -n "${start_ms}" ] && [ -n "${end_ms}" ]; then
      resolve_rtt=$((end_ms - start_ms))
    fi
    sanitized_resolve="$(printf '%s' "${resolve_output}" | sanitize_block)"
    append_command_output 'avahi-resolve -n sugarkube0.local' "${sanitized_resolve}"
  fi
fi
printf 'mdns.sugarkube0.resolve: %s addr: %s rtt_ms: %s\n' "${resolve_status}" "${resolve_addr}" "${resolve_rtt}"

ss_output=""
if command -v ss >/dev/null 2>&1; then
  if ss_output="$(command_timeout ss -lntu 2>/dev/null | grep -E ':(6443|2379|2380|10250)[[:space:]]' || true)"; then
    sanitized_ss="$(printf '%s' "${ss_output}" | sanitize_block)"
    append_command_output "ss -lntu | grep -E ':(6443|2379|2380|10250)\\s'" "${sanitized_ss}"
  fi
fi
for port in 6443 2379 2380 10250; do
  label="$(port_label "${port}")"
  if [ -n "${ss_output}" ] && printf '%s' "${ss_output}" | grep -q ":${port}[[:space:]]"; then
    printf '%s.listen: yes\n' "${label}"
  elif [ -n "${ss_output}" ]; then
    printf '%s.listen: no\n' "${label}"
  else
    printf '%s.listen: unknown\n' "${label}"
  fi
done

dataplane="unknown"
if command -v nft >/dev/null 2>&1; then
  dataplane="nftables"
  if rules_json="$(command_timeout nft -j list ruleset 2>/dev/null)"; then
    if command -v jq >/dev/null 2>&1; then
      filtered="$(printf '%s' "${rules_json}" | jq '.nftables[]? | select(.chain.name? | test("^(kube-proxy|KUBE-)")).chain | {name, hook, policy, counter: .counter}')"
      sanitized_filtered="$(printf '%s' "${filtered}" | sanitize_block)"
      append_command_output 'nft -j list ruleset | jq kube chains' "${sanitized_filtered}"
    fi
  fi
elif command -v iptables >/dev/null 2>&1; then
  dataplane="iptables"
  if ipt_output="$(command_timeout iptables -S 2>/dev/null)"; then
    sanitized_ipt="$(printf '%s' "${ipt_output}" | grep -vE '([0-9]{1,3}\.){3}[0-9]{1,3}' | sanitize_block)"
    append_command_output 'iptables -S' "${sanitized_ipt}"
  fi
  if command -v ip6tables >/dev/null 2>&1; then
    if ip6t_output="$(command_timeout ip6tables -S 2>/dev/null)"; then
      sanitized_ip6t="$(printf '%s' "${ip6t_output}" | sanitize_block)"
      append_command_output 'ip6tables -S' "${sanitized_ip6t}"
    fi
  fi
fi
printf 'dataplane: %s\n' "${dataplane}"

if [ -n "${appendix_data}" ]; then
  printf '\n%s' "${appendix_data}"
fi
