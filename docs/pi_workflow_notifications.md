# Sugarkube Workflow Artifact Notifications

Track GitHub Actions runs without keeping a browser tab open. The
`workflow_artifact_notifier.py` helper polls a workflow run, waits until the
artifacts finish uploading, and then raises a desktop notification using the
native facilities on Linux, macOS, or Windows. The script powers the new
`make notify-workflow` / `just notify-workflow` targets and is safe to run from
any workstation with the GitHub CLI installed.

> ⚠️ When updating this helper, add or adjust tests so `pytest` achieves **100%
> patch coverage on the first run**—no retries. The notifier ships with a unit
> test suite in `tests/test_workflow_artifact_notifier.py`; extend it alongside
> any code changes.

## Prerequisites

- [GitHub CLI (`gh`)](https://cli.github.com/) configured with credentials that
  can read the target repository.
- Python 3.8 or newer (already required by the rest of the tooling).

## Basic usage

Watch a workflow run via its Actions URL:

```bash
make notify-workflow \
  WORKFLOW_NOTIFY_ARGS='--run-url https://github.com/futuroptimist/sugarkube/actions/runs/<run-id>'
# or
just notify-workflow \
  workflow_notify_args='--run-url https://github.com/futuroptimist/sugarkube/actions/runs/<run-id>'
```

The helper polls `gh api /repos/<repo>/actions/runs/<id>` every 30 seconds until
the run reports `status=completed`. Once finished it lists the artifacts,
formats their sizes, and posts a notification via:

- `notify-send` on Linux (freedesktop / GNOME / KDE environments)
- `osascript` on macOS (Notification Center)
- `powershell` on Windows (a lightweight message box)

If the platform-specific notifier binary is missing, the script falls back to a
console summary while printing a warning so you can install the dependency.

## Advanced flags

- `--poll-interval`: seconds between API calls (default `30`).
- `--timeout`: stop waiting after the specified seconds (default `900`). Pass
  `0` to disable.
- `--print-only`: skip desktop notifications and print the summary. Handy inside
  terminals, tmux sessions, or CI jobs.
- `--repo` + `--run-id`: alternative to `--run-url`. `--repo` defaults to the
  `GITHUB_REPOSITORY` environment variable when set.
- `--platform`: override auto-detection for debugging. Accepts `linux`,
  `macos`, or `windows`.

## Example workflow

1. Kick off a new `pi-image` workflow run in GitHub.
2. Copy the run URL from the browser location bar.
3. In a terminal, run `make notify-workflow WORKFLOW_NOTIFY_ARGS='--run-url …'`.
4. Leave the terminal running; switch back to other work.
5. When the run finishes and artifacts upload, the OS notification appears with
   the branch name, triggering event, and artifact sizes. Click the notification
   (or revisit the terminal output) to grab the download URLs.

Because the helper depends on the GitHub CLI, it inherits your existing `gh`
authentication and respects environment overrides such as `GH_HOST` for
GitHub Enterprise instances.
