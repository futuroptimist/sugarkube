---
title: 'Sugarkube Codex Pi token.place & dspace Prompt'
slug: 'prompts-codex-pi-token-dspace'
---

# Codex Pi token.place & dspace Prompt

Use this prompt to streamline building a Raspberry Pi 5 image that hosts
[token.place](https://github.com/futuroptimist/token.place) and
[dspace](https://github.com/democratizedspace/dspace) via
[Docker Compose](https://docs.docker.com/compose/), while leaving room for other
[related projects](https://github.com/futuroptimist#related-projects).
It builds on the base Pi image workflow and layers these services via
`cloud-init` and a shared Compose file.

```text
SYSTEM:
You are an automated contributor for the sugarkube repository.

PURPOSE:
Reduce the end-to-end steps to build and deploy a Pi image ready for
`token.place` and `dspace`, leaving extension points for future repos.

CONTEXT:
- Follow [`AGENTS.md`](../AGENTS.md) and [`README.md`](../README.md) for workflow
  guidelines.
- Raspberry Pi OS build script: [`scripts/build_pi_image.sh`](../scripts/build_pi_image.sh)
  (targets Raspberry Pi OS Bookworm 64‑bit).
- Docker Engine and Compose plugin: install via Docker's Debian guide for ARM devices
  ([Engine](https://docs.docker.com/engine/install/debian/) and
  [Compose plugin](https://docs.docker.com/compose/install/linux/#install-using-the-repository)).
  Confirm with `docker --version` and `docker compose version`.
- First-boot cloud-init configs and Compose manifests:
  [`scripts/cloud-init/`](../scripts/cloud-init/), which seeds
  [`docker-compose.yml`](../scripts/cloud-init/docker-compose.yml) for `token.place`
  and `dspace`.
- Upstream apps:
  - [token.place](https://github.com/futuroptimist/token.place) — see its
    [README](https://github.com/futuroptimist/token.place#readme) for service details.
  - [dspace](https://github.com/democratizedspace/dspace) — see its
    [README](https://github.com/democratizedspace/dspace#readme).
- Existing Pi image prompt: [`prompts-codex-pi-image.md`](./prompts-codex-pi-image.md).
- Repository checks:
  - `pre-commit run --all-files` (executes [`scripts/checks.sh`](../scripts/checks.sh))
  - `pyspelling -c .spellcheck.yaml` (requires `aspell` and `aspell-en`)
  - `linkchecker --no-warnings README.md docs/`
  - `git diff --cached | ./scripts/scan-secrets.py`
- Shape changes and tests so the diff achieves **100% patch coverage on the first test run** with no
  retries.
- Review [CI workflows](../.github/workflows/) to anticipate automated checks.

REQUEST:
1. Add or refine scripts and docs so `token.place` and `dspace` run as services on the Pi
   image via `docker compose` and a shared `docker-compose.yml`.
2. Document the setup steps under `docs/`, listing required environment variables and how to
   extend the Compose file for additional repositories.
3. Keep hooks for adding other repositories later.
4. Run the commands above and confirm success with 100% patch coverage on the first attempt.

OUTPUT:
A pull request with updated scripts and docs enabling `token.place` and
`dspace` on a Pi 5 image with passing checks.
```

## Upgrade Prompt
Type: evergreen

Use this prompt to refine sugarkube's own prompt documentation.

```text
SYSTEM:
You are an automated contributor for the sugarkube repository.
Follow [`AGENTS.md`](../AGENTS.md) and [`README.md`](../README.md).
Run `pre-commit run --all-files`, `pyspelling -c .spellcheck.yaml` (requires
`aspell` and `aspell-en`), `linkchecker --no-warnings README.md docs/`, and
`git diff --cached | ./scripts/scan-secrets.py` before committing.
- Ensure the updated prompt explicitly requires **100% patch coverage on the first test run** without
  retries.

USER:
1. Improve this prompt by clarifying context, links, or instructions.
2. Ensure references stay current.
3. Add or reinforce guidance mandating 100% patch coverage on the first test execution.
4. Run the commands above.

OUTPUT:
A pull request with the improved prompt doc and passing checks.
```
