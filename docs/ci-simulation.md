# CI Workflow Simulation

This document explains how to simulate the CI workflow environment locally to catch issues before pushing to GitHub.

## Why Simulate CI Locally?

Some issues only appear in the CI environment due to:
- Different environment variables (e.g., `BATS_CWD`, `GITHUB_WORKSPACE`)
- Code coverage instrumentation (kcov) affecting test execution
- EXIT traps behaving differently under instrumentation
- Subshell depth and exit status propagation issues

The `ci_simulate.sh` script replicates the exact CI environment to help identify these issues early.

## Quick Start

### Basic Simulation (Recommended)

Run this before every push to ensure your changes work in CI:

```bash
make ci-simulate
```

Or directly:

```bash
./scripts/ci_simulate.sh
```

This sets the same environment variables as CI and runs BATS tests.

### Full Simulation with kcov (Advanced)

To catch kcov instrumentation issues:

```bash
make ci-simulate-kcov
```

Or with installation:

```bash
./scripts/ci_simulate.sh --install-kcov --with-kcov
```

**Note**: Installing kcov requires sudo and takes 2-3 minutes.

## Usage

### Command Line Options

```bash
./scripts/ci_simulate.sh [OPTIONS]

OPTIONS:
  --with-kcov         Run BATS tests under kcov (like CI does)
  --install-kcov      Install kcov if not present (requires sudo)
  --kcov-only         Only run kcov simulation, skip basic tests
  --skip-install      Skip checking for missing dependencies
  -h, --help          Show this help message
```

### Examples

**Before pushing changes:**
```bash
make ci-simulate
```

**After fixing kcov-related issues:**
```bash
./scripts/ci_simulate.sh --with-kcov
```

**First-time setup with kcov:**
```bash
./scripts/ci_simulate.sh --install-kcov --with-kcov
```

## What It Tests

### Basic Simulation
- Sets `BATS_CWD` and `BATS_LIB_PATH` exactly as CI does
- Runs `bats --recursive tests/bats`
- Catches environment variable issues

### kcov Simulation
- Runs BATS under kcov code coverage instrumentation
- Uses the same kcov flags as `.github/workflows/ci.yml`
- Catches EXIT trap issues and subshell depth problems
- Generates coverage report in `coverage/kcov/`

## Common Issues and Fixes

### Issue: Tests pass locally but fail in CI

**Symptom:**
```
not ok 40 summary emits output without color when non-tty
# (in test file tests/bats/summary.bats, line 14)
#   `[ "$status" -eq 0 ]' failed
```

**Solution:**
1. Run `make ci-simulate` to reproduce locally
2. If it passes, run `./scripts/ci_simulate.sh --with-kcov`
3. Fix issues caught by kcov (usually EXIT trap or subshell problems)

### Issue: BATS_CWD undefined

**Symptom:**
```
bash: /scripts/lib/summary.sh: No such file or directory
```

**Solution:**
Ensure `BATS_CWD` is set in `.github/workflows/ci.yml`:
```yaml
env:
  BATS_CWD: ${{ github.workspace }}
```

### Issue: kcov instrumentation failures

**Symptom:**
Tests pass in basic mode but fail under kcov.

**Common causes:**
1. **EXIT traps**: Double-calling functions via trap and explicit call
2. **Subshell depth**: Too many nested subshells (kcov limit ~3 levels)
3. **Exit status propagation**: Missing `return $?` in wrapper functions

**Solutions:**
- Let EXIT traps handle cleanup instead of explicit calls
- Avoid unnecessary subshells: use `"$@"` instead of `( "$@" )`
- Add explicit `return $?` in wrapper functions

## Integration with Pre-commit Hooks

Add to your workflow:

```bash
# Before committing
make ci-simulate

# Or in pre-push hook
git diff --name-only HEAD @{u} | grep -q '\.bats$\|scripts/' && make ci-simulate
```

## Troubleshooting

### kcov not found

Install dependencies:
```bash
sudo apt-get install cmake libdw-dev libcurl4-openssl-dev binutils-dev libiberty-dev
```

Then run:
```bash
./scripts/ci_simulate.sh --install-kcov
```

### Tests hang under kcov

Some tests may timeout under kcov instrumentation. Check for:
- Infinite loops in test stubs
- Missing background process cleanup
- Deadlocks in subshells

## Related Documentation

- `.github/workflows/ci.yml` - Actual CI workflow configuration
- `scripts/ci_commands.sh` - Basic CI command runner (no kcov)
- `outages/2025-11-06-kcov-subshell-depth-summary-tests.json` - kcov issue example

## Success Criteria

Before pushing changes, ensure:
- ✅ `make ci-simulate` passes
- ✅ If touching summary.sh or EXIT traps: `./scripts/ci_simulate.sh --with-kcov` passes
- ✅ No `not ok` failures in output
- ✅ All expected tests show as `ok` or `skip`

## Quick Reference

| Command | When to Use |
|---------|-------------|
| `make ci-simulate` | Before every push |
| `make ci-simulate-kcov` | After fixing EXIT trap or kcov issues |
| `./scripts/ci_simulate.sh --install-kcov` | First-time kcov setup |
| `./scripts/ci_simulate.sh --help` | See all options |
