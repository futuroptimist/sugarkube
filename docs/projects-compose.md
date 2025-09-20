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
