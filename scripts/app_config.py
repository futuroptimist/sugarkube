#!/usr/bin/env python3
"""Load Sugarkube app deployment config and validate immutable image tags."""

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
EXAMPLE_FALLBACK_APPS = {"danielsmith", "dspace", "tokenplace"}
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
ALLOWED_KEYS = {
    "SUGARKUBE_APP",
    "SUGARKUBE_RELEASE",
    "SUGARKUBE_NAMESPACE",
    "SUGARKUBE_CHART",
    "SUGARKUBE_VERSION",
    "SUGARKUBE_VERSION_FILE",
    "SUGARKUBE_PROD_TAG_FILE",
    "SUGARKUBE_VALUES_DEV",
    "SUGARKUBE_VALUES_STAGING",
    "SUGARKUBE_VALUES_PROD",
    "SUGARKUBE_STATUS_HOST_KEY",
    "SUGARKUBE_VERIFY_PATHS",
    "SUGARKUBE_DEBUG_SELECTOR",
    "SUGARKUBE_CORS_VERIFY_PATH",
    "SUGARKUBE_CORS_VERIFY_METHOD",
    "SUGARKUBE_CORS_VERIFY_REQUEST_HEADERS",
    "SUGARKUBE_CORS_VERIFY_BODY",
    "SUGARKUBE_CORS_VERIFY_EXPECTED_STATUSES",
}
REQUIRED_KEYS = {
    "SUGARKUBE_APP",
    "SUGARKUBE_RELEASE",
    "SUGARKUBE_NAMESPACE",
    "SUGARKUBE_CHART",
}
ASSIGNMENT_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)=(.*)$")
BRANCH_SHA_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*-[0-9a-f]{7,}$", re.IGNORECASE)
SEMVER_RE = re.compile(
    r"^v?[0-9]+\.[0-9]+\.[0-9]+(?:-[0-9A-Za-z][0-9A-Za-z.-]*)?(?:\+[0-9A-Za-z][0-9A-Za-z.-]*)?$"
)


class AppConfigError(ValueError):
    """Raised when app config or tag validation fails."""


def normalize_named(value: str, name: str) -> str:
    value = (value or "").strip()
    prefix = f"{name}="
    while value.startswith(prefix):
        value = value[len(prefix) :].strip()
    return value


def normalize_env(value: str) -> str:
    env = normalize_named(value, "env")
    if env == "int":
        env = "staging"
    if env not in SUPPORTED_ENVS:
        raise AppConfigError("env must be one of dev|staging|prod.")
    return env


def validate_app_name(app: str) -> str:
    app = normalize_named(app, "app")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", app or ""):
        raise AppConfigError(
            "app must be a non-empty name using letters, numbers, dots, underscores, "
            "or dashes."
        )
    return app


def validate_tag(tag: str) -> str:
    tag = normalize_named(tag, "tag")
    if not tag:
        raise AppConfigError(
            "tag must not be empty. Use an immutable tag such as main-deadbee or v0.1.0."
        )
    tag_lc = tag.lower()
    if tag_lc in MOVING_TAGS or "latest" in tag_lc:
        raise AppConfigError(
            f"mutable tag '{tag}' is not allowed. Use an immutable branch-SHA tag "
            "(example: main-deadbee) or a semver release tag (example: v0.1.0)."
        )
    if re.search(r"(^|[-_.])(dev|develop|staging|prod|production|release)([-_.]|$)", tag_lc):
        if not BRANCH_SHA_RE.fullmatch(tag):
            raise AppConfigError(
                f"environment-like moving tag '{tag}' is not allowed. Use an immutable "
                "branch-SHA tag ending in at least 7 hex characters."
            )
    if BRANCH_SHA_RE.fullmatch(tag) or SEMVER_RE.fullmatch(tag):
        return tag
    raise AppConfigError(
        f"invalid tag '{tag}'. Use an immutable branch-SHA tag (main-deadbee) "
        "or semver release tag."
    )


def iter_config_candidates(repo_root: Path, app: str, explicit: str | None) -> Iterable[Path]:
    if explicit:
        yield Path(explicit)
    config_dir = os.environ.get("SUGARKUBE_APP_CONFIG_DIR")
    if config_dir:
        yield Path(config_dir) / f"{app}.env"
    yield repo_root / "apps" / f"{app}.env"
    if app in EXAMPLE_FALLBACK_APPS:
        yield repo_root / "docs" / "examples" / "apps" / f"{app}.env"


def parse_dotenv(path: Path) -> dict[str, str]:
    data: dict[str, str] = {}
    for lineno, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        match = ASSIGNMENT_RE.fullmatch(line)
        if not match:
            raise AppConfigError(f"{path}:{lineno}: expected KEY=value dotenv assignment.")
        key, raw_value = match.groups()
        if key not in ALLOWED_KEYS:
            raise AppConfigError(f"{path}:{lineno}: unknown app config key '{key}'.")
        try:
            parts = shlex.split(raw_value, comments=True, posix=True)
        except ValueError as exc:
            raise AppConfigError(
                f"{path}:{lineno}: invalid quoted value for {key}: {exc}."
            ) from exc
        if len(parts) > 1:
            raise AppConfigError(f"{path}:{lineno}: {key} must be a single dotenv value.")
        value = parts[0] if parts else ""
        if any(token in raw_value for token in ("$(", "`", "$((", ";", "&&", "||")):
            raise AppConfigError(f"{path}:{lineno}: shell syntax is not allowed in {key}.")
        data[key] = value
    return data


def load_config(app: str, env: str, explicit: str | None = None) -> dict[str, str]:
    app = validate_app_name(app)
    env = normalize_env(env)
    repo_root = Path(__file__).resolve().parents[1]
    candidates = list(iter_config_candidates(repo_root, app, explicit))
    config_path = next((path for path in candidates if path.is_file()), None)
    if config_path is None:
        searched = ", ".join(str(path) for path in candidates)
        raise AppConfigError(f"no config found for app '{app}'. Searched: {searched}")
    data = parse_dotenv(config_path)
    missing = sorted(REQUIRED_KEYS - data.keys())
    if missing:
        raise AppConfigError(f"{config_path}: missing required keys: {', '.join(missing)}")
    if data["SUGARKUBE_APP"] != app:
        raise AppConfigError(
            f"{config_path}: SUGARKUBE_APP={data['SUGARKUBE_APP']!r} does not match app={app!r}."
        )
    if not (data.get("SUGARKUBE_VERSION") or data.get("SUGARKUBE_VERSION_FILE")):
        raise AppConfigError(
            f"{config_path}: missing chart version pin; set SUGARKUBE_VERSION "
            "or SUGARKUBE_VERSION_FILE."
        )
    values_key = f"SUGARKUBE_VALUES_{env.upper()}"
    values = data.get(values_key, "")
    if not values:
        raise AppConfigError(f"{config_path}: missing {values_key} for env={env}.")
    resolved = dict(data)
    resolved["SUGARKUBE_ENV"] = env
    resolved["SUGARKUBE_VALUES"] = values
    resolved["SUGARKUBE_CONFIG_PATH"] = str(config_path)
    resolved.setdefault("SUGARKUBE_STATUS_HOST_KEY", "ingress.host")
    resolved.setdefault("SUGARKUBE_VERIFY_PATHS", "/")
    return resolved


def resolve_tag(config: dict[str, str], raw_tag: str, *, prod_fallback: bool) -> str:
    tag = normalize_named(raw_tag, "tag")
    if not tag and prod_fallback:
        tag_file = config.get("SUGARKUBE_PROD_TAG_FILE", "")
        if tag_file:
            path = Path(tag_file)
            if not path.is_absolute():
                path = Path(__file__).resolve().parents[1] / path
            if path.is_file():
                for line in path.read_text(encoding="utf-8").splitlines():
                    line = line.split("#", 1)[0].strip()
                    if line:
                        tag = line
                        break
    return validate_tag(tag)


def shell_emit(config: dict[str, str]) -> str:
    keys = [
        "SUGARKUBE_APP",
        "SUGARKUBE_ENV",
        "SUGARKUBE_RELEASE",
        "SUGARKUBE_NAMESPACE",
        "SUGARKUBE_CHART",
        "SUGARKUBE_VALUES",
        "SUGARKUBE_VERSION",
        "SUGARKUBE_VERSION_FILE",
        "SUGARKUBE_PROD_TAG_FILE",
        "SUGARKUBE_STATUS_HOST_KEY",
        "SUGARKUBE_VERIFY_PATHS",
        "SUGARKUBE_DEBUG_SELECTOR",
        "SUGARKUBE_CORS_VERIFY_PATH",
        "SUGARKUBE_CORS_VERIFY_METHOD",
        "SUGARKUBE_CORS_VERIFY_REQUEST_HEADERS",
        "SUGARKUBE_CORS_VERIFY_BODY",
        "SUGARKUBE_CORS_VERIFY_EXPECTED_STATUSES",
        "SUGARKUBE_CONFIG_PATH",
        "SUGARKUBE_TAG",
    ]
    lines = []
    for key in keys:
        if key in config:
            lines.append(f"export {key}={shlex.quote(config[key])}")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("json", "shell"):
        cmd = sub.add_parser(name)
        cmd.add_argument("--app", required=True)
        cmd.add_argument("--env", required=True)
        cmd.add_argument("--config", default="")
        cmd.add_argument("--tag", default="")
        cmd.add_argument("--require-tag", action="store_true")
        cmd.add_argument("--prod-tag-fallback", action="store_true")
    validate = sub.add_parser("validate-tag")
    validate.add_argument("tag")
    host = sub.add_parser("host-value")
    host.add_argument("host_key")
    args = parser.parse_args(argv)
    try:
        if args.command == "validate-tag":
            print(validate_tag(args.tag))
            return 0
        if args.command == "host-value":
            data = json.load(sys.stdin)
            node = data
            for part in args.host_key.split("."):
                if not isinstance(node, dict):
                    return 0
                node = node.get(part)
            if node:
                print(node)
            return 0
        config = load_config(args.app, args.env, args.config or None)
        if args.require_tag or args.tag or args.prod_tag_fallback:
            config["SUGARKUBE_TAG"] = resolve_tag(
                config, args.tag, prod_fallback=bool(args.prod_tag_fallback)
            )
        if args.command == "json":
            print(json.dumps(config, indent=2, sort_keys=True))
        else:
            sys.stdout.write(shell_emit(config))
        return 0
    except AppConfigError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
