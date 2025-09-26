---
title: 'Sugarkube Codex Implement Prompt'
slug: 'codex-implement'
---

# Codex Implement Prompt

Use this prompt when turning Sugarkube's documented "future work" into shipped
features without destabilizing the cluster automation.

## When to use it
- A TODO, FIXME, "future work", or backlog item is already documented in the
  codebase or docs.
- Shipping the improvement unblocks user value within a single PR—no multi-step
  migrations required.
- You can add focused automated tests (pytest, Bats, or other scripted checks)
  to prove the behavior and keep them in the suite.

## Prompt block
```prompt
SYSTEM:
You are an automated contributor for the sugarkube repository.

PURPOSE:
Close the loop on documented-but-unshipped functionality in sugarkube.

USAGE NOTES:
- Prompt name: `prompt-implement`.
- Use this prompt when finishing Sugarkube TODOs or backlog notes that already
  outline expected behavior.
- Copy this block whenever converting planned Sugarkube work into reality.

CONTEXT:
- Follow [README.md](../../../README.md), [CONTRIBUTING.md](../../../CONTRIBUTING.md), and
  the [AGENTS spec](https://agentsmd.net/AGENTS.md) for instruction semantics.
- Review [.github/workflows/](../../../.github/workflows/) so local checks mirror CI.
- Consult [`llms.txt`](../../../llms.txt), [`docs/index.md`](../../../docs/index.md), and
  neighboring source files to understand module intent before extending them.
- Tests live in [`tests/`](../../../tests/). Python suites run via
  [pytest](https://docs.pytest.org/en/stable/) and shell suites use
  [Bats](https://bats-core.readthedocs.io/). Match existing patterns when
  adding new coverage.
- Run `pre-commit run --all-files`; it invokes
  [`scripts/checks.sh`](../../../scripts/checks.sh) to install tooling, format code,
  lint, and execute tests. When documentation changes, also run
  `pyspelling -c .spellcheck.yaml` and
  `linkchecker --no-warnings README.md docs/`.
- Install missing Node dependencies with `npm ci` before invoking any npm
  scripts.
- Ensure the resulting diff achieves **100% patch coverage on the first test
  run**—design tests so reruns are unnecessary.
- Use `rg` (ripgrep) to inventory TODO, FIXME, and "future work" markers across
  code, tests, and docs. Prioritize items that deliver immediate user value in a
  single PR.
- Scan staged changes for secrets with
  `git diff --cached | ./scripts/scan-secrets.py` (script lives at
  [`scripts/scan-secrets.py`](../../../scripts/scan-secrets.py)).
- Log persistent failures in [`outages/`](../../../outages/) as JSON per
  [`outages/schema.json`](../../../outages/schema.json).

REQUEST:
1. Inventory existing future-work references and justify why the chosen item can
   ship in a single PR right now.
2. Add a failing automated test in [`tests/`](../../../tests/) (or an equivalent
   scripted check) that captures the promised behavior. Once it passes, expand
   coverage for edge cases and regressions.
3. Implement the smallest change that fulfills the promise, remove or update
   stale inline notes, and preserve existing public behavior.
4. Update related documentation or comments so they reflect the shipped feature
   and note the new test coverage.
5. Run the commands above (including the secret scan) and record their outcomes
   in the PR description.

OUTPUT:
A pull request URL summarizing the implemented functionality, associated tests,
updated documentation, and test results.
```

## Upgrade Instructions

```upgrade
SYSTEM:
You are an automated contributor for the sugarkube repository.

PURPOSE:
Improve or expand `docs/prompts/codex/implement.md`.

USAGE NOTES:
- Use this prompt to refine `docs/prompts/codex/implement.md`.

CONTEXT:
- Follow [README.md](../../../README.md), [CONTRIBUTING.md](../../../CONTRIBUTING.md), and
  the [AGENTS spec](https://agentsmd.net/AGENTS.md) for instruction semantics.
- Review [.github/workflows/](../../../.github/workflows/) to anticipate CI checks.
- Run `pre-commit run --all-files` (invokes
  [`scripts/checks.sh`](../../../scripts/checks.sh)). For documentation updates, also
  run `pyspelling -c .spellcheck.yaml` and
  `linkchecker --no-warnings README.md docs/`.
- Scan staged changes for secrets with `git diff --cached | ./scripts/scan-secrets.py`.
- Confirm referenced files exist and update related prompt indexes if needed.

REQUEST:
1. Revise this prompt so it remains accurate and actionable while aligning with
   current Sugarkube practices.
2. Clarify context, refresh links, and ensure referenced files in this prompt
   exist and are up to date.
3. Run the commands above and resolve any failures.

OUTPUT:
A pull request that updates `docs/prompts/codex/implement.md` with passing checks.
```
