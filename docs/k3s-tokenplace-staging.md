# k3s token.place runbook (staging)

Use this runbook for relay-only token.place staging deployments on Sugarkube.

## Topology and scope

- Sugarkube runs only token.place relay (`relay.py`).
- No in-cluster backend/GPU service is required.
- Compute nodes remain external (`server.py`, Tauri desktop app, Windows PCs, Apple Silicon Macs,
  Raspberry Pi compute nodes, etc.).
- Runtime model is single replica + single Gunicorn worker + in-memory state; verify the rendered Kubernetes Deployment contract includes `spec.strategy.type: Recreate` before rollout.
- In-memory state loss on pod restart is accepted for now.

## Artifact and values contract

- Chart: `oci://ghcr.io/futuroptimist/charts/tokenplace`
- Image: `ghcr.io/futuroptimist/tokenplace-relay`
- Release: `tokenplace`
- Namespace: `tokenplace`
- Version pin file: `docs/apps/tokenplace.version`
- Values: `docs/examples/tokenplace.values.dev.yaml` + `docs/examples/tokenplace.values.staging.yaml`
- Default staging host: `staging.token.place`


## Pre-flight (before Step 1)

- Verify `docs/apps/tokenplace.version` remains pinned to `0.1.0`.
- Verify the `0.1.0` OCI chart exists only after token.place publishes the current chart.
- If `helm show chart ... --version 0.1.0` succeeds before the final token.place chart publish, confirm the chart is not stale before deploying.

```bash
helm show chart oci://ghcr.io/futuroptimist/charts/tokenplace --version 0.1.0
```

## First install

```bash
just kubeconfig-env staging
TOKENPLACE_TAG=main-deadbee # replace with the immutable tag you want to deploy
just helm-oci-install release=tokenplace namespace=tokenplace chart=oci://ghcr.io/futuroptimist/charts/tokenplace values=docs/examples/tokenplace.values.dev.yaml,docs/examples/tokenplace.values.staging.yaml version_file=docs/apps/tokenplace.version default_tag="$TOKENPLACE_TAG"
```

## Existing release upgrade

```bash
just kubeconfig-env staging
TOKENPLACE_TAG=main-deadbee # replace with the immutable tag you want to deploy
just helm-oci-upgrade release=tokenplace namespace=tokenplace chart=oci://ghcr.io/futuroptimist/charts/tokenplace values=docs/examples/tokenplace.values.dev.yaml,docs/examples/tokenplace.values.staging.yaml version_file=docs/apps/tokenplace.version default_tag="$TOKENPLACE_TAG"
```

Preferred wrapper:

```bash
TOKENPLACE_TAG=main-deadbee # replace with the immutable tag you want to deploy
just tokenplace-oci-deploy env=staging tag="$TOKENPLACE_TAG"
```

## Validation

Render/contract checks (use immutable staging candidate tag):

```bash
helm show chart oci://ghcr.io/futuroptimist/charts/tokenplace --version 0.1.0
helm template tokenplace oci://ghcr.io/futuroptimist/charts/tokenplace --version 0.1.0 --namespace tokenplace -f docs/examples/tokenplace.values.dev.yaml -f docs/examples/tokenplace.values.staging.yaml --set image.tag=main-deadbee > /tmp/tokenplace-staging-render.yaml
grep -n "spec:" -A40 /tmp/tokenplace-staging-render.yaml | grep -n "tls"
grep -n "staging.token.place" /tmp/tokenplace-staging-render.yaml
grep -n "tokenplace-staging-tls" /tmp/tokenplace-staging-render.yaml
yq eval '. | select(.kind == "Deployment" and .metadata.name == "tokenplace") | .spec.strategy.type' /tmp/tokenplace-staging-render.yaml
python3 - <<'PY'
import collections
import sys

render_path = "/tmp/tokenplace-staging-render.yaml"
env_names = []
in_deployment = False
in_first_container = False
in_env = False
for raw_line in open(render_path, encoding="utf-8"):
    line = raw_line.rstrip("\n")
    stripped = line.strip()
    if stripped.startswith("---"):
        in_deployment = False
        in_first_container = False
        in_env = False
        continue
    if stripped == "kind: Deployment":
        in_deployment = True
        continue
    if not in_deployment:
        continue
    if stripped == "containers:":
        in_first_container = True
        continue
    if in_first_container and stripped == "env:":
        in_env = True
        continue
    if in_env and stripped.startswith("- name: "):
        env_names.append(stripped.split(": ", 1)[1])
        continue
    if in_env and stripped and not stripped.startswith("-") and not stripped.startswith("name:"):
        in_env = False

dupes = [name for name, count in collections.Counter(env_names).items() if count > 1]
if dupes:
    sys.exit(f"duplicate env names found: {dupes}")
print("no duplicate env names")
PY
```

Cluster/runtime checks:

```bash
kubectl -n tokenplace get deploy,po,svc,ingress
kubectl -n tokenplace rollout status deploy/tokenplace --timeout=180s
kubectl -n tokenplace get ingress tokenplace -o yaml
curl -vI https://staging.token.place/
curl -fsS https://staging.token.place/livez
curl -fsS https://staging.token.place/healthz
```

## Staging override cleanup note

During initial staging validation we used manual Helm `--set` overrides for XDG runtime paths under a read-only root filesystem.
Now that chart defaults own those paths, remove any manual XDG `--set` overrides from local scripts/shell history and deploy with only the checked-in values overlays.

## Rollback

Rollback by immutable tag:

```bash
just kubeconfig-env staging
TOKENPLACE_PREVIOUS_TAG=main-deadbee # replace with the prior immutable tag
just helm-oci-upgrade release=tokenplace namespace=tokenplace chart=oci://ghcr.io/futuroptimist/charts/tokenplace values=docs/examples/tokenplace.values.dev.yaml,docs/examples/tokenplace.values.staging.yaml version_file=docs/apps/tokenplace.version default_tag="$TOKENPLACE_PREVIOUS_TAG"
```

Rollback by Helm revision:

```bash
just kubeconfig-env staging
TOKENPLACE_REVISION=12 # replace with the known-good Helm revision
just tokenplace-rollback release=tokenplace namespace=tokenplace revision="$TOKENPLACE_REVISION"
```

## Cloudflare tunnel routing (external to Helm)

Cloudflare Tunnel still owns public hostname routing to Traefik; Helm does not manage Cloudflare routes. Route `staging.token.place` to Traefik,
typically `http://traefik.kube-system.svc.cluster.local:80`. Staging overlays render Ingress `spec.tls` because `ingress.tls.enabled: true`; `secretName` alone is not sufficient,
and this runbook assumes `cert-manager` and the referenced `ClusterIssuer` already exist.

```bash
just cf-tunnel-route host=staging.token.place
```


## 0.1.0 release alignment

- OCI chart package version: `0.1.0`
- Chart `appVersion`: `0.1.0`
- token.place Git tag: `v0.1.0`
- Release image tag after final tag push: `ghcr.io/futuroptimist/tokenplace-relay:v0.1.0`
- Staging candidate tag before final tag push: `main-<shortsha>`
