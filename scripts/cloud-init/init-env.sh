#!/usr/bin/env bash
set -euo pipefail

# tokenplace-start
if [ -d token.place ] && [ -f token.place/.env.example ] && [ ! -f token.place/.env ]; then
  cp token.place/.env.example token.place/.env
fi
# tokenplace-end

# dspace-start
if [ -d dspace/frontend ] && [ -f dspace/frontend/.env.example ] && [ ! -f dspace/frontend/.env ]; then
  cp dspace/frontend/.env.example dspace/frontend/.env
fi
# dspace-end

# extra-start
# Add additional environment setup steps below
# extra-end
