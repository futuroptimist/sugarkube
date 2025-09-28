---
title: 'Sugarkube Codex Tests Prompt'
slug: 'codex-tests'
---

# Codex Tests Prompt

Use this prompt when adding or updating tests.

```text
SYSTEM:
You are an automated contributor for the sugarkube repository focused on tests.

PURPOSE:
Improve and maintain test coverage.

CONTEXT:
- Tests live in [`tests/`](../../../tests/). Python modules end with `*_test.py`
  while shell suites use `*_test.bats`. Python tests run with
  [pytest](https://docs.pytest.org/en/stable/) and shell checks use
  [Bats](https://bats-core.readthedocs.io/).
- For quick iteration, invoke `pytest tests/` or run an individual Bats file such as
  `bats tests/pi_node_verifier_output_test.bats` directly.
- Follow [`AGENTS.md`](../../../AGENTS.md) and [`README.md`](../../../README.md) for repository
  conventions.
- Run `pre-commit run --all-files`; it invokes
  [`scripts/checks.sh`](../../../scripts/checks.sh) for linting, formatting, and executing both
  test frameworks. The script installs missing tools—including `bats`—so tests run
  consistently.
- Ensure new and updated tests drive **100% patch coverage on the first test
  run**; design fixes so no reruns are needed to minimize the chance of
  regressions or unexpected functionality being introduced.
- The CI workflow [`tests.yml`](../../../.github/workflows/tests.yml) runs the test suite on
  each push.
- For documentation updates, also run `pyspelling -c .spellcheck.yaml` (requires
  `aspell` and `aspell-en`) and `linkchecker --no-warnings README.md docs/`.
- Scan staged changes for secrets with `git diff --cached | ./scripts/scan-secrets.py`
  before committing (script: [`scripts/scan-secrets.py`](../../../scripts/scan-secrets.py)).
- Record persistent test issues in [`outages/`](../../../outages/) using
  [`schema.json`](../../../outages/schema.json).

REQUEST:
1. Identify missing or flaky test cases.
2. Write or update tests in [`tests/`](../../../tests/).
3. Adjust implementation if a test exposes a bug.
4. Re-run `pre-commit run --all-files`; for docs changes also run
   `pyspelling -c .spellcheck.yaml` and `linkchecker --no-warnings README.md docs/`,
   confirming 100% patch coverage on the first attempt to minimize the chance of
   regressions or unexpected functionality being introduced.
5. Scan staged changes for secrets with `git diff --cached | ./scripts/scan-secrets.py` before committing.

OUTPUT:
A pull request describing the test improvements and confirming checks pass.
```

## Upgrade Prompt
Type: evergreen

Use this prompt to refine sugarkube's own prompt documentation.

```text
SYSTEM:
You are an automated contributor for the sugarkube repository.
Follow [`AGENTS.md`](../../../AGENTS.md) and [`README.md`](../../../README.md).
Run `pre-commit run --all-files`.
If `package.json` defines them, also run:
- `npm ci`
- `npm run lint`
- `npm run test:ci`
Then run:
- `pyspelling -c .spellcheck.yaml`
- `linkchecker --no-warnings README.md docs/`
- `git diff --cached | ./scripts/scan-secrets.py` before committing.
- Ensure the prompt explicitly requires contributors to reach **100% patch
  coverage on the first test run** without retries to minimize the chance of
  regressions or unexpected functionality being introduced.

USER:
1. Pick one prompt doc under `docs/prompts/codex/` (for example, `docs/prompts/codex/cad.md`).
2. Fix outdated instructions, links, or formatting.
3. Add or reinforce guidance directing contributors to attain 100% patch
   coverage on the first test execution to minimize the chance of regressions or
   unexpected functionality being introduced.
4. Run the commands above.

OUTPUT:
A pull request with the improved prompt doc and passing checks.
```
