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

from scripts import app_chart  # noqa: E402
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


def identity(
    raw: bytes, version: str, revision: str, image: str, category: str
) -> tuple[str, str, str]:
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
    runtime_image = value.get("image")
    if runtime_image is not None and runtime_image != image:
        fail(category)
    return version, revision, runtime_image or image


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
    """Resolve token.place settings through the same ordered merge used by app_chart."""
    try:
        document = app_chart.merged_values_document(tuple(str(path) for path in paths))
    except (ValueError, json.JSONDecodeError):
        fail("manifest/evidence mismatch")
    found: dict[str, str] = {}

    def visit(value: object) -> None:
        if isinstance(value, dict):
            name = value.get("name")
            scalar = value.get("value")
            if name in {"DSPACE_TOKEN_PLACE_URL", "DSPACE_TOKEN_PLACE_CHAT_MODEL"} and isinstance(
                scalar, str
            ):
                found[str(name)] = scalar
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    visit(document)
    if set(found) != {"DSPACE_TOKEN_PLACE_URL", "DSPACE_TOKEN_PLACE_CHAT_MODEL"}:
        fail("manifest/evidence mismatch")
    return found["DSPACE_TOKEN_PLACE_URL"], found["DSPACE_TOKEN_PLACE_CHAT_MODEL"]


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

    approved_image = f"{release_manifest.IMAGE_REF}:{expected['image_tag']}@{expected['digest']}"
    token_values = values_expectations(values) if expected["provider"] == "token-place" else None
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
        applications = [item for item in containers if item.get("name") == "dspace"]
    except (json.JSONDecodeError, KeyError, TypeError):
        fail("cluster identity")
    if len(applications) != 1 or applications[0].get("image") != approved_image:
        fail("cluster identity")
    if token_values is not None:
        live_env = {item.get("name"): item.get("value") for item in applications[0].get("env", [])}
        if (
            live_env.get("DSPACE_TOKEN_PLACE_URL") != token_values[0]
            or live_env.get("DSPACE_TOKEN_PLACE_CHAT_MODEL") != token_values[1]
        ):
            fail("cluster identity")

    helm_before = helm_identity(args)

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
        if len(containers) != 1 or containers[0].get("image") != approved_image:
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
        direct_identity = identity(
            direct_build,
            expected["version"],
            expected["revision"],
            approved_image,
            "direct identity",
        )
        if direct_names and "replica_identity" in locals() and direct_identity != replica_identity:
            fail("pod/replica identity")
        replica_identity = direct_identity
        marker(direct_html, expected["revision"], "direct identity")

    public_identity = identity(
        fetch(base_url + "/build-info.json", origin),
        expected["version"],
        expected["revision"],
        approved_image,
        "public identity",
    )
    if public_identity != replica_identity:
        fail("public identity")
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
    if helm_identity(args) != helm_before:
        fail("cluster identity")
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


def helm_identity(args: argparse.Namespace) -> tuple[str, str, int]:
    try:
        status = json.loads(
            command(
                [
                    "helm",
                    "--kubeconfig",
                    args.kubeconfig,
                    "status",
                    args.release,
                    "--namespace",
                    args.namespace,
                    "-o",
                    "json",
                ]
            )
        )
        chart = status["chart"]
        revision = status["version"]
    except (json.JSONDecodeError, KeyError, TypeError):
        fail("cluster identity")
    if not isinstance(chart, str) or not chart.startswith("dspace-") or type(revision) is not int:
        fail("cluster identity")
    if (
        getattr(args, "expected_helm_revision", None) is not None
        and revision != args.expected_helm_revision
    ):
        fail("cluster identity")
    return chart.rsplit("-", 1)[0], chart.rsplit("-", 1)[-1], revision


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


class SafeParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise VerificationError("invalid arguments")


def parser() -> argparse.ArgumentParser:
    result = SafeParser()
    sub = result.add_subparsers(dest="command", required=True)
    for name in ("capabilities", "verify"):
        item = sub.add_parser(name)
        item.add_argument("--environment", required=True, choices=("staging", "prod"))
        item.add_argument("--release", required=True)
        item.add_argument("--namespace", required=True)
        if name == "capabilities":
            # Accepted but deliberately unused so callers can negotiate the
            # extended verify argv before a deployment or rollback mutation.
            item.add_argument("--manifest", type=Path)
            item.add_argument("--smoke-runner")
            item.add_argument("--config", type=Path)
            item.add_argument("--kubeconfig")
        else:
            item.add_argument("--manifest", type=Path, required=True)
            item.add_argument("--smoke-runner")
            item.add_argument("--config", type=Path)
            item.add_argument("--kubeconfig", required=True)
            item.add_argument("--host")
            item.add_argument("--application-version")
            item.add_argument("--source-revision")
            item.add_argument("--provider", choices=("token-place", "openai"))
            item.add_argument("--expected-helm-revision", type=int)
    return result


def main(argv: list[str] | None = None) -> int:
    try:
        args = parser().parse_args(argv)
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
