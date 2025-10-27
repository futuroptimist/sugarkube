#!/usr/bin/env bash
set -euo pipefail

# Test for the specific Python syntax error that was fixed
# This test ensures that the configure_avahi.sh script handles
# malformed Avahi configuration files gracefully

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "${TMP_DIR}"' EXIT

CONF_PATH="${TMP_DIR}/avahi-daemon.conf"
LOG_DIR="${TMP_DIR}/logs"

# Create a configuration file that could cause Python syntax errors
# This simulates the original issue where the Python script was trying
# to execute the Avahi config file as Python code
cat <<'CONF' >"${CONF_PATH}"
[publish]
publish-workstation=yes

[server]
allow-interfaces=eth1
use-ipv4=yes
use-ipv6=no
CONF

ENV_VARS=(
  "SUGARKUBE_MDNS_INTERFACE=eth0"
  "SUGARKUBE_MDNS_IPV4_ONLY=1"
  "AVAHI_CONF_PATH=${CONF_PATH}"
  "SUGARKUBE_LOG_DIR=${LOG_DIR}"
  "SYSTEMCTL_BIN="
)

echo "Testing configure_avahi.sh with potentially problematic configuration..."

# Run the script - it should not fail with Python syntax errors
if ! ( export "${ENV_VARS[@]}"; bash "${REPO_ROOT}/scripts/configure_avahi.sh" ); then
  echo "ERROR: configure_avahi.sh failed with Python syntax error" >&2
  exit 1
fi

# Verify the script processed the configuration correctly
if ! grep -q '^allow-interfaces=eth0$' "${CONF_PATH}"; then
  echo "ERROR: allow-interfaces was not updated correctly" >&2
  exit 1
fi

if ! grep -q '^publish-workstation=yes$' "${CONF_PATH}"; then
  echo "ERROR: publish-workstation was not preserved correctly" >&2
  exit 1
fi

# Test with a completely empty configuration file
EMPTY_CONF="${TMP_DIR}/empty-avahi.conf"
touch "${EMPTY_CONF}"

EMPTY_ENV_VARS=(
  "SUGARKUBE_MDNS_INTERFACE=eth0"
  "SUGARKUBE_MDNS_IPV4_ONLY=1"
  "AVAHI_CONF_PATH=${EMPTY_CONF}"
  "SUGARKUBE_LOG_DIR=${LOG_DIR}"
  "SYSTEMCTL_BIN="
)

echo "Testing configure_avahi.sh with empty configuration file..."

if ! ( export "${EMPTY_ENV_VARS[@]}"; bash "${REPO_ROOT}/scripts/configure_avahi.sh" ); then
  echo "ERROR: configure_avahi.sh failed with empty configuration file" >&2
  exit 1
fi

# Verify the script created a valid configuration from scratch
if ! grep -q '^allow-interfaces=eth0$' "${EMPTY_CONF}"; then
  echo "ERROR: allow-interfaces was not set in empty configuration" >&2
  exit 1
fi

if ! grep -q '^publish-workstation=yes$' "${EMPTY_CONF}"; then
  echo "ERROR: publish-workstation was not set in empty configuration" >&2
  exit 1
fi

# Test error handling with unreadable configuration file
echo "Testing configure_avahi.sh with unreadable configuration file..."

UNREADABLE_CONF="${TMP_DIR}/unreadable-avahi.conf"
# Create a file that exists but can't be read (simulate permission issues)
echo "[server]" > "${UNREADABLE_CONF}"
chmod 000 "${UNREADABLE_CONF}"

UNREADABLE_ENV_VARS=(
  "SUGARKUBE_MDNS_INTERFACE=eth0"
  "SUGARKUBE_MDNS_IPV4_ONLY=1"
  "AVAHI_CONF_PATH=${UNREADABLE_CONF}"
  "SUGARKUBE_LOG_DIR=${LOG_DIR}"
  "SYSTEMCTL_BIN="
)

# This should fail to avoid destroying configuration
if ( export "${UNREADABLE_ENV_VARS[@]}"; bash "${REPO_ROOT}/scripts/configure_avahi.sh" ); then
  echo "ERROR: configure_avahi.sh should have failed with unreadable configuration" >&2
  exit 1
fi

# Restore permissions for cleanup
chmod 644 "${UNREADABLE_CONF}"

echo "SUCCESS: configure_avahi.sh Python syntax error fix test passed"
