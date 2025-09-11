# Docker Repo Deployment Walkthrough

This guide shows how to run any GitHub project that ships a `Dockerfile` or
`docker-compose.yml` on the Raspberry Pi image preloaded with Docker and a
[Cloudflare Tunnel](https://www.cloudflare.com/products/tunnel/). The walkthrough uses
[token.place](https://github.com/futuroptimist/token.place) and
[dspace](https://github.com/democratizedspace/dspace) as real-world examples,
but the steps apply to any repository.

For a prebuilt image that already clones both projects, see
[pi_token_dspace.md](pi_token_dspace.md).

## Step-by-step overview

1. Flash the SD card and boot the Pi using
   [pi_image_cloudflare.md](pi_image_cloudflare.md).
2. SSH in and verify Docker and the Cloudflare Tunnel are active:
   `ssh pi@<hostname>.local` then `systemctl status docker cloudflared-compose`.
3. Create `/opt/projects` and clone a repo such as
   [`token.place`](https://github.com/futuroptimist/token.place) or
   [`dspace`](https://github.com/democratizedspace/dspace):
   ```sh
   sudo mkdir -p /opt/projects && sudo chown pi:pi /opt/projects
   cd /opt/projects
   git clone https://github.com/futuroptimist/token.place
   git clone https://github.com/democratizedspace/dspace
   ```
4. Build or start containers:
   - Single `Dockerfile`: `docker buildx build --platform linux/arm64 -t myapp . --load`
     then `docker run -d --name myapp -p 8080:8080 myapp`.
   - `docker-compose.yml`: `docker compose up -d`.
5. Inspect container logs to confirm the service started:
   - Single container: `docker logs -f myapp`
   - Compose project: `docker compose logs`
6. Confirm the service responds locally, e.g.
   `curl http://localhost:5000` for token.place or
   `curl http://localhost:3002` for dspace.
7. Optionally expose ports through the Cloudflare Tunnel by editing
   `/opt/sugarkube/docker-compose.cloudflared.yml`.
8. Visit the Cloudflare URL to verify remote access, for example
   `curl https://tokenplace.example.com` or
   `curl https://dspace.example.com` once the tunnel restarts.
9. Log recurring deployment failures in `outages/` using
   [`schema.json`](../outages/schema.json).

## Quick start

Try one of these example projects to confirm the image works:

### hello-world

```sh
ssh pi@<hostname>.local
cd /opt/projects
git clone https://github.com/docker-library/hello-world
cd hello-world
docker buildx build --platform linux/arm64 -t hello . --load
docker run --rm hello
```

Once the container prints the "Hello from Docker!" message, move on to
token.place or dspace.

### token.place (Dockerfile)

```sh
ssh pi@<hostname>.local
cd /opt/projects
git clone https://github.com/futuroptimist/token.place
cd token.place
docker buildx build --platform linux/arm64 -f docker/Dockerfile.server -t tokenplace . --load
docker run -d --name tokenplace -p 5000:5000 tokenplace
docker logs -f tokenplace  # watch startup output
curl http://localhost:5000
curl https://tokenplace.example.com  # via Cloudflare
```

### token.place (docker-compose)

```sh
cd /opt/projects
git clone https://github.com/futuroptimist/token.place
cd token.place
docker compose up -d
docker compose ps
curl http://localhost:5000  # relay
curl http://localhost:3000  # server
curl https://tokenplace.example.com  # via Cloudflare
```

### dspace (Dockerfile)

```sh
cd /opt/projects
git clone https://github.com/democratizedspace/dspace
cd dspace/frontend
docker buildx build --platform linux/arm64 -t dspace-frontend . --load
docker run -d --name dspace-frontend -p 3002:3002 dspace-frontend
curl http://localhost:3002
curl https://dspace.example.com  # via Cloudflare
```

### dspace (docker-compose)

```sh
cd /opt/projects
git clone https://github.com/democratizedspace/dspace
cd dspace/frontend
cp .env.example .env  # if present
docker compose up -d
docker compose logs -f  # watch build and runtime logs
curl http://localhost:3002
curl https://dspace.example.com  # via Cloudflare
```

### token.place and dspace together

Spin up both projects with a single `docker-compose.yml` to verify the Pi can
run multiple apps:

```sh
ssh pi@<hostname>.local
cd /opt/projects
git clone https://github.com/futuroptimist/token.place
git clone https://github.com/democratizedspace/dspace
cat <<'EOF' > docker-compose.yml
services:
  tokenplace:
    build:
      context: ./token.place
      dockerfile: docker/Dockerfile.server
    ports:
      - "5000:5000"
  dspace:
    build:
      context: ./dspace/frontend
    ports:
      - "3002:3002"
EOF
docker compose up -d
docker compose logs -f tokenplace dspace
curl http://localhost:5000
curl http://localhost:3002
docker compose down
```

### Auto-start token.place and dspace on boot

Keep the stack running after reboots by wrapping the compose file with a systemd
unit:

```sh
sudo tee /etc/systemd/system/tokenplace-dspace.service <<'EOF'
[Unit]
Description=token.place and dspace
Requires=docker.service
After=network-online.target docker.service

[Service]
WorkingDirectory=/opt/projects
ExecStart=/usr/bin/docker compose up -d
ExecStop=/usr/bin/docker compose down
TimeoutStartSec=0
RemainAfterExit=yes

[Install]
WantedBy=multi-user.target
EOF
sudo systemctl enable --now tokenplace-dspace.service
sudo systemctl status tokenplace-dspace.service --no-pager
```

This example assumes the combined `docker-compose.yml` above lives in
`/opt/projects`.

### Customize ports with `docker-compose.override.yml`

Override the default ports if token.place or dspace conflict with other
services on the Pi:

```sh
cd /opt/projects
cat <<'EOF' > docker-compose.override.yml
services:
  tokenplace:
    ports:
      - "5050:5000"
  dspace:
    ports:
      - "3100:3000"
EOF
docker compose up -d
docker compose ps
curl http://localhost:5050  # token.place
curl http://localhost:3100  # dspace
```

### Persist data with Docker volumes

Keep token.place and dspace data across container restarts:

```sh
cd /opt/projects
cat <<'EOF' > docker-compose.volumes.yml
services:
  tokenplace:
    build:
      context: ./token.place
      dockerfile: docker/Dockerfile.server
    ports:
      - "5000:5000"
    volumes:
      - tokenplace-data:/app/data
  dspace:
    build:
      context: ./dspace/frontend
    ports:
      - "3002:3002"
    volumes:
      - dspace-data:/usr/src/app/data
volumes:
  tokenplace-data:
  dspace-data:
EOF
docker compose -f docker-compose.volumes.yml up -d
docker volume ls | grep tokenplace-data
docker volume ls | grep dspace-data
```

Adjust container paths to match each project's documentation.

Proceed with the detailed steps below to adapt the process for other repositories.

## 1. Prepare the Pi
1. Follow [pi_image_cloudflare.md](pi_image_cloudflare.md) to flash the SD card and
   start the Cloudflare Tunnel.
2. Confirm you can SSH to the Pi: `ssh pi@<hostname>.local`.
3. Ensure the Cloudflare Tunnel service is running:
   ```sh
   systemctl status cloudflared-compose --no-pager
   ```
   It should display `active`.
4. Optionally update packages and reboot:
   ```sh
   sudo apt update && sudo apt upgrade -y
   sudo reboot
   ```
5. Verify Docker is running and the compose plugin is available:
    ```sh
    sudo systemctl status docker --no-pager
    docker compose version
    ```
   If `docker compose version` fails, install the plugin: `sudo apt install docker-compose-plugin`
6. Tail the Cloudflare tunnel logs to confirm it connected:
   ```sh
   journalctl -u cloudflared-compose -n 20 --no-pager
   ```
7. Confirm the Pi's architecture and that Docker can run containers:
   ```sh
   uname -m                     # expect aarch64
   docker run --rm hello-world
   ```

## 2. Clone a repository
1. Choose a location for projects, e.g. `/opt/projects`.
2. Clone the repo:
   ```sh
   mkdir -p /opt/projects
   cd /opt/projects
   git clone https://github.com/futuroptimist/token.place.git
   git clone https://github.com/democratizedspace/dspace.git
   ```
   Replace the URLs with any other repository that contains a `Dockerfile`.
   If you prefer the GitHub CLI:
   ```sh
   gh repo clone futuroptimist/token.place
   gh repo clone democratizedspace/dspace
   ```
3. Review the project's README for architecture-specific notes and required
   environment variables.
   - `token.place` documents settings like `API_RATE_LIMIT` and `TOKEN_PLACE_ENV`
     in its README. Create a `.env` file to override them:
     ```sh
     cd token.place
     printf 'TOKEN_PLACE_ENV=production\n' >> .env
     ```
   - `dspace` lists variables like `NODE_ENV`, `PORT`, and `HOST` in
     `frontend/docker-compose.yml`. Override them with an `.env` file if needed:
     ```sh
     cd dspace/frontend
     printf 'NODE_ENV=production\nPORT=3002\nHOST=0.0.0.0\n' >> .env
     ```
4. Inspect the repo to confirm it includes Docker assets:
   ```sh
   ls token.place/docker            # token.place Dockerfile lives here
   ls dspace/frontend/docker-compose.yml
   ```
   Adjust paths for your repository.
5. Set required environment variables. token.place reads values like `TOKEN_PLACE_ENV`
   and `API_RATE_LIMIT`; dspace's `frontend/docker-compose.yml` sets `NODE_ENV`, `PORT`
   and `HOST`. Create or edit an `.env` file if the project provides one. Example files:

   - `token.place/.env`:
     ```env
     TOKEN_PLACE_ENV=production
     API_RATE_LIMIT=5
     ```
   - `dspace/frontend/.env`:
     ```env
     NODE_ENV=production
     PORT=3002
     HOST=0.0.0.0
     ```
   Adjust values to match your deployment.

## 3. Build or start containers
1. Change into the repo directory.
2. If the repo provides `docker-compose.yml`:
   ```sh
   cp .env.example .env   # if the project uses an env file
   docker compose config  # validate YAML
   docker compose pull    # fetch pre-built multi-arch images
   docker compose up -d   # build and start containers in the background
   docker compose ps      # verify services are running
   ```
3. If the repo only has a `Dockerfile`:
   ```sh
   docker build -t myapp .
   docker run -d --name myapp -p 8080:8080 myapp
   ```
   Adjust port numbers and image names to match the project.
4. If the project doesn't publish ARM images, build for the Pi:
   ```sh
   docker buildx build --platform linux/arm64 -t myapp . --load
   ```
   For example, token.place builds with:
   ```sh
   docker buildx build --platform linux/arm64 -f docker/Dockerfile.server -t tokenplace . --load
   ```
5. Verify the service responds:
   ```sh
   docker ps
   curl http://localhost:8080
   ```
   Substitute the correct port for your project (5000 for token.place,
   3002 for dspace).
6. View logs if startup fails:
   ```sh
   docker logs myapp
   # or
   docker compose logs -f
   ```
7. Optionally stop and clean up:
   ```sh
   docker compose down   # compose project
   docker stop myapp && docker rm myapp
   ```
8. Run commands inside a running container (handy for tests or admin tasks):
   ```sh
   docker exec -it tokenplace python -m pytest   # token.place example
   docker compose exec frontend npm test         # dspace example
   ```
   Swap the command and container names for your project.

### Examples

#### token.place (single Dockerfile)

```sh
cd /opt/projects/token.place
docker buildx build --platform linux/arm64 -f docker/Dockerfile.server -t tokenplace . --load
docker run -d --name tokenplace -p 5000:5000 \
  -e TOKEN_PLACE_ENV=production \
  -e API_RATE_LIMIT=5 \
  tokenplace
docker ps --format 'table {{.Names}}\t{{.Ports}}'
docker logs -f tokenplace  # watch startup output
docker exec -it tokenplace python -m pytest  # optional tests
curl http://localhost:5000  # should return HTML
```

Environment variables like `TOKEN_PLACE_ENV` and `API_RATE_LIMIT` can be
passed with `-e` flags during `docker run`.

#### token.place (docker-compose)

The Pi image includes a minimal compose file so token.place can start with a
single command. The same approach works for repos like dspace that provide
their own `docker-compose.yml`.

```sh
cd /opt/projects/token.place
docker compose -f docker-compose.tokenplace.yml up -d
docker compose -f docker-compose.tokenplace.yml ps
docker compose -f docker-compose.tokenplace.yml logs -f
curl http://localhost:5000
```
Use `docker compose -f docker-compose.tokenplace.yml logs -f` to watch
token.place start up and confirm it binds to port 5000.

#### dspace (single Dockerfile)

```sh
cd /opt/projects
git clone https://github.com/democratizedspace/dspace
cd dspace/frontend
docker buildx build --platform linux/arm64 -t dspace-frontend . --load
docker run -d --name dspace-frontend -p 3002:3002 dspace-frontend
docker logs -f dspace-frontend  # watch startup output
curl http://localhost:3002
```

#### dspace (docker-compose)

```sh
cd /opt/projects/dspace/frontend
cp .env.example .env  # if present
docker compose config
docker compose pull
docker compose up -d
docker compose ps
docker compose logs -f
docker compose exec frontend npm test  # run unit tests
curl http://localhost:3002
```

#### token.place and dspace together

Run both sample projects side by side to confirm the Pi can host multiple
containers. Start token.place, then launch the dspace frontend in the
neighboring directory:

```sh
cd /opt/projects/token.place
docker buildx build --platform linux/arm64 -f docker/Dockerfile.server -t tokenplace . --load
docker run -d --name tokenplace -p 5000:5000 tokenplace
cd ../dspace/frontend
cp .env.example .env  # if present
docker compose up -d
docker ps --format 'table {{.Names}}\t{{.Ports}}'
curl http://localhost:5000  # token.place
curl http://localhost:3002  # dspace
```

#### token.place and dspace via one `docker-compose.yml`

Manage both apps in a single file to simplify startup and shutdown.

```yaml
# /opt/projects/docker-compose.yml
services:
  tokenplace:
    build:
      context: ./token.place
      dockerfile: docker/Dockerfile.server
    ports:
      - "5000:5000"
  dspace:
    build:
      context: ./dspace/frontend
    ports:
      - "3002:3002"
```

```sh
cd /opt/projects
docker compose up -d
docker compose ps
curl http://localhost:5000  # token.place
curl http://localhost:3002  # dspace
docker compose down
```

### Build for ARM with Docker `buildx`

Some repositories only ship x86_64 images. Use Docker `buildx` to compile an arm64
image for the Pi's CPU.

```sh
docker buildx create --name pi --use  # run once to enable buildx
```

#### token.place

```sh
cd /opt/projects/token.place
docker buildx build --platform linux/arm64 -f docker/Dockerfile.server -t tokenplace .
docker run -d --name tokenplace -p 5000:5000 tokenplace
```

#### dspace

```sh
cd /opt/projects/dspace/frontend
docker buildx build --platform linux/arm64 -t dspace-frontend .
docker compose up -d
```

The `--platform` flag forces an arm64 build; omit it if the upstream image
already supports arm64.

## 4. Expose services through Cloudflare
1. Edit `/opt/sugarkube/docker-compose.cloudflared.yml` and add a new
   `ingress` rule mapping a subdomain to the container's port. Example:
   ```yaml
   ingress:
    - hostname: tokenplace.example.com
      service: http://localhost:5000
    - hostname: dspace.example.com
      service: http://localhost:3002
    - service: http_status:404
   ```
2. Restart the tunnel service:
   ```sh
   sudo systemctl restart cloudflared-compose
   ```
3. Visit the Cloudflare-managed URL to verify the service is reachable:
   ```sh
   curl https://tokenplace.example.com
   curl https://dspace.example.com
   ```

## 5. Manage containers
- List running containers: `docker ps`.
- Stop a container: `docker stop tokenplace`.
- Stop a compose stack: `docker compose down`.
- View logs: `docker compose logs -f`.
- Monitor CPU and memory: `docker stats tokenplace dspace`.
- Remove a container: `docker rm tokenplace`.
- Shut down a compose project: `docker compose down`.
- Delete old images and networks: `docker system prune`.

## 6. Update services
1. Pull the latest code:
   ```sh
   cd /opt/projects/<repo>
   git pull
   ```
2. Rebuild and restart:
   - Compose project: `docker compose up -d --build`
   - Single Dockerfile: `docker build -t myapp . && docker restart myapp`

Repeat these steps for each repository you want to deploy.

### token.place

```sh
cd /opt/projects/token.place
git pull
docker buildx build --platform linux/arm64 -f docker/Dockerfile.server -t tokenplace . --load
docker restart tokenplace
```

### dspace

```sh
cd /opt/projects/dspace/frontend
git pull
docker compose up -d --build
```

## 7. Troubleshooting and outages
- Check logs for errors:
  ```sh
  docker compose logs --tail=50
  ```
- For build failures, rerun with verbose output:
  ```sh
  cd /opt/projects/token.place
  docker buildx build --platform linux/arm64 \
    -f docker/Dockerfile.server -t tokenplace . \
    --load --progress=plain
  cd /opt/projects/dspace/frontend
  docker compose build --progress=plain
  ```
- If a deployment fails repeatedly, record it under
  [`outages/`](../outages/README.md) using
  [`outages/schema.json`](../outages/schema.json). Example:
  ```json
  {
    "id": "2025-01-15-tokenplace-startup",
    "date": "2025-01-15",
    "component": "token.place",
    "rootCause": "Missing ENV var",
    "resolution": "Added SECRET_KEY to env file",
    "references": [
      "https://github.com/futuroptimist/token.place/pull/123"
    ]
  }
  ```
