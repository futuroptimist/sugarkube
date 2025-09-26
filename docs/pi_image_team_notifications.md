# Sugarkube Team Notifications

The Pi image now ships an optional `sugarkube-teams` helper that mirrors first boot and SSD clone
progress to Slack, Discord, or Matrix. Operators who enable the webhook receive a short message when:

- `first_boot_service.py` starts running and once the verifier succeeds or fails.
- `ssd_clone_service.py` begins waiting for a target disk, finds one, and exits with success or
  failure (including resume attempts).

These notifications complement the existing `/boot/first-boot-report/` summaries so remote teams can
confirm progress without SSH or serial access.

## Configuration file

During image builds cloud-init writes `/etc/sugarkube/teams-webhook.env` with commented defaults:

```ini
SUGARKUBE_TEAMS_ENABLE="false"
SUGARKUBE_TEAMS_URL=""
SUGARKUBE_TEAMS_KIND="slack"
# SUGARKUBE_TEAMS_MATRIX_ROOM="!room:example.org"
# Example token placeholder for SUGARKUBE_TEAMS_TOKEN (e.g. syt_example_token)
# SUGARKUBE_TEAMS_USERNAME="sugarkube"
# SUGARKUBE_TEAMS_ICON=":rocket:"  # Discord treats this as avatar_url when set
SUGARKUBE_TEAMS_VERIFY_TLS="true"
SUGARKUBE_TEAMS_TIMEOUT="10"
```

Enable the webhook by editing the file and setting `SUGARKUBE_TEAMS_ENABLE="true"`. The helper reads
values at runtime, so a restart of the services is enough:

```sh
sudo nano /etc/sugarkube/teams-webhook.env
sudo systemctl restart first-boot.service || true
sudo systemctl restart ssd-clone.service || true
```

Both services ignore failures if the webhook is disabled or misconfigured; they continue writing
reports locally.

## Slack incoming webhook example

1. Create a Slack incoming webhook for the channel where you want progress updates.
2. Edit `/etc/sugarkube/teams-webhook.env` and set:
   - `SUGARKUBE_TEAMS_ENABLE="true"`
   - `SUGARKUBE_TEAMS_KIND="slack"`
   - `SUGARKUBE_TEAMS_URL="https://hooks.slack.com/services/..."`
   - (Optional) `SUGARKUBE_TEAMS_USERNAME` or `SUGARKUBE_TEAMS_ICON` for friendly branding.
3. Restart `first-boot.service` if the device already finished booting or trigger a new boot.

Example output:

```
:white_check_mark: Sugarkube first boot — Success
Hostname: pi-a
Report directory: /boot/first-boot-report
Summary JSON: /boot/first-boot-report/summary.json
```

Slack attachments include structured fields for the key verifier checks so failures immediately show
which component is unhealthy.

## Discord webhook example

Discord webhooks work with a server channel or thread and accept the same enable/disable flow.

1. In Discord choose **Edit Channel → Integrations → Webhooks → New Webhook** and copy its URL.
2. Configure `/etc/sugarkube/teams-webhook.env` with:
   - `SUGARKUBE_TEAMS_ENABLE="true"`
   - `SUGARKUBE_TEAMS_KIND="discord"`
   - `SUGARKUBE_TEAMS_URL="https://discord.com/api/webhooks/..."`
   - (Optional) `SUGARKUBE_TEAMS_USERNAME` to override the webhook name.
   - (Optional) `SUGARKUBE_TEAMS_ICON` to point at an avatar image URL.
3. Restart the relevant services or trigger a new boot/clone cycle.

Notifications post the heading as a message with embeds that list additional lines and structured
fields so team members can scan the status quickly from mobile or desktop clients.

## Matrix homeserver example

Matrix support expects a user access token with permission to post into a specific room.

1. Create or reuse a Matrix account that has joined the target room.
2. Generate a user access token (`Element Desktop → Settings → Help & About → Advanced → Access Token`).
3. Edit `/etc/sugarkube/teams-webhook.env` and configure:
   - `SUGARKUBE_TEAMS_ENABLE="true"`
   - `SUGARKUBE_TEAMS_KIND="matrix"`
   - `SUGARKUBE_TEAMS_URL="https://matrix.example.org"` (homeserver base URL)
   - `SUGARKUBE_TEAMS_MATRIX_ROOM="!abcdef:example.org"`
   - Set `SUGARKUBE_TEAMS_TOKEN` to your homeserver access token (for example `syt_abc123`).
4. Restart the relevant systemd units or wait for the next clone/boot cycle.

Messages render with a formatted HTML body so timelines contain bullet lists and highlighted status
fields.

## Manual testing

The same Python helper installs at `/opt/sugarkube/sugarkube_teams.py` and exposes a CLI via
`/usr/local/bin/sugarkube-teams`. Use it to validate credentials without waiting for automation:

```sh
sudo sugarkube-teams --event first-boot --status info \
  --line "Manual test" --field Environment=lab
```

When the webhook remains disabled, the CLI prints a warning and exits successfully, keeping
scripted runs safe (regression coverage:
`tests/test_sugarkube_teams.py::test_main_warns_when_disabled`).

You can also invoke the helper through repository tooling:

```sh
make notify-teams TEAMS_ARGS='--event custom --status info --line "dry-run"'
# or
just notify-teams teams_args='--event custom --status info --line "dry-run"'
```

The CLI honors the same environment file and emits warnings instead of raising when the webhook is
disabled, keeping scripted runs safe.

## Troubleshooting

- Check `/var/log/sugarkube/ssd_clone_service.py.log` (or the journal) for lines starting with
  `[ssd-clone-service] teams webhook` to confirm payload delivery.
- `journalctl -u first-boot.service --no-pager` contains matching warnings for the first boot path.
- Set `SUGARKUBE_TEAMS_VERIFY_TLS="false"` only when inspecting self-signed labs and revert to
  `true` afterwards.
- Increase `SUGARKUBE_TEAMS_TIMEOUT` if Matrix or Slack proxies take longer than the default 10s.

Refer back to [Pi Image Quickstart](./pi_image_quickstart.md) for broader first boot context and the
[SSD Recovery](./ssd_recovery.md) guide when clone failures persist even after notifications arrive.
