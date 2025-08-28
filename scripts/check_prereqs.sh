#!/usr/bin/env bash
set -euo pipefail

err() {
  echo "$1" >&2
}

# Verify Docker is available and running
if ! command -v docker >/dev/null 2>&1 || ! docker info >/dev/null 2>&1; then
  err "Docker daemon not running. Start Docker and retry."
  exit 1
fi

# Ensure arch-test is installed
if ! command -v arch-test >/dev/null 2>&1; then
  err "arch-test missing. Run: sudo apt-get install arch-test"
  exit 1
fi

# Confirm 'universe' repo is enabled
if ! grep -Rhs "^[^#].*universe" /etc/apt/sources.list /etc/apt/sources.list.d 2>/dev/null | grep -q universe; then
  err "APT 'universe' repo missing. Run: sudo add-apt-repository -y universe"
  exit 1
fi

# Check free disk space (>15GB)
avail_k=$(df -Pk . | awk 'NR==2 {print $4}')
if [ "$avail_k" -lt $((15*1024*1024)) ]; then
  err "At least 15GB free disk space required."
  exit 1
fi

echo "all prerequisites met"
