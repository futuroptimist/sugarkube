#!/usr/bin/env bats
# End-to-end test that exercises the complete cluster formation workflow
# as described in docs/raspi_cluster_setup.md

setup() {
  if [ "${AVAHI_AVAILABLE:-0}" != "1" ]; then
    # TODO: Provide a hermetic Avahi fixture so this suite runs without AVAHI_AVAILABLE=1.
    # Root cause: The integration exercise requires a host Avahi daemon for mDNS service advertisement.
    # Estimated fix: 60m to bundle a containerised Avahi helper or dedicated stub binaries.
    skip "AVAHI_AVAILABLE not enabled"
  fi

  if ! command -v avahi-browse >/dev/null 2>&1; then
    # TODO: Package avahi-browse for the integration harness to browse advertised services.
    # Root cause: The suite shells out to avahi-browse for service discovery validation.
    # Estimated fix: 20m to include avahi-utils in docs or provide a bats stub.
    skip "avahi-browse not available"
  fi

  if ! command -v avahi-publish >/dev/null 2>&1; then
    # TODO: Ship avahi-publish alongside the cluster formation test fixtures.
    # Root cause: Tests require avahi-publish to simulate bootstrap node service advertisement.
    # Estimated fix: 20m to install avahi-utils or extend the stub harness in tests/fixtures.
    skip "avahi-publish not available"
  fi

  if ! command -v getent >/dev/null 2>&1; then
    # TODO: Provide a getent/NSS stub so mDNS lookups don't depend on host config.
    # Root cause: Integration checks rely on host NSS to resolve .local records via Avahi.
    # Estimated fix: 15m to add a bats stub or bundle libc-bin/nss-mdns alongside the harness.
    # Documented dependency: discovery checks rely on host NSS/getent for .local validation.
    # See docs/mdns_troubleshooting.md#integration-test-prerequisites for setup details.
    skip "getent not available"
  fi

  export TEST_ROOT="${BATS_TEST_TMPDIR}"
  export SCRIPTS_ROOT="${BATS_CWD}/scripts"
  
  # Create a test environment directory
  mkdir -p "${TEST_ROOT}/node0" "${TEST_ROOT}/node1"
  
  # Mock systemctl and other system tools
  export PATH="${TEST_ROOT}/bin:${PATH}"
  mkdir -p "${TEST_ROOT}/bin"
  
  cat >"${TEST_ROOT}/bin/systemctl" <<'EOF'
#!/bin/bash
# Mock systemctl for testing
case "$1" in
  is-active)
    # Return success - avahi-daemon is "active"
    exit 0
    ;;
  start)
    # Pretend to start service
    exit 0
    ;;
  *)
    exit 0
    ;;
esac
EOF
  chmod +x "${TEST_ROOT}/bin/systemctl"
  
  # Store PIDs of background publishers
  publisher_pids=()
}

teardown() {
  # Clean up any avahi-publish processes
  for pid in "${publisher_pids[@]}"; do
    if [ -n "${pid}" ]; then
      kill "${pid}" >/dev/null 2>&1 || true
      wait "${pid}" >/dev/null 2>&1 || true
    fi
  done
  publisher_pids=()
  
  # Clean up test directories
  rm -rf "${TEST_ROOT}"
}

# Helper to simulate a bootstrap node publishing its service
simulate_bootstrap_node() {
  local node_name="$1"
  local cluster="${2:-sugar}"
  local environment="${3:-dev}"
  local port="${4:-6443}"
  
  local service_type="_k3s-${cluster}-${environment}._tcp"
  local service_instance="k3s-${cluster}-${environment}@${node_name}.local"
  
  # Publish the service in the background
  avahi-publish -s "${service_instance}" "${service_type}" "${port}" \
    "role=server" "phase=server" "leader=${node_name}.local" \
    >"${TEST_ROOT}/${node_name}_publish.log" 2>&1 &
  
  local pid=$!
  publisher_pids+=("${pid}")
  
  # Give avahi time to propagate
  sleep 2
  
  echo "${pid}"
}

# Helper to verify a service is browsable
verify_service_browsable() {
  local cluster="${1:-sugar}"
  local environment="${2:-dev}"
  local timeout="${3:-10}"
  
  local service_type="_k3s-${cluster}-${environment}._tcp"
  
  # Try browsing for the service
  timeout "${timeout}" avahi-browse --parsable --terminate --resolve "${service_type}" 2>/dev/null | grep -q "^="
}

@test "Phase 1: Bootstrap node without token publishes service" {
  # This simulates the first node in the cluster:
  # - No SUGARKUBE_TOKEN_DEV set
  # - Should bootstrap and publish mDNS service
  # - Service should be discoverable by other nodes
  
  local node_name="sugarkube0"
  local cluster="sugar"
  local environment="dev"
  
  # Simulate bootstrap: publish the service
  local pid
  pid=$(simulate_bootstrap_node "${node_name}" "${cluster}" "${environment}")
  
  # Verify the service is browsable from the network
  run verify_service_browsable "${cluster}" "${environment}" 10
  [ "$status" -eq 0 ]
  
  # Verify we can find it using the same query mechanism as the script
  run env \
    SUGARKUBE_CLUSTER="${cluster}" \
    SUGARKUBE_ENV="${environment}" \
    SUGARKUBE_MDNS_QUERY_TIMEOUT=5 \
    python3 - <<'PY'
import os
import sys
sys.path.insert(0, os.environ.get('BATS_CWD', '.') + '/scripts')
from k3s_mdns_query import query_mdns

results = query_mdns('server-select', 'sugar', 'dev', debug=lambda msg: print(f"[debug] {msg}", file=sys.stderr))
if results:
    print(f"Found server: {results[0]}")
    sys.exit(0)
else:
    print("No servers found", file=sys.stderr)
    sys.exit(1)
PY
  
  [ "$status" -eq 0 ]
  [[ "$output" =~ "Found server:" ]]
}

@test "Phase 2: Joining node with token discovers bootstrap node" {
  # This simulates the second node in the cluster:
  # - SUGARKUBE_TOKEN_DEV is set
  # - Should discover the bootstrap node via mDNS
  # - Should NOT bootstrap (split-brain prevention)
  
  local bootstrap_node="sugarkube0"
  local cluster="sugar"
  local environment="dev"
  
  # Start bootstrap node service
  local pid
  pid=$(simulate_bootstrap_node "${bootstrap_node}" "${cluster}" "${environment}")
  
  # Simulate the joining node's discovery process
  # This is what discover_via_nss_and_api() does
  run env \
    SUGARKUBE_CLUSTER="${cluster}" \
    SUGARKUBE_ENV="${environment}" \
    SUGARKUBE_MDNS_NO_TERMINATE=1 \
    SUGARKUBE_MDNS_QUERY_TIMEOUT=30 \
    python3 - <<'PY'
import os
import sys
sys.path.insert(0, os.environ.get('BATS_CWD', '.') + '/scripts')
from k3s_mdns_query import query_mdns

# Enable debug output
def debug(msg):
    print(f"[mdns] {msg}", file=sys.stderr)

results = query_mdns('server-select', 'sugar', 'dev', debug=debug)
if results:
    for result in results:
        print(f"DISCOVERED: {result}")
    sys.exit(0)
else:
    print("DISCOVERY FAILED: No servers found", file=sys.stderr)
    sys.exit(1)
PY
  
  [ "$status" -eq 0 ]
  [[ "$output" =~ "DISCOVERED:" ]]
  [[ "$output" =~ "host=" ]]
}

@test "Phase 3: Multiple nodes can all discover the first bootstrap node" {
  # This tests that multiple joining nodes can discover the same bootstrap node
  # simulating sugarkube1, sugarkube2, etc. all joining sugarkube0
  
  local bootstrap_node="sugarkube0"
  local cluster="sugar"
  local environment="dev"
  
  # Start bootstrap node service
  local pid
  pid=$(simulate_bootstrap_node "${bootstrap_node}" "${cluster}" "${environment}")
  
  # Run discovery 3 times (simulating 3 different nodes)
  for i in 1 2 3; do
    run env \
      SUGARKUBE_CLUSTER="${cluster}" \
      SUGARKUBE_ENV="${environment}" \
      SUGARKUBE_MDNS_NO_TERMINATE=1 \
      SUGARKUBE_MDNS_QUERY_TIMEOUT=10 \
      python3 - <<'PY'
import os
import sys
sys.path.insert(0, os.environ.get('BATS_CWD', '.') + '/scripts')
from k3s_mdns_query import query_mdns

results = query_mdns('server-select', 'sugar', 'dev')
if results:
    print(f"Node discovery successful")
    sys.exit(0)
else:
    sys.exit(1)
PY
    
    [ "$status" -eq 0 ]
    [[ "$output" =~ "successful" ]]
  done
}

@test "Discovery respects SUGARKUBE_MDNS_NO_TERMINATE flag" {
  # Verify that NO_TERMINATE=1 actually waits for network responses
  # rather than just checking cache
  
  local node_name="sugarkube0"
  local cluster="sugar"
  local environment="dev"
  
  # First try WITH --terminate (should fail on fresh service)
  run timeout 2 env \
    SUGARKUBE_CLUSTER="${cluster}" \
    SUGARKUBE_ENV="${environment}" \
    SUGARKUBE_MDNS_NO_TERMINATE=0 \
    SUGARKUBE_MDNS_QUERY_TIMEOUT=1 \
    python3 - <<'PY'
import os
import sys
sys.path.insert(0, os.environ.get('BATS_CWD', '.') + '/scripts')
from k3s_mdns_query import query_mdns

results = query_mdns('server-select', 'sugar', 'dev')
print(f"With terminate: {len(results)} results")
PY
  
  # Capture the terminate result
  local terminate_output="$output"
  
  # Now start the service
  local pid
  pid=$(simulate_bootstrap_node "${node_name}" "${cluster}" "${environment}")
  
  # Try again WITHOUT --terminate (should wait and find the service)
  run timeout 35 env \
    SUGARKUBE_CLUSTER="${cluster}" \
    SUGARKUBE_ENV="${environment}" \
    SUGARKUBE_MDNS_NO_TERMINATE=1 \
    SUGARKUBE_MDNS_QUERY_TIMEOUT=30 \
    python3 - <<'PY'
import os
import sys
sys.path.insert(0, os.environ.get('BATS_CWD', '.') + '/scripts')
from k3s_mdns_query import query_mdns

def debug(msg):
    print(f"[mdns] {msg}", file=sys.stderr)

results = query_mdns('server-select', 'sugar', 'dev', debug=debug)
print(f"Without terminate: {len(results)} results")
if results:
    sys.exit(0)
else:
    sys.exit(1)
PY
  
  [ "$status" -eq 0 ]
  [[ "$output" =~ "Without terminate: 1 results" ]]
}

@test "Discovery times out appropriately when no services exist" {
  # Verify that discovery doesn't hang forever when nothing is available
  
  local cluster="sugar"
  local environment="nonexistent"
  
  # Try to discover in an environment with no services
  run timeout 35 env \
    SUGARKUBE_CLUSTER="${cluster}" \
    SUGARKUBE_ENV="${environment}" \
    SUGARKUBE_MDNS_NO_TERMINATE=1 \
    SUGARKUBE_MDNS_QUERY_TIMEOUT=5 \
    python3 - <<'PY'
import os
import sys
import time
sys.path.insert(0, os.environ.get('BATS_CWD', '.') + '/scripts')
from k3s_mdns_query import query_mdns

start = time.time()
results = query_mdns('server-select', 'sugar', 'nonexistent')
elapsed = time.time() - start

print(f"Discovery completed in {elapsed:.1f}s with {len(results)} results")
# Should complete within timeout (5s) + some overhead
if elapsed > 10:
    print(f"ERROR: Took too long ({elapsed:.1f}s)", file=sys.stderr)
    sys.exit(1)
sys.exit(0)
PY
  
  [ "$status" -eq 0 ]
  [[ "$output" =~ Discovery\ completed.*0\ results ]]
}

@test "Phase 4: Three-server HA cluster formation" {
  # This tests a complete 3-server HA cluster formation scenario:
  # - sugarkube0 bootstraps with SUGARKUBE_SERVERS=3
  # - sugarkube1 discovers sugarkube0 and joins as second server
  # - sugarkube2 discovers either node and joins as third server
  # - All three nodes advertise their services
  # - All three nodes can discover each other
  
  local cluster="sugar"
  local environment="dev"
  
  # Node 1: Bootstrap (sugarkube0)
  # Simulates: SUGARKUBE_SERVERS=3, no token → bootstrap
  local pid0
  pid0=$(simulate_bootstrap_node "sugarkube0" "${cluster}" "${environment}")
  
  # Verify sugarkube0 is discoverable
  run timeout 15 env \
    SUGARKUBE_CLUSTER="${cluster}" \
    SUGARKUBE_ENV="${environment}" \
    SUGARKUBE_MDNS_NO_TERMINATE=1 \
    SUGARKUBE_MDNS_QUERY_TIMEOUT=10 \
    python3 - <<'PY'
import os
import sys
sys.path.insert(0, os.environ.get('BATS_CWD', '.') + '/scripts')
from k3s_mdns_query import query_mdns

def debug(msg):
    print(f"[mdns-0] {msg}", file=sys.stderr)

results = query_mdns('server-select', 'sugar', 'dev', debug=debug)
if results and any('sugarkube0' in str(r) for r in results):
    print("✓ sugarkube0 discovered")
    sys.exit(0)
else:
    print("✗ sugarkube0 not found", file=sys.stderr)
    sys.exit(1)
PY
  
  [ "$status" -eq 0 ]
  [[ "$output" =~ "sugarkube0 discovered" ]]
  
  # Node 2: Join as second server (sugarkube1)
  # Simulates: SUGARKUBE_SERVERS=3, token set → join as server
  local pid1
  pid1=$(simulate_bootstrap_node "sugarkube1" "${cluster}" "${environment}")
  
  # Give time for service to propagate
  sleep 3
  
  # Verify both nodes are now discoverable
  run timeout 15 env \
    SUGARKUBE_CLUSTER="${cluster}" \
    SUGARKUBE_ENV="${environment}" \
    SUGARKUBE_MDNS_NO_TERMINATE=1 \
    SUGARKUBE_MDNS_QUERY_TIMEOUT=10 \
    python3 - <<'PY'
import os
import sys
sys.path.insert(0, os.environ.get('BATS_CWD', '.') + '/scripts')
from k3s_mdns_query import query_mdns

def debug(msg):
    print(f"[mdns-1] {msg}", file=sys.stderr)

results = query_mdns('server-select', 'sugar', 'dev', debug=debug)
result_strs = [str(r) for r in results]
has_0 = any('sugarkube0' in s for s in result_strs)
has_1 = any('sugarkube1' in s for s in result_strs)

print(f"Discovered {len(results)} servers")
print(f"Has sugarkube0: {has_0}")
print(f"Has sugarkube1: {has_1}")

if has_0 and has_1:
    print("✓ Both sugarkube0 and sugarkube1 discovered")
    sys.exit(0)
else:
    print("✗ Not all servers found", file=sys.stderr)
    sys.exit(1)
PY
  
  [ "$status" -eq 0 ]
  [[ "$output" =~ "Both sugarkube0 and sugarkube1 discovered" ]]
  
  # Node 3: Join as third server (sugarkube2)
  # Simulates: SUGARKUBE_SERVERS=3, token set → join as final server
  local pid2
  pid2=$(simulate_bootstrap_node "sugarkube2" "${cluster}" "${environment}")
  
  # Give time for service to propagate
  sleep 3
  
  # Verify all three nodes are discoverable
  run timeout 15 env \
    SUGARKUBE_CLUSTER="${cluster}" \
    SUGARKUBE_ENV="${environment}" \
    SUGARKUBE_MDNS_NO_TERMINATE=1 \
    SUGARKUBE_MDNS_QUERY_TIMEOUT=10 \
    python3 - <<'PY'
import os
import sys
sys.path.insert(0, os.environ.get('BATS_CWD', '.') + '/scripts')
from k3s_mdns_query import query_mdns

def debug(msg):
    print(f"[mdns-2] {msg}", file=sys.stderr)

results = query_mdns('server-select', 'sugar', 'dev', debug=debug)
result_strs = [str(r) for r in results]
has_0 = any('sugarkube0' in s for s in result_strs)
has_1 = any('sugarkube1' in s for s in result_strs)
has_2 = any('sugarkube2' in s for s in result_strs)

print(f"Discovered {len(results)} servers")
print(f"Has sugarkube0: {has_0}")
print(f"Has sugarkube1: {has_1}")
print(f"Has sugarkube2: {has_2}")

if has_0 and has_1 and has_2:
    print("✓ All three servers discovered (sugarkube0, sugarkube1, sugarkube2)")
    print("✓ 3-server HA cluster formation complete")
    sys.exit(0)
else:
    print("✗ Not all servers found", file=sys.stderr)
    sys.exit(1)
PY
  
  [ "$status" -eq 0 ]
  [[ "$output" =~ "All three servers discovered" ]]
  [[ "$output" =~ "3-server HA cluster formation complete" ]]
  
  # Verify any joining node can discover all three servers
  # This simulates what would happen when running `kubectl get nodes`
  run timeout 15 env \
    SUGARKUBE_CLUSTER="${cluster}" \
    SUGARKUBE_ENV="${environment}" \
    SUGARKUBE_MDNS_NO_TERMINATE=1 \
    SUGARKUBE_MDNS_QUERY_TIMEOUT=10 \
    python3 - <<'PY'
import os
import sys
sys.path.insert(0, os.environ.get('BATS_CWD', '.') + '/scripts')
from k3s_mdns_query import query_mdns

results = query_mdns('server-select', 'sugar', 'dev')
if len(results) >= 3:
    print(f"✓ Final verification: {len(results)} servers visible")
    print("✓ HA cluster ready: all nodes can discover each other")
    sys.exit(0)
else:
    print(f"✗ Expected 3+ servers, found {len(results)}", file=sys.stderr)
    sys.exit(1)
PY
  
  [ "$status" -eq 0 ]
  [[ "$output" =~ "HA cluster ready" ]]
}
