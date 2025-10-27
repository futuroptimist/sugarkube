#!/usr/bin/env bash
set -euo pipefail

installed="no"
missing=()

if ! command -v iptables >/dev/null 2>&1; then
  missing+=(iptables)
fi

if ! command -v ip6tables >/dev/null 2>&1; then
  missing+=(ip6tables)
fi

if [ "${#missing[@]}" -gt 0 ]; then
  export DEBIAN_FRONTEND="noninteractive"
  apt-get update >/dev/null
  apt-get install -y iptables >/dev/null
  installed="yes"
fi

if ! command -v iptables >/dev/null 2>&1 || ! command -v ip6tables >/dev/null 2>&1; then
  echo "iptables or ip6tables is unavailable after installation attempt" >&2
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

printf 'event=iptables_check installed=%s mode=%s version="%s"\n' "${installed}" "${mode}" "${version}"
