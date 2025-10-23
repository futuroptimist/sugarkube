#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SCRIPT_PATH="${ROOT_DIR}/scripts/configure_avahi.sh"

TMP_DIR="$(mktemp -d)"
trap 'rm -rf "${TMP_DIR}"' EXIT

CONF_PATH="${TMP_DIR}/avahi-daemon.conf"
LOG_DIR="${TMP_DIR}/logs"

cat <<'CONFIG' >"${CONF_PATH}"
[server]
# existing comment
enable-dbus=yes

[publish]
publish-addresses=yes
CONFIG

export SUGARKUBE_MDNS_INTERFACE="eth1"
export SUGARKUBE_MDNS_IPV4_ONLY="1"
export AVAHI_CONF_PATH="${CONF_PATH}"
export SUGARKUBE_LOG_DIR="${LOG_DIR}"

bash "${SCRIPT_PATH}"

if [ ! -f "${CONF_PATH}.bak" ]; then
  echo "Expected backup ${CONF_PATH}.bak to exist" >&2
  exit 1
fi

if ! grep -q '^allow-interfaces=eth1$' "${CONF_PATH}"; then
  echo "allow-interfaces not configured correctly" >&2
  exit 1
fi

if [ "${SUGARKUBE_MDNS_IPV4_ONLY}" = "1" ]; then
  if ! grep -q '^use-ipv4=yes$' "${CONF_PATH}"; then
    echo "use-ipv4=yes missing" >&2
    exit 1
  fi
  if ! grep -q '^use-ipv6=no$' "${CONF_PATH}"; then
    echo "use-ipv6=no missing" >&2
    exit 1
  fi
fi

cp "${CONF_PATH}" "${TMP_DIR}/after_first.conf"

bash "${SCRIPT_PATH}"

if ! cmp -s "${TMP_DIR}/after_first.conf" "${CONF_PATH}"; then
  echo "Configuration changed on second run" >&2
  exit 1
fi

echo "configure_avahi.sh test passed"
