# 🤖 AGENTS

This repository uses lightweight LLM helpers inspired by the [flywheel](https://github.com/futuroptimist/flywheel) project.

## Code Linter Agent
- **When:** every PR
- **Does:** run pre-commit checks via `scripts/checks.sh` and suggest fixes.

## Docs Agent
- **When:** docs or README change
- **Does:** spell-check and link-check documentation.

Before pushing changes run `pre-commit run --all-files`.
