---
title: 'Sugarkube Codex Observability Prompt'
slug: 'prompts-codex-observability'
---

# Codex — Observability Bootstrap

Use this prompt to scaffold a minimal observability stack and dashboard for the
sugarkube platform.

```text
SYSTEM:
You are building the “Sugarkube Dashboard” capability for a k3s-based platform.
Produce production-grade code, manifests, Helm values, and docs.
Optimize for simplicity, reproducibility, and security by default.
Achieve **100% patch coverage on the first test run**—design code and tests so no reruns are
required.

GOAL:
Create a complete, minimal, and extensible observability + kiosk solution:
- Observability runs in k3s.
- A Raspberry Pi acts only as a kiosk.
- Grafana is exposed via Cloudflare Tunnel (Zero Trust optional).
- Dashboards show health of k8s, Cloudflare tunnels, HTTP uptime/TLS, and
  GitHub repo signals for the `futuroptimist` org/user.

INPUTS (parameterize; do not hard-code):
- K8S context name: {{K8S_CONTEXT}}
- Domain: {{BASE_DOMAIN}}
- Grafana subdomain: {{GRAFANA_SUBDOMAIN}}
- Cloudflare Tunnel credentials: {{CF_TUNNEL_TOKEN}} or {{CF_TUNNEL_ID}},
  {{CF_ACCOUNT_ID}}, {{CF_TUNNEL_SECRET}}
- GitHub token (read-only public_repo): {{GITHUB_TOKEN}}
- List of project repos (owner/name): {{REPOS_JSON}}
- Optional: enable_anonymous_grafana_view: {{BOOL}}

DELIVERABLES (file tree):
- `platform/observability/README.md` – how to deploy, upgrade, and troubleshoot.
- `platform/observability/helmfile.yaml` – declares charts and versions.
- `platform/observability/values/kube-prometheus-stack.yaml`
- `platform/observability/values/loki.yaml`
- `platform/observability/values/promtail.yaml`
- `platform/observability/values/blackbox-exporter.yaml`
- `platform/observability/manifests/cloudflared-deployment.yaml` + `config.yaml`
  (ingress to Grafana Service).
- `platform/observability/grafana/provisioning/datasources/datasources.yaml`
  – references in-cluster Prometheus, Loki, (optional Tempo).
- `platform/observability/grafana/dashboards/sugarkube-overview.json` – main
  dashboard.
- `platform/observability/exporters/github/` – tiny service that queries GitHub
  API for repo stars, issues, and last workflow run per repo and exposes
  Prometheus metrics. Include Dockerfile, k8s Deployment/Service, and a scrape
  config.
- `platform/observability/scrape/static/targets.yaml` – optional static scrape
  targets for non-k8s hosts (node_exporter on Pis/NUCs).
- `platform/kiosk/` – Raspberry Pi instructions and systemd units
  (`kiosk.service`, `kiosk-session`), plus an Ansible playbook `kiosk.yml` to
  configure a fresh Pi.
- `platform/security/` – example Grafana org/role provisioning and Zero Trust
  notes.
- `Makefile` – phony targets: `bootstrap-obs`, `upgrade-obs`, `deploy-tunnel`,
  `apply-dashboards`, `kiosk-install`, `kiosk-update`.
- `Taskfile.yml` – same tasks for users who prefer `task`.

TECHNICAL REQUIREMENTS:
1) **kube-prometheus-stack**
   - Namespace: `observability`.
   - Reasonable defaults: 30s scrape, 15d retention, resource requests/limits.
   - Grafana:
     - If `{{enable_anonymous_grafana_view}} == true`, enable anonymous auth
       with `Viewer` role only and `allow_embedding=true`.
     - Sidecar picks up dashboards via ConfigMap label `grafana_dashboard: "1"`.
     - Provision Prometheus/Loki/(Tempo) via a labeled Secret
       `grafana_datasource: "1"`.
2) **Loki + Promtail**
   - Single-process Loki (no external object store) with 7–14d retention.
   - Promtail DaemonSet scraping k8s containers; include log label normalization.
3) **Blackbox Exporter**
   - Targets come from a ConfigMap derived from `{{REPOS_JSON}}` plus explicit
     URLs for `{{GRAFANA_SUBDOMAIN}}.{{BASE_DOMAIN}}`, your public endpoints, and
     LAN services.
   - Export `probe_success`, latency, and TLS expiry.
4) **GitHub metrics**
   - Build a minimal exporter (Go or Python) that:
     - Lists repos in `{{REPOS_JSON}}` (owner/name).
     - Exposes Prometheus metrics: `github_repo_stars`, `github_repo_open_issues`,
       `github_actions_last_run_timestamp`,
       `github_actions_last_run_conclusion{status=...}`.
     - Respects rate limits and caches for 60s.
   - Provide Deployment, Service, and a `ServiceMonitor` so Prometheus scrapes it
     automatically.
5) **Cloudflare Tunnel**
   - `cloudflared` Deployment in k8s with a Secret containing
     `{{CF_TUNNEL_TOKEN}}` (or ID/secret).
   - `config.yaml` ingress maps
     `https://{{GRAFANA_SUBDOMAIN}}.{{BASE_DOMAIN}}` → Grafana Service
     (ClusterIP).
   - Include instructions to enable Cloudflare Access with a policy granting
     viewer rights to your identity.
6) **Dashboard**
   - `sugarkube-overview.json` must include:
     - “Global” row: uptime & TLS status cards from blackbox for key endpoints.
     - “Cluster health” row: API server up, node ready count, pod restarts, top
       CPU/mem pods.
     - “Cloudflare” row: `cloudflared` connections and errors.
     - “GitHub” row: last workflow run per repo, stars, open issues (stat +
       table).
     - A time range default of last 24h, refresh every 30s; autoscroll playlist
       support.
7) **RBAC & safety**
   - Grafana read-only default; no admin endpoints over the tunnel.
   - Prometheus and Loki not exposed publicly.
8) **Makefile/Taskfile targets**
   - `bootstrap-obs`: create ns, repos, add Helm repos, install/upgrade charts
     with the provided values.
   - `deploy-tunnel`: create CF secrets and apply Deployment + config.
   - `apply-dashboards`: apply ConfigMaps/Secrets for Grafana provisioning.
   - `kiosk-install`: run the Ansible play to set up a Pi from a clean
     Raspberry Pi OS Lite image.
   - `kiosk-update`: redeploy kiosk files.
9) **Docs**
   - `README.md` includes one-command quickstart, troubleshooting (Pods pending,
     PV issues, incorrect Service names), and a section on adding a new project
     to the dashboard (edit `REPOS_JSON`, add blackbox target, redeploy).

ACCEPTANCE CRITERIA:
- `make bootstrap-obs` completes without errors on a vanilla k3s cluster.
- `kubectl -n observability get pods` shows Prometheus, Grafana, Alertmanager,
  Loki, Promtail, Blackbox, and GitHub exporter all `READY=1/1` (or appropriate).
- Accessing `https://{{GRAFANA_SUBDOMAIN}}.{{BASE_DOMAIN}}` through the
  Cloudflare URL renders the **“Sugarkube Overview”** dashboard without manual
  login (either anonymous viewer or Zero Trust SSO).
- Blackbox panels show `probe_success=1` for at least one public endpoint and
  one LAN endpoint.
- The GitHub row shows metrics for all repos listed in `{{REPOS_JSON}}` and
  updates within 60s of a new workflow run.
- The kiosk Pi boots to a full-screen Grafana dashboard with no dialogs, no
  mouse cursor, and restarts Chromium if the network flaps.

NON-GOALS:
- Long-term object storage for logs/traces.
- Multi-cluster federation. (Note: design for future federation but do not
  implement it now.)

OUTPUT:
- A ready-to-commit repo subtree under `platform/` with all files, plus a
  concise `README.md` walkthrough.
- No placeholders beyond the declared inputs; use templates with `{{...}}`.
```
