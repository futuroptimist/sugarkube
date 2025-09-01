# Codex — Observability bootstrap for sugarkube

You are contributing to the `futuroptimist/sugarkube` repository.
Goal: add a minimal, reproducible observability stack and a
"sugarkube — Overview" Grafana dashboard. Do all changes as small commits with
descriptive messages. Keep idempotent.

## Tasks
1) Create these files (overwriting if they exist):
   - platform/observability/values/kube-prometheus-stack.yaml
   - platform/observability/values/loki.yaml
   - platform/observability/values/promtail.yaml
   - platform/observability/values/blackbox-exporter.yaml
   - platform/observability/grafana/datasource.yaml (ConfigMap)
   - platform/observability/grafana/sugarkube-overview.configmap.yaml
   - platform/observability/manifests/blackbox-probes.yaml
   - platform/observability/manifests/cloudflared.yaml
   - platform/observability/manifests/github-exporter.yaml (present but optional)

2) Keep the endpoints and repo list current using the user's GitHub profile README
   `https://github.com/futuroptimist` → section "Related Projects".
   Parse it and update:
     - the "Repos" variable in the dashboard JSON
     - REPOS_JSON env in github-exporter manifest

3) Safety & security:
   - Keep Grafana anonymous auth OFF by default; it will sit behind Cloudflare
     Tunnel.
   - Never commit real tokens. Secrets in manifests must be placeholders.
   - Do not expose Prometheus or Loki outside the cluster.

4) Acceptance checks:
   - `yamllint` passes.
   - `kubectl kustomize` or `kubectl apply --dry-run=client` validates in CI.
   - Dashboard JSON loads in Grafana (well-formed JSON, panel queries compile).

5) README patch:
   - Add a short section under docs that shows the helm install commands and how
     to set the Cloudflare hostname (dashboard.example.com → user's domain).
