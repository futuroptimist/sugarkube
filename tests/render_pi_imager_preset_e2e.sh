#!/usr/bin/env bash
# Exercise scripts/render_pi_imager_preset.py end-to-end.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
SCRIPT="${ROOT_DIR}/scripts/render_pi_imager_preset.py"

if [ ! -x "${SCRIPT}" ]; then
  echo "render_pi_imager_preset.py missing or not executable" >&2
  exit 1
fi

tmpdir="$(mktemp -d)"
cleanup() {
  rm -rf "${tmpdir}"
}
trap cleanup EXIT

preset_path="${tmpdir}/preset.json"
cat >"${preset_path}" <<'JSON'
{
  "hostname": "default-host",
  "username": "pi",
  "ssh": {
    "enabled": true,
    "password_authentication": true,
    "authorized_keys": [
      "ssh-ed25519 AAAAdefault default@example"
    ]
  },
  "wifi": {
    "ssid": "DefaultSSID",
    "password": "default-pass",
    "country": "US"
  },
  "locale": {
    "timezone": "UTC",
    "keyboard_layout": "us",
    "keyboard_variant": ""
  }
}
JSON

secrets_path="${tmpdir}/secrets.env"
cat >"${secrets_path}" <<'EOFVARS'
PI_HOSTNAME=secrets-host
PI_USERNAME=secrets-user
SSH_ENABLED=true
SSH_PASSWORD_AUTH=false
SSH_AUTHORIZED_KEYS=ssh-ed25519 AAAAsecrets secrets@example
WIFI_SSID=SecretsSSID
WIFI_PASSWORD=secrets-pass
WIFI_COUNTRY=CA
WIFI_HIDDEN=true
TIMEZONE=America/Toronto
KEYBOARD_LAYOUT=us
KEYBOARD_VARIANT=altgr-intl
EOFVARS

key_file="${tmpdir}/ssh_key.pub"
cat >"${key_file}" <<'EOFKEY'
ssh-ed25519 AAAAkeyfile keyfile@example
EOFKEY

export XDG_CONFIG_HOME="${tmpdir}/config-home"
output_ini="${tmpdir}/output.ini"
config_path="${XDG_CONFIG_HOME}/Raspberry Pi/Imager.conf"

python3 "${SCRIPT}" \
  --preset "${preset_path}" \
  --secrets "${secrets_path}" \
  --output "${output_ini}" \
  --apply \
  --ssh-authorized-key "ssh-ed25519 AAAAcli cli@example" \
  --ssh-key-file "${key_file}" \
  --wifi-ssid "CliSSID" \
  --wifi-password "cli-pass" \
  --timezone "America/Chicago"

python3 - <<'PY' "${output_ini}" "${config_path}"
import configparser
import pathlib
import sys

output_path = pathlib.Path(sys.argv[1])
config_path = pathlib.Path(sys.argv[2])

if not output_path.exists():
    raise SystemExit(f"output.ini missing: {output_path}")
if not config_path.exists():
    raise SystemExit(f"Imager.conf missing: {config_path}")

expected_keys = {
    "ssh-ed25519 AAAAdefault default@example",
    "ssh-ed25519 AAAAsecrets secrets@example",
    "ssh-ed25519 AAAAcli cli@example",
    "ssh-ed25519 AAAAkeyfile keyfile@example",
}

parser = configparser.ConfigParser()
parser.optionxform = str
parser.read(output_path, encoding="utf-8")
settings = parser["imagecustomization"]

assert settings["sshEnabled"] == "true"
assert settings["hostname"] == "secrets-host"
assert settings["sshUserName"] == "secrets-user"
assert settings["wifiSSID"] == "CliSSID"
assert settings["wifiPassword"] == "cli-pass"
assert settings["wifiCountry"] == "CA"
assert settings["wifiSSIDHidden"] == "true"
assert settings["timezone"] == "America/Chicago"
assert settings["keyboardLayout"] == "us"
assert settings["keyboardVariant"] == "altgr-intl"

actual_keys = set(settings["sshAuthorizedKeys"].splitlines())
assert actual_keys == expected_keys, actual_keys

imager_parser = configparser.ConfigParser()
imager_parser.optionxform = str
imager_parser.read(config_path, encoding="utf-8")
imager_settings = imager_parser["imagecustomization"]

assert dict(imager_settings) == dict(settings)
PY

echo "render_pi_imager_preset e2e test passed"
