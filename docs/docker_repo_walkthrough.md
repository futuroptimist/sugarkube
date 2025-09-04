# Docker Repo Deployment Walkthrough

This guide shows how to run any GitHub project that ships a `Dockerfile` or
`docker-compose.yml` on the Raspberry Pi image preloaded with Docker and a
[Cloudflare Tunnel](https://www.cloudflare.com/products/tunnel/). The walkthrough uses
[token.place](https://github.com/futuroptimist/token.place) and
[dspace](https://github.com/democratizedspace/dspace) as real-world examples,
but the steps apply to any repository.

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
4. Inspect the repo to confirm it includes Docker assets:
   ```sh
   ls token.place/docker            # token.place Dockerfile lives here
   ls dspace/frontend/docker-compose.yml
   ```
   Adjust paths for your repository.

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
   3000 for dspace).
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
docker run -d --name tokenplace -p 5000:5000 tokenplace
docker ps --format 'table {{.Names}}\t{{.Ports}}'
docker logs -f tokenplace  # watch startup output
docker exec -it tokenplace python -m pytest  # optional tests
curl http://localhost:5000  # should return HTML
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
curl http://localhost:3000
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
curl http://localhost:3000  # dspace
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
      - "3000:3000"
```

```sh
cd /opt/projects
docker compose up -d
docker compose ps
curl http://localhost:5000  # token.place
curl http://localhost:3000  # dspace
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
       service: http://localhost:3000
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

## 7. Troubleshooting and outages
- Check logs for errors:
  ```sh
  docker compose logs --tail=50
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
