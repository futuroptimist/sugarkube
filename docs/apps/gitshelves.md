# GitShelves on Sugarkube

This is the canonical runbook for GitShelves, a static, browser-only, local-first application. Sugarkube serves static files; user shelf data remains in browser storage and is not sent to a Kubernetes backend.

## Ownership and coordinates

- The [GitShelves repository](https://github.com/futuroptimist/gitshelves) owns application source, image builds, immutable image tags, the Dockerfile, chart source, and chart publication.
- Sugarkube owns the generic app configuration, environment overlays, artifact pins, Helm desired state, rollout verification, and staging Probe definitions.
- Cloudflare owns DNS and Tunnel routing. Those external resources are not managed by Helm or by this change.

| Coordinate | Value |
| --- | --- |
| Image | `ghcr.io/futuroptimist/gitshelves` |
| Chart | `oci://ghcr.io/futuroptimist/charts/gitshelves` |
| Release / namespace | `gitshelves` / `gitshelves` |
| App config | `docs/examples/apps/gitshelves.env` |
| Chart version pin | `docs/apps/gitshelves.version` (`0.1.0`) |
| Production tag pin | `docs/apps/gitshelves.prod.tag` (intentionally empty) |
| Container port | `8080` |
| Verify paths | `/`, `/healthz`, `/livez` |
| Staging / future production | `staging.gitshelves.com` / `gitshelves.com` |

### Artifact links

| Artifact | Link |
| --- | --- |
| App repository | [GitShelves app repository](https://github.com/futuroptimist/gitshelves) |
| Image workflow | [Recent image workflow runs](https://github.com/futuroptimist/gitshelves/actions/workflows/ci-image.yml) |
| Successful main images | [Successful main image workflow runs](https://github.com/futuroptimist/gitshelves/actions/workflows/ci-image.yml?query=branch%3Amain+is%3Asuccess) |
| GHCR image package | [GHCR image package](https://github.com/futuroptimist/gitshelves/pkgs/container/gitshelves) |
| Chart workflow | [Recent chart workflow runs](https://github.com/futuroptimist/gitshelves/actions/workflows/ci-helm.yml) |
| GHCR chart package | [GHCR chart package](https://github.com/futuroptimist/gitshelves/pkgs/container/charts%2Fgitshelves) |
| Dockerfile | [Application Dockerfile](https://github.com/futuroptimist/gitshelves/blob/main/Dockerfile) |
| Chart source path | [Helm chart source](https://github.com/futuroptimist/gitshelves/tree/main/charts/gitshelves) |
| Release guide | [GitShelves release documentation](https://github.com/futuroptimist/gitshelves/tree/main/docs) |

Web UI shortcuts: use the image workflow, GHCR image package, chart workflow, and GHCR chart package above to confirm immutable artifacts.

## Verified preflight and data model

Operator evidence ties merge commit `2125943cca1c3369f0b49bf11ec6ef3f26da5b42` to candidate `main-2125943cca1c`. Its AMD64 digest is `sha256:60669ca6ab1b0d4a9db965624361f74e6bc8339c90731450d8af3dd9eed0f731`; its ARM64 digest is `sha256:23970f301e2798ebd3195381bde1b5f1acf0e06d47bcd99e73a6eb2f9eb89b43`. Ready staging nodes `sugarkube3`, `sugarkube4`, and `sugarkube5` are ARM64. Chart `0.1.0` was verified at digest `sha256:ebeeff198bce16896c70786f11f6814a28841077b93c98047c2e1e30be66e703`.

The application is static and local-first. It needs no Kubernetes Secret, GitHub credentials, database, queue, PVC, backend configuration, or ServiceMonitor. It does not expose `/metrics`; public blackbox checks cover its service contract. Never place private browser data in images, values, or cluster resources.

Only branch-SHA tags ending in a 7–40 character lowercase Git SHA are deployment coordinates. Reject `latest`, `main`, environment names, and other moving tags.

## Initial staging rollout

The Cloudflare Tunnel route is external to Helm and must eventually route hostname `staging.gitshelves.com` to service `http://traefik.kube-system.svc.cluster.local:80`. Do not create it from this repository task.

Run this exact sequence only after the operator establishes that route:

```bash
just app-config app=gitshelves env=staging
just app-chart-status app=gitshelves
just app-deploy app=gitshelves env=staging tag=main-2125943cca1c
just app-status app=gitshelves env=staging
just app-verify app=gitshelves env=staging
```

Preview public verification without network calls:

```bash
just app-verify app=gitshelves env=staging print_only=1
```

Apply and verify staging blackbox Probes only after both the workload and Cloudflare route exist, using the repository's existing blackbox lifecycle commands documented in `docs/observability-blackbox.md`.

## Troubleshooting and evidence

All cluster diagnostics explicitly pin staging:

```bash
kubectl --context sugar-staging get deployment gitshelves -n gitshelves -o wide
kubectl --context sugar-staging get pods -n gitshelves -l app.kubernetes.io/name=gitshelves -o wide
kubectl --context sugar-staging describe pods -n gitshelves -l app.kubernetes.io/name=gitshelves
kubectl --context sugar-staging get service,endpoints -n gitshelves
kubectl --context sugar-staging get ingress -n gitshelves gitshelves -o wide
kubectl --context sugar-staging describe ingress -n gitshelves gitshelves
kubectl --context sugar-staging get certificate,order,challenge -n gitshelves
kubectl --context sugar-staging describe certificate -n gitshelves gitshelves-staging-tls
kubectl --context sugar-staging logs -n kube-system -l app.kubernetes.io/name=traefik --tail=200
kubectl --context sugar-staging logs -n cert-manager deploy/cert-manager --tail=200
```

```bash
helm --kube-context sugar-staging -n gitshelves status gitshelves
helm --kube-context sugar-staging -n gitshelves get values gitshelves
kubectl --context sugar-staging get deployment gitshelves -n gitshelves -o jsonpath='{.spec.template.spec.containers[*].image}{"\n"}'
```

Capture public health and asset evidence:

```bash
curl -fsS https://staging.gitshelves.com/
curl -fsS https://staging.gitshelves.com/healthz
curl -fsS https://staging.gitshelves.com/livez
curl -fSLo /tmp/baseplate_2x6.stl https://staging.gitshelves.com/models/baseplate_2x6.stl
curl -fSLo /tmp/contrib_cube.stl https://staging.gitshelves.com/models/contrib_cube.stl
```

## Promotion and rollback

Production remains blocked. Keep `docs/apps/gitshelves.prod.tag` empty until public staging verification is captured and an operator explicitly approves the exact candidate. A later approved promotion uses `just app-promote-prod app=gitshelves tag=<APPROVED_IMMUTABLE_TAG>`; this PR does not run it.

Rollback normally by redeploying the previous immutable tag:

```bash
just app-redeploy app=gitshelves env=staging tag=main-REPLACE_PREVIOUS_SHORTSHA
just app-status app=gitshelves env=staging
just app-verify app=gitshelves env=staging
```

As an emergency alternative after identifying a known-good revision, use `helm --kube-context sugar-staging -n gitshelves rollback gitshelves <REVISION>` and repeat status and verification. Record the deployed image, Helm revision, public checks, and rollback evidence.
