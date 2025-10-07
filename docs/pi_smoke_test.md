---
personas:
  - software
---

# Pi Image Smoke Test Harness

The Pi image now ships with `pi_node_verifier.sh` to validate cluster readiness on the node
itself. `scripts/pi_smoke_test.py` wraps those checks so you can verify fresh nodes over SSH,
re-run the verifier after a reboot, and export JSON summaries for downstream automation.

## Prerequisites

- `ssh` access to each Raspberry Pi node (the script defaults to the `pi` user)
- Passwordless `sudo` for the remote account (pass `--no-sudo` when not available)
- Python 3.8+ on the control machine running the harness

## Basic usage

```bash
# Run verifier checks against one host
scripts/pi_smoke_test.py 192.168.1.50

# Test multiple hosts and emit JSON for CI consumers
scripts/pi_smoke_test.py --json pi-a.local pi-b.local

# Supply hosts via repeatable --host flags when positional arguments are
# awkward (for example when templating commands)
scripts/pi_smoke_test.py --host pi-a.local --host pi-b.local --json
```

The script prints a PASS/FAIL line for each host. When `--json` is supplied the final line
contains a structured summary that callers can parse.

## Reboot validation

Use `--reboot` to confirm the cluster converges after a restart. The harness waits for SSH to
become available again and repeats the verifier run.

```bash
scripts/pi_smoke_test.py --reboot --reboot-timeout 900 pi-a.local
```

Adjust `--poll-interval` to control how frequently the script probes for SSH availability.

## Skipping or overriding health probes

The verifier can skip individual health checks or point at alternate endpoints:

```bash
scripts/pi_smoke_test.py \
  --skip-token-place \
  --dspace-url https://dspace.internal/healthz \
  pi-a.local
```

## Task runner integration

The root `Makefile` and `justfile` expose a `smoke-test-pi` target. Supply arguments through
`SMOKE_ARGS` (Make) or environment variables when running with `just`:

```bash
make smoke-test-pi SMOKE_ARGS="192.168.1.50 --reboot"
# or
SMOKE_ARGS="pi-a.local" just smoke-test-pi
```

Both helpers call the Python harness, so they support the same flags as invoking the script
directly.

## Unified CLI entrypoint

Prefer the consolidated Sugarkube CLI? The repository ships a `scripts/sugarkube` launcher that
forwards to `python -m sugarkube_toolkit`, letting you run the smoke test via the documented
`sugarkube pi smoke` subcommand:

```bash
./scripts/sugarkube pi smoke --dry-run -- --json pi-a.local pi-b.local
# or, after adding scripts/ to PATH:
sugarkube pi smoke --dry-run -- --json pi-a.local pi-b.local
```

Drop `--dry-run` to run the verifier immediately. Everything after the standalone `--` flows to
`scripts/pi_smoke_test.py`, so existing documentation continues to apply. Regression coverage lives
in `tests/test_sugarkube_toolkit_cli.py::test_pi_smoke_invokes_helper`,
`tests/test_sugarkube_toolkit_cli.py::test_pi_smoke_drops_script_separator`, and
`tests/test_sugarkube_cli_entrypoint.py::test_sugarkube_script_invokes_cli`, which verifies the
legacy wrapper delegates to the unified CLI.

## Test coverage

Automated assurance for the CLI lives in
`tests/pi_smoke_test_unit_test.py::test_parse_args_accepts_host_flag`, which
guards the `--host` flag support documented above.
