#!/usr/bin/env python3
"""Render Raspberry Pi Imager presets from sugarkube JSON templates."""

from __future__ import annotations

import argparse
import configparser
import json
import os
import sys
import warnings
from pathlib import Path
from typing import Dict, Iterable, List, Optional

warnings.filterwarnings("ignore", category=DeprecationWarning, module="crypt")
warnings.filterwarnings("ignore", category=DeprecationWarning, message=".*crypt.*")
try:  # Python 3.13 removes crypt; guard so we can error gracefully.
    import crypt  # type: ignore[attr-defined]
except ImportError:  # pragma: no cover - crypt is present on Linux images we ship.
    crypt = None  # type: ignore[assignment]


def parse_key_value_file(path: Path) -> Dict[str, str]:
    data: Dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise ValueError(f"Invalid line in {path}: {raw_line!r}")
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if (value.startswith('"') and value.endswith('"')) or (
            value.startswith("'") and value.endswith("'")
        ):
            value = value[1:-1]
        data[key] = value
    return data


def parse_bool(value: object, *, field: str) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        raise ValueError(f"Missing boolean value for {field}")
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"Could not interpret {value!r} as a boolean for {field}")


def maybe_bool(value: object, *, field: str) -> Optional[bool]:
    if value is None:
        return None
    try:
        return parse_bool(value, field=field)
    except ValueError as exc:  # pragma: no cover - exercised at runtime
        raise ValueError(f"{exc}") from exc


def hash_password(password: str) -> str:
    if not password:
        raise ValueError("Password cannot be empty when hashing")
    if crypt is None:
        raise RuntimeError(
            "Python's crypt module is unavailable. Provide PI_PASSWORD_HASH instead."
        )
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", category=DeprecationWarning)
        return crypt.crypt(password, crypt.mksalt(crypt.METHOD_SHA512))


def collect_ssh_keys(values: Iterable[str]) -> List[str]:
    seen = set()
    keys: List[str] = []
    for value in values:
        if not value:
            continue
        for candidate in str(value).replace("\r", "").splitlines():
            key = candidate.strip()
            if not key or key in seen:
                continue
            seen.add(key)
            keys.append(key)
    return keys


def format_value(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def write_ini(settings: Dict[str, object], destination: Path) -> None:
    config = configparser.ConfigParser(interpolation=None)
    config.optionxform = str  # preserve camelCase keys expected by Imager
    config["imagecustomization"] = {k: format_value(v) for k, v in settings.items()}
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("w", encoding="utf-8") as handle:
        config.write(handle)


def apply_to_imager_conf(settings: Dict[str, object]) -> Path:
    config_home = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    target = config_home / "Raspberry Pi" / "Imager.conf"
    parser = configparser.ConfigParser(interpolation=None)
    parser.optionxform = str
    if target.exists():
        parser.read(target, encoding="utf-8")
    if "imagecustomization" not in parser:
        parser["imagecustomization"] = {}
    for key, value in settings.items():
        parser["imagecustomization"][key] = format_value(value)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8") as handle:
        parser.write(handle)
    return target


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Render a sugarkube Raspberry Pi Imager preset JSON into the format "
            "used by Imager's advanced options."
        )
    )
    parser.add_argument("--preset", required=True, help="Path to preset JSON file.")
    parser.add_argument(
        "--secrets",
        help="Optional KEY=VALUE file providing Wi-Fi credentials or overrides.",
    )
    parser.add_argument("--output", help="Write an INI snippet to this path.")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Update ~/.config/Raspberry Pi/Imager.conf with the rendered preset.",
    )
    parser.add_argument("--hostname")
    parser.add_argument("--username")
    parser.add_argument("--password", help="Plain-text password to hash with sha512-crypt.")
    parser.add_argument("--password-hash", help="Pre-computed sha512-crypt password hash.")
    parser.add_argument(
        "--ssh-authorized-key",
        action="append",
        dest="ssh_authorized_keys",
        help="Append an SSH public key to the preset.",
    )
    parser.add_argument(
        "--ssh-key-file",
        action="append",
        help="Read one or more SSH keys from these files and add them to the preset.",
    )
    parser.add_argument(
        "--ssh-enabled",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Toggle SSH in the rendered preset (defaults to the JSON value).",
    )
    parser.add_argument(
        "--ssh-password-auth",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Toggle password authentication. Disable to rely on SSH keys only.",
    )
    parser.add_argument("--wifi-ssid")
    parser.add_argument("--wifi-password")
    parser.add_argument("--wifi-country")
    parser.add_argument(
        "--wifi-hidden",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Mark the Wi-Fi network as hidden.",
    )
    parser.add_argument("--timezone")
    parser.add_argument("--keyboard-layout")
    parser.add_argument("--keyboard-variant")
    args = parser.parse_args(argv)

    preset_path = Path(args.preset)
    if not preset_path.exists():
        parser.error(f"Preset {preset_path} does not exist")

    preset = json.loads(preset_path.read_text(encoding="utf-8"))

    secrets: Dict[str, str] = {}
    if args.secrets:
        secrets_path = Path(args.secrets)
        if not secrets_path.exists():
            parser.error(f"Secrets file {secrets_path} does not exist")
        secrets = parse_key_value_file(secrets_path)

    def pick(key: str, *fallback_keys: str, default: Optional[str] = None) -> Optional[str]:
        value = getattr(args, key)
        if value is not None:
            return value
        for candidate in fallback_keys:
            if candidate in secrets:
                return secrets[candidate]
        return default

    hostname = pick("hostname", "PI_HOSTNAME", default=preset.get("hostname"))
    username = pick("username", "PI_USERNAME", default=preset.get("username", ""))
    wifi_ssid = pick("wifi_ssid", "WIFI_SSID", default=preset.get("wifi", {}).get("ssid"))
    wifi_password = pick(
        "wifi_password", "WIFI_PASSWORD", default=preset.get("wifi", {}).get("password")
    )
    wifi_country = pick(
        "wifi_country", "WIFI_COUNTRY", default=preset.get("wifi", {}).get("country")
    )
    keyboard_layout = pick(
        "keyboard_layout",
        "KEYBOARD_LAYOUT",
        default=preset.get("locale", {}).get("keyboard_layout"),
    )
    keyboard_variant = pick(
        "keyboard_variant",
        "KEYBOARD_VARIANT",
        default=preset.get("locale", {}).get("keyboard_variant"),
    )
    timezone_value = pick("timezone", "TIMEZONE", default=preset.get("locale", {}).get("timezone"))

    wifi_hidden = args.wifi_hidden
    if wifi_hidden is None and "WIFI_HIDDEN" in secrets:
        wifi_hidden = maybe_bool(secrets["WIFI_HIDDEN"], field="WIFI_HIDDEN")
    if wifi_hidden is None:
        wifi_hidden = preset.get("wifi", {}).get("hidden")

    ssh_enabled = args.ssh_enabled
    if ssh_enabled is None and "SSH_ENABLED" in secrets:
        ssh_enabled = maybe_bool(secrets["SSH_ENABLED"], field="SSH_ENABLED")
    if ssh_enabled is None:
        ssh_enabled = preset.get("ssh", {}).get("enabled", True)

    ssh_password_auth = args.ssh_password_auth
    if ssh_password_auth is None and "SSH_PASSWORD_AUTH" in secrets:
        ssh_password_auth = maybe_bool(secrets["SSH_PASSWORD_AUTH"], field="SSH_PASSWORD_AUTH")
    if ssh_password_auth is None:
        ssh_password_auth = preset.get("ssh", {}).get("password_authentication", True)

    password_hash = pick("password_hash", "PI_PASSWORD_HASH", default=preset.get("password_hash"))
    plain_password = pick("password", "PI_PASSWORD")
    if plain_password:
        password_hash = hash_password(plain_password)
    if not ssh_password_auth:
        password_hash = None

    ssh_keys: List[str] = []
    ssh_keys.extend(preset.get("ssh", {}).get("authorized_keys", []))
    if "SSH_AUTHORIZED_KEY" in secrets:
        ssh_keys.append(secrets["SSH_AUTHORIZED_KEY"])
    if "SSH_AUTHORIZED_KEYS" in secrets:
        ssh_keys.append(secrets["SSH_AUTHORIZED_KEYS"])
    ssh_keys.extend(args.ssh_authorized_keys or [])
    for key_file in args.ssh_key_file or []:
        content = Path(key_file).read_text(encoding="utf-8")
        ssh_keys.append(content)
    ssh_keys = collect_ssh_keys(ssh_keys)

    if not hostname:
        parser.error("Hostname is required (set in JSON or via --hostname/PI_HOSTNAME)")
    if not username:
        parser.error("Username is required (set in JSON or via --username/PI_USERNAME)")
    if ssh_enabled and not (password_hash or ssh_keys):
        parser.error(
            "SSH is enabled but no password or authorized key was provided. "
            "Disable SSH or supply credentials."
        )

    settings: Dict[str, object] = {"sshEnabled": bool(ssh_enabled)}
    settings["hostname"] = hostname
    settings["sshUserName"] = username
    if password_hash:
        settings["sshUserPassword"] = password_hash
    if ssh_keys:
        settings["sshAuthorizedKeys"] = "\n".join(ssh_keys)
    if wifi_ssid:
        settings["wifiSSID"] = wifi_ssid
        if wifi_password is not None:
            settings["wifiPassword"] = wifi_password
        if wifi_country:
            settings["wifiCountry"] = wifi_country
        if wifi_hidden is not None:
            settings["wifiSSIDHidden"] = bool(wifi_hidden)
    if timezone_value:
        settings["timezone"] = timezone_value
    if keyboard_layout:
        settings["keyboardLayout"] = keyboard_layout
    if keyboard_variant:
        settings["keyboardVariant"] = keyboard_variant

    if not args.output and not args.apply:
        parser.error("Specify --output, --apply, or both.")

    if args.output:
        output_path = Path(args.output)
        write_ini(settings, output_path)
        print(f"Wrote preset snippet to {output_path}")

    if args.apply:
        updated_path = apply_to_imager_conf(settings)
        print(f"Updated Raspberry Pi Imager configuration at {updated_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
