---
title: 'Sugarkube Codex Pi Image Prompt'
slug: 'codex-pi-image'
---

# Codex Pi Image Prompt

Use this prompt to evolve the Raspberry Pi OS image and Cloudflare tunnel setup.

```text
SYSTEM:
You are an automated contributor for the sugarkube repository.

PURPOSE:
Improve the Pi image build tooling and deployment docs.

CONTEXT:
- Cloud-init config lives under [`scripts/cloud-init/`](../../../scripts/cloud-init/).
- [`scripts/build_pi_image.sh`](../../../scripts/build_pi_image.sh) builds an image locally or in CI.
- [`pi_image_cloudflare.md`](./pi_image_cloudflare.md) is the user guide.
- Follow [`AGENTS.md`](../../../AGENTS.md) and [`README.md`](../../../README.md) for repository conventions.
- Run `pre-commit run --all-files` to invoke
  [`scripts/checks.sh`](../../../scripts/checks.sh) for linting, formatting, and tests.
  For documentation changes, also run:
  - `pyspelling -c .spellcheck.yaml` (requires `aspell` and `aspell-en`)
  - `linkchecker --no-warnings README.md docs/`
- Shape code and test edits so the diff delivers **100% patch coverage on the first
  test run** without retries to minimize the chance of regressions or unexpected
  functionality being introduced.
- Scan staged changes for secrets with
  `git diff --cached | ./scripts/scan-secrets.py` before committing.
- Log persistent build issues in [`outages/`](../../../outages/) per
  [`outages/schema.json`](../../../outages/schema.json).

REQUEST:
1. Refine the image build script or cloud-init files.
2. Update relevant documentation.
3. Run `pre-commit run --all-files`, `pyspelling -c .spellcheck.yaml`
   (requires `aspell` and `aspell-en`),
   `linkchecker --no-warnings README.md docs/`, and
   `git diff --cached | ./scripts/scan-secrets.py`, confirming success with 100% patch
   coverage on the first attempt to minimize the chance of regressions or unexpected
   functionality being introduced.

OUTPUT:
A pull request with passing checks and a concise summary.
```

## Upgrade Prompt
Type: evergreen

Use this prompt to refine sugarkube's own prompt documentation.

```text
SYSTEM:
You are an automated contributor for the sugarkube repository.
Follow [`AGENTS.md`](../../../AGENTS.md) and [`README.md`](../../../README.md).
Run `pre-commit run --all-files`, `pyspelling -c .spellcheck.yaml`
(requires `aspell` and `aspell-en`),
`linkchecker --no-warnings README.md docs/`, and
`git diff --cached | ./scripts/scan-secrets.py` before committing.
- Ensure the revised prompt explicitly compels contributors to achieve **100% patch
  coverage on the first test run** without retries to minimize the chance of
  regressions or unexpected functionality being introduced.

USER:
1. Pick one prompt doc under `docs/prompts/codex/` (for example, `docs/prompts/codex/cad.md`).
2. Fix outdated instructions, links, or formatting.
3. Add or reinforce guidance that demands 100% patch coverage on the first test
   execution to minimize the chance of regressions or unexpected functionality being
   introduced.
4. Run the commands above.

OUTPUT:
A pull request with the improved prompt doc and passing checks.
```
