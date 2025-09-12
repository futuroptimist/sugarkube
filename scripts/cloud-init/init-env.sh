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
# Seed a basic PORT so each app listens on the expected interface
for env_path in token.place/.env dspace/frontend/.env; do
  dir="$(dirname "$env_path")"
  [ -d "$dir" ] || continue
  if [ ! -f "$env_path" ]; then
    case "$env_path" in
      token.place/.env)
        printf "PORT=5000\n" > "$env_path"
        ;;
      dspace/frontend/.env)
        printf "PORT=3000\n" > "$env_path"
        ;;
      *)
        :
        ;;
    esac
    chmod 600 "$env_path"
  fi
done

# extra-start
# Add additional environment setup steps below
# extra-end
