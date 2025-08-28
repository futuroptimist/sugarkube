# Pi image build

## Quickstart: build on GitHub Actions

1. Go to **Actions → pi-image → Run workflow**.
2. Pick the `pi_model` (`pi5` or `pi4`) and `standoff_mode` (`heatset` or `printed`).
3. Run the workflow. Each build uploads an artifact named
   `pi-image-<pi_model>-<standoff_mode>-<git_sha>` containing:
   - `pi-image-<pi_model>-<standoff_mode>.img.xz`
   - `pi-image-<pi_model>-<standoff_mode>.img.xz.sha256`
   - `manifest.json` with build metadata.

Verify the image after download:

```bash
sha256sum -c *.sha256
```

### Troubleshooting

| Symptom | Fix |
| --- | --- |
| Docker daemon is not running | Start Docker and retry |
| Missing `universe` repo | `sudo add-apt-repository -y universe` |
| Cache not restored | Check cache key and rerun with same commit |
| GitHub API rate limit | Set `GITHUB_TOKEN` or wait before retrying |
