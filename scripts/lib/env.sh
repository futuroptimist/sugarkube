#!/usr/bin/env bash
# Shared environment-name normalization for just recipes and shell helpers.

sugarkube_normalize_env() {
  local env_input="${1:-dev}"
  local env_name

  env_name="$(printf '%s' "${env_input}" | xargs)"
  while [[ "${env_name}" == env=* ]]; do
    env_name="${env_name#env=}"
  done

  if [ "${env_name}" = "int" ]; then
    printf 'WARNING: env name "int" is deprecated; using env=staging.\n' >&2
    env_name="staging"
  fi

  printf '%s\n' "${env_name}"
}
