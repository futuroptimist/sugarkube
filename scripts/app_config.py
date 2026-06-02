#!/usr/bin/env python3
"""Resolve Sugarkube app configs and validate immutable deploy tags."""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import sys
from pathlib import Path
from typing import Mapping

SUPPORTED_ENVS = {"dev", "staging", "prod"}
EXAMPLE_FALLBACK_APPS = {"danielsmith", "dspace", "tokenplace"}
EXPECTED_KEYS = {
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
REQUIRED_KEYS = EXPECTED_KEYS - {"SUGARKUBE_DEBUG_SELECTOR"}
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
BRANCH_SHA_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*-[0-9a-fA-F]{7,40}$")
SEMVER_RE = re.compile(r"^v?\d+\.\d+\.\d+(?:[-+][0-9A-Za-z][0-9A-Za-z.-]*)?$")
KEY_RE = re.compile(r"^[A-Z][A-Z0-9_]*$")


class AppConfigError(ValueError):
    """Human-readable app config error."""


def normalize_named(value: str | None, name: str) -> str:
    value = (value or "").strip()
    prefix = f"{name}="
    while value.startswith(prefix):
        value = value[len(prefix) :].strip()
    return value


def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def parse_dotenv(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for lineno, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            raise AppConfigError(
                f"{path}:{lineno}: use plain KEY=value assignments, not export syntax"
            )
        if "=" not in line:
            raise AppConfigError(f"{path}:{lineno}: expected KEY=value assignment")
        key, raw_value = line.split("=", 1)
        key = key.strip()
        raw_value = raw_value.strip()
        if not KEY_RE.fullmatch(key):
            raise AppConfigError(f"{path}:{lineno}: invalid key {key!r}")
        if key not in EXPECTED_KEYS:
            raise AppConfigError(f"{path}:{lineno}: unknown app config key {key!r}")
        try:
            parsed = shlex.split(raw_value, comments=True, posix=True)
        except ValueError as exc:
            raise AppConfigError(f"{path}:{lineno}: invalid quoted value for {key}: {exc}") from exc
        if len(parsed) > 1:
            raise AppConfigError(f"{path}:{lineno}: {key} must be a single dotenv value")
        value = parsed[0] if parsed else ""
        if "\x00" in value or "\n" in value or "\r" in value:
            raise AppConfigError(f"{path}:{lineno}: {key} contains an unsafe control character")
        if any(token in value for token in ("$(`", "$(", "`", ";", "&&", "||")):
            raise AppConfigError(
                f"{path}:{lineno}: {key} contains shell syntax that is not allowed in app configs"
            )
        values[key] = value
    return values


def candidate_paths(app: str, explicit: str | None, environ: Mapping[str, str]) -> list[Path]:
    root = repo_root()
    paths: list[Path] = []
    if explicit:
        paths.append(Path(explicit).expanduser())
    config_dir = environ.get("SUGARKUBE_APP_CONFIG_DIR", "").strip()
    if config_dir:
        paths.append(Path(config_dir).expanduser() / f"{app}.env")
    paths.append(root / "apps" / f"{app}.env")
    if app in EXAMPLE_FALLBACK_APPS:
        paths.append(root / "docs" / "examples" / "apps" / f"{app}.env")
    return paths


def find_config(app: str, explicit: str | None, environ: Mapping[str, str] = os.environ) -> Path:
    for path in candidate_paths(app, explicit, environ):
        if path.is_file():
            return path
    searched = "\n  - ".join(str(p) for p in candidate_paths(app, explicit, environ))
    raise AppConfigError(f"No app config found for app={app!r}. Searched:\n  - {searched}")


def resolve_config(
    app: str, env: str, explicit: str | None = None, environ: Mapping[str, str] = os.environ
) -> dict[str, str]:
    app = normalize_named(app, "app")
    env = normalize_named(env, "env")
    if not app:
        raise AppConfigError("app must not be empty")
    if env not in SUPPORTED_ENVS:
        raise AppConfigError(f"env must be one of dev|staging|prod, got {env!r}")
    path = find_config(app, explicit, environ)
    data = parse_dotenv(path)
    missing = sorted(k for k in REQUIRED_KEYS if not data.get(k))
    if missing:
        raise AppConfigError(f"{path}: missing required keys: {', '.join(missing)}")
    configured_app = data["SUGARKUBE_APP"]
    if configured_app != app:
        raise AppConfigError(
            f"{path}: SUGARKUBE_APP={configured_app!r} does not match requested app={app!r}"
        )
    values_key = f"SUGARKUBE_VALUES_{env.upper()}"
    data["SUGARKUBE_ENV"] = env
    data["SUGARKUBE_CONFIG_PATH"] = str(path)
    data["SUGARKUBE_VALUES"] = data[values_key]
    data["SUGARKUBE_HOST_KEY"] = (
        data.get("SUGARKUBE_STATUS_HOST_KEY", "ingress.host") or "ingress.host"
    )
    data["SUGARKUBE_VERIFY_PATHS"] = data.get("SUGARKUBE_VERIFY_PATHS", "/") or "/"
    return data


def read_prod_tag(config: Mapping[str, str]) -> str:
    tag_file = config.get("SUGARKUBE_PROD_TAG_FILE", "")
    if not tag_file:
        return ""
    path = Path(tag_file)
    if not path.is_absolute():
        path = repo_root() / path
    try:
        for raw_line in path.read_text(encoding="utf-8").splitlines():
            line = raw_line.split("#", 1)[0].strip()
            if line:
                return line
    except FileNotFoundError:
        return ""
    return ""


def validate_tag(tag: str) -> str:
    tag = normalize_named(tag, "tag")
    if not tag:
        raise AppConfigError(
            "tag is required; use an immutable branch-SHA tag like main-deadbee "
            "or a release tag like v1.2.3"
        )
    tag_lc = tag.lower()
    if "latest" in tag_lc:
        raise AppConfigError(
            f"mutable tag {tag!r} is not allowed; use main-deadbee, feature-x-deadbee, or v1.2.3"
        )
    if BRANCH_SHA_RE.fullmatch(tag) or SEMVER_RE.fullmatch(tag):
        return tag
    if tag_lc in MOVING_TAGS:
        raise AppConfigError(
            f"mutable tag {tag!r} is not allowed; use an immutable branch-SHA tag "
            f"like {tag_lc}-deadbee or a release tag like v1.2.3"
        )
    if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", tag):
        raise AppConfigError(
            f"tag {tag!r} is missing an immutable suffix; use {tag}-deadbee "
            "or a semver release tag like v1.2.3"
        )
    raise AppConfigError(
        f"unsupported tag {tag!r}; use an immutable branch-SHA tag like main-deadbee "
        "or a semver release tag like v1.2.3"
    )


def load_values_yaml(path: Path) -> object:
    try:
        import yaml  # type: ignore[import-not-found]
    except Exception:
        return None
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception:
        return None


def get_dotted(payload: object, dotted_key: str) -> str:
    node = payload
    for part in dotted_key.split("."):
        if not isinstance(node, dict):
            return ""
        node = node.get(part)
    return str(node) if node else ""


def host_from_values(config: Mapping[str, str]) -> str:
    host_key = (
        config.get("SUGARKUBE_HOST_KEY")
        or config.get("SUGARKUBE_STATUS_HOST_KEY")
        or "ingress.host"
    )
    host = ""
    for raw in reversed((config.get("SUGARKUBE_VALUES") or "").split(",")):
        raw = raw.strip()
        if not raw:
            continue
        path = Path(raw)
        if not path.is_absolute():
            path = repo_root() / path
        payload = load_values_yaml(path)
        if payload is not None:
            host = get_dotted(payload, host_key)
            if host:
                return host
        # stdlib fallback for the common ingress.host shape.
        if host_key == "ingress.host" and path.is_file():
            in_ingress = False
            for line in path.read_text(encoding="utf-8").splitlines():
                if re.match(r"^ingress:\s*$", line):
                    in_ingress = True
                    continue
                if in_ingress and re.match(r"^[^\s]", line):
                    in_ingress = False
                match = re.match(r"^\s+host:\s*['\"]?([^'\"#\s]+)", line)
                if in_ingress and match:
                    return match.group(1)
    return host


def emit_shell(config: Mapping[str, str]) -> None:
    for key in sorted(config):
        if not (
            key in EXPECTED_KEYS
            or key
            in {"SUGARKUBE_ENV", "SUGARKUBE_CONFIG_PATH", "SUGARKUBE_VALUES", "SUGARKUBE_HOST_KEY"}
        ):
            raise AppConfigError(f"refusing to emit unexpected shell key {key!r}")
        print(f"{key}={shlex.quote(str(config[key]))}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("resolve", "shell", "json", "host", "prod-tag"):
        p = sub.add_parser(name)
        p.add_argument("--app", required=True)
        p.add_argument("--env", default="staging")
        p.add_argument("--config", default="")
    tag_p = sub.add_parser("validate-tag")
    tag_p.add_argument("tag")
    args = parser.parse_args(argv)
    try:
        if args.command == "validate-tag":
            print(validate_tag(args.tag))
            return 0
        config = resolve_config(args.app, args.env, args.config or None)
        if args.command == "shell":
            emit_shell(config)
        elif args.command == "json":
            print(json.dumps(config, sort_keys=True, indent=2))
        elif args.command == "host":
            print(host_from_values(config))
        elif args.command == "prod-tag":
            print(read_prod_tag(config))
        else:
            for key in sorted(config):
                print(f"{key}={config[key]}")
        return 0
    except AppConfigError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
