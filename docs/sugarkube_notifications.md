# Sugarkube Remote Notifications

`scripts/sugarkube_teams.py` sends concise status updates to Slack-style webhooks or Matrix rooms
whenever high-value events occur on a Sugarkube Pi. The helper is optional—configure it when you want
chat alerts for first boot, SSD cloning, or manual health checks.

## Configure webhook or Matrix credentials

1. Copy the sample environment file into place on the Pi:
   ```bash
   sudo install -m600 /etc/sugarkube/notifications.env.example \
     /etc/sugarkube/notifications.env
   ```
2. Edit `/etc/sugarkube/notifications.env` and set one (or both) destinations:
   - **Slack/Teams/Discord:** populate `SUGARKUBE_TEAMS_WEBHOOK_URL` with an incoming webhook URL.
     Optional extras include `SUGARKUBE_TEAMS_LABEL` (appends `label · event` in the header) and
     `SUGARKUBE_TEAMS_TIMEOUT` when the webhook host sits behind a slow proxy.
   - **Matrix:** set `SUGARKUBE_MATRIX_HOMESERVER`, `SUGARKUBE_MATRIX_ROOM`,
     `SUGARKUBE_MATRIX_ACCESS_TOKEN`, and optionally `SUGARKUBE_MATRIX_TIMEOUT`. Give the token a
     low-privilege bot account that can post into the target room.
3. Restart the services to load the new environment variables:
   ```bash
   sudo systemctl restart first-boot.service
   sudo systemctl restart ssd-clone.service
   ```

Both units now load `/etc/sugarkube/notifications.env` automatically via
`EnvironmentFile=-/etc/sugarkube/notifications.env`. Leave the file empty to silence notifications
entirely.

## What gets reported?

`sugarkube_teams.py` captures a small set of lifecycle events:

| Event        | Trigger                                             | Status values                      |
| ------------ | --------------------------------------------------- | ---------------------------------- |
| `first-boot` | `first_boot_service.py` start, success, or failure  | `started`, `success`, `failure`    |
| `ssd-clone`  | `ssd_clone_service.py` waiting, running, and errors | `info`, `warning`, `started`, etc. |

Metadata accompanying each message includes hostname, verifier summaries, clone targets, and exit
codes when available. The script emits plain-text bodies for Slack-compatible webhooks and an HTML
variant for Matrix (`m.notice`).

## Send test messages

Use the task-runner wrappers to exercise the notifier without waiting for a real boot cycle:

```bash
sudo make notify-teams TEAMS_ARGS="--event manual --status info --summary 'Notification test'"
# or
sudo just notify-teams TEAMS_ARGS="--event manual --status info --summary 'Notification test'"
```

Add `--dry-run` to either command to print the formatted payload locally instead of posting it.
When a webhook fails, the helper logs the HTTP error and returns `1`, leaving the calling script to
continue without crashing the boot process.

## Troubleshooting tips

- **No messages:** Confirm `/etc/sugarkube/notifications.env` contains at least one destination and
  restart the associated service. Missing credentials cause the helper to exit quietly.
- **Matrix authentication errors:** Double-check the access token scope and that the bot account
  joined the room specified by `SUGARKUBE_MATRIX_ROOM` (room IDs, not aliases, work best).
- **Unexpected status:** Inspect `/boot/first-boot-report/summary.json` or
  `/var/log/sugarkube/ssd-clone.state.json` to correlate chat messages with local logs.
- **Custom workflows:** Call `scripts/sugarkube_teams.py` directly with
  `--event`, `--status`, and `--summary` flags to plug notifications into bespoke automation.
