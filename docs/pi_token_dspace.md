# token.place and dspace Runbook

This runbook walks through building the Raspberry Pi image, flashing it, booting,
and confirming both [token.place](https://github.com/futuroptimist/token.place)
and [dspace](https://github.com/democratizedspace/dspace) work locally and via a
Cloudflare Tunnel. The image builder clones each repository, drops a shared
`docker-compose.yml` under `/opt/projects` and installs a single
`projects-compose.service` to manage the stack. Services use `restart:
unless-stopped` so containers relaunch across reboots.

## 1. Build or download the image

1. In GitHub, open **Actions → pi-image → Run workflow**.
   - Tick **token.place** and **dspace** to bake those repos into `/opt/projects`.
   - Wait for the run to finish; it uploads `sugarkube.img.xz` as an artifact.
2. Download the artifact locally:
   ```sh
   ./scripts/download_pi_image.sh
   ```
   or grab it manually from the workflow run.
3. Alternatively, build on your machine:
   ```sh
   ./scripts/build_pi_image.sh
   ```
   Control the stack with environment variables:

   | Variable | Default | Description |
   | --- | --- | --- |
   | `CLONE_TOKEN_PLACE` | `true` | Clone the `token.place` repository. |
   | `CLONE_DSPACE` | `true` | Clone the `dspace` repository. |
   | `CLONE_SUGARKUBE` | `false` | Include this repo in the image. |
   | `EXTRA_REPOS` | _(empty)_ | Space-separated Git URLs for extra projects. |

   Adjust the stack before building by editing
   [`scripts/cloud-init/docker-compose.yml`](../scripts/cloud-init/docker-compose.yml)
   and inserting services between the `# extra-start` and `# extra-end` markers.

## 2. Flash with Raspberry Pi Imager

- Write `sugarkube.img.xz` to a microSD card with Raspberry Pi Imager.
- Use advanced options (<kbd>Ctrl</kbd>+<kbd>Shift</kbd>+<kbd>X</kbd>) to set the
  hostname, credentials and network.

## 3. Boot and verify locally

1. Insert the card and power on the Pi.
2. On first boot the Pi builds the containers defined in
   `/opt/projects/docker-compose.yml` and enables `projects-compose.service`.
3. Confirm the stack is running:
   ```sh
   sudo systemctl status projects-compose.service
   ```
4. Verify each app on the LAN:
   ```sh
   curl http://<pi-host>:5000  # token.place
   curl http://<pi-host>:3000  # dspace
   ```

## 4. Expose through Cloudflare Tunnel

1. Add your tunnel token to `/opt/sugarkube/.cloudflared.env`.
2. Map hostnames to local services by editing
   `/opt/sugarkube/docker-compose.cloudflared.yml`:
   ```yaml
   ingress:
     - hostname: tokenplace.example.com
       service: http://localhost:5000
     - hostname: dspace.example.com
       service: http://localhost:3000
     - service: http_status:404
   ```
3. Restart the tunnel:
   ```sh
   sudo systemctl restart cloudflared-compose
   ```
4. Verify remote access:
   ```sh
   curl https://tokenplace.example.com
   curl https://dspace.example.com
   ```

## 5. Runtime environment variables

Each project reads an `.env` file in its directory. `init-env.sh` scans
`/opt/projects` for `*.env.example` files and copies them to `.env` when missing,
letting containers start with sane defaults. The script ships an `ensure_env`
helper that creates blank files when a project omits an example. Edit these files
to set variables like `PORT`, API URLs or secrets:

- `/opt/projects/token.place/.env` — example:
  ```ini
  PORT=5000
  ```
- `/opt/projects/dspace/frontend/.env` — example:
  ```ini
  PORT=3000
  ```

Add more calls to `ensure_env` under the `# extra-start` marker in `init-env.sh`
for additional repositories. See each project's README for the full list of
configuration options.

## 6. Extend with new repositories

Pass Git URLs via `EXTRA_REPOS` to clone additional projects into `/opt/projects`.
Add services to `/opt/projects/docker-compose.yml` between `# extra-start` and
`# extra-end`, and extend `init-env.sh` with any new `.env` files, following the
token.place and dspace examples. The image builder drops the token.place or
dspace definitions when the corresponding `CLONE_*` flag is `false`, letting you
build a minimal image and expand it later.

Use these hooks to experiment with other projects and grow the image over time.
