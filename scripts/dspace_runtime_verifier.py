#!/usr/bin/env python3
"""Prove DSPACE build identity and the public /chat journey without leaking content."""

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

from scripts import app_chart, app_config  # noqa: E402
from scripts import dspace_release_manifest as release_manifest  # noqa: E402

CAPABILITIES = [
    "applicationVersion",
    "runtimeSourceRevision",
    "frontendSourceRevision",
    "defaultProvider",
    "publicJourneys",
]
BUILD_FIELDS = {"version", "revision", "shortRevision", "image"}
REVISION_META = re.compile(
    rb'<meta\s+name=["\']dspace-build-revision["\']\s+content=["\']([^"\']+)["\']',
    re.IGNORECASE,
)


class VerificationError(ValueError):
    """A bounded, non-secret verification failure."""


def command(argv: list[str], stage: str) -> str:
    try:
        result = subprocess.run(argv, capture_output=True, text=True, check=False)
    except OSError as exc:
        raise VerificationError(f"{stage}: command could not be started") from exc
    if result.returncode:
        raise VerificationError(f"{stage}: command failed")
    return result.stdout


class SameOriginRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: N802
        if urllib.parse.urlsplit(newurl)[:2] != urllib.parse.urlsplit(req.full_url)[:2]:
            raise VerificationError("public identity: redirect changed origin")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def fetch(url: str, stage: str) -> bytes:
    try:
        with urllib.request.build_opener(SameOriginRedirects).open(url, timeout=15) as response:
            return response.read(1024 * 1024 + 1)
    except VerificationError:
        raise
    except (OSError, urllib.error.URLError) as exc:
        raise VerificationError(f"{stage}: endpoint unreachable") from exc


def identity(body: bytes, version: str, revision: str, image_tag: str | None, stage: str) -> None:
    try:
        value = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise VerificationError(f"{stage}: invalid build identity") from exc
    if not isinstance(value, dict) or not set(value) <= BUILD_FIELDS:
        raise VerificationError(f"{stage}: invalid build identity")
    if value.get("version") != version or value.get("revision") != revision:
        raise VerificationError(f"{stage}: version or revision mismatch")
    if value.get("shortRevision") != revision[:7]:
        raise VerificationError(f"{stage}: short revision mismatch")
    image = value.get("image")
    if image is not None and (not isinstance(image, str) or (image_tag and image_tag not in image)):
        raise VerificationError(f"{stage}: image coordinate mismatch")


def frontend(body: bytes, revision: str, stage: str) -> None:
    found = REVISION_META.search(body)
    if found is None or found.group(1).decode("ascii", "replace") != revision:
        raise VerificationError(f"{stage}: frontend revision mismatch")


def deployment_environment(value: dict[str, Any]) -> dict[str, str]:
    containers = value.get("spec", {}).get("template", {}).get("spec", {}).get("containers", [])
    selected = [item for item in containers if item.get("name") == "dspace"]
    if len(selected) != 1:
        raise VerificationError("cluster identity: Deployment lacks one dspace container")
    return {
        item["name"]: item["value"]
        for item in selected[0].get("env", [])
        if isinstance(item, dict)
        and isinstance(item.get("name"), str)
        and isinstance(item.get("value"), str)
    }


def expected_values(config: dict[str, str]) -> tuple[str, str, str]:
    files = tuple(part.strip() for part in config["SUGARKUBE_VALUES"].split(",") if part.strip())
    merged = app_chart.merged_values_document(files)
    ingress = merged.get("ingress", {}) if isinstance(merged, dict) else {}
    env = merged.get("env", []) if isinstance(merged, dict) else []
    values = {
        item.get("name"): item.get("value")
        for item in env
        if isinstance(item, dict) and isinstance(item.get("value"), str)
    }
    host = ingress.get("host") if isinstance(ingress, dict) else None
    if not isinstance(host, str) or not host:
        raise VerificationError("manifest/evidence mismatch: values lack the public host")
    return (
        host,
        values.get("DSPACE_TOKEN_PLACE_URL", ""),
        values.get("DSPACE_TOKEN_PLACE_CHAT_MODEL", ""),
    )


def ready_pods(value: dict[str, Any], image: str | None, digest: str | None) -> list[str]:
    items = value.get("items")
    if not isinstance(items, list) or not items:
        raise VerificationError("pod/replica identity: no serving replicas")
    names = []
    for pod in items:
        meta, spec, status = pod.get("metadata", {}), pod.get("spec", {}), pod.get("status", {})
        containers = [x for x in spec.get("containers", []) if x.get("name") == "dspace"]
        states = [x for x in status.get("containerStatuses", []) if x.get("name") == "dspace"]
        ready = any(
            x.get("type") == "Ready" and x.get("status") == "True"
            for x in status.get("conditions", [])
        )
        if (
            meta.get("deletionTimestamp") is not None
            or status.get("phase") != "Running"
            or not ready
        ):
            raise VerificationError("pod/replica identity: stale, terminating, or unready replica")
        if len(containers) != 1 or (image is not None and containers[0].get("image") != image):
            raise VerificationError("pod/replica identity: image coordinate mismatch")
        if len(states) != 1 or (
            digest is not None and not str(states[0].get("imageID", "")).endswith(digest)
        ):
            raise VerificationError("pod/replica identity: image digest mismatch")
        names.append(meta.get("name"))
    if not all(isinstance(name, str) and name for name in names):
        raise VerificationError("pod/replica identity: invalid pod discovery")
    return sorted(names)


def verify(args: argparse.Namespace) -> dict[str, Any]:
    manifest = (
        release_manifest.validate(release_manifest._object(args.manifest), None)
        if args.manifest
        else None
    )
    version = manifest["applicationVersion"] if manifest else args.application_version
    revision = manifest["sourceRevision"] if manifest else args.source_revision
    provider = manifest["expectedDefaultChatProvider"] if manifest else args.provider
    if not version or not revision or provider not in release_manifest.PROVIDERS:
        raise VerificationError("manifest/evidence mismatch: incomplete approved expectations")
    config = app_config.load_config(
        "dspace", args.environment, str(args.config) if args.config else None
    )
    host, token_origin, token_model = expected_values(config)
    base_url = f"https://{host}"
    runner = args.smoke_runner or os.environ.get("DSPACE_SMOKE_RUNNER", "")
    runner_path = Path(runner).expanduser()
    if not runner_path.is_file() or not os.access(runner_path, os.X_OK):
        raise VerificationError(
            "provider/chat smoke: smoke runner must be an existing executable file"
        )
    command(
        [
            sys.executable,
            str(REPO_ROOT / "scripts" / "cluster_identity.py"),
            "assert",
            "--kubeconfig",
            args.kubeconfig,
            "--env",
            args.environment,
        ],
        "cluster identity",
    )
    kube = ["kubectl", "--kubeconfig", args.kubeconfig, "-n", args.namespace]
    deployment = json.loads(
        command(kube + ["get", "deployment", args.release, "-o", "json"], "cluster identity")
    )
    live_env = deployment_environment(deployment)
    if provider == "token-place" and (
        not token_origin
        or not token_model
        or live_env.get("DSPACE_TOKEN_PLACE_URL") != token_origin
        or live_env.get("DSPACE_TOKEN_PLACE_CHAT_MODEL") != token_model
    ):
        raise VerificationError("cluster identity: token.place expectations differ from Deployment")
    public_build = fetch(base_url + "/build-info.json", "public identity")
    identity(
        public_build,
        version,
        revision,
        manifest.get("imageTag") if manifest else None,
        "public identity",
    )
    frontend(fetch(base_url + "/", "public identity"), revision, "public identity")
    pods_json = json.loads(
        command(
            kube
            + [
                "get",
                "pods",
                "-l",
                f"app.kubernetes.io/name=dspace,app.kubernetes.io/instance={args.release}",
                "-o",
                "json",
            ],
            "pod/replica identity",
        )
    )
    expected_image = f"{release_manifest.IMAGE_REF}:{manifest['imageTag']}" if manifest else None
    digest = manifest["imageDigest"] if manifest else None
    pods = ready_pods(pods_json, expected_image, digest)
    for pod in pods:
        prefix = f"/api/v1/namespaces/{args.namespace}/pods/{pod}:3000/proxy"
        direct_build = command(
            kube + ["get", "--raw", prefix + "/build-info.json"], "direct identity"
        ).encode()
        identity(
            direct_build,
            version,
            revision,
            manifest.get("imageTag") if manifest else None,
            "direct identity",
        )
        direct_html = command(kube + ["get", "--raw", prefix + "/"], "direct identity").encode()
        frontend(direct_html, revision, "direct identity")
    smoke = [
        str(runner_path),
        "--base-url",
        base_url,
        "--expected-version",
        version,
        "--expected-revision",
        revision,
        "--expected-provider",
        provider,
    ]
    if provider == "token-place":
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
        "applicationVersion": version,
        "runtimeSourceRevision": revision,
        "frontendSourceRevision": revision,
        "defaultProvider": provider,
        "journeys": [{"name": "/chat", "passed": True}],
    }


def staging_gate(args: argparse.Namespace) -> dict[str, Any]:
    candidate = release_manifest.validate(release_manifest._object(args.manifest), False)
    evidence = release_manifest.validate(release_manifest._object(args.staging_evidence), True)
    if candidate["environment"] != "prod" or evidence["environment"] != "staging":
        raise VerificationError(
            "manifest/evidence mismatch: production and staging records required"
        )
    coordinates = (
        "applicationVersion",
        "sourceRevision",
        "imageTag",
        "imageDigest",
        "chartVersion",
        "chartDigest",
        "semanticTag",
        "expectedDefaultChatProvider",
    )
    if any(candidate[key] != evidence[key] for key in coordinates):
        raise VerificationError(
            "manifest/evidence mismatch: staging artifact differs from candidate"
        )
    helm = [
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
    before = json.loads(command(helm, "staging drift"))
    if before.get("version") != evidence["helmRevision"]:
        raise VerificationError("staging drift: Helm revision differs from finalized evidence")
    proof_args = argparse.Namespace(**vars(args))
    proof_args.environment = "staging"
    proof_args.manifest = args.staging_evidence
    proof_args.application_version = proof_args.source_revision = proof_args.provider = None
    proof = verify(proof_args)
    after = json.loads(command(helm, "concurrent Helm change"))
    if after.get("version") != evidence["helmRevision"]:
        raise VerificationError(
            "concurrent Helm change: staging revision changed during verification"
        )
    return proof


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser()
    commands = result.add_subparsers(dest="command", required=True)
    for name in ("capabilities", "verify"):
        sub = commands.add_parser(name)
        sub.add_argument("--environment", choices=("staging", "prod"), required=True)
        sub.add_argument("--release", required=True)
        sub.add_argument("--namespace", required=True)
        if name == "verify":
            sub.add_argument("--manifest", type=Path)
            sub.add_argument("--application-version")
            sub.add_argument("--source-revision")
            sub.add_argument("--provider")
            sub.add_argument("--smoke-runner")
            sub.add_argument("--config", type=Path)
            sub.add_argument(
                "--kubeconfig",
                default=os.environ.get("KUBECONFIG", str(Path.home() / ".kube/config")),
            )
    gate = commands.add_parser("staging-gate")
    gate.add_argument("--manifest", type=Path, required=True)
    gate.add_argument("--staging-evidence", type=Path, required=True)
    gate.add_argument("--smoke-runner", required=True)
    gate.add_argument("--config", type=Path)
    gate.add_argument(
        "--kubeconfig", default=os.environ.get("KUBECONFIG", str(Path.home() / ".kube/config"))
    )
    gate.add_argument("--release", default="dspace")
    gate.add_argument("--namespace", default="dspace")
    return result


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        if args.command == "capabilities":
            value = {
                "schemaVersion": 1,
                "environment": args.environment,
                "release": args.release,
                "namespace": args.namespace,
                "capabilities": CAPABILITIES,
            }
        elif args.command == "verify":
            value = verify(args)
        else:
            value = staging_gate(args)
        print(json.dumps(value, sort_keys=True, separators=(",", ":")))
    except (
        VerificationError,
        release_manifest.ManifestError,
        json.JSONDecodeError,
        KeyError,
        ValueError,
    ) as exc:
        message = (
            str(exc)
            if isinstance(exc, VerificationError)
            else "manifest/evidence mismatch: invalid verification input"
        )
        print(f"ERROR: {message}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
