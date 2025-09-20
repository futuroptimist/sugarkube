INIT_ENV_PATH="${INIT_ENV_PATH:-${CLOUD_INIT_DIR}/init-env.sh}"
FIRST_BOOT_PATH="${FIRST_BOOT_PATH:-${CLOUD_INIT_DIR}/first-boot.py}"
EXPORT_KUBECONFIG_PATH="${EXPORT_KUBECONFIG_PATH:-${CLOUD_INIT_DIR}/export-kubeconfig.sh}"

if [ ! -f "${CLOUD_INIT_PATH}" ]; then
  echo "Cloud-init file not found: ${CLOUD_INIT_PATH}" >&2
  exit 1
fi
if [ ! -s "${CLOUD_INIT_PATH}" ]; then
  echo "Cloud-init file is empty: ${CLOUD_INIT_PATH}" >&2
  exit 1
fi
if ! head -n1 "${CLOUD_INIT_PATH}" | grep -q '^#cloud-config'; then
  echo "Cloud-init file missing #cloud-config header: ${CLOUD_INIT_PATH}" >&2
  exit 1
fi

# Validate cloud-init YAML syntax when PyYAML is available
SKIP_CLOUD_INIT_VALIDATION="${SKIP_CLOUD_INIT_VALIDATION:-0}"
if [ "${SKIP_CLOUD_INIT_VALIDATION}" -ne 1 ]; then
  if command -v python3 >/dev/null 2>&1 && python3 -c "import yaml" >/dev/null 2>&1; then
    if ! python3 - "${CLOUD_INIT_PATH}" <<'PY' >/dev/null 2>&1
import sys, yaml
with open(sys.argv[1]) as f:
    yaml.safe_load(f)
PY
    then
      echo "Cloud-init file contains invalid YAML: ${CLOUD_INIT_PATH}" >&2
      exit 1
    fi
  else
    echo "PyYAML not installed; skipping cloud-init YAML validation" >&2
  fi
else
  echo "Skipping cloud-init YAML validation"
fi

if [ ! -f "${CLOUDFLARED_COMPOSE_PATH}" ]; then
  echo "Cloudflared compose file not found: ${CLOUDFLARED_COMPOSE_PATH}" >&2
  exit 1
fi
if [ ! -s "${CLOUDFLARED_COMPOSE_PATH}" ]; then
  echo "Cloudflared compose file is empty: ${CLOUDFLARED_COMPOSE_PATH}" >&2
  exit 1
fi
if [ ! -f "${PROJECTS_COMPOSE_PATH}" ]; then
  echo "Projects compose file not found: ${PROJECTS_COMPOSE_PATH}" >&2
  exit 1
fi
if [ ! -s "${PROJECTS_COMPOSE_PATH}" ]; then
  echo "Projects compose file is empty: ${PROJECTS_COMPOSE_PATH}" >&2
  exit 1
fi
if [ ! -f "${START_PROJECTS_PATH}" ]; then
  echo "Start projects script not found: ${START_PROJECTS_PATH}" >&2
  exit 1
fi
if [ ! -s "${START_PROJECTS_PATH}" ]; then
  echo "Start projects script is empty: ${START_PROJECTS_PATH}" >&2
  exit 1
fi
if [ ! -f "${INIT_ENV_PATH}" ]; then
  echo "Init env script not found: ${INIT_ENV_PATH}" >&2
  exit 1
fi
if [ ! -s "${INIT_ENV_PATH}" ]; then
  echo "Init env script is empty: ${INIT_ENV_PATH}" >&2
  exit 1
fi
if [ ! -f "${FIRST_BOOT_PATH}" ]; then
  echo "First boot reporter not found: ${FIRST_BOOT_PATH}" >&2
  exit 1
fi
if [ ! -s "${FIRST_BOOT_PATH}" ]; then
  echo "First boot reporter is empty: ${FIRST_BOOT_PATH}" >&2
  exit 1
fi
if [ ! -f "${EXPORT_KUBECONFIG_PATH}" ]; then
  echo "Export kubeconfig script not found: ${EXPORT_KUBECONFIG_PATH}" >&2
  exit 1
fi
if [ ! -s "${EXPORT_KUBECONFIG_PATH}" ]; then
  echo "Export kubeconfig script is empty: ${EXPORT_KUBECONFIG_PATH}" >&2
  exit 1
fi
