# GitShelves on Sugarkube

This is the canonical runbook for serving GitShelves from app-owned GHCR artifacts. GitShelves is a static, browser-only, local-first application. User data stays in browser storage; Kubernetes serves static files and does not hold application records.

## Ownership and coordinates

- The GitShelves repository builds and publishes immutable images and versioned Helm charts, and owns application behavior.
- Sugarkube owns environment overlays, immutable deployment selection, Helm release operations, and verification.
- Cloudflare owns DNS and Tunnel routing. Those resources are external to Helm and are not changed by this repository.

| Coordinate | Value |
| --- | --- |
| Image | `ghcr.io/futuroptimist/gitshelves` |
| Chart | `oci://ghcr.io/futuroptimist/charts/gitshelves` |
| Release / namespace | `gitshelves` / `gitshelves` |
| App config | `docs/examples/apps/gitshelves.env` |
| Values | `docs/examples/gitshelves.values.{dev,staging,prod}.yaml` |
| Chart / production pins | `docs/apps/gitshelves.version` / `docs/apps/gitshelves.prod.tag` |
| Container port | `8080` |
| Verify paths | `/`, `/healthz`, `/livez` |
| Staging / future production host | `staging.gitshelves.com` / `gitshelves.com` |

### Artifact links

| Artifact | Link |
| --- | --- |
| App repository | [GitShelves app repository](https://github.com/futuroptimist/gitshelves) |
| Image workflow | [Recent image workflow runs](https://github.com/futuroptimist/gitshelves/actions/workflows/ci-image.yml) |
| Successful main images | [Successful main image runs](https://github.com/futuroptimist/gitshelves/actions/workflows/ci-image.yml?query=branch%3Amain+is%3Asuccess) |
| GHCR image package | [GHCR image package versions](https://github.com/futuroptimist/gitshelves/pkgs/container/gitshelves) |
| Chart workflow | [Recent chart workflow runs](https://github.com/futuroptimist/gitshelves/actions/workflows/ci-helm.yml) |
| GHCR chart package | [GHCR chart package versions](https://github.com/futuroptimist/gitshelves/pkgs/container/charts%2Fgitshelves) |
| Dockerfile | [Application Dockerfile](https://github.com/futuroptimist/gitshelves/blob/main/Dockerfile) |
| Chart source path | [Helm chart source](https://github.com/futuroptimist/gitshelves/tree/main/charts/gitshelves) |
| Release guide | [GitShelves release documentation](https://github.com/futuroptimist/gitshelves/tree/main/docs) |

Web UI shortcuts: use the image workflow and GHCR image package above to find an immutable tag; use the chart workflow and GHCR chart package to confirm a chart version.

## Verified artifact preflight

Operator preflight tied candidate `main-2125943cca1c` to merge commit `2125943cca1c3369f0b49bf11ec6ef3f26da5b42`. The published image resolved to AMD64 digest `sha256:60669ca6ab1b0d4a9db965624361f74e6bc8339c90731450d8af3dd9eed0f731` and ARM64 digest `sha256:23970f301e2798ebd3195381bde1b5f1acf0e06d47bcd99e73a6eb2f9eb89b43`. Ready nodes `sugarkube3`, `sugarkube4`, and `sugarkube5` are ARM64. Chart `0.1.0` resolved to `sha256:ebeeff198bce16896c70786f11f6814a28841077b93c98047c2e1e30be66e703`; its values and templates consume only replica count, image, ClusterIP service, ingress, and resources as represented by the overlays.

Tags for staging and production must be lowercase immutable branch-SHA tags. Reject `latest`, `main`, `main-latest`, environment names, and other moving aliases. Production's pin intentionally has no active tag: promotion remains blocked until public staging verification and explicit approval. No Secret, database, queue, PVC, backend API, GitHub credential, or ServiceMonitor is required. In particular, the static application has no `/metrics` endpoint.

## Initial staging rollout

The Cloudflare Tunnel must eventually route hostname `staging.gitshelves.com` to service `http://traefik.kube-system.svc.cluster.local:80`. Configure that outside Helm; **do not create the route in this repository task**. After the workload and route exist, operators may apply and verify the staging Probe lifecycle using the existing observability commands. Applying Probes before then would create expected failures.

```bash
just app-config app=gitshelves env=staging
just app-chart-status app=gitshelves
just app-deploy app=gitshelves env=staging tag=main-2125943cca1c
just app-status app=gitshelves env=staging
just app-verify app=gitshelves env=staging
```

Preview verification without network or cluster mutation:

```bash
just app-verify app=gitshelves env=staging print_only=1
```

## Troubleshooting and evidence

Use the staging context explicitly and retain the deployed image, Helm revision, and command output as rollout evidence.

```bash
kubectl --context sugar-staging get deployment,pods -n gitshelves -l app.kubernetes.io/name=gitshelves -o wide
kubectl --context sugar-staging describe deployment -n gitshelves gitshelves
kubectl --context sugar-staging get service,endpoints -n gitshelves gitshelves -o wide
kubectl --context sugar-staging get ingress -n gitshelves gitshelves -o wide
kubectl --context sugar-staging describe ingress -n gitshelves gitshelves
kubectl --context sugar-staging get certificate,order,challenge -n gitshelves
kubectl --context sugar-staging describe certificate -n gitshelves gitshelves-staging-tls
kubectl --context sugar-staging logs -n kube-system -l app.kubernetes.io/name=traefik --tail=200
kubectl --context sugar-staging logs -n cert-manager deploy/cert-manager --tail=200
helm --kube-context sugar-staging status gitshelves --namespace gitshelves
helm --kube-context sugar-staging get values gitshelves --namespace gitshelves
kubectl --context sugar-staging get deployment gitshelves -n gitshelves -o jsonpath='{.spec.template.spec.containers[*].image}{"\n"}'
```

Verify public health and both core downloads only after the Cloudflare route and certificate exist:

```bash
curl -fsS https://staging.gitshelves.com/
curl -fsS https://staging.gitshelves.com/healthz
curl -fsS https://staging.gitshelves.com/livez
curl -fSLo /tmp/baseplate_2x6.stl https://staging.gitshelves.com/models/baseplate_2x6.stl
curl -fSLo /tmp/contrib_cube.stl https://staging.gitshelves.com/models/contrib_cube.stl
test -s /tmp/baseplate_2x6.stl && test -s /tmp/contrib_cube.stl
```

## Promotion and rollback

Do not promote as part of onboarding. Once staging is publicly verified and approved, record the exact approved immutable tag in `docs/apps/gitshelves.prod.tag` through a separate reviewed change, then use `just app-promote-prod` according to the generic contract.

Rollback normally means redeploying the previous known-good immutable tag, followed by status and verification:

```bash
just app-redeploy app=gitshelves env=staging tag=main-REPLACE_PREVIOUS_SHORTSHA
just app-status app=gitshelves env=staging
just app-verify app=gitshelves env=staging
```

As an emergency alternative when an exact prior Helm revision is the reviewed recovery coordinate:

```bash
helm --kube-context sugar-staging history gitshelves --namespace gitshelves
helm --kube-context sugar-staging rollback gitshelves <REVISION> --namespace gitshelves --wait
```
