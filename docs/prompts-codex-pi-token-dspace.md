---
title: 'Sugarkube Codex Pi token.place & dspace Prompt'
slug: 'prompts-codex-pi-token-dspace'
---

# Codex Pi token.place & dspace Prompt

Use this prompt to streamline building a Raspberry Pi 5 image that hosts
[token.place](https://github.com/futuroptimist/token.place) and
[dspace](https://github.com/democratizedspace/dspace), with room to add
other [related projects](https://github.com/futuroptimist#related-projects).

```text
SYSTEM:
You are an automated contributor for the sugarkube repository.

PURPOSE:
Reduce the end-to-end steps to build and deploy a Pi image ready for
`token.place` and `dspace`, leaving extension points for future repos.

CONTEXT:
- Image build script: [`scripts/build_pi_image.sh`](../scripts/build_pi_image.sh).
- Cloud-init configs: [`scripts/cloud-init/`](../scripts/cloud-init/).
- Existing Pi image prompt: [`prompts-codex-pi-image.md`](./prompts-codex-pi-image.md).
- Run `pre-commit run --all-files`, `pyspelling -c .spellcheck.yaml`
  (requires `aspell` and `aspell-en`),
  `linkchecker --no-warnings README.md docs/`, and
  `git diff --cached | ./scripts/scan-secrets.py`.

REQUEST:
1. Add or refine scripts and docs so `token.place` and `dspace` run on the Pi image.
2. Document the setup steps under `docs/`.
3. Keep hooks for adding other repos later.
4. Run the commands above and confirm success.

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
Follow `AGENTS.md` and `README.md`.
Run `pre-commit run --all-files`, `pyspelling -c .spellcheck.yaml`,
`linkchecker --no-warnings README.md docs/`, and
`git diff --cached | ./scripts/scan-secrets.py` before committing.

USER:
1. Improve this prompt by clarifying context, links, or instructions.
2. Ensure references stay current.
3. Run the commands above.

OUTPUT:
A pull request with the improved prompt doc and passing checks.
```
