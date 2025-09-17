#!/usr/bin/env python3
"""Generate Raspberry Pi Imager presets for sugarkube deployments."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Iterable, List


def _hash_secret(secret: str) -> str:
    try:
        import crypt
    except ImportError as exc:  # pragma: no cover - Windows fallback
        raise SystemExit(
            "Credential hashing requires the 'crypt' module. "
            "Run on a POSIX host or provide a pre-hashed value via the CLI option."
        ) from exc

    salt = crypt.mksalt(crypt.METHOD_SHA512)
    return crypt.crypt(secret, salt)


def _read_secret(path: Path) -> str:
    value = path.read_text(encoding="utf-8").strip()
    if not value:
        raise SystemExit(f"Secret file '{path}' is empty")
    return value


def _load_keys(key_args: Iterable[str], key_files: Iterable[Path]) -> List[str]:
    keys: List[str] = []
    seen = set()
    for key in key_args:
        normalized = key.strip()
        if not normalized:
            continue
        if normalized not in seen:
            keys.append(normalized)
            seen.add(normalized)
    for file_path in key_files:
        lines = file_path.read_text(encoding="utf-8").splitlines()
        for line in lines:
            normalized = line.strip()
            if not normalized:
                continue
            if normalized not in seen:
                keys.append(normalized)
                seen.add(normalized)
    return keys


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--hostname",
        required=True,
        help="Device hostname to embed in the preset.",
    )
    parser.add_argument(
        "--username",
        required=True,
        help="Primary login username.",
    )
    password_group = parser.add_mutually_exclusive_group(required=False)
    password_group.add_argument(
        "--password",
        help="Plaintext password that will be hashed with SHA-512.",
    )
    password_group.add_argument("--password-file", type=Path, help="Read password from this file.")
    password_group.add_argument(
        "--password-hash",
        help="Pre-hashed password (crypt $6$ format).",
    )
    parser.add_argument("--os-name", default="Raspberry Pi OS Lite (64-bit)")
    parser.add_argument("--timezone", default="UTC")
    parser.add_argument("--locale", default="en_US")
    parser.add_argument("--keyboard", default="us")
    parser.add_argument("--wifi-ssid", help="Wi-Fi SSID for first boot provisioning.")
    parser.add_argument("--wifi-password", help="Wi-Fi password.")
    parser.add_argument(
        "--wifi-country",
        default="US",
        help="Two-letter ISO country code (e.g., US).",
    )
    parser.add_argument(
        "--wifi-hidden",
        action="store_true",
        help="Mark the Wi-Fi network as hidden.",
    )
    parser.add_argument(
        "--ssh-key",
        action="append",
        default=[],
        help="SSH public key string to authorize. Can be provided multiple times.",
    )
    parser.add_argument(
        "--ssh-key-file",
        action="append",
        default=[],
        type=Path,
        help="File containing SSH public keys (one per line).",
    )
    parser.add_argument(
        "--persist-settings",
        dest="persist_settings",
        action="store_true",
        default=True,
        help="Persist advanced settings across flashes (default: true).",
    )
    parser.add_argument(
        "--no-persist-settings",
        dest="persist_settings",
        action="store_false",
        help="Disable persisting advanced settings on the SD card.",
    )
    parser.add_argument(
        "--disable-first-run",
        dest="disable_first_run",
        action="store_true",
        default=True,
        help="Skip Raspberry Pi OS first-run wizard (default: enabled).",
    )
    parser.add_argument(
        "--enable-first-run",
        dest="disable_first_run",
        action="store_false",
        help="Leave the Raspberry Pi OS first-run wizard enabled.",
    )
    parser.add_argument(
        "--output",
        default=Path("presets/sugarkube-preset.json"),
        type=Path,
        help="Destination file or '-' for stdout.",
    )
    parser.add_argument(
        "--pretty",
        action="store_true",
        help="Pretty-print JSON with indentation (default: compact).",
    )
    return parser.parse_args(argv)


def _resolve_password(args: argparse.Namespace) -> str:
    if args.password_hash:
        return args.password_hash

    env_path = os.environ.get("SUGARKUBE_PRESET_SECRET_FILE")
    password_file: Path | None = args.password_file
    if password_file is None and env_path:
        password_file = Path(env_path).expanduser()

    if password_file:
        secret = _read_secret(password_file)
    else:
        secret = args.password or ""

    if not secret:
        raise SystemExit(
            "Provide --password, --password-file, --password-hash, or set "
            "SUGARKUBE_PRESET_SECRET_FILE"
        )
    return _hash_secret(secret)


def _wifi_settings(args: argparse.Namespace) -> dict | None:
    if not args.wifi_ssid and not args.wifi_password:
        return None
    if args.wifi_ssid and not args.wifi_password:
        raise SystemExit("--wifi-password is required when --wifi-ssid is provided")
    if args.wifi_password and not args.wifi_ssid:
        raise SystemExit("--wifi-ssid is required when --wifi-password is provided")
    return {
        "ssid": args.wifi_ssid,
        "password": args.wifi_password,
        "country": args.wifi_country,
        "hidden": bool(args.wifi_hidden),
    }


def build_preset(args: argparse.Namespace) -> dict:
    password_hash = _resolve_password(args)
    ssh_keys = _load_keys(args.ssh_key, args.ssh_key_file)
    wifi = _wifi_settings(args)

    config: dict = {
        "hostname": args.hostname,
        "username": args.username,
        "password": password_hash,
        "disable_default_user": True,
        "persist_settings": bool(args.persist_settings),
        "skip_first_run": bool(args.disable_first_run),
        "locale": args.locale,
        "keyboard": args.keyboard,
        "timezone": args.timezone,
    }

    if ssh_keys:
        config["ssh"] = {"enabled": True, "authorized_keys": ssh_keys}
    else:
        config["ssh"] = {"enabled": True}

    if wifi:
        config["wifi"] = wifi
        config["wlan"] = wifi

    preset = {
        "version": 2,
        "os": {"name": args.os_name},
        "config": config,
    }
    return preset


def write_output(preset: dict, args: argparse.Namespace) -> None:
    if args.pretty:
        payload = json.dumps(preset, indent=2, sort_keys=True) + "\n"
    else:
        payload = json.dumps(preset, separators=(",", ":")) + "\n"

    if str(args.output) == "-":
        sys.stdout.write(payload)
        return

    output_path = Path(args.output).expanduser()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(payload, encoding="utf-8")
    print(f"Wrote preset to {output_path}")


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    preset = build_preset(args)
    write_output(preset, args)
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    raise SystemExit(main())
