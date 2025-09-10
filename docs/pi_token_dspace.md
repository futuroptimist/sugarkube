# token.place and dspace Quickstart

Build a Raspberry Pi 5 image that includes the
[token.place](https://github.com/futuroptimist/token.place) and
[dspace](https://github.com/democratizedspace/dspace) repositories so you can run
both apps out of the box. The image builder clones these projects, drops a
`docker-compose.yml` under `/opt/projects` and installs a single
`projects-compose.service` to manage them. Each service uses `restart: unless-stopped`
so the containers stay up across reboots. Hooks remain for additional repositories.

## Build the image

```sh
# inside the sugarkube repo
./scripts/build_pi_image.sh
```

`build_pi_image.sh` clones `token.place` and `dspace` by default. To skip either
repo, set `CLONE_TOKEN_PLACE=false` or `CLONE_DSPACE=false`. Add more projects by
passing their Git URLs via `EXTRA_REPOS`:

```sh
EXTRA_REPOS="https://github.com/example/repo.git" ./scripts/build_pi_image.sh
```

The script clones each repo into `/opt/projects` and assigns ownership to the `pi`
user.

## Run the apps

On first boot the Pi builds the containers defined in
`/opt/projects/docker-compose.yml`. Each service uses `restart: unless-stopped`
so it relaunches after reboots or crashes. The `start-projects.sh` helper enables
the `projects-compose.service` unit which starts the stack automatically. Manage
the services with `systemctl`:

```sh
# check service status
sudo systemctl status projects-compose.service

# restart the stack
sudo systemctl restart projects-compose.service
```

Visit `http://<pi-host>:5000` for token.place and `http://<pi-host>:3000` for
dspace. To expose them through a Cloudflare Tunnel, update
`/opt/sugarkube/docker-compose.cloudflared.yml` as shown in
[docker_repo_walkthrough.md](docker_repo_walkthrough.md).

### Environment variables

Each project reads an `.env` file in its directory. `init-env.sh` scans
`/opt/projects` for `*.env.example` files and copies them to `.env` when missing,
letting containers start with sane defaults:

- `/opt/projects/token.place/.env`
- `/opt/projects/dspace/frontend/.env`
- any additional repo that ships an `.env.example`

Edit these files with real values and restart the service.

See each repository's README for the full list of configuration options.

## Extend with new repositories

Pass Git URLs via `EXTRA_REPOS` to clone additional projects into
`/opt/projects`. Add services to `/opt/projects/docker-compose.yml` beneath the
`# extra-start` marker:

```yaml
services:
  # existing services ...
  # extra-start
  myapp:
    image: ghcr.io/example/myapp:latest
    env_file:
      - /opt/projects/myapp/.env
    restart: unless-stopped
  # extra-end
```

If the new repository includes an `.env.example`, `init-env.sh` copies it to
`.env` on first boot so the container starts with sensible defaults. Extend the
script when custom setup is required.

The image builder drops the token.place or dspace definitions when the
corresponding `CLONE_*` flag is `false`, letting you build a minimal image and
expand it later.

Use these hooks to experiment with other projects and grow the image over time.
