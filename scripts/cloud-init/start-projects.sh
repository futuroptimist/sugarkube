#!/usr/bin/env bash
set -euo pipefail

svc="projects-compose.service"
log_dir="/var/log/sugarkube"
migration_log="${log_dir}/migrations.log"

mkdir -p "$log_dir"

log_migration_step() {
  local ts
  ts=$(date --iso-8601=seconds 2>/dev/null || date)
  printf '%s %s\n' "$ts" "$1" >>"$migration_log" 2>/dev/null || true
}

log_migration_step "start-projects.sh invoked"

if ! command -v docker >/dev/null 2>&1; then
  echo "docker not found; skipping ${svc}" >&2
  log_migration_step "skipped: docker not installed"
  exit 0
fi

# Show engine and compose versions for diagnostics
docker --version || true
if ! docker compose version >/dev/null 2>&1; then
  echo "docker compose plugin not found; skipping ${svc}" >&2
  log_migration_step "skipped: docker compose plugin missing"
  exit 0
fi
docker compose version

# Seed .env files before the service starts so defaults exist
if [ -x /opt/projects/init-env.sh ]; then
  if /opt/projects/init-env.sh; then
    log_migration_step "init-env.sh completed"
  else
    log_migration_step "init-env.sh failed (continuing)"
  fi
fi

if ! command -v systemctl >/dev/null 2>&1; then
  echo "systemctl not found; skipping ${svc}" >&2
  log_migration_step "skipped: systemctl unavailable"
  exit 0
fi

# extra-start
# Additional startup checks can be inserted here, for example database migrations
# or health probes for new repositories.
# extra-end

if systemctl list-unit-files | grep -q "^${svc}"; then
  systemctl enable --now "${svc}"
  log_migration_step "enabled ${svc}"
else
  echo "${svc} not found; skipping" >&2
  log_migration_step "skipped: ${svc} not installed"
fi

# extra-start
# Additional startup hooks can be inserted here, for example enabling services
# or running health probes for new repositories.
# extra-end
