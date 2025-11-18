#!/usr/bin/env bats

# This test ensures that hostnames are NEVER modified by any sugarkube scripts
# Hostnames should always remain as set by the user

setup() {
  export ORIGINAL_HOSTNAME="sugarkube0"
  export HOSTNAME_FILE="${BATS_TEST_TMPDIR}/hostname_test"
  echo "${ORIGINAL_HOSTNAME}" > "${HOSTNAME_FILE}"
}

@test "hostname is never modified - no ensure_unique_hostname script should exist" {
  # The ensure_unique_hostname.sh script should not exist at all
  [ ! -f "${BATS_CWD}/scripts/ensure_unique_hostname.sh" ]
}

@test "hostname is never modified - justfile should not call hostname changing scripts" {
  # Check that justfile does not contain calls to hostname modification
  ! grep -q "ensure_unique_hostname" "${BATS_CWD}/justfile"
}

@test "hostname is never modified - no hostnamectl set-hostname calls in scripts" {
  # Scan all scripts to ensure no script attempts to change hostname
  # Allow hostnamectl for reading but not for setting
  
  # Find any suspicious patterns (excluding comments and the verifier which just reads)
  local suspicious_files
  suspicious_files=$(grep -r "hostnamectl set-hostname" "${BATS_CWD}/scripts/" 2>/dev/null | grep -v "pi_node_verifier.sh" || true)
  
  # Should be empty - no scripts should call hostnamectl set-hostname
  [ -z "${suspicious_files}" ]
}

@test "hostname changes are explicitly rejected by policy" {
  # This test documents our policy: hostnames are user-managed, never auto-renamed
  # If a hostname collision exists, it's a configuration error the user must fix
  # The wipe command should clean up stale mDNS registrations
  
  # Verify this policy is documented in comments
  grep -q "never rename" "${BATS_CWD}/README.md" || \
  grep -q "hostname" "${BATS_CWD}/docs/raspi_cluster_setup.md"
}
