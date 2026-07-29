#!/usr/bin/env python3
"""Prove DSPACE build identity, replica agreement, and the remote /chat journey."""

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
from typing import Any, Callable

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts import app_chart, app_config  # noqa: E402
from scripts import dspace_release_manifest as release  # noqa: E402

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
META_RE = re.compile(
    r'<meta\s+name=["\']dspace-build-revision["\']\s+content=["\']([^"\']+)["\']',
    re.IGNORECASE,
)


class VerificationError(ValueError):
    """A bounded, non-secret DSPACE verification failure."""


Runner = Callable[[list[str]], str]


def command(argv: list[str]) -> str:
    completed = subprocess.run(argv, check=False, capture_output=True, text=True)
    if completed.returncode:
        raise VerificationError(f"cluster identity: command failed: {Path(argv[0]).name}")
    return completed.stdout


def json_command(runner: Runner, argv: list[str], stage: str) -> dict[str, Any]:
    try:
        value = json.loads(runner(argv))
    except (OSError, json.JSONDecodeError) as exc:
        raise VerificationError(f"{stage}: invalid or unavailable JSON") from exc
    if not isinstance(value, dict):
        raise VerificationError(f"{stage}: expected a JSON object")
    return value


def read_url(url: str, expected_origin: str) -> bytes:
    request = urllib.request.Request(url, headers={"Accept": "application/json,text/html"})
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            final_origin = urllib.parse.urlsplit(response.geturl())
            actual = f"{final_origin.scheme}://{final_origin.netloc}"
            if actual != expected_origin:
                raise VerificationError("public identity: redirect crossed the approved origin")
            return response.read(1_048_577)
    except VerificationError:
        raise
    except (OSError, urllib.error.URLError) as exc:
        raise VerificationError("public identity: endpoint is unreachable") from exc


def identity(build_body: bytes, html_body: bytes, target: dict[str, Any], stage: str) -> None:
    if len(build_body) > 1_048_576 or len(html_body) > 1_048_576:
        raise VerificationError(f"{stage}: response exceeded the bounded limit")
    try:
        build = json.loads(build_body)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise VerificationError(f"{stage}: build identity was invalid") from exc
    expected_revision = target["sourceRevision"]
    if (
        not isinstance(build, dict)
        or build.get("version") != target["applicationVersion"]
        or build.get("revision") != expected_revision
        or build.get("shortRevision") != expected_revision[:7]
    ):
        raise VerificationError(f"{stage}: version or source revision mismatch")
    image = build.get("image")
    if image is not None and image not in {
        target["imageTag"],
        f"{release.IMAGE_REF}:{target['imageTag']}",
        f"{release.IMAGE_REF}:{target['imageTag']}@{target['imageDigest']}",
    }:
        raise VerificationError(f"{stage}: runtime image coordinate mismatch")
    try:
        marker = META_RE.search(html_body.decode("utf-8"))
    except UnicodeDecodeError as exc:
        raise VerificationError(f"{stage}: frontend marker was invalid") from exc
    if marker is None or marker.group(1) != expected_revision:
        raise VerificationError(f"{stage}: frontend source revision mismatch")


def _env_expectations(values: tuple[str, ...]) -> tuple[str | None, str | None, str]:
    document = app_chart.merged_values_document(values)
    found, env = app_chart.nested_value(document, ("env",))
    entries = env if found and isinstance(env, list) else []
    resolved = {
        item.get("name"): item.get("value")
        for item in entries
        if isinstance(item, dict) and isinstance(item.get("name"), str)
    }
    origin = resolved.get("DSPACE_TOKEN_PLACE_URL")
    model = resolved.get("DSPACE_TOKEN_PLACE_CHAT_MODEL")
    found, host = app_chart.nested_value(document, ("ingress", "host"))
    if not found or not isinstance(host, str) or not host:
        raise VerificationError("manifest/evidence mismatch: values do not select a public host")
    return (
        origin if isinstance(origin, str) else None,
        model if isinstance(model, str) else None,
        host,
    )


def _pods(
    runner: Runner,
    args: argparse.Namespace,
    target: dict[str, Any],
    token_origin: str | None,
    token_model: str | None,
) -> list[str]:
    selector = f"app.kubernetes.io/name=dspace,app.kubernetes.io/instance={args.release}"
    value = json_command(
        runner,
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
        ],
        "pod/replica identity",
    )
    names = []
    for pod in value.get("items", []):
        metadata = pod.get("metadata", {})
        status = pod.get("status", {})
        if metadata.get("deletionTimestamp") is not None:
            raise VerificationError("pod/replica identity: stale or terminating replica")
        ready = any(
            c.get("type") == "Ready" and c.get("status") == "True"
            for c in status.get("conditions", [])
        )
        containers = [
            c for c in pod.get("spec", {}).get("containers", []) if c.get("name") == "dspace"
        ]
        statuses = [c for c in status.get("containerStatuses", []) if c.get("name") == "dspace"]
        if (
            status.get("phase") != "Running"
            or not ready
            or len(containers) != 1
            or len(statuses) != 1
        ):
            raise VerificationError("pod/replica identity: every replica must be Running and Ready")
        expected_image = f"{release.IMAGE_REF}:{target['imageTag']}"
        if containers[0].get("image") not in {
            expected_image,
            f"{expected_image}@{target['imageDigest']}",
        }:
            raise VerificationError("pod/replica identity: image coordinate mismatch")
        live_env = {
            item.get("name"): item.get("value")
            for item in containers[0].get("env", [])
            if isinstance(item, dict)
        }
        if target["expectedDefaultChatProvider"] == "token-place" and (
            live_env.get("DSPACE_TOKEN_PLACE_URL") != token_origin
            or live_env.get("DSPACE_TOKEN_PLACE_CHAT_MODEL") != token_model
        ):
            raise VerificationError(
                "cluster identity: live token.place routing differs from values"
            )
        try:
            digest = release._image_id_digest(statuses[0].get("imageID", ""))
        except release.ManifestError as exc:
            raise VerificationError("pod/replica identity: invalid resolved image ID") from exc
        if digest != target["imageDigest"]:
            raise VerificationError("pod/replica identity: resolved image digest mismatch")
        name = metadata.get("name")
        if not isinstance(name, str) or not name:
            raise VerificationError("pod/replica identity: replica has no name")
        names.append(name)
    if not names:
        raise VerificationError("pod/replica identity: no serving replicas")
    return sorted(names)


def verify(args: argparse.Namespace, runner: Runner = command) -> dict[str, Any]:
    try:
        target = release.validate(release._object(args.manifest), None)
    except release.ManifestError as exc:
        raise VerificationError("manifest/evidence mismatch: invalid approved record") from exc
    if target["environment"] != args.environment:
        raise VerificationError("manifest/evidence mismatch: environment mismatch")
    config = app_config.load_config("dspace", args.environment, args.config or None)
    if (
        config["SUGARKUBE_RELEASE"] != args.release
        or config["SUGARKUBE_NAMESPACE"] != args.namespace
    ):
        raise VerificationError("manifest/evidence mismatch: release configuration mismatch")
    values = tuple(part.strip() for part in config["SUGARKUBE_VALUES"].split(",") if part.strip())
    origin, model, host = _env_expectations(values)
    helm = json_command(
        runner,
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
        ],
        "cluster identity",
    )
    metadata = helm.get("chart", {}).get("metadata", {})
    if (
        helm.get("name") != args.release
        or helm.get("namespace") != args.namespace
        or helm.get("info", {}).get("status") != "deployed"
        or metadata.get("name") != "dspace"
        or metadata.get("version") != target["chartVersion"]
    ):
        raise VerificationError("cluster identity: live Helm release/chart mismatch")
    if target.get("recordType") == "final" and helm.get("version") != target["helmRevision"]:
        raise VerificationError("concurrent Helm change: finalized Helm revision is stale")
    base_url = f"https://{host}"
    public_build = read_url(base_url + "/build-info.json", base_url)
    public_html = read_url(base_url + "/", base_url)
    identity(public_build, public_html, target, "public identity")
    pod_names = _pods(runner, args, target, origin, model)
    for pod in pod_names:
        prefix = f"/api/v1/namespaces/{args.namespace}/pods/{pod}:3000/proxy"
        try:
            direct_build = runner(
                [
                    "kubectl",
                    "--kubeconfig",
                    args.kubeconfig,
                    "get",
                    "--raw",
                    prefix + "/build-info.json",
                ]
            ).encode()
            direct_html = runner(
                ["kubectl", "--kubeconfig", args.kubeconfig, "get", "--raw", prefix + "/"]
            ).encode()
        except (OSError, VerificationError) as exc:
            raise VerificationError("direct identity: replica endpoint is unreachable") from exc
        identity(direct_build, direct_html, target, "direct identity")
    smoke = args.smoke_runner.expanduser()
    if not smoke.is_file() or not os.access(smoke, os.X_OK):
        raise VerificationError(
            "provider/chat smoke: smoke runner must be an existing executable file"
        )
    smoke_argv = [
        str(smoke),
        "--base-url",
        base_url,
        "--expected-version",
        target["applicationVersion"],
        "--expected-revision",
        target["sourceRevision"],
        "--expected-provider",
        target["expectedDefaultChatProvider"],
    ]
    if target["expectedDefaultChatProvider"] == "token-place":
        if not origin or not model:
            raise VerificationError("manifest/evidence mismatch: token.place values are incomplete")
        smoke_argv += [
            "--expected-token-place-origin",
            origin,
            "--expected-token-place-model",
            model,
        ]
    try:
        completed = subprocess.run(smoke_argv, check=False, capture_output=True, text=True)
    except OSError as exc:
        raise VerificationError("provider/chat smoke: smoke runner could not execute") from exc
    if completed.returncode:
        raise VerificationError("provider/chat smoke: remote /chat harness failed")
    return dict(
        zip(
            RESULT_FIELDS,
            (
                1,
                args.environment,
                args.release,
                args.namespace,
                target["applicationVersion"],
                target["sourceRevision"],
                target["sourceRevision"],
                target["expectedDefaultChatProvider"],
                [{"name": "/", "passed": True}, {"name": "/chat", "passed": True}],
            ),
        )
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command_name", required=True)
    for name in ("capabilities", "verify"):
        command_parser = sub.add_parser(name)
        command_parser.add_argument("--environment", required=True, choices=("staging", "prod"))
        command_parser.add_argument("--release", required=True)
        command_parser.add_argument("--namespace", required=True)
        if name == "verify":
            command_parser.add_argument("--manifest", type=Path, required=True)
            command_parser.add_argument("--smoke-runner", type=Path, required=True)
            command_parser.add_argument("--config", default="")
            command_parser.add_argument("--kubeconfig", required=True)
    args = parser.parse_args(argv)
    try:
        if args.command_name == "capabilities":
            result = {
                "schemaVersion": 1,
                "environment": args.environment,
                "release": args.release,
                "namespace": args.namespace,
                "capabilities": CAPABILITIES,
            }
        else:
            result = verify(args)
        print(json.dumps(result, separators=(",", ":"), ensure_ascii=True))
    except (VerificationError, app_config.AppConfigError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
