#!/usr/bin/env bash
set -euo pipefail

cp -n .env.example .env 2>/dev/null || true
docker compose up -d
