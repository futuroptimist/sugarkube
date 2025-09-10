#!/usr/bin/env bash
set -euo pipefail

shopt -s globstar nullglob
for example in **/.env.example; do
  target="${example%.example}"
  [ -f "$target" ] || cp "$example" "$target"
done

# extra-start
# Add additional environment setup steps below
# extra-end
