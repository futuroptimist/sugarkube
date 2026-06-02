#!/usr/bin/env python3
"""Load Sugarkube app deployment config files for generic just recipes."""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import sys
from pathlib import Path
from typing import Iterable

SUPPORTED_ENVS = {"dev", "staging", "prod"}
DEFAULT_HOST_KEY = "ingress.host"

ALLOWED_KEYS = {
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

MOVING_TAGS = {
    "latest",
    "main",
    "master",
    "dev",
    "develop",
    "development",
    "staging",
    "stage",
    "prod",
    "production",
    "release",
    "stable",
}
BRANCH_SHA_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*-[0-9a-fA-F]{7,}$")
SEMVER_RE = re.compile(r"^v?\d+\.\d+\.\d+(?:[-+][0-9A-Za-z][0-9A-Za-z._-]*)?$")
APP_RE = re.compile(r"^[A-Za-z0-9._-]+$")
KEY_RE = re.compile(r"^[A-Z][A-Z0-9_]*$")


class AppConfigError(ValueError):
    """Raised for config or argument validation errors."""


def normalize_named(value: str, name: str) -> str:
    value = (value or "").strip()
    prefix = f"{name}="
    while value.startswith(prefix):
        value = value[len(prefix) :].strip()
    return value


def parse_env_name(raw: str) -> str:
    env_name = normalize_named(raw, "env")
    if env_name == "int":
        env_name = "staging"
    if env_name not in SUPPORTED_ENVS:
        raise AppConfigError("env must be one of dev|staging|prod")
    return env_name


def parse_app_name(raw: str) -> str:
    app = normalize_named(raw, "app")
    if not app:
        raise AppConfigError("app must not be empty")
    if not APP_RE.match(app) or "/" in app or ".." in app:
        raise AppConfigError(
            "app must be a simple slug using letters, numbers, dot, underscore, or dash"
        )
    return app


def _strip_inline_comment(value: str) -> str:
    in_single = False
    in_double = False
    escaped = False
    out: list[str] = []
    for char in value:
        if escaped:
            out.append(char)
            escaped = False
            continue
        if char == "\\" and not in_single:
            out.append(char)
            escaped = True
            continue
        if char == "'" and not in_double:
            in_single = not in_single
        elif char == '"' and not in_single:
            in_double = not in_double
        if char == "#" and not in_single and not in_double:
            break
        out.append(char)
    if in_single or in_double:
        raise AppConfigError("unterminated quoted value")
    return "".join(out).strip()


def _parse_value(raw: str, line_no: int) -> str:
    raw = _strip_inline_comment(raw)
    if not raw:
        return ""
    if any(token in raw for token in ("$(", "`", "${", ";", "&&", "||", "<", ">")):
        raise AppConfigError(f"line {line_no}: shell syntax is not allowed in app configs")
    if (raw.startswith("'") and raw.endswith("'")) or (raw.startswith('"') and raw.endswith('"')):
        try:
            parts = shlex.split(raw, posix=True)
        except ValueError as exc:
            raise AppConfigError(f"line {line_no}: invalid quoted value: {exc}") from exc
        if len(parts) != 1:
            raise AppConfigError(f"line {line_no}: expected a single value")
        return parts[0]
    return raw.strip()


def parse_dotenv(path: Path) -> dict[str, str]:
    data: dict[str, str] = {}
    for line_no, original in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = original.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].lstrip()
        if "=" not in line:
            raise AppConfigError(f"line {line_no}: expected KEY=value assignment")
        key, raw_value = line.split("=", 1)
        key = key.strip()
        if not KEY_RE.match(key):
            raise AppConfigError(f"line {line_no}: invalid key {key!r}")
        if key not in ALLOWED_KEYS:
            raise AppConfigError(f"line {line_no}: unknown app config key {key!r}")
        data[key] = _parse_value(raw_value, line_no)
    missing = sorted(REQUIRED_KEYS - data.keys())
    if missing:
        raise AppConfigError(f"missing required app config keys: {', '.join(missing)}")
    return data


def candidate_paths(app: str, explicit_config: str | None = None) -> Iterable[Path]:
    if explicit_config:
        yield Path(explicit_config).expanduser()
        return
    config_dir = os.environ.get("SUGARKUBE_APP_CONFIG_DIR")
    if config_dir:
        yield Path(config_dir).expanduser() / f"{app}.env"
    yield Path("apps") / f"{app}.env"
    yield Path("docs/examples/apps") / f"{app}.env"


def load_config(app_raw: str, env_raw: str, explicit_config: str | None = None) -> dict[str, str]:
    app = parse_app_name(app_raw)
    env_name = parse_env_name(env_raw)
    checked: list[str] = []
    config_path = None
    for path in candidate_paths(app, explicit_config):
        checked.append(str(path))
        if path.is_file():
            config_path = path
            break
    if config_path is None:
        raise AppConfigError(f"no config found for app={app}; checked: {', '.join(checked)}")
    data = parse_dotenv(config_path)
    configured_app = data.get("SUGARKUBE_APP", "")
    if configured_app != app:
        raise AppConfigError(
            f"config {config_path} declares SUGARKUBE_APP={configured_app!r}, expected {app!r}"
        )
    values_key = f"SUGARKUBE_VALUES_{env_name.upper()}"
    data["SUGARKUBE_ENV"] = env_name
    data["SUGARKUBE_CONFIG_PATH"] = str(config_path)
    data["SUGARKUBE_VALUES"] = data[values_key]
    data["SUGARKUBE_STATUS_HOST_KEY"] = data.get("SUGARKUBE_STATUS_HOST_KEY") or DEFAULT_HOST_KEY
    data["SUGARKUBE_VERIFY_PATHS"] = data.get("SUGARKUBE_VERIFY_PATHS") or "/"
    return data


def validate_tag(tag_raw: str) -> str:
    tag = normalize_named(tag_raw, "tag")
    if not tag:
        raise AppConfigError(
            "tag must not be empty; use an immutable branch-SHA tag like "
            "main-deadbee or a release tag like v1.2.3"
        )
    if any(ch.isspace() for ch in tag) or any(ch in tag for ch in "/:@"):
        raise AppConfigError(
            f"invalid tag {tag!r}; use an image tag only, for example main-deadbee or v1.2.3"
        )
    lower = tag.lower()
    if "latest" in lower:
        raise AppConfigError(
            f"mutable tag {tag!r} is not allowed; use an immutable branch-SHA tag "
            "like main-deadbee or a release tag like v1.2.3"
        )
    if lower in MOVING_TAGS:
        raise AppConfigError(
            f"mutable tag {tag!r} is not allowed; use an immutable branch-SHA tag "
            f"like {lower}-deadbee or a release tag like v1.2.3"
        )
    if lower.endswith(tuple(f"-{name}" for name in MOVING_TAGS)):
        raise AppConfigError(
            f"environment-like moving tag {tag!r} is not allowed; use a tag "
            "ending in a Git SHA, for example main-deadbee"
        )
    if SEMVER_RE.match(tag) or BRANCH_SHA_RE.match(tag):
        return tag
    if re.search(r"-[0-9a-fA-F]{1,6}$", tag):
        raise AppConfigError(
            f"tag {tag!r} looks like a branch-SHA tag but the hex suffix is "
            "too short; use at least 7 hex characters"
        )
    raise AppConfigError(
        f"tag {tag!r} is not recognized as immutable; use branch-SHA tags "
        "like main-deadbee or semver tags like v1.2.3"
    )


def read_prod_tag(config: dict[str, str]) -> str:
    tag_file = Path(config["SUGARKUBE_PROD_TAG_FILE"])
    if not tag_file.is_file():
        return ""
    for line in tag_file.read_text(encoding="utf-8").splitlines():
        stripped = line.split("#", 1)[0].strip()
        if stripped:
            return stripped
    return ""


def shell_quote_map(values: dict[str, str]) -> str:
    return "\n".join(
        f"export {key}={shlex.quote(str(value))}" for key, value in sorted(values.items())
    )


def get_dotted(data: object, dotted_key: str) -> object | None:
    node = data
    for part in dotted_key.split("."):
        if not isinstance(node, dict):
            return None
        node = node.get(part)
    return node


def cmd_config(args: argparse.Namespace) -> int:
    config = load_config(args.app, args.env, args.config)
    if args.format == "shell":
        print(shell_quote_map(config))
    elif args.format == "json":
        print(json.dumps(config, indent=2, sort_keys=True))
    else:
        for key in sorted(config):
            print(f"{key}={config[key]}")
    return 0


def cmd_validate_tag(args: argparse.Namespace) -> int:
    print(validate_tag(args.tag))
    return 0


def cmd_prod_tag(args: argparse.Namespace) -> int:
    config = load_config(args.app, args.env, args.config)
    tag = normalize_named(args.tag or "", "tag") or read_prod_tag(config)
    print(validate_tag(tag))
    return 0


def cmd_extract_host(args: argparse.Namespace) -> int:
    try:
        data = json.load(sys.stdin)
    except json.JSONDecodeError as exc:
        raise AppConfigError(f"invalid Helm values JSON: {exc}") from exc
    host = get_dotted(data, args.host_key or DEFAULT_HOST_KEY)
    if host:
        print(host)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    config = sub.add_parser("config", help="load and print app config")
    config.add_argument("--app", required=True)
    config.add_argument("--env", required=True)
    config.add_argument("--config")
    config.add_argument("--format", choices=("env", "shell", "json"), default="env")
    config.set_defaults(func=cmd_config)

    validate = sub.add_parser("validate-tag", help="validate and normalize an immutable image tag")
    validate.add_argument("tag")
    validate.set_defaults(func=cmd_validate_tag)

    prod = sub.add_parser("prod-tag", help="resolve explicit tag or app prod tag file")
    prod.add_argument("--app", required=True)
    prod.add_argument("--env", default="prod")
    prod.add_argument("--config")
    prod.add_argument("--tag", default="")
    prod.set_defaults(func=cmd_prod_tag)

    host = sub.add_parser(
        "extract-host", help="extract dotted host key from Helm values JSON on stdin"
    )
    host.add_argument("--host-key", default=DEFAULT_HOST_KEY)
    host.set_defaults(func=cmd_extract_host)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except AppConfigError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
