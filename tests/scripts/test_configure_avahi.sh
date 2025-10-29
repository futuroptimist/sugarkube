#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "${TMP_DIR}"' EXIT

CONF_PATH="${TMP_DIR}/avahi-daemon.conf"
LOG_DIR="${TMP_DIR}/logs"

cat <<'CONF' >"${CONF_PATH}"
# Sample Avahi configuration
[publish]
# Placeholder section to ensure additional sections remain untouched
publish-addresses=yes

[server]
allow-interfaces=eth1
use-ipv4=no
use-ipv6=yes
CONF

AVAHI_HOSTS_PATH="${TMP_DIR}/avahi.hosts"

ENV_VARS=(
  "SUGARKUBE_MDNS_INTERFACE=eth0"
  "SUGARKUBE_MDNS_IPV4_ONLY=1"
  "AVAHI_CONF_PATH=${CONF_PATH}"
  "SUGARKUBE_LOG_DIR=${LOG_DIR}"
  "SYSTEMCTL_BIN="
  "SUGARKUBE_AVAHI_HOSTS_PATH=${AVAHI_HOSTS_PATH}"
  "SUGARKUBE_EXPECTED_IPV4=10.0.0.10"
  "HOSTNAME=test-node.local"
)

( export "${ENV_VARS[@]}"; bash "${REPO_ROOT}/scripts/configure_avahi.sh" )

if ! grep -q '^allow-interfaces=eth0$' "${CONF_PATH}"; then
  echo "allow-interfaces was not updated" >&2
  exit 1
fi

if ! grep -q '^use-ipv4=yes$' "${CONF_PATH}"; then
  echo "use-ipv4 was not forced to yes" >&2
  exit 1
fi

if ! grep -q '^use-ipv6=no$' "${CONF_PATH}"; then
  echo "use-ipv6 was not forced to no" >&2
  exit 1
fi

if ! grep -q '^10.0.0.10 test-node.local$' "${AVAHI_HOSTS_PATH}"; then
  echo "Avahi hosts entry was not created" >&2
  exit 1
fi

if [ ! -f "${CONF_PATH}.bak" ]; then
  echo "Backup was not created" >&2
  exit 1
fi

SECOND_COPY="${TMP_DIR}/avahi-second.conf"
cp "${CONF_PATH}" "${SECOND_COPY}"
SECOND_HOSTS_COPY="${TMP_DIR}/avahi.hosts.second"
cp "${AVAHI_HOSTS_PATH}" "${SECOND_HOSTS_COPY}"

( export "${ENV_VARS[@]}"; bash "${REPO_ROOT}/scripts/configure_avahi.sh" )

if ! cmp -s "${CONF_PATH}" "${SECOND_COPY}"; then
  echo "Configuration changed on second run" >&2
  exit 1
fi

if ! cmp -s "${AVAHI_HOSTS_PATH}" "${SECOND_HOSTS_COPY}"; then
  echo "Avahi hosts file changed on second run" >&2
  exit 1
fi

echo "configure_avahi.sh idempotency test passed"

# Test error handling with malformed configuration file
echo "Testing error handling with malformed configuration..."

MALFORMED_CONF="${TMP_DIR}/malformed-avahi.conf"
cat <<'MALFORMED' >"${MALFORMED_CONF}"
[publish]
publish-workstation=yes
use-ipv4=yes
use-ipv6=no
MALFORMED

MALFORMED_ENV_VARS=(
  "SUGARKUBE_MDNS_INTERFACE=eth0"
  "SUGARKUBE_MDNS_IPV4_ONLY=1"
  "AVAHI_CONF_PATH=${MALFORMED_CONF}"
  "SUGARKUBE_LOG_DIR=${LOG_DIR}"
  "SYSTEMCTL_BIN="
  "SUGARKUBE_AVAHI_HOSTS_PATH=${AVAHI_HOSTS_PATH}"
  "SUGARKUBE_EXPECTED_IPV4=10.0.0.10"
  "HOSTNAME=test-node.local"
)

# This should not fail even with malformed input
if ! ( export "${MALFORMED_ENV_VARS[@]}"; bash "${REPO_ROOT}/scripts/configure_avahi.sh" ); then
  echo "Script failed with malformed configuration" >&2
  exit 1
fi

# Verify the script created a valid output despite malformed input
if ! grep -q '^allow-interfaces=eth0$' "${MALFORMED_CONF}"; then
  echo "allow-interfaces was not set correctly with malformed input" >&2
  exit 1
fi

echo "configure_avahi.sh error handling test passed"
