# token.place and dspace Quickstart

Build a Raspberry Pi 5 image that includes the
[token.place](https://github.com/futuroptimist/token.place) and
[dspace](https://github.com/democratizedspace/dspace) repositories so you can run
both apps out of the box. The image builder clones these projects, drops a shared
`docker-compose.yml` under `/opt/projects` and installs a single
`projects-compose.service` to manage them. Each service uses `restart: unless-stopped`
so the containers stay up across reboots. Hooks remain for additional repositories.
Docker Engine and the Compose plugin come from Docker's Debian repository for up-to-date ARM builds.

## Build the image

```sh
# inside the sugarkube repo
./scripts/build_pi_image.sh
```

### Build-time flags

The build script accepts environment variables to trim or extend the stack:

- `CLONE_TOKEN_PLACE` (default `true`) — clone the `token.place` repository.
- `CLONE_DSPACE` (default `true`) — clone the `dspace` repository.
- `EXTRA_REPOS` — space-separated Git URLs for additional projects.

`build_pi_image.sh` clones `token.place` and `dspace` by default. Adjust the stack before
building by editing [`scripts/cloud-init/docker-compose.yml`](../scripts/cloud-init/docker-compose.yml)
and dropping new services under the `# extra-start` marker. To skip cloning either
repo, set `CLONE_TOKEN_PLACE=false` or `CLONE_DSPACE=false`. Add more projects by passing
their Git URLs via `EXTRA_REPOS`:

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
letting containers start with sane defaults. Edit these files to set variables like
`PORT`, API URLs or secrets:

- copies any `*.env.example` to `.env`
- ensures blank files exist for token.place and dspace even if the repos omit
  examples
- handles any additional repo dropped into `/opt/projects`

Update the placeholders with real values and restart the service:

See each repository's README for the full list of configuration options.

## Extend with new repositories

Pass Git URLs via `EXTRA_REPOS` to clone additional projects into `/opt/projects`.
Add services to `/opt/projects/docker-compose.yml` between `# extra-start` and
`# extra-end`, and extend `init-env.sh` with any new `.env` files, following the
token.place and dspace examples. The image builder drops the token.place or dspace
definitions when the corresponding `CLONE_*` flag is `false`, letting you build a
minimal image and expand it later.

Use these hooks to experiment with other projects and grow the image over time.
