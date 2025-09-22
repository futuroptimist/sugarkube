# token.place and dspace Runbook

This runbook walks through building the Raspberry Pi image, flashing it, booting,
and confirming both [token.place](https://github.com/futuroptimist/token.place)
and [dspace](https://github.com/democratizedspace/dspace) work locally and via a
Cloudflare Tunnel. The image builder clones each repository, drops a shared
`docker-compose.yml` under `/opt/projects` and installs a single
`projects-compose.service` to manage the stack. Services use `restart:
unless-stopped` so containers relaunch across reboots.

## Prerequisites

Confirm Docker Engine and the Compose plugin are available:

```sh
docker --version
docker compose version
```

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
   | `TOKEN_PLACE_BRANCH` | `main` | `token.place` branch to check out. |
   | `CLONE_DSPACE` | `true` | Clone the `dspace` repository. |
   | `DSPACE_BRANCH` | `v3` | `dspace` branch to check out. |
   | `CLONE_SUGARKUBE` | `false` | Include this repo in the image. |
   | `EXTRA_REPOS` | _(empty)_ | Space-separated Git URLs for extra projects. |

   Add services to [`scripts/cloud-init/docker-compose.yml`](../scripts/cloud-init/docker-compose.yml)
   between the `# extra-start` and `# extra-end` markers and mirror those entries in
   [`scripts/cloud-init/init-env.sh`](../scripts/cloud-init/init-env.sh) with matching `ensure_env`
   calls.

## 2. Flash with Raspberry Pi Imager

- Write `sugarkube.img.xz` to a microSD card with Raspberry Pi Imager.
- Use advanced options (<kbd>Ctrl</kbd>+<kbd>Shift</kbd>+<kbd>X</kbd>) to set the
  hostname, credentials and network.

## 3. Boot and verify locally

1. Insert the card and power on the Pi.
2. On first boot the Pi installs Docker, builds the containers defined in
   `/opt/projects/docker-compose.yml` and enables `projects-compose.service`.
3. Confirm Docker and the stack are running:
   ```sh
   docker --version
   docker compose version
   sudo systemctl status projects-compose.service
   sudo systemctl status k3s-ready.target
   ```
4. Verify each app on the LAN:
   ```sh
   curl http://<pi-host>:5000  # token.place
   curl http://<pi-host>:3000  # dspace
   ```

### Automate health verification

- The `first-boot.service` already captures compose and HTTP health in
  `/boot/first-boot-report/summary.*`. Re-run the bundled verifier anytime you need
  a refreshed log in `/boot/first-boot-report.txt`:
  ```sh
  sudo TOKEN_PLACE_HEALTH_URL="http://127.0.0.1:5000/" \
       DSPACE_HEALTH_URL="http://127.0.0.1:3000/" \
       /opt/sugarkube/pi_node_verifier.sh --log /boot/first-boot-report.txt
  ```
- The script now evaluates:
  - `k3s_node_ready`: confirms `kubectl get nodes` reports a `Ready` status.
  - `projects_compose_active`: ensures `projects-compose.service` is `active`.
  - `token_place_http` and `dspace_http`: fetch the configured URLs and fail if the
    endpoints refuse connections or return non-success responses. GraphQL APIs served
    over HTTP/HTTPS are covered automatically.
- Override health URLs or relax TLS checks with environment variables:
  | Variable | Default | Description |
  | --- | --- | --- |
  | `TOKEN_PLACE_HEALTH_URL` | `http://127.0.0.1:5000/` | URL the verifier curls for token.place. Set to `skip` to disable. |
  | `TOKEN_PLACE_HEALTH_INSECURE` | `false` | Set to `true` to ignore TLS verification errors. |
  | `DSPACE_HEALTH_URL` | `http://127.0.0.1:3000/` | URL the verifier curls for dspace. Set to `skip` to disable. |
  | `DSPACE_HEALTH_INSECURE` | `false` | Set to `true` to ignore TLS verification errors. |
  | `HEALTH_TIMEOUT` | `5` | Timeout (seconds) for each HTTP probe. |
- When the environment variables are unset the defaults above keep probing the
  LAN services. Populate them in `/etc/environment` or before invoking the
  verifier on remote hosts.

## 4. Expose through Cloudflare Tunnel

1. Add your tunnel token to `/opt/sugarkube/.cloudflared.env`.
2. Create `/opt/sugarkube/cloudflared.yml` with ingress rules:
   ```yaml
   ingress:
     - hostname: tokenplace.example.com
       service: http://localhost:5000
     - hostname: dspace.example.com
       service: http://localhost:3000
     - service: http_status:404
   ```
3. Mount the config in `/opt/sugarkube/docker-compose.cloudflared.yml`:
   ```yaml
   services:
     tunnel:
       command: tunnel --config /etc/cloudflared/config.yml run
       env_file:
         - /opt/sugarkube/.cloudflared.env
       volumes:
         - /opt/sugarkube/cloudflared.yml:/etc/cloudflared/config.yml:ro
   ```
4. Restart the tunnel:
   ```sh
   sudo systemctl restart cloudflared-compose
   ```
5. Verify remote access:
   ```sh
   curl https://tokenplace.example.com
   curl https://dspace.example.com
   ```
   ```

## 5. Runtime environment variables

Each project reads an `.env` file in its directory. `init-env.sh` scans
`/opt/projects` for `*.env.example` files and copies them to `.env` when missing,
letting containers start with sane defaults. The script ships an `ensure_env`
helper that creates blank files when a project omits an example, and seeds a
default `PORT` so containers start with predictable endpoints. Edit these files
to set variables like ports, API URLs, or secrets.

| Service       | Path to env file                               | Key variables |
| ------------- | ---------------------------------------------- | ------------- |
| token.place   | `/opt/projects/token.place/.env`               | `PORT`, Supabase secrets |
| dspace        | `/opt/projects/dspace/frontend/.env`           | `PORT`, Supabase anon key |
| grafana-agent | `/opt/projects/observability/grafana-agent.env` | Cluster label, scrape interval |
| netdata       | `/opt/projects/observability/netdata.env`       | Claim token, Netdata port |

Add more calls to `ensure_env` under the `# extra-start` marker in `init-env.sh`
for additional repositories. Common variables include:

- **token.place:** `PORT`, `NEXTAUTH_SECRET`, `NEXTAUTH_URL`
- **dspace:** `PORT`, `NEXT_PUBLIC_SUPABASE_URL`, `NEXT_PUBLIC_SUPABASE_ANON_KEY`

See each project's README for the full list of configuration options. The
observability services ship ready-to-go: scrape
`http://<pi-host>:9100/metrics` for host stats, `http://<pi-host>:8080/metrics`
for container insights, `http://<pi-host>:12345/metrics` for the aggregated
Grafana Agent feed, and `http://<pi-host>:19999` for Netdata's dashboard. Edit
the `.env` files to change scrape intervals, claim Netdata nodes, or disable
components entirely.

### token.place variables

| Variable          | Default       | Description                                             |
| ----------------- | ------------- | ------------------------------------------------------- |
| `API_RATE_LIMIT`  | `60/hour`     | Per-IP rate limit for API requests                      |
| `API_DAILY_QUOTA` | `1000/day`    | Per-IP daily request quota                              |
| `USE_MOCK_LLM`    | `0`           | Use mock LLM instead of downloading a model (`1` = yes) |
| `TOKEN_PLACE_ENV` | `development` | Deployment environment                                  |
| `PROD_API_HOST`   | `127.0.0.1`   | IP address for production API host                      |

### dspace variables

| Variable        | Default   | Description                                                  |
| --------------- | --------- | ------------------------------------------------------------ |
| `METRICS_TOKEN` | _(unset)_ | Require `Authorization: Bearer` for the `/metrics` endpoint |

token.place also honours variables such as `TOKEN_PLACE_ENV` and API tokens
documented in its README. The dspace frontend reads values like
`NEXT_PUBLIC_SUPABASE_URL` and `NEXT_PUBLIC_SUPABASE_ANON_KEY`. Populate these
secrets in the respective `.env` files before exposing the services.

Populate these files with values from each project's README. Add more calls to
`ensure_env` under the `# extra-start` marker in `init-env.sh` for additional
repositories.

## 6. Extend with new repositories

1. Pass Git URLs via `EXTRA_REPOS` to clone additional projects into
   `/opt/projects`.
2. Add services to `/opt/projects/docker-compose.yml` between `# extra-start`
   and `# extra-end`.
3. Extend `init-env.sh` with `ensure_env` calls for new `.env` files.
4. Reboot or run `sudo systemctl restart projects-compose` to apply changes.

The image builder drops the token.place or dspace definitions when the
corresponding `CLONE_*` flag is `false`, letting you build a minimal image and
expand it later. Use these hooks to experiment with other projects and grow the
image over time.
