#!/usr/bin/env bash
set -euo pipefail

installed="no"
packages=()

if ! command -v iptables >/dev/null 2>&1; then
  packages+=(iptables)
fi

if ! command -v ip6tables >/dev/null 2>&1; then
  needs_iptables=1
  for pkg in "${packages[@]}"; do
    if [[ "$pkg" == "iptables" ]]; then
      needs_iptables=0
      break
    fi
  done
  if [[ ${needs_iptables:-1} -eq 1 ]]; then
    packages+=(iptables)
  fi
fi

if ! command -v nft >/dev/null 2>&1; then
  packages+=(nftables)
fi

if [ "${#packages[@]}" -gt 0 ]; then
  export DEBIAN_FRONTEND="noninteractive"
  apt-get update >/dev/null
  apt-get install -y "${packages[@]}" >/dev/null
  installed="yes"
fi

if ! command -v iptables >/dev/null 2>&1 || ! command -v ip6tables >/dev/null 2>&1; then
  echo "iptables or ip6tables is unavailable after installation attempt" >&2
  exit 1
fi

if ! command -v nft >/dev/null 2>&1; then
  echo "nft is unavailable after installation attempt" >&2
  exit 1
fi

version_line="$(iptables -V 2>/dev/null | head -n1 || true)"
mode="unknown"
version="unavailable"

if [ -n "${version_line}" ]; then
  version="${version_line#iptables }"
  if printf '%s' "${version_line}" | grep -qi 'nf_tables'; then
    mode="nft"
  elif printf '%s' "${version_line}" | grep -qi 'legacy'; then
    mode="legacy"
  fi
fi

nft_status="missing"
if command -v nft >/dev/null 2>&1; then
  nft_status="present"
fi

printf 'event=iptables_check installed=%s mode=%s version="%s" nft=%s\n' \
  "${installed}" "${mode}" "${version}" "${nft_status}"
