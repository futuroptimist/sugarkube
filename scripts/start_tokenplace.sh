#!/usr/bin/env bash
set -euo pipefail

docker buildx build --platform linux/arm64 -f docker/Dockerfile.server \
  -t tokenplace . --load
docker run -d --name tokenplace -p 5000:5000 tokenplace
