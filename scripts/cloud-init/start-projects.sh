#!/usr/bin/env bash
set -euo pipefail

svc="projects-compose.service"

if ! command -v docker >/dev/null 2>&1; then
  echo "docker not found; skipping ${svc}" >&2
  exit 0
fi

# Show engine and compose versions for diagnostics
docker --version || true
if ! docker compose version >/dev/null 2>&1; then
  echo "docker compose plugin not found; skipping ${svc}" >&2
  exit 0
fi
docker compose version || true

if ! command -v systemctl >/dev/null 2>&1; then
  echo "systemctl not found; skipping ${svc}" >&2
  exit 0
fi

if systemctl list-unit-files | grep -q "^${svc}"; then
  systemctl enable --now "${svc}"
else
  echo "${svc} not found; skipping" >&2
fi
