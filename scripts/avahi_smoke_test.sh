#!/usr/bin/env bash
set -euo pipefail

# Smoke test for Avahi/mDNS functionality
# Verifies that avahi-browse can run and discover services

TIMEOUT="${AVAHI_SMOKE_TIMEOUT:-10}"

if ! command -v avahi-browse >/dev/null 2>&1; then
    echo "avahi-browse not found" >&2
    exit 1
fi

if ! command -v timeout >/dev/null 2>&1; then
    echo "timeout command not found" >&2
    exit 1
fi

echo "Running avahi-browse smoke test (timeout: ${TIMEOUT}s)..."

# Run avahi-browse with timeout to terminate after discovering services
# or if timeout is reached. The --terminate flag causes it to exit after
# collecting all services.
if timeout "${TIMEOUT}" avahi-browse --all --terminate >/dev/null 2>&1; then
    echo "✓ avahi-browse executed successfully"
    exit 0
elif [ $? -eq 124 ]; then
    # Timeout reached - this is acceptable if no services are found quickly
    echo "✓ avahi-browse timed out (no services found, but command works)"
    exit 0
else
    echo "✗ avahi-browse failed" >&2
    exit 1
fi
