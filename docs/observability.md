# Observability operations

## Declarative application metrics verification

Application metrics contracts live in `platform/observability/app-metrics.json`. The inventory is strict, data-only configuration: it declares the Kubernetes context, namespace, `ServiceMonitor`, Secret name/key, canonical target labels, required metric families, allowed bounded application label enums, forbidden sensitive labels, retry settings, and the expected unauthenticated public `/metrics` status.

Operators can install, check, and verify a configured staging application without placing credentials in Git, arguments, environment variables, logs, or temporary files:

```bash
just observability-app-metrics-secret-install app=tokenplace env=staging
just observability-app-metrics-secret-check app=tokenplace env=staging
just observability-app-metrics-verify app=tokenplace env=staging
```

`just observability-verify env=staging` remains the full observability verification entry point and now also runs all configured application metrics verifiers after the established DSPACE and observability checks. Production application metrics verification is intentionally refused until production observability is codified.
