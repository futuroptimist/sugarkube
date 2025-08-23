#!/usr/bin/env bash
set -euo pipefail

# Ensure required Python tooling is available
if ! command -v flake8 >/dev/null 2>&1; then
  if command -v uv >/dev/null 2>&1; then
    uv pip install --system \
      flake8 isort black pytest pytest-cov coverage pyspelling linkchecker \
      >/dev/null 2>&1
  else
    pip install flake8 isort black pytest pytest-cov coverage pyspelling linkchecker \
      >/dev/null 2>&1
  fi
fi

# python checks
flake8 . --exclude=.venv
isort --check-only . --skip .venv
black --check . --exclude ".venv/"

# js checks
if [ -f package.json ]; then
  if command -v npm >/dev/null 2>&1; then
    if [ -f package-lock.json ]; then
      npm ci
      npx playwright install --with-deps
      npm run lint
      npm run format:check
      npm test -- --coverage
    else
      echo "package-lock.json not found, skipping JS checks" >&2
    fi
  else
    echo "npm not found, skipping JS checks" >&2
  fi
fi

# run tests
pytest --cov=. --cov-report=xml --cov-report=term -q

# docs checks
if ! command -v aspell >/dev/null 2>&1; then
  if command -v apt-get >/dev/null 2>&1; then
    sudo apt-get update && sudo apt-get install -y aspell aspell-en
  elif command -v brew >/dev/null 2>&1; then
    brew install aspell
  else
    echo "aspell not found" >&2
    exit 1
  fi
fi
# Only run the spell checker when both `pyspelling` and its `aspell` backend
# are available. Some environments (like minimal CI containers) do not include
# the `aspell` binary by default which would cause `pyspelling` to error.  In
# those cases we silently skip the spelling check instead of failing the whole
# pre-commit run.
if command -v pyspelling >/dev/null 2>&1 && command -v aspell >/dev/null 2>&1 \
  && [ -f .spellcheck.yaml ]; then
  pyspelling -c .spellcheck.yaml
fi
if command -v linkchecker >/dev/null 2>&1; then
  linkchecker --no-warnings README.md docs/
fi
