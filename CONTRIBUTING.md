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
git diff --cached | ./scripts/scan-secrets.py
```
`scan-secrets.py` skips scanning itself even if diff paths omit the `b/` prefix.
Findings are printed to stderr so stdout remains clean for tooling.

- If `README.md` or files under `docs/` change, run the combined helper so spellcheck and link checks
  stay in sync:

```bash
make docs-verify
# or
just docs-verify
```

- When `pyspelling` or `linkchecker` are missing locally, install prerequisites and rerun the
  individual commands:

```bash
pyspelling -c .spellcheck.yaml
linkchecker --no-warnings README.md docs/
```

The `--no-warnings` flag suppresses parse warnings so the command exits cleanly.

The pre-commit script also checks links in those paths.

- Use the commit format `emoji : summary` with a short body.
- Open a pull request once CI passes.

## Code of Conduct

All contributors must follow the [Code of Conduct](CODE_OF_CONDUCT.md).
