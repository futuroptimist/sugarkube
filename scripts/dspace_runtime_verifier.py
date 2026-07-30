#!/usr/bin/env python3
"""Prove DSPACE build identity, replica agreement, and the public chat journey."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts import app_config  # noqa: E402
from scripts import dspace_release_manifest as release_manifest  # noqa: E402

CAPABILITIES = [
    "applicationVersion",
    "runtimeSourceRevision",
    "frontendSourceRevision",
    "defaultProvider",
    "publicJourneys",
]
RESULT_FIELDS = (
    "schemaVersion",
    "environment",
    "release",
    "namespace",
    "applicationVersion",
    "runtimeSourceRevision",
    "frontendSourceRevision",
    "defaultProvider",
    "journeys",
)
BUILD_FIELDS = {"version", "revision", "shortRevision", "image"}
META_RE = re.compile(
    r'<meta\s+[^>]*name=["\']dspace-build-revision["\'][^>]*content=["\']([^"\']+)',
    re.IGNORECASE,
)


class VerificationError(ValueError):
    """A bounded, non-secret verification failure."""


def fail(category: str) -> None:
    raise VerificationError(category)


def command(argv: list[str]) -> str:
    completed = subprocess.run(argv, text=True, capture_output=True, check=False)
    if completed.returncode:
        fail("cluster identity")
    return completed.stdout


class SameOriginRedirect(urllib.request.HTTPRedirectHandler):
    def __init__(self, origin: tuple[str, str]):
        self.origin = origin

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        parsed = urllib.parse.urlsplit(newurl)
        if (parsed.scheme, parsed.netloc) != self.origin:
            fail("public identity")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def fetch(url: str, public_origin: tuple[str, str] | None = None) -> bytes:
    opener = (
        urllib.request.build_opener(SameOriginRedirect(public_origin))
        if public_origin
        else urllib.request.build_opener()
    )
    try:
        with opener.open(url, timeout=15) as response:
            return response.read(1024 * 1024 + 1)
    except (OSError, urllib.error.URLError, VerificationError) as exc:
        if isinstance(exc, VerificationError):
            raise
        fail("public identity" if public_origin else "direct identity")
    raise AssertionError("unreachable")


def identity(raw: bytes, version: str, revision: str, image_tag: str, category: str) -> None:
    if len(raw) > 1024 * 1024:
        fail(category)
    try:
        value = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError):
        fail(category)
    if not isinstance(value, dict) or set(value) - BUILD_FIELDS:
        fail(category)
    if (
        value.get("version") != version
        or value.get("revision") != revision
        or value.get("shortRevision") != revision[:7]
    ):
        fail(category)
    image = value.get("image")
    if image is not None and image not in {image_tag, f"{release_manifest.IMAGE_REF}:{image_tag}"}:
        fail(category)


def marker(raw: bytes, revision: str, category: str) -> None:
    if len(raw) > 1024 * 1024:
        fail(category)
    try:
        match = META_RE.search(raw.decode("utf-8"))
    except UnicodeDecodeError:
        fail(category)
    if match is None or match.group(1) != revision:
        fail(category)


def values_expectations(paths: list[Path]) -> tuple[str, str]:
    """Resolve the two non-secret token.place settings from the ordered values chain."""
    wanted = {
        "DSPACE_TOKEN_PLACE_URL": None,
        "DSPACE_TOKEN_PLACE_CHAT_MODEL": None,
    }
    item = re.compile(r"^\s*-?\s*name:\s*([A-Z0-9_]+)\s*(?:#.*)?$")
    scalar = re.compile(r"^\s*value:\s*([^#]+?)\s*(?:#.*)?$")
    for path in paths:
        pending = None
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            fail("manifest/evidence mismatch")
        for line in lines:
            named = item.match(line)
            if named:
                pending = named.group(1) if named.group(1) in wanted else None
                continue
            valued = scalar.match(line)
            if pending and valued:
                wanted[pending] = valued.group(1).strip().strip("\"'")
                pending = None
    if not all(wanted.values()):
        fail("manifest/evidence mismatch")
    return str(wanted["DSPACE_TOKEN_PLACE_URL"]), str(wanted["DSPACE_TOKEN_PLACE_CHAT_MODEL"])


def load_manifest(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return release_manifest.validate(value)
    except (OSError, json.JSONDecodeError, release_manifest.ManifestError):
        fail("manifest/evidence mismatch")
    raise AssertionError("unreachable")


def verify(args: argparse.Namespace) -> dict[str, Any]:
    manifest = load_manifest(args.manifest)
    expected = {
        "version": manifest["applicationVersion"],
        "revision": manifest["sourceRevision"],
        "provider": manifest["expectedDefaultChatProvider"],
        "image_tag": manifest["imageTag"],
        "digest": manifest["imageDigest"],
    }
    for field, supplied in (
        ("version", args.application_version),
        ("revision", args.source_revision),
        ("provider", args.provider),
    ):
        if supplied is not None and supplied != expected[field]:
            fail("manifest/evidence mismatch")

    config = app_config.load_config(
        "dspace", args.environment, str(args.config) if args.config else None
    )
    values = [Path(item).expanduser() for item in config["SUGARKUBE_VALUES"].split(",")]
    values = [path if path.is_absolute() else REPO_ROOT / path for path in values]
    host = args.host or _resolve_host(values)
    base_url = f"https://{host}"
    origin = ("https", host)

    runner = args.smoke_runner or os.environ.get("DSPACE_SMOKE_RUNNER", "")
    smoke = Path(runner).expanduser() if runner else None
    if smoke is None or not smoke.is_file() or not os.access(smoke, os.X_OK):
        fail("provider/chat smoke")

    selector = f"app.kubernetes.io/name=dspace,app.kubernetes.io/instance={args.release}"
    raw_pods = command(
        [
            "kubectl",
            "--kubeconfig",
            args.kubeconfig,
            "-n",
            args.namespace,
            "get",
            "pods",
            "-l",
            selector,
            "-o",
            "json",
        ]
    )
    try:
        pods = json.loads(raw_pods).get("items", [])
    except (json.JSONDecodeError, AttributeError):
        fail("pod/replica identity")
    if not pods:
        fail("pod/replica identity")

    token_values = None
    if expected["provider"] == "token-place":
        token_values = values_expectations(values)
        try:
            deployment = json.loads(
                command(
                    [
                        "kubectl",
                        "--kubeconfig",
                        args.kubeconfig,
                        "-n",
                        args.namespace,
                        "get",
                        "deployment",
                        args.release,
                        "-o",
                        "json",
                    ]
                )
            )
            containers = deployment["spec"]["template"]["spec"]["containers"]
            application = next(item for item in containers if item.get("name") == "dspace")
            live_env = {item.get("name"): item.get("value") for item in application.get("env", [])}
        except (json.JSONDecodeError, KeyError, StopIteration, TypeError):
            fail("cluster identity")
        if (
            live_env.get("DSPACE_TOKEN_PLACE_URL") != token_values[0]
            or live_env.get("DSPACE_TOKEN_PLACE_CHAT_MODEL") != token_values[1]
        ):
            fail("cluster identity")

    direct_names = []
    for pod in pods:
        metadata, spec, status = pod.get("metadata", {}), pod.get("spec", {}), pod.get("status", {})
        if metadata.get("deletionTimestamp") is not None or status.get("phase") != "Running":
            fail("pod/replica identity")
        if not any(
            c.get("type") == "Ready" and c.get("status") == "True"
            for c in status.get("conditions", [])
        ):
            fail("pod/replica identity")
        containers = [c for c in spec.get("containers", []) if c.get("name") == "dspace"]
        statuses = [c for c in status.get("containerStatuses", []) if c.get("name") == "dspace"]
        approved_image = f"{release_manifest.IMAGE_REF}:{expected['image_tag']}"
        if len(containers) != 1 or containers[0].get("image") not in {
            approved_image,
            f"{approved_image}@{expected['digest']}",
        }:
            fail("pod/replica identity")
        if len(statuses) != 1 or not str(statuses[0].get("imageID", "")).endswith(
            expected["digest"]
        ):
            fail("pod/replica identity")
        name = metadata.get("name")
        if not isinstance(name, str) or not name:
            fail("pod/replica identity")
        direct_names.append(name)
        proxy = ["kubectl", "--kubeconfig", args.kubeconfig, "get", "--raw"]
        prefix = f"/api/v1/namespaces/{args.namespace}/pods/{name}:3000/proxy"
        try:
            direct_build = command(proxy + [prefix + "/build-info.json"]).encode()
            direct_html = command(proxy + [prefix + "/"]).encode()
        except VerificationError:
            fail("direct identity")
        identity(
            direct_build,
            expected["version"],
            expected["revision"],
            expected["image_tag"],
            "direct identity",
        )
        marker(direct_html, expected["revision"], "direct identity")

    identity(
        fetch(base_url + "/build-info.json", origin),
        expected["version"],
        expected["revision"],
        expected["image_tag"],
        "public identity",
    )
    marker(fetch(base_url + "/", origin), expected["revision"], "public identity")

    smoke_argv = [
        str(smoke),
        "--base-url",
        base_url,
        "--expected-version",
        expected["version"],
        "--expected-revision",
        expected["revision"],
        "--expected-provider",
        expected["provider"],
    ]
    if expected["provider"] == "token-place":
        assert token_values is not None
        token_origin, token_model = token_values
        smoke_argv += [
            "--expected-token-place-origin",
            token_origin,
            "--expected-token-place-model",
            token_model,
        ]
    completed = subprocess.run(smoke_argv, text=True, capture_output=True, check=False)
    if completed.returncode:
        fail("provider/chat smoke")
    return {
        "schemaVersion": 1,
        "environment": args.environment,
        "release": args.release,
        "namespace": args.namespace,
        "applicationVersion": expected["version"],
        "runtimeSourceRevision": expected["revision"],
        "frontendSourceRevision": expected["revision"],
        "defaultProvider": expected["provider"],
        "journeys": [
            {"name": "/build-info.json", "passed": True},
            {"name": "/", "passed": True},
            {"name": "/chat", "passed": True},
        ],
    }


def _resolve_host(paths: list[Path]) -> str:
    result = command(
        [
            sys.executable,
            str(REPO_ROOT / "scripts/app_chart.py"),
            "resolve-host",
            "--values",
            ",".join(str(path) for path in paths),
        ]
    ).strip()
    if not result or "/" in result:
        fail("manifest/evidence mismatch")
    return result


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser()
    sub = result.add_subparsers(dest="command", required=True)
    for name in ("capabilities", "verify"):
        item = sub.add_parser(name)
        item.add_argument("--environment", required=True, choices=("staging", "prod"))
        item.add_argument("--release", required=True)
        item.add_argument("--namespace", required=True)
        if name == "verify":
            item.add_argument("--manifest", type=Path, required=True)
            item.add_argument("--smoke-runner")
            item.add_argument("--config", type=Path)
            item.add_argument("--kubeconfig", required=True)
            item.add_argument("--host")
            item.add_argument("--application-version")
            item.add_argument("--source-revision")
            item.add_argument("--provider", choices=("token-place", "openai"))
    return result


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        value = (
            {
                "schemaVersion": 1,
                "environment": args.environment,
                "release": args.release,
                "namespace": args.namespace,
                "capabilities": CAPABILITIES,
            }
            if args.command == "capabilities"
            else verify(args)
        )
        print(json.dumps(value, separators=(",", ":")))
        return 0
    except (VerificationError, app_config.AppConfigError) as exc:
        if isinstance(exc, app_config.AppConfigError):
            exc = VerificationError("manifest/evidence mismatch")
        print(f"ERROR: DSPACE verification failed ({exc})", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
