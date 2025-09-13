#!/usr/bin/env bash
set -euo pipefail

shopt -s globstar nullglob
for example in **/.env.example; do
  target="${example%.example}"
  if [ ! -f "$target" ]; then
    cp "$example" "$target"
    chmod 600 "$target"
    echo "Created $target from template"
  fi
done

ensure_env() {
  local env_path="$1"
  local dir
  dir="$(dirname "$env_path")"
  [ -d "$dir" ] || return 0
  if [ ! -f "$env_path" ]; then
    touch "$env_path"
    echo "Created $env_path"
  fi
  chmod 600 "$env_path"
}

# Ensure token.place and dspace have .env files even without examples
ensure_env token.place/.env
ensure_env dspace/frontend/.env

# extra-start
# Add additional environment setup steps below. Example:
# ensure_env other_repo/.env  # create .env if missing
# echo "FOO=bar" >> other_repo/.env
# extra-end
