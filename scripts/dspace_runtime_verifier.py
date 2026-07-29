#!/usr/bin/env python3
"""Prove DSPACE runtime identity and the non-destructive public /chat journey."""

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

CAPABILITIES = (
    "applicationVersion",
    "runtimeSourceRevision",
    "frontendSourceRevision",
    "defaultProvider",
    "publicJourneys",
)
IMAGE_REF = "ghcr.io/democratizedspace/dspace"
REVISION_META = re.compile(
    rb'<meta\s+name=["\']dspace-build-revision["\']\s+content=["\']([^"\']+)["\']',
    re.IGNORECASE,
)


class VerificationError(ValueError):
    """A bounded, non-secret verification failure."""


Runner = Callable[[list[str]], str]


def run(command: list[str]) -> str:
    try:
        completed = subprocess.run(command, capture_output=True, check=False, text=True)
    except OSError as exc:
        raise VerificationError(f"cluster identity: could not execute {command[0]}") from exc
    if completed.returncode:
        raise VerificationError(f"cluster identity: {command[0]} command failed")
    return completed.stdout


def json_run(runner: Runner, command: list[str], stage: str) -> Any:
    try:
        return json.loads(runner(command))
    except (OSError, json.JSONDecodeError) as exc:
        raise VerificationError(f"{stage}: command did not return valid JSON") from exc


def fetch(url: str, expected_origin: str, opener=urllib.request.urlopen) -> bytes:
    request = urllib.request.Request(url, headers={"Accept": "application/json,text/html"})
    try:
        with opener(request, timeout=15) as response:
            final = urllib.parse.urlsplit(response.geturl())
            expected = urllib.parse.urlsplit(expected_origin)
            if (final.scheme, final.netloc) != (expected.scheme, expected.netloc):
                raise VerificationError("public identity: redirect crossed the approved origin")
            return response.read(1_048_577)
    except VerificationError:
        raise
    except (OSError, urllib.error.URLError) as exc:
        raise VerificationError("public identity: endpoint was unreachable") from exc


def identity(raw: bytes, version: str, revision: str, image_tag: str, stage: str) -> None:
    if len(raw) > 1_048_576:
        raise VerificationError(f"{stage}: response exceeded the bounded limit")
    try:
        value = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise VerificationError(f"{stage}: build identity was malformed") from exc
    if not isinstance(value, dict):
        raise VerificationError(f"{stage}: build identity was malformed")
    if value.get("version") != version or value.get("revision") != revision:
        raise VerificationError(f"{stage}: version or revision mismatch")
    if value.get("shortRevision") != revision[:7]:
        raise VerificationError(f"{stage}: short revision mismatch")
    coordinate = value.get("image") or value.get("imageCoordinate")
    if coordinate is not None and coordinate not in {image_tag, f"{IMAGE_REF}:{image_tag}"}:
        raise VerificationError(f"{stage}: runtime image coordinate mismatch")


def marker(raw: bytes, revision: str, stage: str) -> None:
    if len(raw) > 1_048_576:
        raise VerificationError(f"{stage}: response exceeded the bounded limit")
    match = REVISION_META.search(raw)
    if match is None or match.group(1).decode("utf-8", "replace") != revision:
        raise VerificationError(f"{stage}: frontend revision marker mismatch")


def environment_values(paths: list[Path]) -> dict[str, str]:
    """Read only the reviewed DSPACE env scalar pairs from the ordered values chain."""
    result: dict[str, str] = {}
    name: str | None = None
    for path in paths:
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError as exc:
            raise VerificationError(
                "manifest/evidence mismatch: values chain is unreadable"
            ) from exc
        for line in lines:
            found_name = re.match(r"^\s*-\s+name:\s*([A-Z0-9_]+)\s*$", line)
            if found_name:
                name = found_name.group(1)
                continue
            found_value = re.match(r"^\s+value:\s*[\"']?([^\"'#]+?)[\"']?\s*(?:#.*)?$", line)
            if found_value and name:
                result[name] = found_value.group(1).strip()
                name = None
    return result


def application_container(pod: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    containers = [x for x in pod.get("spec", {}).get("containers", []) if x.get("name") == "dspace"]
    statuses = [
        x for x in pod.get("status", {}).get("containerStatuses", []) if x.get("name") == "dspace"
    ]
    if len(containers) != 1 or len(statuses) != 1:
        raise VerificationError("pod/replica identity: missing named dspace container")
    return containers[0], statuses[0]


def verify(args: argparse.Namespace, runner: Runner = run, public_fetch=fetch) -> dict[str, Any]:
    smoke = args.smoke_runner.expanduser()
    if not smoke.is_file() or not os.access(smoke, os.X_OK):
        raise VerificationError("provider/chat smoke: runner must be an existing executable file")
    origin = f"https://{args.host}"
    helm_command = [
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
    helm_before = json_run(runner, helm_command, "cluster identity")
    chart = (
        helm_before.get("chart", {}).get("metadata", {}) if isinstance(helm_before, dict) else {}
    )
    if helm_before.get("version") != args.helm_revision if args.helm_revision else False:
        raise VerificationError("concurrent Helm change: revision differs from approved evidence")
    if chart.get("name") != "dspace" or chart.get("version") != args.chart_version:
        raise VerificationError("cluster identity: installed chart identity mismatch")
    identity(
        public_fetch(origin + "/build-info.json", origin),
        args.application_version,
        args.source_revision,
        args.image_tag,
        "public identity",
    )
    marker(public_fetch(origin + "/", origin), args.source_revision, "public identity")
    pods = json_run(
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
            f"app.kubernetes.io/name=dspace,app.kubernetes.io/instance={args.release}",
            "-o",
            "json",
        ],
        "pod/replica identity",
    )
    items = pods.get("items", []) if isinstance(pods, dict) else []
    if not items:
        raise VerificationError("pod/replica identity: no serving replicas")
    pod_names: list[str] = []
    for pod in items:
        metadata, status = pod.get("metadata", {}), pod.get("status", {})
        name = metadata.get("name")
        if (
            not isinstance(name, str)
            or metadata.get("deletionTimestamp") is not None
            or status.get("phase") != "Running"
            or not any(
                x.get("type") == "Ready" and x.get("status") == "True"
                for x in status.get("conditions", [])
            )
        ):
            raise VerificationError("pod/replica identity: stale, terminating, or unready replica")
        container, container_status = application_container(pod)
        expected_image = f"{IMAGE_REF}:{args.image_tag}"
        if container.get("image") not in {expected_image, f"{expected_image}@{args.image_digest}"}:
            raise VerificationError("pod/replica identity: image coordinate mismatch")
        if not str(container_status.get("imageID", "")).endswith(args.image_digest):
            raise VerificationError("pod/replica identity: image digest mismatch")
        base = f"/api/v1/namespaces/{args.namespace}/pods/{name}:{args.pod_port}/proxy"
        raw_info = runner(
            ["kubectl", "--kubeconfig", args.kubeconfig, "get", "--raw", base + "/build-info.json"]
        ).encode()
        raw_html = runner(
            ["kubectl", "--kubeconfig", args.kubeconfig, "get", "--raw", base + "/"]
        ).encode()
        identity(
            raw_info,
            args.application_version,
            args.source_revision,
            args.image_tag,
            "direct identity",
        )
        marker(raw_html, args.source_revision, "direct identity")
        pod_names.append(name)
    values = environment_values(args.values)
    deployment = json_run(
        runner,
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
        ],
        "cluster identity",
    )
    deployed_containers = [
        item
        for item in deployment.get("spec", {})
        .get("template", {})
        .get("spec", {})
        .get("containers", [])
        if item.get("name") == "dspace"
    ]
    if len(deployed_containers) != 1:
        raise VerificationError("cluster identity: live Deployment lacks named dspace container")
    deployed_env = {
        item.get("name"): item.get("value")
        for item in deployed_containers[0].get("env", [])
        if isinstance(item, dict) and isinstance(item.get("value"), str)
    }
    smoke_command = [
        str(smoke),
        "--base-url",
        origin,
        "--expected-version",
        args.application_version,
        "--expected-revision",
        args.source_revision,
        "--expected-provider",
        args.provider,
    ]
    if args.provider == "token-place":
        token_origin = values.get("DSPACE_TOKEN_PLACE_URL")
        token_model = values.get("DSPACE_TOKEN_PLACE_CHAT_MODEL")
        if not token_origin or not token_model:
            raise VerificationError(
                "provider/chat smoke: reviewed token.place expectations are missing"
            )
        if (
            deployed_env.get("DSPACE_TOKEN_PLACE_URL") != token_origin
            or deployed_env.get("DSPACE_TOKEN_PLACE_CHAT_MODEL") != token_model
        ):
            raise VerificationError(
                "cluster identity: live Deployment routing differs from reviewed values"
            )
        smoke_command += [
            "--expected-token-place-origin",
            token_origin,
            "--expected-token-place-model",
            token_model,
        ]
    try:
        smoke_result = subprocess.run(smoke_command, capture_output=True, check=False, text=True)
    except OSError as exc:
        raise VerificationError("provider/chat smoke: runner could not be executed") from exc
    if smoke_result.returncode:
        raise VerificationError("provider/chat smoke: non-destructive /chat proof failed")
    helm_after = json_run(runner, helm_command, "concurrent Helm change")
    if helm_after.get("version") != helm_before.get("version"):
        raise VerificationError("concurrent Helm change: revision changed during verification")
    return {
        "schemaVersion": 1,
        "environment": args.environment,
        "release": args.release,
        "namespace": args.namespace,
        "applicationVersion": args.application_version,
        "runtimeSourceRevision": args.source_revision,
        "frontendSourceRevision": args.source_revision,
        "defaultProvider": args.provider,
        "journeys": [{"name": "/", "passed": True}, {"name": "/chat", "passed": True}],
    }


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description=__doc__)
    commands = root.add_subparsers(dest="command", required=True)
    for name in ("capabilities", "verify"):
        command = commands.add_parser(name)
        command.add_argument("--environment", choices=("staging", "prod"), required=True)
        command.add_argument("--release", required=True)
        command.add_argument("--namespace", required=True)
        if name == "verify":
            command.add_argument("--application-version", required=True)
            command.add_argument("--source-revision", required=True)
            command.add_argument("--provider", choices=("token-place", "openai"), required=True)
            command.add_argument("--image-tag", required=True)
            command.add_argument("--image-digest", required=True)
            command.add_argument("--chart-version", required=True)
            command.add_argument("--helm-revision", type=int)
            command.add_argument("--host", required=True)
            command.add_argument("--values", type=Path, action="append", default=[])
            command.add_argument("--smoke-runner", type=Path, required=True)
            command.add_argument("--kubeconfig", required=True)
            command.add_argument("--pod-port", type=int, default=3000)
    return root


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        if args.command == "capabilities":
            result = {
                "schemaVersion": 1,
                "environment": args.environment,
                "release": args.release,
                "namespace": args.namespace,
                "capabilities": list(CAPABILITIES),
            }
        else:
            result = verify(args)
        print(json.dumps(result, separators=(",", ":")))
    except VerificationError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
