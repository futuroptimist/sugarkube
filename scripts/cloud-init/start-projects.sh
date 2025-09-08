#!/usr/bin/env bash
set -euo pipefail

svc="projects-compose.service"
if systemctl list-unit-files | grep -q "^${svc}"; then
  systemctl enable --now "${svc}"
else
  echo "${svc} not found; skipping" >&2
fi
