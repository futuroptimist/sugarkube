# token.place and dspace Quickstart

Build a Raspberry Pi 5 image that includes the
[token.place](https://github.com/futuroptimist/token.place) and
[dspace](https://github.com/democratizedspace/dspace) repositories so you can run
both apps out of the box. The image builder clones these projects, installs
`tokenplace.service` and `dspace.service`, and leaves hooks for additional
repositories.

## Build the image

```sh
# inside the sugarkube repo
./scripts/build_pi_image.sh
```

`build_pi_image.sh` clones `token.place` and `dspace` by default. To skip either
repo, set `CLONE_TOKEN_PLACE=false` or `CLONE_DSPACE=false`. To add more
projects, pass their Git URLs via `EXTRA_REPOS`:

```sh
EXTRA_REPOS="https://github.com/example/repo.git" ./scripts/build_pi_image.sh
```

The script clones each repo into `/opt/projects` and assigns ownership to the
`pi` user. Service units for both apps live under
`scripts/cloud-init/` and are baked into `/etc/systemd/system/` on the Pi.

## Run the apps

On first boot the Pi builds the containers and enables systemd services for both
apps (only if the corresponding repo exists under `/opt/projects`). The services
start automatically and can be managed with `systemctl`:

```sh
# check service status
sudo systemctl status tokenplace.service
sudo systemctl status dspace.service

# restart a service
sudo systemctl restart tokenplace.service
```

Visit `http://<pi-host>:5000` for token.place and `http://<pi-host>:3000` for
dspace. To expose them through a Cloudflare Tunnel, update
`/opt/sugarkube/docker-compose.cloudflared.yml` as shown in
[docker_repo_walkthrough.md](docker_repo_walkthrough.md).

## Extend with new repositories

Pass Git URLs via `EXTRA_REPOS` to clone additional projects into
`/opt/projects`. Create a systemd unit that mirrors `tokenplace.service` or
`dspace.service` to run them on boot. Start by copying one of the existing
services and editing the paths:

```sh
cp scripts/cloud-init/tokenplace.service scripts/cloud-init/newapp.service
# edit WorkingDirectory and docker compose paths as needed
EXTRA_REPOS="https://github.com/example/repo.git" ./scripts/build_pi_image.sh
```

After boot:

```sh
sudo systemctl enable --now newapp.service
```

Use these hooks to experiment with other projects and grow the image over time.
