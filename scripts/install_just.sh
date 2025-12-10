#!/usr/bin/env bash
# Install the `just` command for development and CI environments.

set -euo pipefail

SCRIPT_NAME=$(basename "$0")
PREFIX=${JUST_INSTALL_PREFIX:-/usr/local/bin}
REQUESTED_VERSION=${JUST_VERSION:-latest}

print_usage() {
  cat <<'USAGE'
Usage: install_just.sh [--help]

Installs the `just` command to a writable prefix (default: /usr/local/bin).
Set JUST_INSTALL_PREFIX to override the destination and JUST_VERSION to pin
an explicit release tag (defaults to the latest upstream release).
USAGE
}

if [ "${1:-}" = "--help" ]; then
  print_usage
  exit 0
fi

if command -v just >/dev/null 2>&1; then
  existing=$(command -v just || true)
  if [ -x "${existing}" ]; then
    echo "just already available at ${existing}" >&2
    exit 0
  fi
fi

case "$(uname -s)" in
  Linux) platform="unknown-linux-musl" ;;
  *)
    echo "${SCRIPT_NAME}: unsupported platform $(uname -s); only Linux is supported" >&2
    exit 1
    ;;
esac

case "$(uname -m)" in
  x86_64|amd64) arch="x86_64" ;;
  aarch64|arm64) arch="aarch64" ;;
  *)
    echo "${SCRIPT_NAME}: unsupported architecture $(uname -m); need x86_64 or aarch64" >&2
    exit 1
    ;;
esac

if [ "${REQUESTED_VERSION}" = "latest" ]; then
  tag=$(python - <<'PY'
import json
import sys
import urllib.request

try:
    with urllib.request.urlopen(
        "https://api.github.com/repos/casey/just/releases/latest"
    ) as resp:
        payload = json.load(resp)
    print(payload.get("tag_name", ""))
except Exception as exc:  # pragma: no cover - exercised via shell tests
    print(exc, file=sys.stderr)
    sys.exit(1)
PY
)
  if [ -z "${tag}" ]; then
    echo "${SCRIPT_NAME}: failed to determine latest just version" >&2
    exit 1
  fi
else
  tag="${REQUESTED_VERSION}"
fi

archive="just-${tag}-${arch}-${platform}.tar.gz"
base_url="https://github.com/casey/just/releases/download/${tag}"
url="${base_url}/${archive}"

tmpdir=$(mktemp -d)
trap 'rm -rf "${tmpdir}"' EXIT

echo "Downloading just from ${url}" >&2
ARCHIVE_PATH="${tmpdir}/${archive}"
JUST_URL="${url}" JUST_ARCHIVE="${ARCHIVE_PATH}" SCRIPT_NAME="${SCRIPT_NAME}" \
python - <<'PY'
import os
import pathlib
import sys
import urllib.request

url = os.environ["JUST_URL"]
dest = pathlib.Path(os.environ["JUST_ARCHIVE"])

try:
    with urllib.request.urlopen(url) as response, dest.open("wb") as handle:
        handle.write(response.read())
except Exception as exc:  # pragma: no cover - exercised in shell test
    print(f"{os.environ['SCRIPT_NAME']}: failed to download {url}: {exc}", file=sys.stderr)
    sys.exit(1)
PY

tar -xzf "${tmpdir}/${archive}" -C "${tmpdir}" || { echo "${SCRIPT_NAME}: failed to extract ${archive}" >&2; exit 1; }

install -d "${PREFIX}"
install -m 0755 "${tmpdir}/just" "${PREFIX}/just"

just_path="${PREFIX%/}/just"
if ! "${just_path}" --version >/dev/null 2>&1; then
  echo "${SCRIPT_NAME}: installed just but validation failed" >&2
  exit 1
fi

echo "Installed just to ${just_path}" >&2
