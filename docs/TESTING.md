# Testing Infrastructure

Sugarkube uses a comprehensive testing strategy combining unit tests, integration tests, and
end-to-end validation to ensure reliability across the Pi cluster deployment pipeline.

## Test Frameworks

### Unit Tests

**Python Tests**: Located in `tests/` with `*_test.py` naming convention
- Run with [pytest](https://docs.pytest.org/en/stable/)
- Coverage reporting enabled via `--cov` flag
- Focus on individual component behavior and edge cases

**Shell Tests**: Located in `tests/bats/` with `*.bats` naming convention
- Run with [Bats](https://bats-core.readthedocs.io/)
- Test shell script logic and command-line interfaces
- Validate parsing, error handling, and state transitions

### Integration Tests

**mDNS Roundtrip**: Located in `tests/integration/mdns_roundtrip.bats`
- Enables a hermetic Avahi stub when `avahi-*` binaries are missing, so no
  host services are required.
- Tests service publishing and discovery
- Validates the complete mDNS discovery flow

**Pi Smoke Tests**: Located in `tests/pi_smoke_test_unit_test.py`
- SSH-based validation of Pi node health
- Tests cluster readiness and service availability
- Supports reboot validation and JSON output

## Running Tests

### Quick Iteration

```bash
# Run all Python unit tests
pytest tests/

# Run specific test file
pytest tests/test_mdns_parsing.py

# Run Bats shell tests
bats tests/bats/discover_flow.bats

# Run integration tests (requires Avahi)
AVAHI_AVAILABLE=1 bats tests/integration/mdns_roundtrip.bats
```

### Full Test Suite

```bash
# Run complete test suite with linting
pre-commit run --all-files
```

This command executes `scripts/checks.sh` which:
- Installs missing tools (including `bats`)
- Runs ShellCheck on all shell scripts
- Executes both Python and Bats test suites
- Generates coverage reports

### CI Integration

The GitHub Actions workflow `.github/workflows/tests.yml` runs:
- Python tests with coverage reporting
- Uploads coverage to Codecov (when token available)
- Fails fast on first test failure (`--maxfail=1`)

## Test Coverage Requirements

- **100% patch coverage** on first test run for new features
- Design fixes to avoid reruns and minimize regression risk
- Record persistent test issues in `outages/` using `schema.json`

## Test Categories

### Discovery Flow Tests
- `tests/bats/discover_flow.bats`: Core discovery logic
- `tests/test_mdns_discovery_parsing.py`: mDNS parsing edge cases
- `tests/test_k3s_discover_token_resolution_cli.py`: Token handling

### Pi Image Tests
- `tests/build_pi_image_test.py`: Image building pipeline
- `tests/pi_smoke_test_unit_test.py`: Node health validation
- `tests/test_qemu_pi_smoke_test.py`: QEMU-based testing

### Documentation Tests
- `tests/test_doc_*.py`: Documentation validation
- `tests/test_tutorial_*.py`: Tutorial completeness
- Spellcheck and link validation via `pyspelling` and `linkchecker`

### Security Tests
- `tests/scan_secrets_test.py`: Secret detection
- `tests/test_sendemail_validate_hook.py`: Email workflow validation

## Debugging Test Failures

### Environment Issues
- Ensure required tools are installed (`bats`, `avahi-utils`, `shellcheck`)
- Check environment variables (`AVAHI_AVAILABLE`, `LOG_LEVEL`)
- Verify network connectivity for integration tests
- Network namespace suites retry TCP probes before skipping and include the last failure reason in
  the skip message. Use that context to determine whether the runner lacks kernel support or
  needs additional privileges.

### Test-Specific Debugging
- Use `LOG_LEVEL=debug` for verbose discovery test output
- Enable `SUGARKUBE_DEBUG_MDNS=1` for mDNS troubleshooting
- Check `outages/` directory for known issues and resolutions

### Coverage Analysis
- Review coverage reports to identify untested code paths
- Focus on critical discovery and bootstrap logic
- Ensure error handling and edge cases are covered
