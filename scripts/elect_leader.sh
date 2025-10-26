#!/usr/bin/env bash
set -euo pipefail

trim_trailing_dots() {
  local value="$1"
  while [[ "${value}" == *'.' ]]; do
    value="${value%.}"
  done
  printf '%s\n' "${value}"
}

normalize_lower() {
  printf '%s\n' "$1" | tr '[:upper:]' '[:lower:]'
}

primary_mac_address() {
  if ! command -v ip >/dev/null 2>&1; then
    return 1
  fi

  local line iface mac
  while IFS= read -r line; do
    iface="${line#* }"
    iface="${iface%%:*}"
    iface="${iface// /}"
    if [ -z "${iface}" ] || [ "${iface}" = "lo" ]; then
      continue
    fi
    if [[ " ${line} " != *" link/ether "* ]]; then
      continue
    fi
    mac="$(printf '%s\n' "${line}" | awk 'match($0, /link\/ether ([0-9a-f:]+)/, m) {print m[1]; exit}')"
    if [ -n "${mac}" ]; then
      printf '%s\n' "${mac}"
      return 0
    fi
  done < <(ip -o link 2>/dev/null)

  return 1
}

build_expected_hosts() {
  local count="$1"
  local prefix="$2"
  local domain="$3"

  if [ -z "${count}" ]; then
    return 1
  fi
  if ! [[ "${count}" =~ ^[0-9]+$ ]]; then
    return 1
  fi
  if [ "${count}" -le 0 ]; then
    return 1
  fi

  local i candidate fqdn
  for ((i = 0; i < count; i++)); do
    candidate="${prefix}${i}"
    candidate="$(normalize_lower "${candidate}")"
    if [ -n "${domain}" ]; then
      fqdn="${candidate}.${domain}"
    else
      fqdn="${candidate}"
    fi
    printf '%s\n' "${fqdn}"
  done

  return 0
}

resolve_hostname() {
  local fqdn
  fqdn="$(hostname -f 2>/dev/null || true)"
  fqdn="$(trim_trailing_dots "${fqdn}")"
  fqdn="$(normalize_lower "${fqdn}")"
  if [ -n "${fqdn}" ]; then
    printf '%s\n' "${fqdn}"
    return 0
  fi

  fqdn="$(hostname 2>/dev/null || true)"
  fqdn="$(trim_trailing_dots "${fqdn}")"
  fqdn="$(normalize_lower "${fqdn}")"
  if [ -n "${fqdn}" ]; then
    printf '%s\n' "${fqdn}"
    return 0
  fi

  printf 'unknown\n'
  return 0
}

main() {
  local raw_key domain base host_short mac normalized_mac full_key expected_output winner="no"

  raw_key="$(resolve_hostname)"
  host_short="$(hostname -s 2>/dev/null || true)"
  host_short="$(trim_trailing_dots "${host_short}")"
  host_short="$(normalize_lower "${host_short}")"
  if [ -z "${host_short}" ]; then
    host_short="${raw_key%%.*}"
  fi

  domain=""
  base="${raw_key}"
  if [[ "${raw_key}" == *.* ]]; then
    base="${raw_key%%.*}"
    domain="${raw_key#*.}"
  fi
  domain="$(trim_trailing_dots "${domain}")"

  mac="$(primary_mac_address || true)"
  if [ -n "${mac}" ]; then
    normalized_mac="${mac//:/}"
    full_key="${raw_key}_${normalized_mac}"
  else
    full_key="${raw_key}"
  fi

  local -a expected_hosts=()
  local expected_list prefix
  prefix="${SUGARKUBE_NODE_PREFIX:-sugarkube}"
  prefix="$(normalize_lower "${prefix}")"
  if expected_output="$(build_expected_hosts "${SUGARKUBE_SERVERS:-}" "${prefix}" "${domain}" 2>/dev/null || true)"; then
    if [ -n "${expected_output}" ]; then
      mapfile -t expected_hosts < <(printf '%s\n' "${expected_output}" | sort -u)
    fi
  fi

  if [ "${#expected_hosts[@]}" -gt 0 ]; then
    local smallest="${expected_hosts[0]}"
    local candidate
    for candidate in "${expected_hosts[@]}"; do
      if [[ "${candidate}" < "${smallest}" ]]; then
        smallest="${candidate}"
      fi
    done

    local matches_expected=0
    for candidate in "${expected_hosts[@]}"; do
      if [ "${raw_key}" = "${candidate}" ]; then
        matches_expected=1
        break
      fi
      if [ "${host_short}" = "${candidate%%.*}" ]; then
        matches_expected=1
        break
      fi
      if [ "${base}" = "${candidate%%.*}" ]; then
        matches_expected=1
        break
      fi
    done

    if [ "${matches_expected}" -eq 1 ]; then
      local comparison_key="${raw_key}"
      if [ -n "${domain}" ] && [[ "${comparison_key}" != *'.'* ]]; then
        comparison_key="${comparison_key}.${domain}"
      fi
      if [ "${comparison_key}" = "${smallest}" ] || [ "${base}" = "${smallest%%.*}" ]; then
        winner="yes"
      fi
    fi
  else
    if [[ "${base}" == *0 ]]; then
      winner="yes"
    fi
  fi

  printf 'winner=%s\n' "${winner}"
  printf 'key=%s\n' "${full_key}"
}

main "$@"
