# Contributing

Thanks for your interest in improving sugarkube!

## Workflow

- Fork the repository and create a branch named `codex/<feature>`.
- Install dependencies and set up pre-commit:
  ```bash
  npm ci
  pre-commit install
  ```
- Run the full check suite before pushing:
  ```bash
  pre-commit run --all-files
  ```
- Open a pull request with a clear description and references to any issues.

## Code of Conduct

This project follows the [Contributor Covenant](CODE_OF_CONDUCT.md).
By participating you agree to uphold its terms.
