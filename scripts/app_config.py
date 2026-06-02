#!/usr/bin/env python3
"""Load Sugarkube dotenv app configs and validate immutable app tags."""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import sys
from pathlib import Path
from typing import Mapping

REPO_ROOT = Path(__file__).resolve().parents[1]
SUPPORTED_ENVS = {"dev", "staging", "prod"}
MOVING_TAGS = {
    "latest",
    "main",
    "master",
    "dev",
    "develop",
    "staging",
    "prod",
    "production",
    "release",
}
KNOWN_KEYS = {
    "SUGARKUBE_APP",
    "SUGARKUBE_RELEASE",
    "SUGARKUBE_NAMESPACE",
    "SUGARKUBE_CHART",
    "SUGARKUBE_VERSION_FILE",
    "SUGARKUBE_PROD_TAG_FILE",
    "SUGARKUBE_VALUES_DEV",
    "SUGARKUBE_VALUES_STAGING",
    "SUGARKUBE_VALUES_PROD",
    "SUGARKUBE_STATUS_HOST_KEY",
    "SUGARKUBE_VERIFY_PATHS",
    "SUGARKUBE_DEBUG_SELECTOR",
}
REQUIRED_KEYS = {
    "SUGARKUBE_APP",
    "SUGARKUBE_RELEASE",
    "SUGARKUBE_NAMESPACE",
    "SUGARKUBE_CHART",
    "SUGARKUBE_VERSION_FILE",
    "SUGARKUBE_PROD_TAG_FILE",
    "SUGARKUBE_VALUES_DEV",
    "SUGARKUBE_VALUES_STAGING",
    "SUGARKUBE_VALUES_PROD",
}
DANGEROUS_VALUE_PATTERNS = ("`", "$(", ";", "&&", "||", "|", "<", ">")
KEY_RE = re.compile(r"^[A-Z][A-Z0-9_]*$")
APP_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
BRANCH_SHA_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*-[0-9a-fA-F]{7,}$")
SEMVER_RE = re.compile(
    r"^v?[0-9]+\.[0-9]+\.[0-9]+(?:-[0-9A-Za-z][0-9A-Za-z.-]*)?(?:\+[0-9A-Za-z][0-9A-Za-z.-]*)?$"
)


class ConfigError(ValueError):
    """Raised when app config cannot be safely loaded."""


def normalize_named_arg(value: str, name: str) -> str:
    """Strip repeated just named-arg prefixes, e.g. tag=tag=main-deadbee."""

    normalized = str(value or "").strip()
    prefix = f"{name}="
    while normalized.startswith(prefix):
        normalized = normalized[len(prefix) :]
    return normalized.strip()


def normalize_env(value: str) -> str:
    env = normalize_named_arg(value, "env") or "staging"
    if env == "int":
        env = "staging"
    if env not in SUPPORTED_ENVS:
        raise ConfigError(f"env must be one of dev|staging|prod, got {env!r}.")
    return env


def validate_app_slug(app: str) -> str:
    slug = normalize_named_arg(app, "app")
    if not slug or not APP_RE.match(slug):
        raise ConfigError("app must be a non-empty slug using letters, numbers, dots, underscores, or hyphens.")
    return slug


def candidate_paths(app: str, explicit_config: str = "") -> list[Path]:
    paths: list[Path] = []
    if explicit_config:
        paths.append(Path(explicit_config).expanduser())
    config_dir = os.environ.get("SUGARKUBE_APP_CONFIG_DIR", "").strip()
    if config_dir:
        paths.append(Path(config_dir).expanduser() / f"{app}.env")
    paths.append(REPO_ROOT / "apps" / f"{app}.env")
    paths.append(REPO_ROOT / "docs" / "examples" / "apps" / f"{app}.env")
    return paths


def resolve_config_path(app: str, explicit_config: str = "") -> Path:
    checked = candidate_paths(app, explicit_config)
    for path in checked:
        candidate = path if path.is_absolute() else REPO_ROOT / path
        if candidate.is_file():
            return candidate
    rendered = "\n  - ".join(str(p) for p in checked)
    raise ConfigError(f"No app config found for app={app}. Checked:\n  - {rendered}")


def strip_inline_comment(value: str) -> str:
    in_single = False
    in_double = False
    for index, char in enumerate(value):
        if char == "'" and not in_double:
            in_single = not in_single
        elif char == '"' and not in_single:
            in_double = not in_double
        elif char == "#" and not in_single and not in_double:
            if index == 0 or value[index - 1].isspace():
                return value[:index].rstrip()
    return value.strip()


def parse_value(raw_value: str, line_number: int) -> str:
    value = strip_inline_comment(raw_value.strip())
    if not value:
        return ""
    if (value[0], value[-1:]) in {("'", "'"), ('"', '"')}:
        try:
            parts = shlex.split(value, posix=True)
        except ValueError as exc:
            raise ConfigError(f"line {line_number}: invalid quoted value: {exc}") from exc
        if len(parts) != 1:
            raise ConfigError(f"line {line_number}: quoted values must contain one token.")
        value = parts[0]
    elif any(ch.isspace() for ch in value):
        raise ConfigError(f"line {line_number}: unquoted values may not contain whitespace.")
    for pattern in DANGEROUS_VALUE_PATTERNS:
        if pattern in value:
            raise ConfigError(
                f"line {line_number}: value contains unsupported shell syntax {pattern!r}; "
                "app configs must be static dotenv assignments."
            )
    return value


def load_dotenv(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].lstrip()
        if "=" not in line:
            raise ConfigError(f"line {line_number}: expected KEY=value assignment.")
        key, raw_value = line.split("=", 1)
        key = key.strip()
        if not KEY_RE.match(key):
            raise ConfigError(f"line {line_number}: invalid key {key!r}.")
        if key not in KNOWN_KEYS:
            raise ConfigError(f"line {line_number}: unsupported app config key {key!r}.")
        values[key] = parse_value(raw_value, line_number)
    missing = sorted(REQUIRED_KEYS - values.keys())
    if missing:
        raise ConfigError(f"missing required app config keys: {', '.join(missing)}")
    return values


def load_app_config(app: str, env: str, explicit_config: str = "") -> dict[str, str]:
    app_slug = validate_app_slug(app)
    env_name = normalize_env(env)
    path = resolve_config_path(app_slug, explicit_config)
    values = load_dotenv(path)
    configured_app = values.get("SUGARKUBE_APP", "")
    if configured_app != app_slug:
        raise ConfigError(
            f"config {path} declares SUGARKUBE_APP={configured_app!r}, expected {app_slug!r}."
        )
    values_key = f"SUGARKUBE_VALUES_{env_name.upper()}"
    values_chain = values.get(values_key, "")
    if not values_chain:
        raise ConfigError(f"config {path} does not define {values_key}.")
    resolved = dict(values)
    resolved["SUGARKUBE_ENV"] = env_name
    resolved["SUGARKUBE_CONFIG_PATH"] = str(path)
    resolved["SUGARKUBE_VALUES"] = values_chain
    resolved.setdefault("SUGARKUBE_STATUS_HOST_KEY", "ingress.host")
    resolved.setdefault("SUGARKUBE_VERIFY_PATHS", "/")
    resolved.setdefault("SUGARKUBE_DEBUG_SELECTOR", f"app.kubernetes.io/name={app_slug}")
    return resolved


def validate_immutable_tag(tag: str) -> str:
    candidate = normalize_named_arg(tag, "tag")
    if not candidate:
        raise ConfigError(
            "tag is required. Use an immutable branch-SHA tag like main-deadbee or a semver release tag like v1.2.3."
        )
    lowered = candidate.lower()
    if "latest" in lowered:
        raise ConfigError(
            f"mutable tag {candidate!r} is not allowed. Use an immutable branch-SHA tag like main-deadbee or a semver release tag."
        )
    if lowered in MOVING_TAGS:
        raise ConfigError(
            f"mutable tag {candidate!r} is not allowed. Bare branch/environment tags move; use branch-SHA (main-deadbee) or semver."
        )
    for moving in MOVING_TAGS - {"latest"}:
        if lowered.endswith(f"-{moving}"):
            raise ConfigError(
                f"environment-like moving tag {candidate!r} is not allowed. Use branch-SHA (main-deadbee) or semver."
            )
    if BRANCH_SHA_RE.match(candidate) or SEMVER_RE.match(candidate):
        return candidate
    raise ConfigError(
        f"tag {candidate!r} is not recognized as immutable. Use branch-SHA with a 7+ hex suffix (main-deadbee) or semver (v1.2.3)."
    )


def read_prod_tag(path_value: str) -> str:
    path = Path(path_value).expanduser()
    if not path.is_absolute():
        path = REPO_ROOT / path
    if not path.is_file():
        return ""
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.split("#", 1)[0].strip()
        if line:
            return line
    return ""


def dotted_get(payload: object, dotted_key: str) -> object | None:
    node = payload
    for part in dotted_key.split("."):
        if not isinstance(node, dict):
            return None
        node = node.get(part)
    return node


def emit_shell(config: Mapping[str, str]) -> None:
    ordered_keys = [
        "SUGARKUBE_CONFIG_PATH",
        "SUGARKUBE_APP",
        "SUGARKUBE_ENV",
        "SUGARKUBE_RELEASE",
        "SUGARKUBE_NAMESPACE",
        "SUGARKUBE_CHART",
        "SUGARKUBE_VERSION_FILE",
        "SUGARKUBE_PROD_TAG_FILE",
        "SUGARKUBE_VALUES",
        "SUGARKUBE_STATUS_HOST_KEY",
        "SUGARKUBE_VERIFY_PATHS",
        "SUGARKUBE_DEBUG_SELECTOR",
    ]
    for key in ordered_keys:
        print(f"export {key}={shlex.quote(config.get(key, ''))}")


def emit_human(config: Mapping[str, str]) -> None:
    for key in sorted(config):
        print(f"{key}={config[key]}")


def command_config(args: argparse.Namespace) -> int:
    config = load_app_config(args.app, args.env, args.config)
    if args.format == "shell":
        emit_shell(config)
    elif args.format == "json":
        print(json.dumps(config, indent=2, sort_keys=True))
    else:
        emit_human(config)
    return 0


def command_validate_tag(args: argparse.Namespace) -> int:
    print(validate_immutable_tag(args.tag))
    return 0


def command_prod_tag(args: argparse.Namespace) -> int:
    config = load_app_config(args.app, "prod", args.config)
    tag = normalize_named_arg(args.tag or "", "tag") or read_prod_tag(config["SUGARKUBE_PROD_TAG_FILE"])
    print(validate_immutable_tag(tag))
    return 0


def command_host(args: argparse.Namespace) -> int:
    try:
        payload = json.load(sys.stdin)
    except json.JSONDecodeError as exc:
        raise ConfigError(f"unable to parse Helm values JSON: {exc}") from exc
    host = dotted_get(payload, args.host_key or "ingress.host")
    if host:
        print(host)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    config_parser = subparsers.add_parser("config", help="resolve app config")
    config_parser.add_argument("--app", required=True)
    config_parser.add_argument("--env", default="staging")
    config_parser.add_argument("--config", default="")
    config_parser.add_argument("--format", choices=("human", "shell", "json"), default="human")
    config_parser.set_defaults(func=command_config)

    tag_parser = subparsers.add_parser("validate-tag", help="validate and normalize immutable tag")
    tag_parser.add_argument("tag")
    tag_parser.set_defaults(func=command_validate_tag)

    prod_tag_parser = subparsers.add_parser("prod-tag", help="resolve explicit or configured prod tag")
    prod_tag_parser.add_argument("--app", required=True)
    prod_tag_parser.add_argument("--config", default="")
    prod_tag_parser.add_argument("--tag", default="")
    prod_tag_parser.set_defaults(func=command_prod_tag)

    host_parser = subparsers.add_parser("host", help="extract a dotted host key from Helm values JSON")
    host_parser.add_argument("--host-key", default="ingress.host")
    host_parser.set_defaults(func=command_host)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except ConfigError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
