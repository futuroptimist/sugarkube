# token.place and dspace Quickstart

Build a Raspberry Pi 5 image that includes the
[token.place](https://github.com/futuroptimist/token.place) and
[dspace](https://github.com/democratizedspace/dspace) repositories so you can run
both apps out of the box. The image builder clones these projects, copies a
unified `docker-compose.apps.yml`, and installs a single
`sugarkube-apps.service` to manage them. Hooks remain for additional
repositories.

## Build the image

```sh
# inside the sugarkube repo
./scripts/build_pi_image.sh
```

`build_pi_image.sh` clones `token.place` and `dspace` by default. To skip either
repo, set `CLONE_TOKEN_PLACE=false` or `CLONE_DSPACE=false`. Add more projects by
passing their Git URLs via `EXTRA_REPOS`. Supply an alternate compose file via
`APPS_COMPOSE_PATH` if you maintain your own service definitions:

```sh
EXTRA_REPOS="https://github.com/example/repo.git" ./scripts/build_pi_image.sh
```

The script clones each repo into `/opt/projects` and assigns ownership to the
`pi` user.

## Run the apps

On first boot the Pi builds the containers and enables `sugarkube-apps.service`
when either repo exists under `/opt/projects`. Manage all app containers through
this unit:

```sh
# check service status
sudo systemctl status sugarkube-apps.service

# restart both apps
sudo systemctl restart sugarkube-apps.service
```

Visit `http://<pi-host>:5000` for token.place and `http://<pi-host>:3002` for
dspace. To expose them through a Cloudflare Tunnel, update
`/opt/sugarkube/docker-compose.cloudflared.yml` as shown in
[docker_repo_walkthrough.md](docker_repo_walkthrough.md).

## Extend with new repositories

Pass Git URLs via `EXTRA_REPOS` to clone additional projects into
`/opt/projects`. Edit `/opt/sugarkube/docker-compose.apps.yml` to define new
services and run:

```sh
sudo systemctl restart sugarkube-apps.service
```

Use these hooks to experiment with other projects and grow the image over time.
