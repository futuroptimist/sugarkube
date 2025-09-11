#!/usr/bin/env bash
set -euo pipefail

shopt -s globstar nullglob
for example in **/.env.example; do
  target="${example%.example}"
  [ -f "$target" ] || cp "$example" "$target"
done

# Ensure token.place and dspace have .env files even without examples
for env_path in token.place/.env dspace/frontend/.env; do
  dir="$(dirname "$env_path")"
  [ -d "$dir" ] || continue
  [ -f "$env_path" ] || touch "$env_path"
done

# extra-start
# Add additional environment setup steps below
# extra-end
