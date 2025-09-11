#!/usr/bin/env bash
set -euo pipefail

compose_dir="$(cd "$(dirname "$0")" && pwd)"
compose_file="${compose_dir}/docker-compose.yml"

# Copy any *.env.example to .env and secure permissions
shopt -s globstar nullglob
for example in "${compose_dir}"/**/.env.example; do
  target="${example%.example}"
  if [ ! -f "$target" ]; then
    cp "$example" "$target"
    chmod 600 "$target"
  fi
done

# Touch env files referenced in docker-compose.yml so services start with defaults
if [ -f "$compose_file" ]; then
  in_env=0
  while IFS= read -r line; do
    if [[ $line =~ env_file: ]]; then
      in_env=1
      continue
    fi
    if [[ $in_env -eq 1 ]]; then
      if [[ $line =~ ^[[:space:]]*-[[:space:]]*(.*) ]]; then
        env_file="${BASH_REMATCH[1]}"
        env_path="$env_file"
        [[ $env_path != /* ]] && env_path="${compose_dir}/${env_path}"
        dir="$(dirname "$env_path")"
        [ -d "$dir" ] || mkdir -p "$dir"
        [ -f "$env_path" ] || touch "$env_path"
        chmod 600 "$env_path"
      else
        in_env=0
      fi
    fi
  done <"$compose_file"
fi

# extra-start
# Add additional environment setup steps below
# extra-end
