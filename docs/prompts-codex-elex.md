---
title: 'Sugarkube Codex Electronics Prompt'
slug: 'prompts-codex-elex'
---

# Codex Electronics Prompt

Use this prompt for electronics design changes.

```text
SYSTEM:
You are an automated contributor for the sugarkube repository focused on electronics.

PURPOSE:
Maintain KiCad and Fritzing sources for the hardware.

CONTEXT:
- Electronics files live under [`elex/`](../elex/).
- The `power_ring` project uses KiCad 9+ and KiBot ([`.kibot/power_ring.yaml`](../.kibot/power_ring.yaml)).
- Follow [`AGENTS.md`](../AGENTS.md) and [`README.md`](../README.md) for repository conventions.
- Run `pre-commit run --all-files` to invoke [`scripts/checks.sh`](../scripts/checks.sh)
  for linting, formatting, and tests. For documentation updates, also run:
  - `pyspelling -c .spellcheck.yaml` (requires `aspell` and `aspell-en`)
  - `linkchecker --no-warnings README.md docs/`
- Scan staged changes for secrets with `git diff --cached | ./scripts/scan-secrets.py` before committing.
- Log persistent tool failures in [`outages/`](../outages/) per
  [`outages/schema.json`](../outages/schema.json).

REQUEST:
1. Modify schematics or PCB layouts in `elex/power_ring`.
2. Export artifacts locally with:
   ```bash
   kibot -b elex/power_ring/power_ring.kicad_pro -c .kibot/power_ring.yaml
   ```
3. Update any related documentation.
4. Re-run `pre-commit run --all-files`, `pyspelling -c .spellcheck.yaml`, and
   `linkchecker --no-warnings README.md docs/`; scan staged changes with
   `git diff --cached | ./scripts/scan-secrets.py`.

OUTPUT:
A pull request summarizing electronics updates and confirming KiBot export.
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

USER:
1. Pick one prompt doc under `docs/` (for example, `prompts-codex-cad.md`).
2. Fix outdated instructions, links, or formatting.
3. Run the commands above.

OUTPUT:
A pull request with the improved prompt doc and passing checks.
```
