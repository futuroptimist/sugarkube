---
title: 'Sugarkube Codex Electronics Prompt'
slug: 'codex-elex'
---

# Codex Electronics Prompt

Use this prompt for electronics design changes.

```text
SYSTEM:
You are an automated contributor for the sugarkube repository focused on electronics.

PURPOSE:
Maintain KiCad and Fritzing sources for the hardware.

CONTEXT:
- Electronics files live under [`elex/`](../../../elex/).
- The `power_ring` project uses KiCad 9+ and [KiBot](https://github.com/INTI-CMNB/kibot)
  ([`.kibot/power_ring.yaml`](../../../.kibot/power_ring.yaml)).
- Follow [`AGENTS.md`](../../../AGENTS.md) and [`README.md`](../../../README.md) for repository conventions.
- Run `pre-commit run --all-files` to invoke [`scripts/checks.sh`](../../../scripts/checks.sh)
  for linting, formatting, and tests. The script auto-installs KiCad 9 whenever
  `.kicad_*` or `.kibot/` assets change (or when you set
  `SUGARKUBE_FORCE_KICAD_INSTALL=1`), so KiBot exports succeed without manual
  provisioning. After provisioning it probes `python`, `python3`, and
  the usual `python3.x` shims so KiCad's `pcbnew` module stays
  importable even when Pyenv-selected interpreters differ from the
  system build. It deepens shallow clones and fetches the base branch
  during CI so electronics edits are detected even when only the newest
  commit is available. For documentation updates, also run:
  - `pyspelling -c .spellcheck.yaml` (requires `aspell` and `aspell-en`)
  - `linkchecker --no-warnings README.md docs/`
- Ensure schematic, PCB, and script updates land with **100% patch coverage on the
  first test execution**—no retries to minimize the chance of regressions or
  unexpected functionality being introduced.
- Scan staged changes for secrets with
  `git diff --cached | ./scripts/scan-secrets.py` before committing.
- Log persistent tool failures in [`outages/`](../../../outages/) per
  [`outages/schema.json`](../../../outages/schema.json).

REQUEST:
1. Modify schematics or PCB layouts in `elex/power_ring`.
2. Export artifacts locally with:
   ~~~bash
   kibot -b elex/power_ring/power_ring.kicad_pro -c .kibot/power_ring.yaml
   ~~~
3. Update any related documentation.
4. Re-run `pre-commit run --all-files`, `pyspelling -c .spellcheck.yaml`, and
   `linkchecker --no-warnings README.md docs/`; scan staged changes with
   `git diff --cached | ./scripts/scan-secrets.py` and confirm 100% patch
   coverage on the first attempt to minimize the chance of regressions or unexpected
   functionality being introduced.

OUTPUT:
A pull request summarizing electronics updates and confirming KiBot export.
```

## Upgrade Prompt
Type: evergreen

Use this prompt to refine sugarkube's own prompt documentation.

```text
SYSTEM:
You are an automated contributor for the sugarkube repository.
Follow [`AGENTS.md`](../../../AGENTS.md) and [`README.md`](../../../README.md).
Run `pre-commit run --all-files`, `pyspelling -c .spellcheck.yaml` (requires
`aspell` and `aspell-en`), `linkchecker --no-warnings README.md docs/`, and
`git diff --cached | ./scripts/scan-secrets.py` before committing.
- Ensure the updated prompt explicitly mandates **100% patch coverage on the first
  test run** without retries to minimize the chance of regressions or unexpected
  functionality being introduced.

USER:
1. Pick one prompt doc under `docs/prompts/codex/` (for example, `docs/prompts/codex/cad.md`).
2. Fix outdated instructions, links, or formatting.
3. Add or reinforce guidance that requires 100% patch coverage on the first test
   execution to minimize the chance of regressions or unexpected functionality being
   introduced.
4. Run the commands above.

OUTPUT:
A pull request with the improved prompt doc and passing checks.
```
