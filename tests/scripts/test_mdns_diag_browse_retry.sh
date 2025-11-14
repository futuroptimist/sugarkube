#!/usr/bin/env bash
# Test mdns_diag.sh avahi-browse retry logic
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
MDNS_DIAG_SCRIPT="${REPO_ROOT}/scripts/mdns_diag.sh"

TMP_DIR="$(mktemp -d)"
trap 'rm -rf "${TMP_DIR}"' EXIT

BIN_DIR="${TMP_DIR}/bin"
STATE_DIR="${TMP_DIR}/state"
mkdir -p "${BIN_DIR}" "${STATE_DIR}"

# Test 1: avahi-browse succeeds on first attempt
echo "Test 1: avahi-browse succeeds on first attempt"

cat >"${BIN_DIR}/avahi-browse" <<'SH'
#!/usr/bin/env bash
echo "=;eth0;IPv4;k3s-sugar-test;_k3s-sugar-test._tcp;local"
exit 0
SH
chmod +x "${BIN_DIR}/avahi-browse"

cat >"${BIN_DIR}/systemctl" <<'SH'
#!/usr/bin/env bash
exit 0
SH
chmod +x "${BIN_DIR}/systemctl"

cat >"${BIN_DIR}/avahi-resolve" <<'SH'
#!/usr/bin/env bash
echo "testhost.local 192.168.1.10"
exit 0
SH
chmod +x "${BIN_DIR}/avahi-resolve"

cat >"${BIN_DIR}/getent" <<'SH'
#!/usr/bin/env bash
echo "192.168.1.10 testhost.local"
exit 0
SH
chmod +x "${BIN_DIR}/getent"

export PATH="${BIN_DIR}:${PATH}"
export MDNS_DIAG_HOSTNAME=testhost.local
export MDNS_DIAG_BROWSE_RETRIES=2
export SUGARKUBE_CLUSTER=sugar
export SUGARKUBE_ENV=test

status=0
output=$("${MDNS_DIAG_SCRIPT}" 2>&1) || status=$?

if [ "${status}" -ne 0 ]; then
  echo "FAIL: Expected exit code 0, got ${status}"
  echo "Output: ${output}"
  exit 1
fi

if ! grep -q "Found 1 service(s)" <<<"${output}"; then
  echo "FAIL: Expected to find services"
  echo "Output: ${output}"
  exit 1
fi

echo "PASS: Test 1"

# Test 2: avahi-browse fails on first attempt, succeeds on retry
echo "Test 2: avahi-browse fails on first attempt, succeeds on retry"

cat >"${BIN_DIR}/avahi-browse" <<'SH'
#!/usr/bin/env bash
STATE_DIR="${STATE_DIR:-/tmp}"
CALL_FILE="${STATE_DIR}/browse_calls"
touch "${CALL_FILE}"
call_count=$(wc -l < "${CALL_FILE}")
echo "call ${call_count}" >> "${CALL_FILE}"

if [ "${call_count}" -eq 0 ]; then
  # First call fails (daemon restarting)
  exit 1
else
  # Second call succeeds
  echo "=;eth0;IPv4;k3s-sugar-test;_k3s-sugar-test._tcp;local"
  exit 0
fi
SH
chmod +x "${BIN_DIR}/avahi-browse"

export STATE_DIR
rm -f "${STATE_DIR}/browse_calls"

status=0
output=$("${MDNS_DIAG_SCRIPT}" 2>&1) || status=$?

if [ "${status}" -ne 0 ]; then
  echo "FAIL: Expected exit code 0 (success on retry), got ${status}"
  echo "Output: ${output}"
  exit 1
fi

if ! grep -q "Found 1 service(s)" <<<"${output}"; then
  echo "FAIL: Expected to find services on retry"
  echo "Output: ${output}"
  exit 1
fi

# Verify it actually retried
if [ ! -f "${STATE_DIR}/browse_calls" ]; then
  echo "FAIL: browse_calls file not created"
  exit 1
fi

call_count=$(wc -l < "${STATE_DIR}/browse_calls")
if [ "${call_count}" -lt 2 ]; then
  echo "FAIL: Expected at least 2 calls, got ${call_count}"
  exit 1
fi

echo "PASS: Test 2"

# Test 3: avahi-browse fails all retries
echo "Test 3: avahi-browse fails all retries"

cat >"${BIN_DIR}/avahi-browse" <<'SH'
#!/usr/bin/env bash
# Always fail
exit 1
SH
chmod +x "${BIN_DIR}/avahi-browse"

export MDNS_DIAG_BROWSE_RETRIES=2

status=0
output=$("${MDNS_DIAG_SCRIPT}" 2>&1) || status=$?

if [ "${status}" -eq 0 ]; then
  echo "FAIL: Expected non-zero exit code when avahi-browse fails"
  echo "Output: ${output}"
  exit 1
fi

if ! grep -q "after 2" <<<"${output}"; then
  echo "FAIL: Expected message about retry count"
  echo "Output: ${output}"
  exit 1
fi

if ! grep -q "daemon may be restarting" <<<"${output}"; then
  echo "FAIL: Expected message about daemon restarting"
  echo "Output: ${output}"
  exit 1
fi

echo "PASS: Test 3"

echo "All tests passed!"
