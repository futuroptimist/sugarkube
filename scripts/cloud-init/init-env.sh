#!/usr/bin/env bash
set -euo pipefail

shopt -s globstar nullglob

# Copy any example env files to .env with restricted permissions
for example in **/.env.example; do
  target="${example%.example}"
  if [ ! -f "$target" ]; then
    cp "$example" "$target"
    chmod 600 "$target"
  fi
done

# Touch env files referenced in docker-compose.yml when missing. This keeps
# token.place, dspace and any future services aligned with the compose stack.
if [ -f docker-compose.yml ]; then
  grep -oE '[- ]+[./A-Za-z0-9_/-]+\.env' docker-compose.yml \
    | sed -E 's/^[- ]+//; s/^\.\///' \
    | sort -u \
    | while read -r env_path; do
        case "$env_path" in
          /*) target="$env_path" ;;
          *)  target="$(pwd)/$env_path" ;;
        esac
        dir="$(dirname "$target")"
        [ -d "$dir" ] || continue
        if [ ! -f "$target" ]; then
          touch "$target"
          chmod 600 "$target"
        fi
      done
fi

# extra-start
# Add additional environment setup steps below
# extra-end
