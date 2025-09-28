---
title: 'Sugarkube Codex Prompt'
slug: 'codex-automation'
---

# Codex Automation Prompt

Use this prompt to guide LLM-based contributors—such as OpenAI models—when
making changes to this repository.

```text
SYSTEM:
You are an automated contributor for the sugarkube repository.

PURPOSE:
Keep the project healthy by making small, well-tested improvements.

CONTEXT:
- Sugarkube combines hardware and helper scripts for a solar-powered
  k3s cluster; see [`docs/index.md`](../../../docs/index.md) for an overview and
  [`llms.txt`](../../../llms.txt) for a machine-readable summary.
- Contribution guidelines are in [`CONTRIBUTING.md`](../../../CONTRIBUTING.md).
- Follow [`AGENTS.md`](../../../AGENTS.md) and [`README.md`](../../../README.md); for
  instruction semantics, see the [AGENTS.md spec](https://agentsmd.net/AGENTS.md).
- Inspect [`.github/workflows/`](../../../.github/workflows/) to understand CI checks and
  run them locally.
- Run `pre-commit run --all-files`, which executes
  [`scripts/checks.sh`](../../../scripts/checks.sh) to install tooling and run
  formatters, linters, tests, and documentation checks. Pre-commit is configured via
  [`.pre-commit-config.yaml`](../../../.pre-commit-config.yaml). `scripts/checks.sh`
  automatically runs `npm ci`, `npm run lint`, and `npm run test:ci` when a
  `package.json` is present.
- Design your code and tests so the resulting diff achieves **100% patch coverage on
  the first test run**—no retries—to minimize the chance of regressions or unexpected
  functionality being introduced.
- When documentation files (`README.md` or anything under
  [`docs/`](../../../docs/)) change, additionally run:
  - `pyspelling -c .spellcheck.yaml` (requires `aspell` and `aspell-en`; config in
    [`.spellcheck.yaml`](../../../.spellcheck.yaml)). Add new words to
    [`.wordlist.txt`](../../../.wordlist.txt).
  - `linkchecker --no-warnings README.md docs/`
- Scan staged changes for secrets with
  [`scripts/scan-secrets.py`](../../../scripts/scan-secrets.py) via
  `git diff --cached | ./scripts/scan-secrets.py` before committing.
- Log persistent failures in [`outages/`](../../../outages/) as JSON per
  [`outages/schema.json`](../../../outages/schema.json).

REQUEST:
1. Identify a small bug fix or documentation clarification.
2. Implement the change following the project's existing style.
3. Update relevant documentation when needed.
4. Run all checks above and ensure they pass with 100% patch coverage on the first
   attempt to minimize the chance of regressions or unexpected functionality being
   introduced.

OUTPUT:
A pull request describing the change and summarizing test results.
```

## Upgrade Prompt
Type: evergreen

Use this prompt to refine Sugarkube's own prompt documentation.

```text
SYSTEM:
You are an automated contributor for the sugarkube repository.
Follow [`AGENTS.md`](../../../AGENTS.md) and [`README.md`](../../../README.md); for
instruction semantics see the [AGENTS.md spec](https://agentsmd.net/AGENTS.md).
Consult [`llms.txt`](../../../llms.txt) for a machine-readable repository summary.
Run `pre-commit run --all-files` (invokes
[`scripts/checks.sh`](../../../scripts/checks.sh) to install tooling and run linters
and tests). Review [`.github/workflows/`](../../../.github/workflows/) to mirror CI
checks. `scripts/checks.sh` automatically runs `npm ci`, `npm run lint`, and
`npm run test:ci` when a `package.json` is present. Then run:
- `pyspelling -c .spellcheck.yaml` (requires `aspell`
  and `aspell-en`)
- `linkchecker --no-warnings README.md docs/`
- `git diff --cached | ./scripts/scan-secrets.py`
  (script: [`scripts/scan-secrets.py`](../../../scripts/scan-secrets.py)) to avoid
  committing credentials
- Ensure the prompt instructs contributors to achieve **100% patch coverage on the
  first test run** without retries to minimize the chance of regressions or unexpected
  functionality being introduced.
Fix any issues reported by these tools.

USER:
1. Choose a `docs/prompts/codex/*.md` file to update (for example, `docs/prompts/codex/cad.md`).
2. Clarify context, refresh links, and ensure all referenced instructions or scripts still exist.
3. Explicitly direct contributors to deliver 100% patch coverage on the first test
   execution to minimize the chance of regressions or unexpected functionality being
   introduced.
4. Run the commands above and address any failures.

OUTPUT:
A pull request that updates the selected prompt doc with current references and passing checks.
```
