#!/usr/bin/env bash
set -euo pipefail

# Test that Avahi/mDNS hardening changes are properly configured in build script

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BUILD_SCRIPT="${REPO_ROOT}/scripts/build_pi_image.sh"

echo "Testing Avahi/mDNS hardening in build_pi_image.sh..."

# Test 1: Check required packages are in ensure_packages call
echo "✓ Checking required packages..."
required_packages=(
    "avahi-daemon"
    "avahi-utils"
    "dbus"
    "libnss-mdns"
    "nftables"
)

for pkg in "${required_packages[@]}"; do
    if ! grep -q "${pkg}" "${BUILD_SCRIPT}"; then
        echo "✗ Package ${pkg} not found in build script" >&2
        exit 1
    fi
    echo "  ✓ ${pkg} found"
done

# Test 2: Check Avahi scripts are bundled
echo "✓ Checking Avahi scripts are bundled..."
avahi_scripts=(
    "configure_avahi.sh"
    "wait_for_avahi_dbus.sh"
    "check_avahi_config_effective.sh"
    "configure_nsswitch_mdns.sh"
    "log.sh"
)

for script in "${avahi_scripts[@]}"; do
    if ! grep -q "install.*${script}" "${BUILD_SCRIPT}"; then
        echo "✗ Script ${script} not found in install commands" >&2
        exit 1
    fi
    echo "  ✓ ${script} is installed"
done

# Test 3: Check systemd service is installed
echo "✓ Checking avahi-configure.service is installed..."
if ! grep -q "avahi-configure.service" "${BUILD_SCRIPT}"; then
    echo "✗ avahi-configure.service not found" >&2
    exit 1
fi
echo "  ✓ avahi-configure.service found"

# Test 4: Verify scripts exist and are executable
echo "✓ Checking scripts exist and are executable..."
for script in "${avahi_scripts[@]}"; do
    script_path="${REPO_ROOT}/scripts/${script}"
    if [ ! -f "${script_path}" ]; then
        echo "✗ Script not found: ${script_path}" >&2
        exit 1
    fi
    if [ ! -x "${script_path}" ]; then
        echo "✗ Script not executable: ${script_path}" >&2
        exit 1
    fi
    echo "  ✓ ${script} exists and is executable"
done

# Test 5: Verify systemd service file exists
echo "✓ Checking systemd service file exists..."
service_file="${REPO_ROOT}/scripts/systemd/avahi-configure.service"
if [ ! -f "${service_file}" ]; then
    echo "✗ Service file not found: ${service_file}" >&2
    exit 1
fi
echo "  ✓ ${service_file} exists"

# Test 6: Verify service file has correct dependencies
echo "✓ Checking service dependencies..."
if ! grep -q "After=dbus.service avahi-daemon.service" "${service_file}"; then
    echo "✗ Service missing proper After= dependencies" >&2
    exit 1
fi
if ! grep -q "Requires=dbus.service avahi-daemon.service" "${service_file}"; then
    echo "✗ Service missing proper Requires= dependencies" >&2
    exit 1
fi
echo "  ✓ Service has correct ordering dependencies"

# Test 7: Test nsswitch configuration script
echo "✓ Testing nsswitch configuration..."
tmpfile=$(mktemp)
trap "rm -f ${tmpfile}" EXIT
cat > "${tmpfile}" <<'EOF'
hosts:          files dns
EOF

if ! NSSWITCH_PATH="${tmpfile}" "${REPO_ROOT}/scripts/configure_nsswitch_mdns.sh" >/dev/null 2>&1; then
    echo "✗ configure_nsswitch_mdns.sh failed" >&2
    exit 1
fi

if ! grep -q "files mdns_minimal \[NOTFOUND=return\] resolve dns" "${tmpfile}"; then
    echo "✗ nsswitch not configured correctly" >&2
    cat "${tmpfile}"
    exit 1
fi
echo "  ✓ nsswitch configuration works correctly"

# Test 8: Test idempotency
echo "✓ Testing idempotency..."
if ! NSSWITCH_PATH="${tmpfile}" "${REPO_ROOT}/scripts/configure_nsswitch_mdns.sh" >/dev/null 2>&1; then
    echo "✗ Second run of configure_nsswitch_mdns.sh failed" >&2
    exit 1
fi

if ! grep -q "files mdns_minimal \[NOTFOUND=return\] resolve dns" "${tmpfile}"; then
    echo "✗ nsswitch configuration changed on second run" >&2
    exit 1
fi
echo "  ✓ nsswitch configuration is idempotent"

echo ""
echo "✅ All Avahi/mDNS hardening tests passed!"
