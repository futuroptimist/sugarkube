#!/usr/bin/env python3
"""Prove DSPACE public and per-replica identity and its remote chat journey.

Only bounded, non-secret facts are emitted.  In particular, HTTP and child-process
output is never included in diagnostics or in the result document.
"""

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
MARKER_RE = re.compile(
    r"<meta\s+[^>]*name=[\"']dspace-build-revision[\"'][^>]*content=[\"']([^\"']+)",
    re.IGNORECASE,
)


class VerificationError(ValueError):
    """A safe, classified verification failure."""


class SafeArgumentParser(argparse.ArgumentParser):
    """Reject malformed input without reflecting values that may be secrets."""

    def error(self, message: str) -> None:
        self.exit(2, "ERROR: invalid arguments\n")


def fail(stage: str) -> None:
    raise VerificationError(f"{stage} verification failed")


def command(argv: list[str], stage: str) -> str:
    completed = subprocess.run(argv, capture_output=True, text=True, check=False)
    if completed.returncode:
        fail(stage)
    return completed.stdout


def json_command(argv: list[str], stage: str) -> dict[str, Any]:
    try:
        value = json.loads(command(argv, stage))
    except (json.JSONDecodeError, UnicodeError):
        fail(stage)
    if not isinstance(value, dict):
        fail(stage)
    return value


class SameOriginRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        if urllib.parse.urlsplit(newurl)[:2] != urllib.parse.urlsplit(req.full_url)[:2]:
            fail("public identity")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def get(url: str, stage: str) -> str:
    try:
        with urllib.request.build_opener(SameOriginRedirect()).open(url, timeout=15) as response:
            if response.status != 200:
                fail(stage)
            return response.read(1024 * 1024).decode("utf-8")
    except VerificationError:
        raise
    except (OSError, UnicodeError, urllib.error.URLError):
        fail(stage)


def identity(build_text: str, html: str, manifest: dict[str, Any], stage: str) -> None:
    try:
        build = json.loads(build_text)
    except json.JSONDecodeError:
        fail(stage)
    revision = manifest["sourceRevision"]
    if (
        not isinstance(build, dict)
        or build.get("applicationVersion") != manifest["applicationVersion"]
    ):
        fail(stage)
    if build.get("revision") != revision or build.get("shortRevision") != revision[:7]:
        fail(stage)
    coordinate = build.get("image") or build.get("imageCoordinate")
    if (
        coordinate is not None
        and coordinate != f"{release_manifest.IMAGE_REF}:{manifest['imageTag']}"
    ):
        fail(stage)
    marker = MARKER_RE.search(html)
    if marker is None or marker.group(1) != revision:
        fail(stage)


def values_expectations(paths: str) -> tuple[str, str, str]:
    try:
        import yaml

        merged: dict[str, Any] = {}
        for name in paths.split(","):
            document = yaml.safe_load(Path(name).read_text(encoding="utf-8")) or {}
            merged.update(document)
        host = merged.get("ingress", {}).get("host")
        env = {item.get("name"): item.get("value") for item in merged.get("env", [])}
        origin = env.get("DSPACE_TOKEN_PLACE_URL")
        model = env.get("DSPACE_TOKEN_PLACE_CHAT_MODEL")
    except (OSError, AttributeError, TypeError, ValueError):
        fail("manifest/evidence mismatch")
    if not all(isinstance(item, str) and item for item in (host, origin, model)):
        fail("manifest/evidence mismatch")
    return host, origin, model


def verify(args: argparse.Namespace) -> dict[str, Any]:
    try:
        manifest = release_manifest.validate(release_manifest._object(args.manifest))
    except release_manifest.ManifestError:
        fail("manifest/evidence mismatch")
    if manifest["environment"] != args.environment:
        fail("manifest/evidence mismatch")
    if not args.smoke_runner.is_file() or not os.access(args.smoke_runner, os.X_OK):
        fail("provider/chat smoke")
    config = app_config.load_config("dspace", args.environment, args.config or None)
    host, token_origin, token_model = values_expectations(config["SUGARKUBE_VALUES"])
    base_url = "https://" + host
    identity(
        get(base_url + "/build-info.json", "public identity"),
        get(base_url + "/", "public identity"),
        manifest,
        "public identity",
    )

    kubectl = ["kubectl", "--kubeconfig", args.kubeconfig, "-n", args.namespace]
    selector = f"app.kubernetes.io/name=dspace,app.kubernetes.io/instance={args.release}"
    pods = json_command(
        kubectl + ["get", "pods", "-l", selector, "-o", "json"], "pod/replica identity"
    ).get("items")
    if not isinstance(pods, list) or not pods:
        fail("pod/replica identity")
    names: list[str] = []
    for pod in pods:
        metadata, spec, status = pod.get("metadata", {}), pod.get("spec", {}), pod.get("status", {})
        if metadata.get("deletionTimestamp") or status.get("phase") != "Running":
            fail("pod/replica identity")
        if not any(
            c.get("type") == "Ready" and c.get("status") == "True"
            for c in status.get("conditions", [])
        ):
            fail("pod/replica identity")
        containers = [c for c in spec.get("containers", []) if c.get("name") == "dspace"]
        states = [c for c in status.get("containerStatuses", []) if c.get("name") == "dspace"]
        if len(containers) != 1 or len(states) != 1:
            fail("pod/replica identity")
        if containers[0].get("image") != f"{release_manifest.IMAGE_REF}:{manifest['imageTag']}":
            fail("pod/replica identity")
        if (
            release_manifest._image_id_digest(states[0].get("imageID", ""))
            != manifest["imageDigest"]
        ):
            fail("pod/replica identity")
        name = metadata.get("name")
        if not isinstance(name, str) or not name:
            fail("pod/replica identity")
        names.append(name)
        proxy = f"/api/v1/namespaces/{args.namespace}/pods/{name}:{args.port}/proxy"
        direct_build = command(
            kubectl + ["get", "--raw", proxy + "/build-info.json"], "direct identity"
        )
        direct_html = command(kubectl + ["get", "--raw", proxy + "/"], "direct identity")
        identity(direct_build, direct_html, manifest, "direct identity")

    smoke = [
        str(args.smoke_runner),
        "--base-url",
        base_url,
        "--expected-version",
        manifest["applicationVersion"],
        "--expected-revision",
        manifest["sourceRevision"],
        "--expected-provider",
        manifest["expectedDefaultChatProvider"],
    ]
    if manifest["expectedDefaultChatProvider"] == "token-place":
        smoke += [
            "--expected-token-place-origin",
            token_origin,
            "--expected-token-place-model",
            token_model,
        ]
    command(smoke, "provider/chat smoke")
    return {
        "schemaVersion": 1,
        "environment": args.environment,
        "release": args.release,
        "namespace": args.namespace,
        "applicationVersion": manifest["applicationVersion"],
        "runtimeSourceRevision": manifest["sourceRevision"],
        "frontendSourceRevision": manifest["sourceRevision"],
        "defaultProvider": manifest["expectedDefaultChatProvider"],
        "journeys": [
            {"name": "/build-info.json", "passed": True},
            {"name": "/chat", "passed": True},
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = SafeArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True, parser_class=SafeArgumentParser)
    for name in ("capabilities", "verify"):
        child = sub.add_parser(name)
        child.add_argument("--environment", choices=("staging", "prod"), required=True)
        child.add_argument("--release", default="dspace")
        child.add_argument("--namespace", default="dspace")
        if name == "verify":
            child.add_argument("--manifest", type=Path, required=True)
            child.add_argument("--smoke-runner", type=Path, required=True)
            child.add_argument("--config", type=Path)
            child.add_argument("--kubeconfig", required=True)
            child.add_argument("--port", type=int, default=3000)
    args = parser.parse_args(argv)
    try:
        if args.command == "capabilities":
            result = {
                "schemaVersion": 1,
                "environment": args.environment,
                "release": args.release,
                "namespace": args.namespace,
                "capabilities": CAPABILITIES,
            }
        else:
            result = verify(args)
        print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    except (VerificationError, KeyError, app_config.AppConfigError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
