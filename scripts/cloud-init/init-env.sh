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

# Seed default ports when not already set so the containers expose predictable
# endpoints on first boot. token.place defaults to 5000 and dspace to 3000.
if [ -f token.place/.env ] && ! grep -q '^PORT=' token.place/.env 2>/dev/null; then
  echo 'PORT=5000' >> token.place/.env
fi
if [ -f dspace/frontend/.env ] && ! grep -q '^PORT=' dspace/frontend/.env 2>/dev/null; then
  echo 'PORT=3000' >> dspace/frontend/.env
fi

# extra-start
# Add additional environment setup steps below. Example:
# ensure_env other_repo/.env  # create .env if missing
# echo "FOO=bar" >> other_repo/.env
# extra-end
