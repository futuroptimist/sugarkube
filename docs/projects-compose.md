# projects-compose Service

The prebuilt Pi image includes Docker Engine, the Compose plugin and a
systemd unit called `projects-compose.service`. On first boot the unit builds
and starts [token.place](https://github.com/futuroptimist/token.place) and
[dspace](https://github.com/democratizedspace/dspace) from the shared
`/opt/projects/docker-compose.yml` file.

## Wait for k3s before chaining workloads

Downstream services can now depend on `k3s-ready.target`, a systemd target that
requires both `projects-compose.service` and a successful `kubectl wait` for the
cluster's nodes. The `k3s-ready.service` helper polls until `kubectl get nodes`
returns `Ready`, then marks the target `active (reached)`. Hook additional
units into the boot flow by declaring `After=k3s-ready.target` or `Requires=` to
ensure workloads start only after the cluster and compose stack stabilize.

Inspect the current state with:

```sh
sudo systemctl status k3s-ready.target
```

## Environment files

Each project reads an `.env` file from its directory. `init-env.sh` seeds these
files so containers start with sensible defaults:

| Service | `.env` location | Default |
| --- | --- | --- |
| token.place | `/opt/projects/token.place/.env` | `PORT=5000` |
| dspace | `/opt/projects/dspace/frontend/.env` | `PORT=3000` |
| grafana-agent | `/opt/projects/observability/grafana-agent.env` | 30-second scrape interval |
| netdata | `/opt/projects/observability/netdata.env` | Port 19999, unclaimed |

Edit the files to add variables described in each project's README, such as API
keys or upstream URLs.

## Extend the stack

Grow the compose stack with additional repositories:

1. Clone the repository into `/opt/projects` (set `EXTRA_REPOS` when building
   the image or clone after boot).
2. Add a service definition to `/opt/projects/docker-compose.yml` between
   `# extra-start` and `# extra-end`.
3. Append an `ensure_env <repo>/.env` line under the matching marker in
   `/opt/projects/init-env.sh`.
4. Restart the unit:
   ```sh
   sudo systemctl restart projects-compose.service
   ```

These hooks keep the Pi image ready for new services without editing existing
entries.

## Built-in observability exporters

The compose file now ships a small observability stack so fresh nodes expose
metrics and live dashboards without any manual wiring:

- `prom/node-exporter` on **port 9100** surfaces kernel, CPU, memory, and disk
  metrics from the host namespace.
- `gcr.io/cadvisor/cadvisor` on **port 8080** exports container and cgroup
  statistics for the compose workloads.
- `grafana/agent` listens on **port 12345** and fan-outs both exporters into a
  single `/metrics` endpoint. Operators can point an existing Prometheus server
  at `http://<pi-host>:12345/metrics` or extend the Flow config at
  `/opt/projects/observability/grafana-agent.river` to add remote_write targets
  and extra scrapes.
- `netdata/netdata` serves a self-hosted dashboard on **port 19999**. Claim the
  node with `NETDATA_CLAIM_TOKEN`/`NETDATA_CLAIM_ROOMS` to publish to Netdata
  Cloud, or leave the values blank to run locally.

`init-env.sh` copies the `.env.example` files into `.env` so you can update
scrape intervals, override ports, or insert credentials without editing tracked
files. Restart the stack after changes:

```sh
sudo systemctl restart projects-compose.service
```

## Self-healing retries

`projects-compose.service` now declares an `OnFailure` hook that starts
`sugarkube-self-heal@projects-compose.service`. The helper reruns `docker compose`
pulls, restarts the unit, and captures logs in `/boot/first-boot-report/self-heal/`.
After three failed attempts the Pi isolates into `rescue.target` so you can
review the Markdown summary and fix credentials or network issues before trying
again.
