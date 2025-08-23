# Docker Repo Deployment Walkthrough

This guide shows how to run any GitHub project that ships a `Dockerfile` or
`docker-compose.yml` on the Raspberry Pi image preloaded with Docker and a
Cloudflare Tunnel. Token.place and dspace are real-world examples, but the
steps work for any repository.

## 1. Prepare the Pi
1. Follow [pi_image_cloudflare.md](pi_image_cloudflare.md) to flash the SD card and
   start the Cloudflare Tunnel.
2. Confirm you can SSH to the Pi: `ssh pi@<hostname>.local`.
3. Confirm Docker and the compose plugin are available:
   ```sh
   docker --version
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

### Examples

#### token.place (single Dockerfile)

```sh
cd /opt/projects/token.place
docker build -f docker/Dockerfile.server -t tokenplace .
docker run -d --name tokenplace -p 5000:5000 tokenplace
curl http://localhost:5000  # should return HTML
```

#### dspace (docker-compose)

```sh
cd /opt/projects/dspace/frontend
cp .env.example .env  # if present
docker compose up -d
docker compose ps
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
3. Visit the Cloudflare-managed URL to verify the service is reachable.

## 5. Manage containers
- List running containers: `docker ps`.
- Stop a container: `docker stop tokenplace`.
- View logs: `docker compose logs -f`.

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
