#!/usr/bin/env bash
set -euo pipefail

# Test the detect_node_primary_ipv4 function

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
K3S_DISCOVER="${REPO_ROOT}/scripts/k3s-discover.sh"

# Source the function we want to test
source "${K3S_DISCOVER}" >/dev/null 2>&1 || true

# Test 1: Check that the function exists
if ! declare -f detect_node_primary_ipv4 >/dev/null; then
    echo "FAIL: detect_node_primary_ipv4 function not found"
    exit 1
fi
echo "PASS: detect_node_primary_ipv4 function exists"

# Test 2: Check that function returns an IPv4 address format
result=""
if result="$(detect_node_primary_ipv4 2>/dev/null)"; then
    # Validate it looks like an IP address (basic check)
    if [[ "${result}" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
        echo "PASS: detect_node_primary_ipv4 returned valid IPv4: ${result}"
    else
        echo "WARN: detect_node_primary_ipv4 returned non-IPv4 format: ${result}"
    fi
else
    echo "INFO: detect_node_primary_ipv4 returned no result (may be expected if no eth0 interface)"
fi

# Test 3: Test with mock IP command that simulates eth0
mock_ip_output() {
    echo "2: eth0    inet 192.168.1.100/24 brd 192.168.1.255 scope global eth0"
}

# Export mock function
export -f mock_ip_output

# Test with mocked IP command
export IP_CMD=mock_ip_output
export SUGARKUBE_MDNS_INTERFACE=eth0

result=""
if result="$(detect_node_primary_ipv4 2>/dev/null)"; then
    if [ "${result}" = "192.168.1.100" ]; then
        echo "PASS: detect_node_primary_ipv4 correctly parsed mock IP output: ${result}"
    else
        echo "FAIL: Expected 192.168.1.100, got: ${result}"
        exit 1
    fi
else
    echo "FAIL: detect_node_primary_ipv4 failed with mock IP command"
    exit 1
fi

echo "All tests passed!"
