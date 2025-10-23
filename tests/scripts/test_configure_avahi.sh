#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

TMP_DIR="$(mktemp -d)"
trap 'rm -rf "${TMP_DIR}"' EXIT

CONF_PATH="${TMP_DIR}/avahi-daemon.conf"
LOG_DIR="${TMP_DIR}/logs"

cat >"${CONF_PATH}" <<'CONF'
# Sample config without server section
[wide-area]
enable-wide-area=yes
CONF

ORIGINAL_CONTENT="$(cat "${CONF_PATH}")"

SUGARKUBE_MDNS_INTERFACE="eno1" \
SUGARKUBE_MDNS_IPV4_ONLY="1" \
AVAHI_CONF_PATH="${CONF_PATH}" \
SUGARKUBE_LOG_DIR="${LOG_DIR}" \
AVAHI_SKIP_SYSTEMCTL="1" \
"${REPO_ROOT}/scripts/configure_avahi.sh"

grep -q '^\[server\]' "${CONF_PATH}"
grep -q '^allow-interfaces=eno1$' "${CONF_PATH}"
grep -q '^use-ipv4=yes$' "${CONF_PATH}"
grep -q '^use-ipv6=no$' "${CONF_PATH}"

if [ ! -f "${CONF_PATH}.bak" ]; then
  echo "Expected backup file ${CONF_PATH}.bak to exist" >&2
  exit 1
fi

if ! diff -u <(printf '%s\n' "${ORIGINAL_CONTENT}") "${CONF_PATH}.bak" >/dev/null; then
  echo "Backup file does not match original contents" >&2
  exit 1
fi

first_hash="$(sha256sum "${CONF_PATH}" | awk '{print $1}')"

SUGARKUBE_MDNS_INTERFACE="eno1" \
SUGARKUBE_MDNS_IPV4_ONLY="1" \
AVAHI_CONF_PATH="${CONF_PATH}" \
SUGARKUBE_LOG_DIR="${LOG_DIR}" \
AVAHI_SKIP_SYSTEMCTL="1" \
"${REPO_ROOT}/scripts/configure_avahi.sh"

second_hash="$(sha256sum "${CONF_PATH}" | awk '{print $1}')"

if [ "${first_hash}" != "${second_hash}" ]; then
  echo "Configuration changed on second run" >&2
  exit 1
fi

echo "configure_avahi.sh test passed"
