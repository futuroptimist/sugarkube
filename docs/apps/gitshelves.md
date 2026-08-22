# GitShelves on Sugarkube

This is the canonical runbook for GitShelves. GitShelves is a static, browser-only, local-first application: Kubernetes serves files, while user data remains in browser storage.

## Ownership and artifact model

- The [GitShelves repository](https://github.com/futuroptimist/gitshelves) owns the application, Docker image, immutable image tags, Helm chart, and immutable chart releases.
- Sugarkube owns the environment overlays, artifact pins, generic Helm operations, rollout checks, and staging observability definitions.
- Cloudflare owns DNS and Tunnel hostname routes outside Helm. This PR neither creates nor changes those routes.

| Coordinate | Value |
| --- | --- |
| Image | `ghcr.io/futuroptimist/gitshelves` |
| Chart | `oci://ghcr.io/futuroptimist/charts/gitshelves` |
| Release / namespace | `gitshelves` / `gitshelves` |
| App config | `docs/examples/apps/gitshelves.env` |
| Chart version pin | `docs/apps/gitshelves.version` (`0.1.0`) |
| Production tag pin | `docs/apps/gitshelves.prod.tag` (intentionally empty) |
| Values | `docs/examples/gitshelves.values.dev.yaml` plus the selected environment overlay |
| Container port | `8080` |
| Verify paths | `/`, `/healthz`, `/livez` |
| Staging / future production host | `staging.gitshelves.com` / `gitshelves.com` |

### Artifact links

| Artifact | Link |
| --- | --- |
| App repository | [GitShelves app repository](https://github.com/futuroptimist/gitshelves) |
| Image workflow | [Recent image workflow runs](https://github.com/futuroptimist/gitshelves/actions/workflows/ci-image.yml) |
| Successful main images | [Successful main workflow runs](https://github.com/futuroptimist/gitshelves/actions/workflows/ci-image.yml?query=branch%3Amain+is%3Asuccess) |
| GHCR image package | [GHCR image package](https://github.com/futuroptimist/gitshelves/pkgs/container/gitshelves) |
| Chart workflow | [Recent chart workflow runs](https://github.com/futuroptimist/gitshelves/actions/workflows/ci-helm.yml) |
| GHCR chart package | [GHCR chart package](https://github.com/futuroptimist/gitshelves/pkgs/container/charts%2Fgitshelves) |
| Dockerfile | [Application Dockerfile](https://github.com/futuroptimist/gitshelves/blob/main/Dockerfile) |
| Chart source path | [Helm chart source](https://github.com/futuroptimist/gitshelves/tree/main/charts/gitshelves) |
| Image and Helm release guide | [Release documentation](https://github.com/futuroptimist/gitshelves/blob/main/docs/releasing.md) |
| Release guide | [Application release documentation](https://github.com/futuroptimist/gitshelves/tree/main/docs) |

Web UI shortcuts: use the image workflow and GHCR image package above to find an immutable build, and the chart workflow and GHCR chart package to confirm its chart.

## Verified preflight evidence

An operator verified merge commit `2125943cca1c3369f0b49bf11ec6ef3f26da5b42` and image tag `main-2125943cca1c`. Its AMD64 manifest digest is `sha256:60669ca6ab1b0d4a9db965624361f74e6bc8339c90731450d8af3dd9eed0f731`; its ARM64 digest is `sha256:23970f301e2798ebd3195381bde1b5f1acf0e06d47bcd99e73a6eb2f9eb89b43`. The published chart is version `0.1.0`, digest `sha256:ebeeff198bce16896c70786f11f6814a28841077b93c98047c2e1e30be66e703`. Ready staging nodes `sugarkube3`, `sugarkube4`, and `sugarkube5` are ARM64.

Chart `0.1.0` consumes `replicaCount`, `image`, `service`, `ingress`, and `resources`; the overlays intentionally configure no unsupported keys. GitShelves has no server-side data, secrets, database, queue, PVC, backend API, or GitHub credentials. It exposes no `/metrics`, so no ServiceMonitor is required. Core STL downloads are `/models/baseplate_2x6.stl` and `/models/contrib_cube.stl`.

## Immutable release policy

Only lowercase branch-SHA tags such as `main-2125943cca1c` may be deployed. Reject moving or semantic aliases including `latest`, `main`, `main-latest`, `staging`, `production`, and `v1.2.3`. The chart version is pinned independently. Production remains blocked: do not put the staging candidate in the production pin until public staging verification and explicit approval are complete.

## Initial staging deployment

The Cloudflare Tunnel route must eventually route hostname `staging.gitshelves.com` to service `http://traefik.kube-system.svc.cluster.local:80`. That route is external to Helm and must not be created by this repository-only change.

Run this exact sequence only after that external route is ready:

```bash
just app-config app=gitshelves env=staging
just app-chart-status app=gitshelves
just app-deploy app=gitshelves env=staging tag=main-2125943cca1c
just app-status app=gitshelves env=staging
just app-verify app=gitshelves env=staging
```

Preview public requests without making them:

```bash
just app-verify app=gitshelves env=staging print_only=1
```

Apply and verify the staging Probe resources only after both the workload and Cloudflare route exist, using the existing observability lifecycle commands documented in [`docs/observability-blackbox.md`](../observability-blackbox.md). This PR must not apply them.

## Staging troubleshooting and evidence

All cluster reads below pin the staging context explicitly.

```bash
kubectl --context sugar-staging get deployment -n gitshelves gitshelves -o wide
kubectl --context sugar-staging describe deployment -n gitshelves gitshelves
kubectl --context sugar-staging get pods -n gitshelves -l app.kubernetes.io/name=gitshelves -o wide
kubectl --context sugar-staging describe pods -n gitshelves -l app.kubernetes.io/name=gitshelves
kubectl --context sugar-staging get service,endpoints -n gitshelves
kubectl --context sugar-staging get ingress -n gitshelves gitshelves -o wide
kubectl --context sugar-staging describe ingress -n gitshelves gitshelves
```

```bash
kubectl --context sugar-staging get certificate,order,challenge -n gitshelves
kubectl --context sugar-staging describe certificate -n gitshelves gitshelves-staging-tls
kubectl --context sugar-staging logs -n kube-system -l app.kubernetes.io/name=traefik --tail=200
kubectl --context sugar-staging logs -n cert-manager deploy/cert-manager --tail=200
```

```bash
helm show chart oci://ghcr.io/futuroptimist/charts/gitshelves --version 0.1.0
helm --kube-context sugar-staging -n gitshelves status gitshelves
helm --kube-context sugar-staging -n gitshelves get values gitshelves
kubectl --context sugar-staging get deployment -n gitshelves gitshelves -o jsonpath='{.spec.template.spec.containers[*].image}{"\n"}'
```

```bash
curl -fsS https://staging.gitshelves.com/
curl -fsS https://staging.gitshelves.com/healthz
curl -fsS https://staging.gitshelves.com/livez
curl -fSLo /dev/null https://staging.gitshelves.com/models/baseplate_2x6.stl
curl -fSLo /dev/null https://staging.gitshelves.com/models/contrib_cube.stl
```

Capture the deployed image, Helm revision, rollout, Ingress, certificate, public-path results, and a previous known-good tag as release and rollback evidence.

## Promotion and rollback

Production promotion remains blocked and `docs/apps/gitshelves.prod.tag` must stay empty. After staging approval, a separate reviewed change may record the exact staging-tested immutable tag and run the generic production promotion; until then, leave `gitshelves.com` untouched.

Prefer rollback by redeploying the previous immutable tag:

```bash
just app-redeploy app=gitshelves env=staging tag=main-REPLACE_PREVIOUS_SHORTSHA
just app-status app=gitshelves env=staging
just app-verify app=gitshelves env=staging
```

If restoring the entire prior rendered release state is deliberately required, Helm revision rollback is the emergency alternative:

```bash
helm --kube-context sugar-staging -n gitshelves history gitshelves
helm --kube-context sugar-staging -n gitshelves rollback gitshelves <REVISION>
```
