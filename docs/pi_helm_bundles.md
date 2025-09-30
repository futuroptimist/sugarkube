---
personas:
  - software
---

# Sugarkube Helm Bundle Hooks

The base image now ships with `sugarkube-helm-bundles.service`, a post-boot helper that
applies pinned Helm releases as soon as `k3s-ready.target` succeeds. The goal is to keep
first boot deterministic: if a chart fails to install or never becomes healthy, the
service stops the boot flow and surfaces detailed logs under `/boot/first-boot-report/`
so you can fix the issue before moving on.

## How it works

1. `scripts/cloud-init/apply-helm-bundles.sh` installs with the image under
   `/opt/sugarkube/apply-helm-bundles.sh`.
2. Cloud-init creates `/etc/sugarkube/helm-bundles.d/` and populates a README describing
   the configuration keys.
3. `sugarkube-helm-bundles.service` depends on `k3s-ready.target`. When the target is
   started during provisioning, the service runs the helper once with elevated logging:
   - Each `*.env` file in `/etc/sugarkube/helm-bundles.d/` becomes a bundle definition.
   - The helper runs `helm upgrade --install --atomic` with optional values files and
     extra flags.
   - After a release installs, the helper waits for the configured rollout targets using
     `kubectl rollout status`.
   - Optional `HEALTHCHECK_CMD` entries run under `timeout` so expensive probes cannot
     hang the boot.
   - Success and failure logs land in `/var/log/sugarkube/helm-bundles.log` and, when the
     boot partition is available, under `/boot/first-boot-report/helm-bundles/`.
4. If any bundle fails, the service exits non-zero. Systemd immediately invokes
   `sugarkube-self-heal@.service`, giving you retries, journal captures, and an early
   escape to `rescue.target` when things remain broken.

## Authoring bundle definitions

Create one `*.env` file per release under `/etc/sugarkube/helm-bundles.d/`. Each file is a
POSIX shell fragment with simple key/value assignments. Required keys:

- `RELEASE` – Helm release name.
- `CHART` – Chart reference (`oci://`, repository/name, or local path).

Optional keys:

- `VERSION` – Pin a chart version. Defaults to Helm's latest.
- `NAMESPACE` – Target namespace (`default`).
- `VALUES_FILE` or `VALUES_FILES` – One or many values files. Separate multiple entries
  with commas.
- `EXTRA_HELM_ARGS` – Additional flags (e.g., `--set image.tag=v1 --wait`).
- `WAIT_TARGETS` – Comma-separated rollout resources. Each entry uses
  `deployment.apps/my-controller` or `namespace:statefulset.apps/cache` syntax.
- `WAIT_TIMEOUT` – Seconds to wait for each rollout (default: 300).
- `HEALTHCHECK_CMD` – Extra command run with `bash -o pipefail -c`.
- `HEALTHCHECK_TIMEOUT` – Seconds allotted to `HEALTHCHECK_CMD`.
- `NOTES` – Free-form text copied into the bundle report.

Example: `/etc/sugarkube/helm-bundles.d/metrics-server.env`

```env
RELEASE=metrics-server
CHART=oci://registry-1.docker.io/bitnamicharts/metrics-server
VERSION=7.2.6
NAMESPACE=kube-system
WAIT_TARGETS=deployment.apps/metrics-server
EXTRA_HELM_ARGS="--set apiService.create=true"
NOTES="Expose Kubernetes resource metrics on first boot"
```

Place supporting values files under `/opt/sugarkube/helm-values/` (cloud-init creates the
directory) or adjust `VALUES_FILE` to point elsewhere.

## Observing results

- Run `sudo systemctl status sugarkube-helm-bundles.service` to inspect the last run.
- Review `/var/log/sugarkube/helm-bundles.log` for a host-wide timeline.
- Review `/boot/first-boot-report/helm-bundles/*.log` and matching `.failed/.status`
  markers to understand per-release success or failure without SSH.

When a release fails, the boot process halts early via `sugarkube-self-heal@.service`. Use
the generated logs to fix the chart (values, versions, dependencies), rerun the helper
manually with `sudo /opt/sugarkube/apply-helm-bundles.sh`, and reboot once the bundles
succeed.
