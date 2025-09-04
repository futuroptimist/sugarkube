# token.place and dspace Quickstart

Build a Raspberry Pi 5 image that includes the
[token.place](https://github.com/futuroptimist/token.place) and
[dspace](https://github.com/democratizedspace/dspace) repositories so you can run
both apps out of the box. The image builder clones these projects, sets up
systemd services, and leaves hooks for additional repositories.

## Build the image

```sh
# inside the sugarkube repo
./scripts/build_pi_image.sh
```

`build_pi_image.sh` clones `token.place` and `dspace` by default. To add more
projects, pass their Git URLs via `EXTRA_REPOS`:

```sh
EXTRA_REPOS="https://github.com/example/repo.git" ./scripts/build_pi_image.sh
```

The script clones each repo into `/opt/projects` and assigns ownership to the
`pi` user. A compose file at `/opt/sugarkube/docker-compose.apps.yml` defines
`token.place` and `dspace` services; extend it to add more repos later.

## Run the apps

After flashing the image and booting the Pi, services start automatically via
`apps-compose.service`. Visit `http://<pi-host>:5000` for token.place and
`http://<pi-host>:3000` for dspace.

To expose them through a Cloudflare Tunnel, update
`/opt/sugarkube/docker-compose.cloudflared.yml` as shown in
[docker_repo_walkthrough.md](docker_repo_walkthrough.md).

To add more apps, clone additional repositories with `EXTRA_REPOS` and extend
`docker-compose.apps.yml` with new service entries. You can also use `EXTRA_REPOS`
to experiment with other projects and extend the image over time.
