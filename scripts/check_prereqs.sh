#!/usr/bin/env bash
set -euo pipefail

err=0

# Check Docker daemon
if ! command -v docker >/dev/null 2>&1; then
  echo "docker command not found" >&2
  err=1
elif ! docker info >/dev/null 2>&1; then
  echo "Docker daemon is not running or not accessible" >&2
  err=1
fi

# Check arch-test
if ! command -v arch-test >/dev/null 2>&1; then
  echo "arch-test is required. Install with: sudo apt-get install arch-test" >&2
  err=1
fi

# Ensure universe repo enabled
if ! grep -R "^[^#].*universe" /etc/apt/sources.list /etc/apt/sources.list.d 2>/dev/null | head -n1 >/dev/null; then
  echo "APT 'universe' repository not enabled. Run: sudo add-apt-repository -y universe" >&2
  err=1
fi

# Check free disk space (>15GB)
avail_kb=$(df --output=avail -k . | tail -n1)
if [ "$avail_kb" -lt $((15 * 1024 * 1024)) ]; then
  echo "Insufficient disk space. Need at least 15GB free" >&2
  err=1
fi

if [ "$err" -ne 0 ]; then
  exit 1
fi
