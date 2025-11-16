# Outage Report: TXT Record Parsing Failure in mDNS Discovery

**Date**: 2025-11-16  
**Component**: `scripts/k3s_mdns_parser.py` TXT record parsing  
**Severity**: Critical (cluster formation blocked)  
**Status**: Resolved

## Summary

Cross-node mDNS discovery failed because the `_parse_txt_fields()` function expected TXT records to have a `txt=` prefix, but `avahi-browse --parsable --resolve` outputs TXT records as separate semicolon-delimited fields **without** this prefix. This caused ALL TXT records to be skipped during parsing, resulting in `role=None` for discovered services. Since the `server-select` rendering mode filters for `role="server"`, discovery returned 0 servers even when services were successfully found and parsed.

## Impact

- **Complete discovery failure**: Joining nodes could not discover bootstrap nodes
- **Cluster formation blocked**: sugarkube1 could not join cluster despite sugarkube0 advertising its service
- **Misleading logs**: Logs showed records were found ("1 records") but no results returned ("0 results for mode=server-select")
- **Affected all environments**: dev, int, prod all impacted

## Timeline

### sugarkube0 (Bootstrap Node)
```
20:33:24  Discovery starts (no token, bootstrap allowed)
20:38:05  Bootstrap role service published successfully
20:38:11  Self-check confirms bootstrap service visible
20:38:40  k3s API ready, republishing as server role
20:39:13  Server role service published successfully
20:39:19  Self-check confirms server service visible
```

### sugarkube1 (Joining Node)
```
20:48:04  Discovery starts (token present, cannot bootstrap)
20:48:04  Simple discovery enabled, browsing for services
20:48:04  avahi-browse timeouts begin (30s timeout × 2 attempts)
20:50:07  Discovery completes: "2 lines, 1 records" found
20:50:07  But: "returning 0 results for mode=server-select"
20:50:07  Error: "No joinable servers found via mDNS service browsing"
20:50:07  Exit: Cannot bootstrap (token present but no servers)
```

Total elapsed: ~123 seconds (mostly waiting for avahi-browse timeouts)

## Root Cause Analysis

### The Bug

The `_parse_txt_fields()` function in `scripts/k3s_mdns_parser.py` had this logic:

```python
def _parse_txt_fields(fields: Sequence[str]) -> Dict[str, str]:
    txt: Dict[str, str] = {}
    for field in fields:
        field = field.strip()
        if not field:
            continue
        field = _strip_quotes(field)
        if not field.startswith("txt="):  # ← Bug: This check fails!
            continue  # ← Skips ALL TXT records from avahi-browse
        # ... rest of parsing never executes
```

### What avahi-browse Actually Outputs

When running `avahi-browse --parsable --resolve _k3s-sugar-dev._tcp`, the output format is:

```
=;interface;protocol;name;type;domain;hostname;address;port;txt1;txt2;txt3;...
```

Fields 0-8 are the record metadata. Fields 9+ are TXT records, **each as a separate semicolon-delimited field**:

```
=;eth0;IPv4;k3s-sugar-dev@sugarkube0.local (server);_k3s-sugar-dev._tcp;local;sugarkube0.local;192.168.86.41;6443;"role=server";"phase=server";"cluster=sugar";"env=dev";"k3s=1"
                                                                                                                      ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
                                                                                                                      TXT records - NO txt= prefix!
```

### The Mismatch

- **Parser expected**: `txt="role=server,phase=server,cluster=sugar"`
- **avahi-browse outputs**: `"role=server";"phase=server";"cluster=sugar"` (separate fields, no prefix)
- **Result**: The `if not field.startswith("txt="):` check failed for every TXT field
- **Effect**: TXT dict remained empty, `record.txt = {}`

### Discovery Flow Breakdown

1. **avahi-browse finds service**: ✅ Returns 2 lines
2. **Parser normalizes lines**: ✅ Produces 1 record  
3. **Parser extracts TXT fields**: ❌ All TXT fields skipped (no txt= prefix)
4. **Record created with empty TXT dict**: `record.txt = {}`
5. **server-select mode checks**: `if record.txt.get("role") != "server":`
6. **Check fails**: `None != "server"` is True, so record is skipped
7. **Result**: Returns empty list (0 servers)

## Evidence

### Log Analysis

From `logs/up/20251116T044635Z_7b2a7da_sugarkube1_just-up-dev.log`:

```
[k3s-discover mdns] _load_lines_from_avahi: got 2 normalized lines from _k3s-sugar-dev._tcp
[k3s-discover mdns] query_mdns: initial browse returned 2 lines, 1 records
[k3s-discover mdns] query_mdns: returning 0 results for mode=server-select
```

This confirms:
- ✅ avahi-browse found and returned data (2 lines)
- ✅ Parser created a record (1 records)
- ❌ But server-select returned nothing (0 results)

The only explanation: the record was created but lacked the `role="server"` TXT field.

### Manual Testing

Testing the parser directly with avahi-browse format:

```python
>>> from k3s_mdns_parser import parse_mdns_records
>>> line = '=;eth0;IPv4;test;_k3s-sugar-dev._tcp;local;host.local;192.168.1.1;6443;"role=server";"phase=server"'
>>> records = parse_mdns_records([line], 'sugar', 'dev')
>>> records[0].txt
{}  # ← Empty! TXT fields not parsed
>>> records[0].txt.get("role")
None  # ← This causes server-select to return 0 results
```

After the fix:

```python
>>> records[0].txt
{'role': 'server', 'phase': 'server'}
>>> records[0].txt.get("role")
'server'
```

## Resolution

### Code Changes

**File**: `scripts/k3s_mdns_parser.py`  
**Function**: `_parse_txt_fields()`

**Before**:
```python
def _parse_txt_fields(fields: Sequence[str]) -> Dict[str, str]:
    txt: Dict[str, str] = {}
    for field in fields:
        field = field.strip()
        if not field:
            continue
        field = _strip_quotes(field)
        if not field.startswith("txt="):  # ← Rejects avahi-browse format
            continue
        payload = field[4:]
        # ... rest of parsing
```

**After**:
```python
def _parse_txt_fields(fields: Sequence[str]) -> Dict[str, str]:
    txt: Dict[str, str] = {}
    for field in fields:
        field = field.strip()
        if not field:
            continue
        field = _strip_quotes(field)
        
        # Handle two formats:
        # 1. avahi-browse --parsable format: fields are TXT records directly
        # 2. Legacy format with txt= prefix: txt="role=server,phase=active"
        payload = field
        if field.startswith("txt="):
            payload = field[4:]
            if not payload:
                continue
            payload = _strip_quotes(payload.strip())
            if not payload:
                continue
        
        # Parse payload - could be single key=value or comma-separated list
        entries = [payload]
        if "," in payload and "=" in payload:
            entries = [item.strip() for item in payload.split(",") if item.strip()]
        
        for entry in entries:
            # ... rest of parsing unchanged
```

### Key Changes

1. **Removed hard requirement for txt= prefix**: Now accepts fields with or without the prefix
2. **Backward compatible**: Still handles legacy `txt="k=v,k2=v2"` format if encountered
3. **Default to direct parsing**: If no `txt=` prefix, treat the field as a TXT record directly

## Testing

### New Tests Added

**File**: `tests/scripts/test_k3s_mdns_parser.py`

1. **`test_parse_txt_fields_without_prefix`**:
   - Tests parsing of actual avahi-browse format
   - Verifies all TXT fields are extracted: role, phase, cluster, env, k3s, ip4, ip6, host, leader
   - Uses real format from sugarkube0's published service

2. **`test_parse_txt_fields_with_and_without_prefix`**:
   - Tests both formats together (legacy txt= and raw avahi-browse)
   - Ensures backward compatibility
   - Confirms both formats produce correct TXT dicts

### Test Results

```bash
$ python3 -m pytest tests/scripts/test_k3s_mdns_parser.py -v
================================================= test session starts ==================================================
tests/scripts/test_k3s_mdns_parser.py::test_parse_bootstrap_and_server_ipv4_preferred PASSED                     [ 10%]
tests/scripts/test_k3s_mdns_parser.py::test_parse_unresolved_bootstrap_uses_service_name PASSED                  [ 20%]
tests/scripts/test_k3s_mdns_parser.py::test_parse_trims_trailing_dots_from_host_fields PASSED                    [ 30%]
tests/scripts/test_k3s_mdns_parser.py::test_resolved_record_replaces_unresolved_placeholder PASSED               [ 40%]
tests/scripts/test_k3s_mdns_parser.py::test_record_updates_when_txt_richer PASSED                                [ 50%]
tests/scripts/test_k3s_mdns_parser.py::test_parse_preserves_mixed_case_hostnames PASSED                          [ 60%]
tests/scripts/test_k3s_mdns_parser.py::test_parse_normalises_txt_whitespace_and_missing_host_falls_back_to_leader PASSED [ 70%]
tests/scripts/test_k3s_mdns_parser.py::test_parse_accepts_uppercase_cluster_and_env_values PASSED                [ 80%]
tests/scripts/test_k3s_mdns_parser.py::test_parse_txt_fields_without_prefix PASSED                               [ 90%]
tests/scripts/test_k3s_mdns_parser.py::test_parse_txt_fields_with_and_without_prefix PASSED                      [100%]
================================================== 10 passed in 0.05s ===================================================

$ python3 -m pytest tests/scripts/test_k3s_mdns_query.py -v
================================================= test session starts ==================================================
tests/scripts/test_k3s_mdns_query.py::test_query_mdns_keeps_output_when_avahi_errors PASSED                      [  9%]
tests/scripts/test_k3s_mdns_query.py::test_query_mdns_handles_avahi_timeout PASSED                               [ 18%]
tests/scripts/test_k3s_mdns_query.py::test_query_mdns_queries_legacy_service_type_when_needed PASSED             [ 27%]
tests/scripts/test_k3s_mdns_query.py::test_query_mdns_bootstrap_leaders_uses_txt_leader PASSED                   [ 36%]
tests/scripts/test_k3s_mdns_query.py::test_query_mdns_uses_service_name_when_unresolved PASSED                   [ 45%]
tests/scripts/test_k3s_mdns_query.py::test_query_mdns_handles_missing_avahi PASSED                               [ 54%]
tests/scripts/test_k3s_mdns_query.py::test_query_mdns_server_hosts_returns_unique_hosts PASSED                   [ 63%]
tests/scripts/test_k3s_mdns_query.py::test_query_mdns_falls_back_without_resolve PASSED                          [ 72%]
tests/scripts/test_k3s_mdns_query.py::test_query_mdns_retries_on_failure PASSED                                  [ 81%]
tests/scripts/test_k3s_mdns_query.py::test_query_mdns_logs_exit_codes_and_stderr PASSED                          [ 90%]
tests/scripts/test_k3s_mdns_query.py::test_query_mdns_uses_allow_iface PASSED                                    [100%]
================================================== 11 passed in 4.57s ===================================================
```

All 21 tests pass (10 parser + 11 query), including 2 new regression tests.

## Verification

After the fix, running the same scenario:

1. **sugarkube0 bootstraps**: ✅ Publishes service with role=server
2. **sugarkube1 discovers**: ✅ avahi-browse finds service (2 lines, 1 records)
3. **Parser extracts TXT**: ✅ TXT dict includes `{"role": "server", "phase": "server", ...}`
4. **server-select filters**: ✅ Record matches `role="server"` condition
5. **Result**: ✅ Returns 1 server: `mode=server host=sugarkube0.local port=6443 address=192.168.86.41`

## Lessons Learned

### Why This Bug Existed

1. **Test coverage gap**: Existing tests used synthetic `txt=` prefix format, not actual avahi-browse output
2. **Incorrect assumptions**: Parser was written based on expected format, not actual avahi-browse behavior
3. **Insufficient integration testing**: Unit tests with fixtures didn't catch the real-world format mismatch

### Why It Wasn't Caught Earlier

1. **Self-checks passed**: Bootstrap nodes could verify their own services (using same buggy parser)
2. **Misleading logs**: "1 records" suggested parsing worked, hiding the empty TXT dict
3. **No real avahi-browse testing**: Tests mocked avahi-browse or used fixture files with wrong format

### Why It Manifested Now

Real-world testing on Raspberry Pi 5 hardware was the first time:
- Two physical nodes tried to discover each other
- Actual avahi-browse was invoked (not mocked)
- Real network conditions exposed the timeout behavior
- Full discovery→parse→filter→render pipeline was exercised

## Prevention

### Immediate Actions Taken

1. ✅ **Added regression tests** with actual avahi-browse format
2. ✅ **Fixed parser** to handle both formats
3. ✅ **Verified backward compatibility** with existing test fixtures
4. ✅ **Documented the bug** in this outage report

### Future Improvements

1. **Integration testing**: Add tests that exercise real avahi-browse commands
2. **Format validation**: Document expected avahi-browse output format in code comments
3. **Logging enhancement**: Log TXT dict contents when records are parsed (for debugging)
4. **Discovery E2E test**: Create end-to-end test that simulates full discovery flow

### Documentation Updates

No documentation changes needed - the fix is transparent to users. The system now works as documented in `docs/raspi_cluster_setup.md`.

## References

- **Primary fix**: `scripts/k3s_mdns_parser.py` `_parse_txt_fields()` function
- **Test coverage**: `tests/scripts/test_k3s_mdns_parser.py`
- **Related outage**: `outages/2025-11-15-discovery-visibility-gap.json` (documented symptoms)
- **User guide**: `docs/raspi_cluster_setup.md` (How Discovery Works section)
- **avahi-browse docs**: `man avahi-browse` (parsable output format)

## Conclusion

This was a critical bug that completely prevented cross-node discovery. The fix was surgical (modified one function) and maintains backward compatibility while correctly handling the actual avahi-browse output format. With comprehensive test coverage added, this specific failure mode should not recur.

The bug highlights the importance of:
- Testing with real tools, not just mocks
- Using actual command output formats in test fixtures
- Validating assumptions against real-world behavior
- End-to-end integration testing in realistic environments
