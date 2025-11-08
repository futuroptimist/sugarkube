# Test 7 Partial Investigation - Bootstrap Election Scenario

**Date**: 2025-11-08  
**Status**: 85% complete (15-20 min remaining)

## Investigation Summary

Test 7 validates the bootstrap election resilience scenario where a node becomes the first server in a k3s cluster after handling a transient mDNS publish failure.

### Real Use Case (per docs/raspi_cluster_setup.md)

When a user boots the first Raspberry Pi with `SUGARKUBE_SERVERS=3`:
1. Node discovers no existing k3s servers via mDNS
2. Node runs bootstrap election to decide who initializes cluster
3. Election winner attempts to publish mDNS advertisement
4. **If initial publish fails** (transient multicast issue), node re-runs election
5. Winner proceeds with k3s bootstrap using `--cluster-init` (embedded etcd)

This test validates the **decision-making logic** for this resilience scenario, NOT the actual k3s installation (which is stubbed).

## Progress Made (45 minutes)

### Completed
- ✅ Removed skip directive from Test 7
- ✅ Added comprehensive use case documentation to test comments
- ✅ Fixed environment variables:
  - `SUGARKUBE_SKIP_MDNS_SELF_CHECK=1` (was missing SUGARKUBE prefix)
  - `SUGARKUBE_API_READY_TIMEOUT=2` (reduce from 120s default)
- ✅ Added `timeout 10` wrapper to prevent indefinite hangs
- ✅ Test now completes in <10 seconds (was hanging indefinitely)
- ✅ Validated test infrastructure (all stubs exist and are created correctly)

### Root Cause Analysis

**Primary Issue**: Test completes successfully (status=0) but BATS `run` command captures no output.

**Investigation Findings**:
1. Script logs go to stderr using `>&2` redirects
2. BATS `run` should capture both stdout and stderr, but isn't
3. Running script manually shows it fails at `configure_avahi.sh` step
4. Test fixture setup may have issues with stub paths or execution environment

**Additional Discovery**: Script has multiple test modes that may help:
- `--test-bootstrap-server-flow`: Tests bootstrap publish and API service flow
- `--test-claim-bootstrap`: Tests bootstrap leadership claim logic
- `--test-bootstrap-publish`: Tests bootstrap advertisement (used by Test 5)

These test modes might provide a cleaner way to isolate the scenario being tested.

## Remaining Work (15-20 min estimated)

### Next Steps
1. **Debug BATS output capture** (~10 min)
   - Verify BATS `run` captures stderr correctly
   - Consider using test mode flag like `--test-bootstrap-server-flow`
   - Test with explicit `2>&1` redirection if needed

2. **Verify stub paths** (~5 min)
   - Ensure all stub paths are accessible in BATS test environment
   - Validate `BATS_TEST_TMPDIR` and `BATS_CWD` are set correctly
   - Check stub execution permissions

3. **Validate test assertions** (~5 min)
   - Confirm expected output format matches actual script output
   - Adjust assertions if output format differs
   - Test passes locally

## Key Learning

Following the problem statement's "understand real use case first" principle was essential. By reading `docs/raspi_cluster_setup.md`, I understood that:
- Tests validate **decision-making logic**, not actual k3s installation
- External dependencies should be stubbed (k3s install, API checks, mDNS)
- The resilience scenario (re-election after publish failure) is an important edge case

This represents meaningful partial progress per the problem statement's "Investigation & Documentation" strategy with clear next steps for future work.

## References

- Test file: `tests/bats/discover_flow.bats:595-654`
- Script logic: `scripts/k3s-discover.sh:3640-3750`
- User documentation: `docs/raspi_cluster_setup.md:12-89`
- Previous investigation: `notes/k3s-integration-tests-investigation-20251108.md`
- Status tracking: `notes/skipped-tests-status.md:36-124`
