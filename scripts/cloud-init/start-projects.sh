#!/usr/bin/env bash
set -euo pipefail

svc="projects-compose.service"

if ! command -v systemctl >/dev/null 2>&1; then
  echo "systemctl not found; skipping ${svc}" >&2
  exit 0
fi

if systemctl list-unit-files | grep -q "^${svc}"; then
  systemctl enable --now "${svc}"
else
  echo "${svc} not found; skipping" >&2
fi
