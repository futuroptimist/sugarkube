#!/usr/bin/env bash
set -euo pipefail

shopt -s globstar nullglob
for example in **/.env.example; do
  target="${example%.example}"
  if [ ! -f "$target" ]; then
    cp "$example" "$target"
    chmod 600 "$target"
  fi
done

# Ensure token.place and dspace have .env files even without examples
for env_path in token.place/.env dspace/frontend/.env; do
  dir=${env_path%/*}
  if [ -d "$dir" ] && [ ! -f "$env_path" ]; then
    touch "$env_path"
  fi
done

# extra-start
# Add additional environment setup steps below
# extra-end
