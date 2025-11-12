#!/usr/bin/env bash
# Test mdns_ready.sh function
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
MDNS_READY_SCRIPT="${REPO_ROOT}/scripts/mdns_ready.sh"

TMP_DIR="$(mktemp -d)"
trap 'rm -rf "${TMP_DIR}"' EXIT

BIN_DIR="${TMP_DIR}/bin"
mkdir -p "${BIN_DIR}"

# Test 1: D-Bus success path
echo "Test 1: D-Bus success path"
cat >"${BIN_DIR}/gdbus" <<'SH'
#!/usr/bin/env bash
echo "('0.8')"
exit 0
SH
chmod +x "${BIN_DIR}/gdbus"

cat >"${BIN_DIR}/avahi-browse" <<'SH'
#!/usr/bin/env bash
exit 1
SH
chmod +x "${BIN_DIR}/avahi-browse"

export PATH="${BIN_DIR}:${PATH}"
export AVAHI_DBUS_TIMEOUT_MS=1000

status=0  # Initialize status variable
output=$("${MDNS_READY_SCRIPT}" 2>&1) || status=$?
status=${status:-0}

if [ "${status}" -ne 0 ]; then
  echo "FAIL: Expected exit code 0, got ${status}"
  echo "Output: ${output}"
  exit 1
fi

if ! grep -q "method=dbus" <<<"${output}"; then
  echo "FAIL: Expected method=dbus in output"
  echo "Output: ${output}"
  exit 1
fi

if ! grep -q "outcome=ok" <<<"${output}"; then
  echo "FAIL: Expected outcome=ok in output"
  echo "Output: ${output}"
  exit 1
fi

echo "PASS: D-Bus success path"

# Test 2: D-Bus failure, CLI fallback success
echo "Test 2: D-Bus failure, CLI fallback success"
cat >"${BIN_DIR}/gdbus" <<'SH'
#!/usr/bin/env bash
echo "Error: Method GetVersionString unavailable" >&2
exit 1
SH
chmod +x "${BIN_DIR}/gdbus"

cat >"${BIN_DIR}/avahi-browse" <<'SH'
#!/usr/bin/env bash
echo "=;eth0;IPv4;test;_test._tcp;local"
exit 0
SH
chmod +x "${BIN_DIR}/avahi-browse"

status=0  # Initialize status variable
output=$("${MDNS_READY_SCRIPT}" 2>&1) || status=$?
status=${status:-0}

if [ "${status}" -ne 0 ]; then
  echo "FAIL: Expected exit code 0, got ${status}"
  echo "Output: ${output}"
  exit 1
fi

if ! grep -q "method=cli" <<<"${output}"; then
  echo "FAIL: Expected method=cli in output"
  echo "Output: ${output}"
  exit 1
fi

if ! grep -q "outcome=ok" <<<"${output}"; then
  echo "FAIL: Expected outcome=ok in output"
  echo "Output: ${output}"
  exit 1
fi

if ! grep -q "dbus_fallback=true" <<<"${output}"; then
  echo "FAIL: Expected dbus_fallback=true in output"
  echo "Output: ${output}"
  exit 1
fi

if ! grep -q "browse_command=" <<<"${output}"; then
  echo "FAIL: Expected browse_command in output"
  echo "Output: ${output}"
  exit 1
fi

echo "PASS: D-Bus failure, CLI fallback success"

# Test 3: Both methods fail
echo "Test 3: Both methods fail"
cat >"${BIN_DIR}/gdbus" <<'SH'
#!/usr/bin/env bash
echo "Error: Connection failed" >&2
exit 1
SH
chmod +x "${BIN_DIR}/gdbus"

cat >"${BIN_DIR}/avahi-browse" <<'SH'
#!/usr/bin/env bash
echo "Error: Daemon not running" >&2
exit 2
SH
chmod +x "${BIN_DIR}/avahi-browse"

status=0  # Initialize status variable
output=$("${MDNS_READY_SCRIPT}" 2>&1) || status=$?
status=${status:-0}

if [ "${status}" -ne 1 ]; then
  echo "FAIL: Expected exit code 1, got ${status}"
  echo "Output: ${output}"
  exit 1
fi

if ! grep -q "outcome=fail" <<<"${output}"; then
  echo "FAIL: Expected outcome=fail in output"
  echo "Output: ${output}"
  exit 1
fi

if ! grep -q "method=cli" <<<"${output}"; then
  echo "FAIL: Expected method=cli in output (attempted)"
  echo "Output: ${output}"
  exit 1
fi

echo "PASS: Both methods fail"

# Test 4: D-Bus disabled in config
echo "Test 4: D-Bus disabled in config"
AVAHI_CONF="${TMP_DIR}/avahi-daemon.conf"
cat >"${AVAHI_CONF}" <<'CONF'
[server]
enable-dbus=no
CONF

export AVAHI_CONF_PATH="${AVAHI_CONF}"

status=0  # Initialize status variable
output=$("${MDNS_READY_SCRIPT}" 2>&1) || status=$?
status=${status:-0}

if [ "${status}" -ne 2 ]; then
  echo "FAIL: Expected exit code 2 (disabled), got ${status}"
  echo "Output: ${output}"
  exit 1
fi

if ! grep -q "outcome=disabled" <<<"${output}"; then
  echo "FAIL: Expected outcome=disabled in output"
  echo "Output: ${output}"
  exit 1
fi

if ! grep -q "reason=enable_dbus_no" <<<"${output}"; then
  echo "FAIL: Expected reason=enable_dbus_no in output"
  echo "Output: ${output}"
  exit 1
fi

echo "PASS: D-Bus disabled in config"

# Test 5: avahi-browse missing, gdbus missing
echo "Test 5: Both tools missing"
rm -f "${BIN_DIR}/gdbus" "${BIN_DIR}/avahi-browse"
unset AVAHI_CONF_PATH  # Clear config from previous test

status=0  # Initialize status variable
output=$("${MDNS_READY_SCRIPT}" 2>&1) || status=$?
status=${status:-0}

if [ "${status}" -ne 1 ]; then
  echo "FAIL: Expected exit code 1, got ${status}"
  echo "Output: ${output}"
  exit 1
fi

if ! grep -q "outcome=fail" <<<"${output}"; then
  echo "FAIL: Expected outcome=fail in output"
  echo "Output: ${output}"
  exit 1
fi

if ! grep -q "reason=cli_missing" <<<"${output}"; then
  echo "FAIL: Expected reason=cli_missing in output"
  echo "Output: ${output}"
  exit 1
fi

echo "PASS: Both tools missing"

# Test 6: Verify structured logging fields
echo "Test 6: Verify structured logging includes required fields"
cat >"${BIN_DIR}/gdbus" <<'SH'
#!/usr/bin/env bash
echo "('0.8')"
exit 0
SH
chmod +x "${BIN_DIR}/gdbus"

unset AVAHI_CONF_PATH
status=0  # Reset status variable
output=$("${MDNS_READY_SCRIPT}" 2>&1) || status=$?
status=${status:-0}

if [ "${status}" -ne 0 ]; then
  echo "FAIL: Expected exit code 0, got ${status}"
  echo "Output: ${output}"
  exit 1
fi

# Check for required structured log fields
required_fields=("event=mdns_ready" "method=" "elapsed_ms=" "outcome=")
for field in "${required_fields[@]}"; do
  if ! grep -q "${field}" <<<"${output}"; then
    echo "FAIL: Missing required field: ${field}"
    echo "Output: ${output}"
    exit 1
  fi
done

echo "PASS: Structured logging fields present"

echo ""
echo "All tests passed!"
