# Docker Repo Deployment Walkthrough

This guide shows how to run any GitHub project that ships a `Dockerfile` or
`docker-compose.yml` on the Raspberry Pi image preloaded with Docker and a
Cloudflare Tunnel. We'll walk through the generic steps and then apply them to
[token.place](https://github.com/futuroptimist/token.place) and
[dspace](https://github.com/democratizedspace/dspace) as real-world examples.

## 1. Prepare the Pi
1. Follow [pi_image_cloudflare.md](pi_image_cloudflare.md) to flash the SD card and
   start the Cloudflare Tunnel.
2. Confirm you can SSH to the Pi: `ssh pi@<hostname>.local`.

## 2. Clone a repository
1. Choose a location for projects, e.g. `/opt/projects`.
2. Clone one or more repositories:
   ```sh
   mkdir -p /opt/projects
   cd /opt/projects
   git clone https://github.com/futuroptimist/token.place.git
   git clone https://github.com/democratizedspace/dspace.git
   ```
   These commands pull `token.place` and `dspace` as examples; swap the URLs for
   any other repository that contains a `Dockerfile`.

## 3. Build or start containers
1. Change into the repo directory: `cd <repo>`.
2. If the repo provides `docker-compose.yml`:
   ```sh
   cp .env.example .env   # if the project uses an env file
   docker compose up -d   # build and start containers in the background
   ```
3. If the repo only has a `Dockerfile`:
   ```sh
   docker build -t myapp .
   docker run -d --name myapp -p 3000:3000 myapp
   ```
   Adjust port numbers and image names to match the project.

### Example: token.place
The `token.place` repo ships separate Dockerfiles for its services under the
`docker/` directory. To run the server container:

```sh
cd /opt/projects/token.place
docker build -t tokenplace-server -f docker/Dockerfile.server .
docker run -d --name tokenplace-server -p 5000:5000 tokenplace-server
```

### Example: dspace
The `dspace` repository's `frontend` folder contains a `Dockerfile` and
`docker-compose.yml`. Using Docker Compose starts the development server on
port 3002:

```sh
cd /opt/projects/dspace/frontend
docker compose up -d
```

## 4. Expose services through Cloudflare
1. Edit `/opt/sugarkube/docker-compose.cloudflared.yml` and add a new
   `ingress` rule mapping a subdomain to the container's port. For a
   `tokenplace-server` container on port 5000:

   ```yaml
   ingress:
     - hostname: tokenplace.example.com
       service: http://tokenplace-server:5000
   ```
2. Restart the tunnel:
   ```sh
   docker compose -f /opt/sugarkube/docker-compose.cloudflared.yml up -d
   ```
3. Visit the Cloudflare-managed URL to verify the service is reachable.

## 5. Manage containers
- List running containers: `docker ps`.
- Stop a container: `docker stop <container>`.
- View logs: `docker compose logs -f`.

Repeat these steps for each repository you want to deploy.
