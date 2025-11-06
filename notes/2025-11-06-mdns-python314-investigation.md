# mDNS Test Failures Investigation - Python 3.14 CI Issue

**Date**: 2025-11-06  
**Status**: UNRESOLVED - 3 tests still failing in Python 3.14 CI  
**Branch**: copilot/fix-python-coverage-step  
**Related Issue**: CI pytest step failing

## Executive Summary

After fixing the primary kcov test discovery issue and Makefile syntax errors, we uncovered 3 persistent mDNS test failures that only occur in Python 3.14 CI environment but pass locally on Python 3.12.3. Multiple approaches have been attempted without success.

## Failing Tests

All 3 tests in `tests/test_mdns_discovery_parsing.py`:

1. `test_server_first_returns_expected_host` - expects `["sugar-control-0.local"]`, gets `[]`
2. `test_server_count_detects_all_servers` - expects `["2"]`, gets `["0"]`
3. `test_print_server_hosts_lists_unique_hosts` - expects `["sugar-control-0.local", "sugar-control-1.local"]`, gets `[]`

**Common symptom**: Tests return empty arrays instead of expected data. No errors, exit code 0, but no results.

## Environment Details

- **Local (passing)**: Python 3.12.3 on Ubuntu
- **CI (failing)**: Python 3.14.0 on ubuntu-latest GitHub Actions runner
- **Test framework**: pytest with subprocess calls to bash script
- **Script under test**: `scripts/k3s-discover.sh` with inline Python code

## Test Architecture

```
Test (Python) 
  → subprocess.run(["bash", "k3s-discover.sh", "--run-avahi-query", mode], env=mdns_env)
    → Bash script exports variables
      → Inline Python code (python3 -)
        → Imports: k3s_mdns_query, k3s_mdns_parser, mdns_helpers
        → Calls query_mdns()
          → subprocess.run(["avahi-browse", ...])
            → Mock avahi-browse script (in test fixture's tmp_path/bin/)
```

## Fixes Attempted (Chronologically)

### Attempt 1: Add sys.path manipulation (Commit 750097c)
**Hypothesis**: Python 3.14 requires explicit sys.path setup for stdin scripts  
**Implementation**: Added SCRIPT_DIR to sys.path in inline Python heredocs
```python
scripts_dir = os.environ.get("SCRIPT_DIR")
if scripts_dir and scripts_dir not in sys.path:
    sys.path.insert(0, scripts_dir)
```
**Result**: Tests still failing - empty results

### Attempt 2: Preserve PYTHONPATH via env command (Commit e5cced4)
**Hypothesis**: The `env` command was dropping PYTHONPATH, breaking module imports  
**Implementation**: Added PYTHONPATH to environment variable arrays
```bash
if [ -n "${PYTHONPATH:-}" ]; then
  query_env+=("PYTHONPATH=${PYTHONPATH}")
fi
```
**Result**: Tests still failing - empty results

### Attempt 3: Preserve PATH via env command (Commit 347ad86)
**Hypothesis**: Without PATH, subprocess can't find mock avahi-browse  
**Implementation**: Added PATH preservation alongside PYTHONPATH
```bash
if [ -n "${PATH:-}" ]; then
  query_env+=("PATH=${PATH}")
fi
```
**Result**: Tests still failing - empty results

### Attempt 4: Replace env command with export (Commit f48b24e) ⭐ CURRENT
**Hypothesis**: The `env` command with explicit variables creates a minimal environment, losing all other essential variables (HOME, USER, TMPDIR, LC_*, etc.) needed by Python 3.14  
**Implementation**: Completely removed `env` command usage, using direct exports instead
```bash
# Before:
env "${query_env[@]}" SCRIPT_DIR="${SCRIPT_DIR}" python3 -

# After:
export SUGARKUBE_CLUSTER="${CLUSTER}"
export SUGARKUBE_ENV="${ENVIRONMENT}"
export SUGARKUBE_TOKEN="${TOKEN}"  # if set
export SCRIPT_DIR="${SCRIPT_DIR}"
python3 -
```
**Result**: Tests STILL failing - empty results (but tests pass locally on Python 3.12.3)

## Test Fixture Details

The test fixture (`mdns_env`) in `tests/test_mdns_discovery_parsing.py` creates:

```python
env = os.environ.copy()  # Copies ALL environment variables
env.update({
    "PATH": f"{bin_dir}:{env.get('PATH', '')}",  # Prepends mock bin dir
    "SUGARKUBE_SERVERS": "1",
    "SUGARKUBE_NODE_TOKEN_PATH": str(tmp_path / "node-token"),
    "SUGARKUBE_BOOT_TOKEN_PATH": str(tmp_path / "boot-token"),
    "SUGARKUBE_CLUSTER": "sugar",
    "SUGARKUBE_ENV": "dev",
    "SUGARKUBE_MDNS_DBUS": "0",
})
```

Mock `avahi-browse` script is created at runtime in `tmp_path / "bin" / "avahi-browse"` and returns hardcoded test data.

## Analysis & Observations

### What Works
- All 8 tests pass locally on Python 3.12.3
- The bash script receives the correct environment from the test
- The bash script successfully exports variables
- No import errors or exceptions occur
- Script exits with code 0 (success)

### What Fails
- Python 3.14 in CI returns empty results
- No stderr output or error messages
- The inline Python code appears to run but produces no output
- The query_mdns() function returns empty arrays

### Key Questions Unanswered

1. **Why does the inline Python code produce no output in Python 3.14?**
   - Is there a silent failure in the heredoc processing?
   - Does Python 3.14 handle stdin differently?
   - Is the stdout being lost somehow?

2. **Is the mock avahi-browse being called at all?**
   - Could add logging to the mock script
   - Could check /tmp for any debug dumps

3. **Are there Python 3.14-specific subprocess changes?**
   - PEP 594 removed some modules
   - subprocess.run behavior changes?
   - stdin handling changes?

4. **Could this be a pytest interaction issue?**
   - Different capture behavior in Python 3.14?
   - Environment isolation differences?

## Python 3.14 Notable Changes (Potentially Relevant)

From Python 3.14 release notes:
- PEP 594: Many deprecated modules removed
- Improved error messages for import failures
- Changes to subprocess module internals
- UTF-8 mode enabled by default on all platforms
- Changes to environment variable handling

## Code Locations

### Test File
`tests/test_mdns_discovery_parsing.py` (lines 96-135)

### Script Under Test
`scripts/k3s-discover.sh`
- Function: `run_avahi_query()` (line ~2027)
- Function: `mdns_absence_check_cli()` (line ~1466)

### Python Module
`scripts/k3s_mdns_query.py`
- Function: `query_mdns()` (line ~225)
- Function: `_invoke_avahi()` (line ~59)

## Debugging Suggestions for Next Attempt

### 1. Add Debug Output
Add debug prints to the inline Python script to see what's executing:
```python
import sys
print("DEBUG: Python version:", sys.version, file=sys.stderr)
print("DEBUG: PATH:", os.environ.get('PATH'), file=sys.stderr)
print("DEBUG: SCRIPT_DIR:", os.environ.get('SCRIPT_DIR'), file=sys.stderr)
print("DEBUG: About to call query_mdns", file=sys.stderr)
results = query_mdns(...)
print("DEBUG: Results:", results, file=sys.stderr)
```

### 2. Test Python 3.14 Locally
If possible, install Python 3.14 locally and run the tests:
```bash
pyenv install 3.14.0
pyenv local 3.14.0
pytest tests/test_mdns_discovery_parsing.py -xvs
```

### 3. Simplify the Test
Create a minimal reproduction case:
```python
def test_inline_python_heredoc():
    result = subprocess.run(
        ["bash", "-c", "python3 - <<'PY'\nimport sys\nprint('hello')\nPY"],
        capture_output=True, text=True
    )
    assert result.stdout.strip() == "hello"
```

### 4. Check Subprocess Behavior
Test if subprocess.run works differently in Python 3.14:
```python
def test_subprocess_avahi():
    # Manually create mock avahi-browse
    result = subprocess.run(["./mock-avahi-browse"], ...)
    # Check if it runs at all
```

### 5. Enable SUGARKUBE_DEBUG
The code supports debug mode:
```bash
export SUGARKUBE_DEBUG=1
```
This would print debug messages from query_mdns if it's being called.

### 6. Check for Timeout Issues
The query_mdns function has a timeout (default 10s). Maybe Python 3.14's subprocess times out differently:
```python
timeout = _resolve_timeout(os.environ.get(_TIMEOUT_ENV))  # Default 10.0
```

### 7. Test Without pytest
Run the script directly in CI to isolate pytest from the equation:
```bash
export PATH="/tmp/mock-bin:$PATH"
bash scripts/k3s-discover.sh --run-avahi-query server-first
```

## Hypothesis: Stdout Buffering or Capture Issue

**New Theory**: Python 3.14 may have changed how stdout is buffered or captured when using stdin scripts. The inline Python code might be executing correctly but its output isn't making it back through the heredoc.

**Test**: Try forcing stdout flush:
```python
for line in results:
    print(line)
    sys.stdout.flush()  # Force immediate output
```

## Hypothesis: Heredoc Processing Change

**New Theory**: Bash or Python 3.14 might handle heredocs differently, especially with the `<<'PY'` syntax.

**Test**: Try using a different approach:
- Write Python code to a temp file
- Execute the temp file instead of using heredoc
- Or use `python3 -c "..."` instead of `python3 -`

## Related Files Changed in This PR

1. `pyproject.toml` - Added pytest configuration (testpaths, norecursedirs)
2. `.gitignore` - Added kcov/ directory
3. `Makefile` - Fixed tab characters (lines 197-202)
4. `scripts/k3s-discover.sh` - Multiple environment variable handling changes
5. `outages/*.json` - Documented all issues

## Summary for Next Investigation

The root cause is NOT:
- ❌ Module import failures (sys.path is set correctly)
- ❌ Missing PYTHONPATH (we export it)
- ❌ Missing PATH (we export it)
- ❌ Missing environment variables (we inherit full environment)
- ❌ Makefile syntax (fixed separately)
- ❌ kcov test discovery (fixed separately)

The root cause MAY BE:
- ⚠️ Python 3.14 stdout buffering/capture changes with stdin scripts
- ⚠️ Python 3.14 subprocess.run behavior changes
- ⚠️ Heredoc processing differences between Python versions
- ⚠️ pytest capture mechanism interaction with Python 3.14
- ⚠️ Silent timeout or exception being swallowed
- ⚠️ Mock avahi-browse script not executing in Python 3.14 environment

## Action Items for Next Developer

1. **Immediate**: Add extensive debug logging to isolate where the failure occurs
2. **Test**: Install Python 3.14 locally and reproduce the issue
3. **Simplify**: Create minimal reproduction without the full test infrastructure
4. **Compare**: Run same code in Python 3.12 vs 3.14 with verbose output
5. **Alternative**: Consider rewriting inline Python as separate script file
6. **Workaround**: If unfixable, consider skipping these tests on Python 3.14 with a marker

## Contact & References

- PR: copilot/fix-python-coverage-step
- CI Workflow: `.github/workflows/ci.yml`
- Related Commits: f48b24e, 347ad86, e5cced4, 750097c
- Outage Documentation: `outages/2025-11-06-ci-python314-module-import-inline-scripts.json`
