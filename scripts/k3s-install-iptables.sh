#!/usr/bin/env bash
set -euo pipefail

installed="no"
alternatives_updated="no"
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

set_legacy_alternative() {
  local name="$1"
  local legacy_path="/usr/sbin/${name}-legacy"

  if ! command -v update-alternatives >/dev/null 2>&1; then
    return 0
  fi

  if [ ! -x "${legacy_path}" ]; then
    return 0
  fi

  local current_value=""
  if update-alternatives --query "${name}" >/dev/null 2>&1; then
    current_value="$(update-alternatives --query "${name}" | awk '/Value: / {print $2}')"
    if [ "${current_value}" = "${legacy_path}" ]; then
      return 0
    fi
  else
    update-alternatives --install \
      "/usr/sbin/${name}" "${name}" "${legacy_path}" 10 >/dev/null
  fi

  update-alternatives --set "${name}" "${legacy_path}" >/dev/null
  alternatives_updated="yes"
}

# Always prefer the legacy backend for kube-proxy compatibility.
set_legacy_alternative iptables
set_legacy_alternative ip6tables

iptables_cmd="$(command -v iptables)"

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

printf 'event=iptables_check installed=%s mode=%s version="%s" alternatives_updated=%s path="%s"\n' \
  "${installed}" "${mode}" "${version}" "${alternatives_updated}" "${iptables_cmd}"
