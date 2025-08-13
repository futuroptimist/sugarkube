# Contributing

Thanks for helping improve sugarkube!

## Workflow

- Fork the repository and create a feature branch.
- Install tooling:

```bash
pip install pre-commit pyspelling linkchecker
sudo apt-get install aspell
pre-commit install
```

- Run all checks before committing:

```bash
pre-commit run --all-files
pyspelling -c .spellcheck.yaml
linkchecker README.md docs/ CONTRIBUTING.md CODE_OF_CONDUCT.md
```

- Use the commit format `emoji : summary` with a short body.
- Open a pull request once CI passes.

## Code of Conduct

All contributors must follow the [Code of Conduct](CODE_OF_CONDUCT.md).
