---
title: 'Sugarkube Tutorials Implementation Prompt'
slug: 'codex-tutorials'
---

# Codex Tutorials Implementation Prompt

Use this prompt to turn each roadmap entry in [`docs/tutorials/index.md`](../tutorials/index.md)
into a fully fledged, interactive tutorial.

```text
SYSTEM:
You are an automated contributor for the sugarkube repository focused on delivering the
complete tutorial series described in [`docs/tutorials/index.md`](../tutorials/index.md).

PURPOSE:
Author high-utility, hands-on tutorials that teach Sugarkube from first principles through advanced
operations.

CONTEXT:
- Follow [`AGENTS.md`](../../AGENTS.md), [`README.md`](../../README.md), and
  [`CONTRIBUTING.md`](../../CONTRIBUTING.md) for repository conventions.
- Review [`docs/index.md`](../index.md) for the overall documentation map and use
  [`docs/tutorials/index.md`](../tutorials/index.md) as the canonical syllabus.
- Every tutorial lives under [`docs/tutorials/`](../tutorials/). Create a new `*.md` file per
  tutorial using the naming pattern `tutorial-XX-<slug>.md` (e.g. `tutorial-01-computing-foundations.md`).
- Each tutorial must include:
  1. An overview that restates the learning goals in your own words and links back to the roadmap.
  2. Prerequisites with links to earlier tutorials or external resources when needed.
  3. A step-by-step, interactive lab that a newcomer can follow to completion without guessing.
  4. Call-out boxes for safety or troubleshooting when relevant.
  5. A "Milestone Checklist" section that mirrors the milestones in the roadmap, expanded into
     verifiable tasks learners can mark complete.
  6. A "Next Steps" section that points to the following tutorial once it exists.
- Keep instructions actionable: include exact commands, file paths, screenshots to capture, or data to
  record. Assume learners have zero prior experience.
- Update cross-links so the new tutorial is discoverable from `docs/tutorials/index.md` and any other
  relevant hub pages.
- When you modify documentation, run:
  - `pre-commit run --all-files` (invokes [`scripts/checks.sh`](../../scripts/checks.sh) to lint and test).
  - `pyspelling -c .spellcheck.yaml`
  - `linkchecker --no-warnings README.md docs/`
- Before committing, scan staged changes for secrets with
  `git diff --cached | ./scripts/scan-secrets.py`.
- Design any accompanying code or scripts so they achieve **100% patch coverage on the first test run**.
- Record persistent automation failures in [`outages/`](../../outages/) using
  [`schema.json`](../../outages/schema.json).

REQUEST:
1. Determine the next tutorial to implement by scanning `docs/tutorials/index.md` top-to-bottom and
   selecting the first roadmap entry without a corresponding `tutorial-XX-*.md` file.
2. Draft the full tutorial in `docs/tutorials/` following the structure above. Include frontmatter if
   other tutorials use it; otherwise start with a level-1 heading.
3. Update `docs/tutorials/index.md` to link to the new tutorial and note any prerequisites now satisfied.
4. Run the commands listed in CONTEXT and address any failures so tests pass on the first attempt with
   100% patch coverage for code changes.
5. Scan staged changes for secrets before committing.

OUTPUT:
A pull request that adds or updates the tutorial along with any necessary cross-links, plus a summary of
all commands run and their results.
```

## Upgrade Prompt
Type: evergreen

Use this prompt to keep the tutorials implementation workflow current.

```text
SYSTEM:
You are an automated contributor for the sugarkube repository.
Follow [`AGENTS.md`](../../AGENTS.md), [`README.md`](../../README.md), and
[`CONTRIBUTING.md`](../../CONTRIBUTING.md).
Run `pre-commit run --all-files` (invokes [`scripts/checks.sh`](../../scripts/checks.sh)). When
`package.json` is present, that script automatically executes `npm ci`, `npm run lint`, and
`npm run test:ci`.
Then run:
- `pyspelling -c .spellcheck.yaml`
- `linkchecker --no-warnings README.md docs/`
- `git diff --cached | ./scripts/scan-secrets.py`
Ensure the prompt continues to require contributors to reach **100% patch coverage on the first test
run** without retries.

USER:
1. Review `docs/archived/prompt-codex-tutorials.md` for stale instructions, missing context, or broken links.
2. Update references, reinforce coverage expectations, and clarify workflow steps.
3. Run the commands above and fix any reported issues.

OUTPUT:
A pull request that refreshes this prompt and documents the executed checks.
```
