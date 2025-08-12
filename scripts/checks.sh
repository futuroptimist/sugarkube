#!/usr/bin/env bash
set -euo pipefail

# python checks
flake8 . --exclude=.venv
isort --check-only . --skip .venv
black --check . --exclude ".venv/"

# js checks
if [ -f package.json ]; then
  npm ci
  npx playwright install --with-deps
  npm run lint
  npm run format:check
  npm test -- --coverage
fi

# run tests
pytest --cov=. --cov-report=xml --cov-report=term -q

# docs checks
if command -v pyspelling >/dev/null 2>&1 && [ -f .spellcheck.yaml ]; then
  pyspelling -c .spellcheck.yaml
fi
if command -v linkchecker >/dev/null 2>&1; then
  linkchecker --no-warnings README.md docs/
fi
