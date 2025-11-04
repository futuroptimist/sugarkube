#!/usr/bin/env bash
set -euo pipefail
# Mirror CI locally in the same order. Adjust if workflows change.
make test-bats
make test-e2e
make test-smoke-qemu
