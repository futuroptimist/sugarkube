#!/usr/bin/env bash
# Trusted, fixed-operation validation wrapper for the sugarkube @claude
# workflow. This script is always installed from the pinned workflow ref
# (github.workflow_sha), never from arbitrary pull request content, so it
# stays trustworthy even when the checked-out repository content is
# adversarial. Every operation is a verbatim command sugarkube already runs
# elsewhere (scripts/checks.sh, .github/workflows/tests.yml,
# verify-justfile.yml, spellcheck.yml, pi-image.yml) with no arguments and
# no shell interpolation of caller-provided data.
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: claude-validate.sh <operation>

Fixed operations (each takes zero arguments):
  prepare-deps    Install lint/test/docs tooling used by the other operations.
  lint            flake8 . --exclude=.venv,scripts/qrcodegen.py --max-line-length=100
  isort-check     isort --check-only . --skip .venv --skip scripts/qrcodegen.py
  format-check    black --check . --line-length=100 --exclude "(.venv/|scripts/qrcodegen\.py)"
  test-ci         pytest --cov=. --cov-report=xml --cov-report=term --maxfail=1 --disable-warnings -q
  shellcheck      shellcheck scripts/*.sh
  justfile-fmt    just --unstable --fmt --check
  spellcheck      pyspelling -c .spellcheck.yaml
  linkcheck       linkchecker --no-warnings --ignore-url '^https?://' README.md docs/
  network-probe   Assert no secret-bearing env vars are visible and outbound network is denied.
EOF
}

if [[ "$#" -ne 1 ]]; then
  usage >&2
  exit 64
fi

op="$1"

pip_install() {
  if command -v uv >/dev/null 2>&1; then
    uv pip install --system "$@"
  else
    python3 -m pip install "$@"
  fi
}

case "$op" in
  prepare-deps)
    pip_install flake8 'isort<6' black pytest pytest-cov coverage pyspelling linkchecker
    sudo apt-get update
    sudo apt-get install -y --no-install-recommends shellcheck aspell aspell-en
    if ! command -v just >/dev/null 2>&1; then
      ./scripts/install_just.sh
    fi
    ;;
  lint)
    flake8 . --exclude=.venv,scripts/qrcodegen.py --max-line-length=100
    ;;
  isort-check)
    isort --check-only . --skip .venv --skip scripts/qrcodegen.py
    ;;
  format-check)
    black --check . --line-length=100 --exclude "(.venv/|scripts/qrcodegen\.py)"
    ;;
  test-ci)
    pytest --cov=. --cov-report=xml --cov-report=term --maxfail=1 --disable-warnings -q
    ;;
  shellcheck)
    # shellcheck disable=SC2035
    shellcheck scripts/*.sh
    ;;
  justfile-fmt)
    just --unstable --fmt --check
    ;;
  spellcheck)
    pyspelling -c .spellcheck.yaml
    ;;
  linkcheck)
    linkchecker --no-warnings --ignore-url '^https?://' README.md docs/
    ;;
  network-probe)
    python3 - <<'PY'
import os
import socket
import sys

secret_markers = ("TOKEN", "SECRET", "OIDC", "ACTIONS_ID_TOKEN", "GITHUB_TOKEN", "CLAUDE_CODE_OAUTH_TOKEN")
leaked = [name for name in os.environ if any(marker in name.upper() for marker in secret_markers)]
if leaked:
    print("secret-bearing environment variables visible: " + ",".join(sorted(leaked)), file=sys.stderr)
    sys.exit(1)

sock = socket.socket()
sock.settimeout(2)
reachable = sock.connect_ex(("1.1.1.1", 443)) == 0
sock.close()
if reachable:
    print("outbound network unexpectedly reachable", file=sys.stderr)
    sys.exit(1)
PY
    ;;
  *)
    echo "Unknown operation: $op" >&2
    usage >&2
    exit 64
    ;;
esac
