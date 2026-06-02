# k3s token.place runbook (dev)

Use dev for local cluster experiments only. Staging and production releases should follow the
GHCR-first generic flow in [`docs/apps/tokenplace.md`](apps/tokenplace.md).

## Dev deploy

```bash
APP_TAG=main-REPLACE_SHORTSHA
```

```bash
just app-deploy app=tokenplace env=dev tag="$APP_TAG"
```

Compatibility shim:

```bash
APP_TAG=main-REPLACE_SHORTSHA
```

```bash
just tokenplace-oci-deploy env=dev tag="$APP_TAG"
```

## Dev verify

```bash
just app-verify app=tokenplace env=dev
```

```bash
just app-status app=tokenplace env=dev
```

## Dev rollback

```bash
PREVIOUS_TAG=main-REPLACE_PREVIOUS_SHORTSHA
```

```bash
just app-deploy app=tokenplace env=dev tag="$PREVIOUS_TAG"
```
