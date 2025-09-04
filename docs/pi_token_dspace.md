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

## Run the apps

After flashing the image and booting the Pi, start the services:

```sh
# token.place
cd /opt/projects/token.place
docker buildx build --platform linux/arm64 -f docker/Dockerfile.server -t tokenplace . --load
docker run -d --name tokenplace -p 5000:5000 tokenplace

# dspace frontend
cd /opt/projects/dspace/frontend
cp .env.example .env  # if the file exists
docker compose up -d
```

Visit `http://<pi-host>:5000` for token.place and `http://<pi-host>:3000` for
dspace. To expose them through a Cloudflare Tunnel, update
`/opt/sugarkube/docker-compose.cloudflared.yml` as shown in
[docker_repo_walkthrough.md](docker_repo_walkthrough.md).

Use `EXTRA_REPOS` to experiment with other projects and extend the image over
time.
