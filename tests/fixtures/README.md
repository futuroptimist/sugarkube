# ls-remote fixtures

`tests/fixtures/ls_remote_tags.json` records `git ls-remote --tags` output for
the GitHub Actions pinned in the Pi image workflow tests. The mapping format is:

```json
{
  "actions/checkout": ["v5"],
  "actions/cache": ["v4.3.0"],
  "actions/upload-artifact": ["v4.6.2"]
}
```

Regenerate entries with the exact commands below, then update
`ls_remote_tags.json` accordingly:

```bash
git ls-remote https://github.com/actions/checkout.git v5
git ls-remote https://github.com/actions/cache.git v4.3.0
git ls-remote https://github.com/actions/upload-artifact.git v4.6.2
```

When `SUGARKUBE_LS_REMOTE_FIXTURES` is set in CI or locally, fixture mode is
strict: missing repositories or tags raise immediately instead of falling back
to the network.
