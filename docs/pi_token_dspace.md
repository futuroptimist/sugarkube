# token.place and dspace Quickstart

Build a Raspberry Pi 5 image that includes the
[token.place](https://github.com/futuroptimist/token.place) and
[dspace](https://github.com/democratizedspace/dspace) repositories so you can run
both apps out of the box. The image builder clones these projects and leaves
hooks for additional repositories.

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
`pi` user.

## Services on first boot

On first boot the Pi builds and starts systemd services for both projects.
Check their status with:

```sh
sudo systemctl status tokenplace.service
sudo systemctl status dspace.service
```

Visit `http://<pi-host>:5000` for token.place and `http://<pi-host>:3000` for
dspace. To expose them through a Cloudflare Tunnel, update
`/opt/sugarkube/docker-compose.cloudflared.yml` as shown in
[docker_repo_walkthrough.md](docker_repo_walkthrough.md).

## Extend with additional repositories

Use `EXTRA_REPOS` to clone extra projects during image build. After boot,
register them as services using `install_repo_service.sh`:

```sh
sudo /usr/local/sbin/install_repo_service.sh myapp /opt/projects/myapp \
  "bash /usr/local/sbin/start_myapp.sh" "docker compose down"
```

Write a `start_myapp.sh` script that builds and launches your app, then copy it
into `/usr/local/sbin` before rerunning the image build. This keeps hooks open
for future repositories.
