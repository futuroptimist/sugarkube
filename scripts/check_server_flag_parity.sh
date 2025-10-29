#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage: check_server_flag_parity.sh [--server <host>] [--intended-config <path>]
                                   [--server-config <path>] [--server-service <path>]

Compare the intended k3s configuration against the discovered server's
configuration for critical flags that must match when joining a cluster.
USAGE
}

SERVER_HOST=""
INTENDED_OVERRIDE=""
SERVER_CONFIG_OVERRIDE=""
SERVER_SERVICE_OVERRIDE=""

while [ "$#" -gt 0 ]; do
  case "$1" in
    --server|--server-host)
      if [ "$#" -lt 2 ]; then
        echo "--server requires a host argument" >&2
        exit 2
      fi
      SERVER_HOST="$2"
      shift 2
      ;;
    --intended-config)
      if [ "$#" -lt 2 ]; then
        echo "--intended-config requires a path argument" >&2
        exit 2
      fi
      INTENDED_OVERRIDE="$2"
      shift 2
      ;;
    --server-config)
      if [ "$#" -lt 2 ]; then
        echo "--server-config requires a path argument" >&2
        exit 2
      fi
      SERVER_CONFIG_OVERRIDE="$2"
      shift 2
      ;;
    --server-service)
      if [ "$#" -lt 2 ]; then
        echo "--server-service requires a path argument" >&2
        exit 2
      fi
      SERVER_SERVICE_OVERRIDE="$2"
      shift 2
      ;;
    --help|-h)
      usage
      exit 0
      ;;
    *)
      printf 'Unknown argument: %s\n' "$1" >&2
      exit 2
      ;;
  esac
done

DEFAULT_K3S_CONFIG="/etc/rancher/k3s/config.yaml"
if [ -n "${INTENDED_OVERRIDE}" ]; then
  INTENDED_PATH="${INTENDED_OVERRIDE}"
elif [ -n "${SUGARKUBE_INTENDED_K3S_CONFIG_PATH:-}" ]; then
  INTENDED_PATH="${SUGARKUBE_INTENDED_K3S_CONFIG_PATH}"
else
  INTENDED_PATH="${DEFAULT_K3S_CONFIG}"
fi

if [ -n "${SERVER_CONFIG_OVERRIDE}" ]; then
  SERVER_CONFIG_PATH_BASE="${SERVER_CONFIG_OVERRIDE}"
elif [ -n "${SUGARKUBE_SERVER_CONFIG_PATH:-}" ]; then
  SERVER_CONFIG_PATH_BASE="${SUGARKUBE_SERVER_CONFIG_PATH}"
else
  SERVER_CONFIG_PATH_BASE="${DEFAULT_K3S_CONFIG}"
fi

SERVER_SERVICE_PATH=""
if [ -n "${SERVER_SERVICE_OVERRIDE}" ]; then
  SERVER_SERVICE_PATH="${SERVER_SERVICE_OVERRIDE}"
elif [ -n "${SUGARKUBE_SERVER_SERVICE_PATH:-}" ]; then
  SERVER_SERVICE_PATH="${SUGARKUBE_SERVER_SERVICE_PATH}"
else
  for candidate in \
    /etc/systemd/system/k3s.service \
    /usr/lib/systemd/system/k3s.service \
    /lib/systemd/system/k3s.service \
    /etc/systemd/system/multi-user.target.wants/k3s.service
  do
    if [ -r "${candidate}" ]; then
      SERVER_SERVICE_PATH="${candidate}"
      break
    fi
  done
fi

TMPDIR="$(mktemp -d 2>/dev/null || mktemp -d -t parity-check)"
cleanup_tmpdir() {
  rm -rf "${TMPDIR}"
}
trap cleanup_tmpdir EXIT

copy_if_readable() {
  local source="$1"
  local dest="$2"
  if [ -n "${source}" ] && [ -r "${source}" ]; then
    if ! cat "${source}" >"${dest}" 2>/dev/null; then
      return 1
    fi
    return 0
  fi
  return 1
}

run_command_to_file() {
  local command="$1"
  local dest="$2"
  if [ -z "${command}" ]; then
    return 1
  fi
  if bash -c "${command}" >"${dest}" 2>/dev/null; then
    return 0
  fi
  return 1
}

INTENDED_LOCAL=""
if copy_if_readable "${INTENDED_PATH}" "${TMPDIR}/intended.yaml"; then
  INTENDED_LOCAL="${TMPDIR}/intended.yaml"
fi

SERVER_CONFIG_LOCAL=""
SERVER_CONFIG_LABEL=""
if copy_if_readable "${SERVER_CONFIG_PATH_BASE}" "${TMPDIR}/server-config.yaml"; then
  SERVER_CONFIG_LOCAL="${TMPDIR}/server-config.yaml"
  SERVER_CONFIG_LABEL="${SERVER_CONFIG_PATH_BASE}"
elif run_command_to_file "${SUGARKUBE_SERVER_CONFIG_CMD:-}" "${TMPDIR}/server-config.yaml"; then
  SERVER_CONFIG_LOCAL="${TMPDIR}/server-config.yaml"
  SERVER_CONFIG_LABEL="${SUGARKUBE_SERVER_CONFIG_CMD}";
fi

SERVER_SERVICE_LOCAL=""
SERVER_SERVICE_LABEL=""
if copy_if_readable "${SERVER_SERVICE_PATH}" "${TMPDIR}/server-service.txt"; then
  SERVER_SERVICE_LOCAL="${TMPDIR}/server-service.txt"
  SERVER_SERVICE_LABEL="${SERVER_SERVICE_PATH}"
elif run_command_to_file "${SUGARKUBE_SERVER_SERVICE_CMD:-}" "${TMPDIR}/server-service.txt"; then
  SERVER_SERVICE_LOCAL="${TMPDIR}/server-service.txt"
  SERVER_SERVICE_LABEL="${SUGARKUBE_SERVER_SERVICE_CMD}"
fi

if [ -z "${SERVER_CONFIG_LOCAL}" ] && [ -z "${SERVER_SERVICE_LOCAL}" ]; then
  printf 'Unable to read server configuration or service definition; tried %s' \
    "${SERVER_CONFIG_PATH_BASE}" >&2
  if [ -n "${SERVER_SERVICE_PATH}" ]; then
    printf ' and %s' "${SERVER_SERVICE_PATH}" >&2
  fi
  printf '\n' >&2
  exit 1
fi

INTENDED_LABEL="${INTENDED_PATH}"
if [ -z "${INTENDED_LABEL}" ]; then
  INTENDED_LABEL="intended-config"
fi
if [ -z "${SERVER_CONFIG_LABEL}" ] && [ -n "${SERVER_CONFIG_PATH_BASE}" ]; then
  SERVER_CONFIG_LABEL="${SERVER_CONFIG_PATH_BASE}"
fi
if [ -z "${SERVER_SERVICE_LABEL}" ] && [ -n "${SERVER_SERVICE_PATH}" ]; then
  SERVER_SERVICE_LABEL="${SERVER_SERVICE_PATH}"
fi

python3 - "$SERVER_HOST" \
  "${INTENDED_LOCAL}" "${INTENDED_LABEL}" \
  "${SERVER_CONFIG_LOCAL}" "${SERVER_CONFIG_LABEL}" \
  "${SERVER_SERVICE_LOCAL}" "${SERVER_SERVICE_LABEL}" <<'PY'
import os
import re
import shlex
import sys
from pathlib import Path
import subprocess

PROXY_MODE_KEY = "proxy-mode"
NFTABLES_MIN_MINOR = 33

CRITICAL_FLAGS = [
    ("cluster-cidr", "10.42.0.0/16"),
    ("service-cidr", "10.43.0.0/16"),
    ("cluster-domain", "cluster.local"),
    ("flannel-backend", "vxlan"),
    ("secrets-encryption", "false"),
    (PROXY_MODE_KEY, "iptables"),
]

KEYS = {key for key, _ in CRITICAL_FLAGS}
ENV_MAPPING = {
    "cluster-cidr": "K3S_CLUSTER_CIDR",
    "service-cidr": "K3S_SERVICE_CIDR",
    "cluster-domain": "K3S_CLUSTER_DOMAIN",
    "flannel-backend": "K3S_FLANNEL_BACKEND",
    "secrets-encryption": "K3S_SECRETS_ENCRYPTION",
}

server_host = sys.argv[1]
intended_path = sys.argv[2]
intended_label = sys.argv[3]
server_config_path = sys.argv[4]
server_config_label = sys.argv[5]
server_service_path = sys.argv[6]
server_service_label = sys.argv[7]

phase = os.environ.get("SUGARKUBE_SERVER_FLAG_PARITY_PHASE", "")
intended_dir = os.environ.get("SUGARKUBE_INTENDED_K3S_CONFIG_DIR", "")
server_config_dir = os.environ.get("SUGARKUBE_SERVER_CONFIG_DIR", "")


def new_store():
    store = {}
    for key, default in CRITICAL_FLAGS:
        store[key] = {"value": default, "source": "default"}
    return store


def normalize_value(key: str, raw: str | None) -> str | None:
    if raw is None:
        return None
    value = str(raw).strip()
    if value == "":
        return None
    if key == "secrets-encryption":
        lowered = value.lower()
        if lowered in {"true", "1", "yes", "on"}:
            return "true"
        if lowered in {"false", "0", "no", "off"}:
            return "false"
        return lowered
    if key == PROXY_MODE_KEY:
        lowered = value.lower()
        if lowered in {"nftables", "nft"}:
            return "nftables"
        if lowered in {"iptables", "ip-tables"}:
            return "iptables"
        if lowered == "ipvs":
            return "ipvs"
        return lowered
    if key == "flannel-backend":
        return value.lower()
    return value


def extract_proxy_mode_from_text(text: str) -> str | None:
    candidate = text
    if "proxy-mode=" in text:
        candidate = text.split("proxy-mode=", 1)[1]
    if "#" in candidate:
        candidate = candidate.split("#", 1)[0]
    candidate = candidate.strip()
    if candidate.startswith(("'", '"')):
        candidate = candidate[1:]
        if candidate.endswith(("'", '"')):
            candidate = candidate[:-1]
    for delimiter in (",", " "):
        if delimiter in candidate:
            candidate = candidate.split(delimiter, 1)[0]
    return normalize_value(PROXY_MODE_KEY, candidate)


def parse_yaml_values(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return values
    for raw_line in text.splitlines():
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if PROXY_MODE_KEY in KEYS:
            proxy_mode = extract_proxy_mode_from_text(stripped)
            if proxy_mode:
                values[PROXY_MODE_KEY] = proxy_mode
        if ":" not in stripped:
            continue
        key_part, value_part = stripped.split(":", 1)
        key = key_part.strip().strip("'").strip('"')
        if key not in KEYS:
            continue
        value = value_part.strip()
        if not value:
            values[key] = ""
            continue
        if value.startswith(("'", '"')):
            quote = value[0]
            remainder = value[1:]
            if remainder.endswith(quote):
                remainder = remainder[:-1]
            else:
                if quote in remainder:
                    remainder = remainder.split(quote, 1)[0]
            value = remainder
        else:
            if "#" in value:
                value = value.split("#", 1)[0]
        values[key] = value.strip()
    return values


def apply_yaml(store: dict[str, dict[str, str]], path: str, label: str) -> bool:
    if not path:
        return False
    values = parse_yaml_values(Path(path))
    applied = False
    for key, raw in values.items():
        value = normalize_value(key, raw)
        if value is None:
            continue
        store[key] = {"value": value, "source": label}
        applied = True
    return applied


def apply_yaml_dir(store: dict[str, dict[str, str]], directory: str, label: str) -> bool:
    if not directory:
        return False
    dir_path = Path(directory)
    if not dir_path.is_dir():
        return False
    applied = False
    for candidate in sorted(dir_path.glob("*.yml")) + sorted(dir_path.glob("*.yaml")):
        if apply_yaml(store, str(candidate), f"{label}:{candidate.name}"):
            applied = True
    return applied


def apply_tokens(store: dict[str, dict[str, str]], tokens: list[str], label: str) -> bool:
    applied = False
    i = 0
    total = len(tokens)
    while i < total:
        argument = tokens[i]
        if argument.startswith("--kube-proxy-arg"):
            proxy_arg_value = None
            if argument == "--kube-proxy-arg" and i + 1 < total:
                proxy_arg_value = tokens[i + 1]
                i += 1
            elif argument.startswith("--kube-proxy-arg="):
                proxy_arg_value = argument.split("=", 1)[1]
            if proxy_arg_value:
                proxy_mode = extract_proxy_mode_from_text(proxy_arg_value)
                if proxy_mode:
                    store[PROXY_MODE_KEY] = {"value": proxy_mode, "source": label}
                    applied = True
            i += 1
            continue
        if not argument.startswith("--"):
            i += 1
            continue
        if argument == "--secrets-encryption":
            store["secrets-encryption"] = {"value": "true", "source": label}
            applied = True
            i += 1
            continue
        if argument == "--disable-secrets-encryption":
            store["secrets-encryption"] = {"value": "false", "source": label}
            applied = True
            i += 1
            continue
        matched = False
        for key in KEYS:
            flag = f"--{key}"
            if argument.startswith(flag + "="):
                store[key] = {
                    "value": normalize_value(key, argument[len(flag) + 1 :]),
                    "source": label,
                }
                applied = True
                matched = True
                break
            if argument == flag and i + 1 < total:
                store[key] = {
                    "value": normalize_value(key, tokens[i + 1]),
                    "source": label,
                }
                applied = True
                matched = True
                i += 1
                break
        if not matched:
            i += 1
            continue
        i += 1
    return applied


def apply_exec(store: dict[str, dict[str, str]], command: str, label: str) -> bool:
    if not command:
        return False
    try:
        tokens = shlex.split(command)
    except ValueError:
        return False
    return apply_tokens(store, tokens, label)


def load_exec_from_service(path: str) -> list[str]:
    if not path:
        return []
    try:
        lines = Path(path).read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    tokens: list[str] = []
    collecting = False
    fragments: list[str] = []
    for raw_line in lines:
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("ExecStart="):
            content = stripped.split("=", 1)[1].lstrip()
            if content.startswith("-"):
                content = content[1:].lstrip()
            if content.endswith("\\"):
                fragments = [content[:-1].strip()]
                collecting = True
            else:
                fragments = [content]
                tokens.extend(shlex.split(" ".join(fragments)))
                fragments = []
                collecting = False
            continue
        if collecting:
            if stripped.endswith("\\"):
                fragments.append(stripped[:-1].strip())
            else:
                fragments.append(stripped)
                tokens.extend(shlex.split(" ".join(fragments)))
                fragments = []
                collecting = False
    if fragments:
        tokens.extend(shlex.split(" ".join(fragments)))
    return tokens


def parse_kubernetes_version(text: str) -> tuple[int, int, str] | None:
    pattern = re.compile(r"v?(\d+)\.(\d+)(?:\.(\d+))?")
    for match in pattern.finditer(text):
        major = int(match.group(1))
        if major != 1:
            continue
        minor = int(match.group(2))
        raw = match.group(0)
        return major, minor, raw
    return None


def detect_kubernetes_version() -> tuple[int, int, str] | None:
    env_version = os.environ.get("SUGARKUBE_DETECTED_K8S_VERSION", "").strip()
    if env_version:
        parsed = parse_kubernetes_version(env_version)
        if parsed:
            return parsed
    env_cmd = os.environ.get("SUGARKUBE_DETECTED_K8S_VERSION_CMD", "").strip()
    commands: list[str] = []
    if env_cmd:
        commands.append(env_cmd)
    commands.extend(
        [
            "k3s kubectl version --short",
            "kubectl version --short",
            "k3s --version",
        ]
    )
    for command in commands:
        if not command:
            continue
        try:
            output = subprocess.check_output(
                command, shell=True, stderr=subprocess.STDOUT, text=True
            )
        except (OSError, subprocess.CalledProcessError):
            continue
        parsed = parse_kubernetes_version(output)
        if parsed:
            return parsed
    return None


intended_store = new_store()
server_store = new_store()

intended_sources = 0
server_sources = 0

if apply_yaml(intended_store, intended_path, intended_label):
    intended_sources += 1
if apply_yaml_dir(intended_store, intended_dir, "intended-dropin"):
    intended_sources += 1

server_config_used = False
if apply_yaml(server_store, server_config_path, server_config_label):
    server_sources += 1
    server_config_used = True
if apply_yaml_dir(server_store, server_config_dir, "server-dropin"):
    server_sources += 1
    server_config_used = True

if server_service_path:
    service_tokens = load_exec_from_service(server_service_path)
    if service_tokens and apply_tokens(
        server_store,
        service_tokens,
        server_service_label or "k3s.service",
    ):
        server_sources += 1

install_exec = os.environ.get("INSTALL_K3S_EXEC", "")
if install_exec and apply_exec(intended_store, install_exec, "INSTALL_K3S_EXEC"):
    intended_sources += 1

detected_version = detect_kubernetes_version()
detected_minor = None
detected_label = None
if detected_version:
    detected_minor = detected_version[1]
    detected_label = detected_version[2]

if detected_minor is not None and detected_minor < NFTABLES_MIN_MINOR:
    fallback_applied = False
    fallback_source = f"nftables-unsupported:{detected_label or detected_minor}"
    for store in (intended_store, server_store):
        proxy_entry = store.get(PROXY_MODE_KEY)
        if proxy_entry and proxy_entry.get("value") == "nftables":
            store[PROXY_MODE_KEY] = {"value": "iptables", "source": fallback_source}
            fallback_applied = True
    if fallback_applied:
        message_label = detected_label or f"v1.{detected_minor}"
        print(
            f"Detected Kubernetes {message_label} without kube-proxy nftables support; "
            "falling back to proxy-mode=iptables",
            file=sys.stderr,
        )

for key, env_var in ENV_MAPPING.items():
    env_value = os.environ.get(env_var)
    if env_value:
        value = normalize_value(key, env_value)
        if value is None:
            continue
        intended_store[key] = {"value": value, "source": env_var}
        intended_sources += 1

server_env_prefix = os.environ.get("SUGARKUBE_SERVER_ENV_PREFIX", "")
if server_env_prefix:
    for key, env_var in ENV_MAPPING.items():
        server_env = os.environ.get(f"{server_env_prefix}{env_var}")
        if server_env:
            value = normalize_value(key, server_env)
            if value is None:
                continue
            server_store[key] = {"value": value, "source": f"{server_env_prefix}{env_var}"}
            server_sources += 1

if not server_config_used and not server_service_path and not server_env_prefix:
    # We only relied on defaults, warn the operator that validation is incomplete.
    print(
        "Unable to load server configuration; set SUGARKUBE_SERVER_CONFIG_PATH "
        "or SUGARKUBE_SERVER_SERVICE_PATH",
        file=sys.stderr,
    )
    sys.exit(1)

mismatches = []
for key, _ in CRITICAL_FLAGS:
    intended_value = intended_store[key]["value"]
    server_value = server_store[key]["value"]
    if intended_value != server_value:
        mismatches.append(
            {
                "key": key,
                "intended": intended_store[key],
                "server": server_store[key],
            }
        )

if mismatches:
    red = "\033[31m"
    reset = "\033[0m"
    if server_host:
        header = f"{red}Flag parity check failed for server '{server_host}'{reset}"
    else:
        header = f"{red}Flag parity check failed for discovered server{reset}"
    if phase:
        header = f"{header} during {phase}"
    print(header, file=sys.stderr)
    for mismatch in mismatches:
        key = mismatch["key"]
        intended_val = mismatch["intended"]["value"]
        intended_src = mismatch["intended"]["source"]
        server_val = mismatch["server"]["value"]
        server_src = mismatch["server"]["source"]
        print(
            f"{red}  {key}: intended={intended_val} ({intended_src}) "
            f"server={server_val} ({server_src}){reset}",
            file=sys.stderr,
        )
    hint = (
        os.environ.get(
            "SUGARKUBE_SERVER_FLAG_PARITY_HINT",
            "Resolve the mismatch or align the node configuration before retrying the join.",
        )
        or "Resolve the mismatch or align the node configuration before retrying the join."
    )
    print(f"{red}{hint}{reset}", file=sys.stderr)
    sys.exit(1)

sys.exit(0)
PY
