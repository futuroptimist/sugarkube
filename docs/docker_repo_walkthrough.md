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
3. Ensure the Cloudflare Tunnel container is running:
   ```sh
   docker compose -f /opt/sugarkube/docker-compose.cloudflared.yml ps
   ```
   `cloudflared` should display `Up`.
4. Optionally update packages and reboot:
   ```sh
   sudo apt update && sudo apt upgrade -y
   sudo reboot
   ```
4. Verify Docker is running and the compose plugin is available:
   ```sh
   sudo systemctl status docker --no-pager
   docker compose version
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

## 3. Build or start containers
1. Change into the repo directory.
2. If the repo provides `docker-compose.yml`:
   ```sh
   cp .env.example .env   # if the project uses an env file
   docker compose up -d   # build and start containers in the background
   ```
3. If the repo only has a `Dockerfile`:
   ```sh
   docker build -t myapp .
   docker run -d --name myapp -p 8080:8080 myapp
   ```
   Adjust port numbers and image names to match the project.
4. Verify the service responds:
   ```sh
   docker ps
   curl http://localhost:8080
   ```
   Substitute the correct port for your project (5000 for token.place,
   3000 for dspace).
5. View logs if startup fails:
   ```sh
   docker logs myapp
   # or
   docker compose logs -f
   ```

### Examples

#### token.place (single Dockerfile)

```sh
cd /opt/projects/token.place
docker build -f docker/Dockerfile.server -t tokenplace .
docker run -d --name tokenplace -p 5000:5000 tokenplace
docker logs -f tokenplace  # watch startup output
curl http://localhost:5000  # should return HTML
```

#### dspace (docker-compose)

```sh
cd /opt/projects/dspace/frontend
cp .env.example .env  # if present
docker compose up -d
docker compose ps
docker compose logs -f
curl http://localhost:3000
```

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
2. Restart the tunnel:
   ```sh
   docker compose -f /opt/sugarkube/docker-compose.cloudflared.yml up -d
   ```
3. Visit the Cloudflare-managed URL to verify the service is reachable:
   ```sh
   curl https://tokenplace.example.com
   curl https://dspace.example.com
   ```

## 5. Manage containers
- List running containers: `docker ps`.
- Stop a container: `docker stop tokenplace`.
- View logs: `docker compose logs -f`.
- Remove a container: `docker rm tokenplace`.
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
  [`outages/schema.json`](../outages/schema.json).
