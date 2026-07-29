#!/usr/bin/env python3
"""Prove the identity and safe public chat journey of a DSPACE release."""

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
from scripts import dspace_release_manifest as release_manifest  # noqa: E402

CAPABILITIES = [
    "applicationVersion",
    "runtimeSourceRevision",
    "frontendSourceRevision",
    "defaultProvider",
    "publicJourneys",
]
META_RE = re.compile(
    r'<meta\s+[^>]*name=["\']dspace-build-revision["\'][^>]*content=["\']([^"\']+)',
    re.I,
)
SAFE_ENV_NAMES = {"DSPACE_TOKEN_PLACE_URL", "DSPACE_TOKEN_PLACE_CHAT_MODEL"}
IMMUTABLE_FIELDS = (
    "applicationVersion",
    "sourceRevision",
    "imageTag",
    "imageDigest",
    "chartVersion",
    "chartDigest",
    "semanticTag",
    "expectedDefaultChatProvider",
)


class VerificationError(ValueError):
    """A bounded, non-secret verification failure."""


Runner = Callable[[list[str]], str]


def run(command: list[str]) -> str:
    completed = subprocess.run(command, check=False, capture_output=True, text=True)
    if completed.returncode:
        raise VerificationError(f"provider/chat smoke: command failed ({command[0]})")
    return completed.stdout


def json_run(runner: Runner, command: list[str], label: str) -> dict[str, Any]:
    try:
        value = json.loads(runner(command))
    except (json.JSONDecodeError, OSError) as exc:
        raise VerificationError(f"{label}: command did not return valid JSON") from exc
    if not isinstance(value, dict):
        raise VerificationError(f"{label}: expected a JSON object")
    return value


class SameOriginRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        if urllib.parse.urlsplit(newurl)[:2] != urllib.parse.urlsplit(req.full_url)[:2]:
            raise VerificationError("public identity: redirect changed origin")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def fetch(url: str) -> str:
    try:
        with urllib.request.build_opener(SameOriginRedirect()).open(url, timeout=15) as response:
            return response.read(1024 * 1024).decode("utf-8")
    except VerificationError:
        raise
    except (OSError, UnicodeError, urllib.error.HTTPError) as exc:
        raise VerificationError("public identity: endpoint unavailable") from exc


def identity(build: str, html: str, expected: dict[str, str], label: str) -> None:
    try:
        info = json.loads(build)
    except json.JSONDecodeError as exc:
        raise VerificationError(f"{label}: invalid build identity") from exc
    if not isinstance(info, dict):
        raise VerificationError(f"{label}: invalid build identity")
    if info.get("version") != expected["version"]:
        raise VerificationError(f"{label}: application version mismatch")
    if info.get("revision") != expected["revision"]:
        raise VerificationError(f"{label}: source revision mismatch")
    if info.get("shortRevision") != expected["revision"][:7]:
        raise VerificationError(f"{label}: short revision mismatch")
    image = info.get("image") or info.get("imageTag")
    if image is not None and expected["tag"] not in str(image):
        raise VerificationError(f"{label}: runtime image coordinate mismatch")
    marker = META_RE.search(html)
    if marker is None or marker.group(1) != expected["revision"]:
        raise VerificationError(f"{label}: frontend revision marker mismatch")


def values_expectations(paths: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for raw in paths.split(","):
        path = Path(raw.strip())
        path = path if path.is_absolute() else REPO_ROOT / path
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError as exc:
            raise VerificationError("manifest/evidence mismatch: values chain unavailable") from exc
        for index, line in enumerate(lines):
            match = re.match(r"^\s*-\s*name:\s*([^#\s]+)\s*$", line)
            if not match or match.group(1) not in SAFE_ENV_NAMES:
                continue
            for following in lines[index + 1 :]:
                if re.match(r"^\s*-\s*name:", following):
                    break
                value = re.match(r"^\s*value:\s*([^#]+?)\s*$", following)
                if value:
                    result[match.group(1)] = value.group(1).strip(" \"'")
                    break
    return result


def deployment_env(deployment: dict[str, Any]) -> dict[str, str]:
    containers = (
        deployment.get("spec", {}).get("template", {}).get("spec", {}).get("containers", [])
    )
    dspace = [item for item in containers if item.get("name") == "dspace"]
    if len(dspace) != 1:
        raise VerificationError("cluster identity: Deployment lacks one dspace container")
    return {
        item.get("name"): item.get("value")
        for item in dspace[0].get("env", [])
        if item.get("name") in SAFE_ENV_NAMES and isinstance(item.get("value"), str)
    }


def verify(
    args: argparse.Namespace, runner: Runner = run, http_fetch: Callable[[str], str] = fetch
) -> dict[str, Any]:
    if not args.smoke_runner.is_file() or not os.access(args.smoke_runner, os.X_OK):
        raise VerificationError(
            "provider/chat smoke: smoke runner must be an existing executable file"
        )
    manifest = release_manifest._object(args.manifest)
    release_manifest.validate(manifest, manifest.get("recordType") == "final")
    if manifest["environment"] != args.environment:
        raise VerificationError("manifest/evidence mismatch: environment mismatch")
    config = app_config.load_config("dspace", args.environment, args.config or None)
    paths = tuple(item.strip() for item in config["SUGARKUBE_VALUES"].split(",") if item.strip())
    host = app_chart.expected_ingress_host(paths, "")
    base_url = f"https://{host}"
    expected = {
        "version": manifest["applicationVersion"],
        "revision": manifest["sourceRevision"],
        "tag": manifest["imageTag"],
    }
    identity(
        http_fetch(f"{base_url}/build-info.json"),
        http_fetch(base_url + "/"),
        expected,
        "public identity",
    )

    command = ["kubectl", "--kubeconfig", args.kubeconfig, "-n", args.namespace]
    deployment = json_run(
        runner, [*command, "get", f"deployment/{args.release}", "-o", "json"], "cluster identity"
    )
    configured = values_expectations(config["SUGARKUBE_VALUES"])
    live_env = deployment_env(deployment)
    provider = manifest["expectedDefaultChatProvider"]
    if provider == "token-place":
        if any(not configured.get(name) for name in SAFE_ENV_NAMES) or live_env != configured:
            raise VerificationError(
                "cluster identity: token.place rendered/live expectations differ"
            )

    pod_data = json_run(
        runner,
        [
            *command,
            "get",
            "pods",
            "-l",
            f"app.kubernetes.io/name=dspace,app.kubernetes.io/instance={args.release}",
            "-o",
            "json",
        ],
        "pod/replica identity",
    )
    pods = pod_data.get("items")
    if not isinstance(pods, list) or not pods:
        raise VerificationError("pod/replica identity: no serving replicas")
    names: list[str] = []
    for pod in pods:
        metadata, status = pod.get("metadata", {}), pod.get("status", {})
        if (
            metadata.get("deletionTimestamp")
            or status.get("phase") != "Running"
            or not any(
                c.get("type") == "Ready" and c.get("status") == "True"
                for c in status.get("conditions", [])
            )
        ):
            raise VerificationError("pod/replica identity: stale, terminating, or unready replica")
        containers = [
            c for c in pod.get("spec", {}).get("containers", []) if c.get("name") == "dspace"
        ]
        statuses = [c for c in status.get("containerStatuses", []) if c.get("name") == "dspace"]
        coordinate = f"{release_manifest.IMAGE_REF}:{manifest['imageTag']}"
        if len(containers) != 1 or containers[0].get("image", "").split("@")[0] != coordinate:
            raise VerificationError("pod/replica identity: image coordinate mismatch")
        try:
            digest = release_manifest._image_id_digest(statuses[0].get("imageID", ""))
        except (IndexError, release_manifest.ManifestError) as exc:
            raise VerificationError("pod/replica identity: image digest unavailable") from exc
        if digest != manifest["imageDigest"]:
            raise VerificationError("pod/replica identity: image digest mismatch")
        name = metadata.get("name")
        if not isinstance(name, str) or not name:
            raise VerificationError("pod/replica identity: unnamed replica")
        names.append(name)
        proxy = f"/api/v1/namespaces/{args.namespace}/pods/{name}:3000/proxy"
        try:
            direct_build = runner(
                [
                    "kubectl",
                    "--kubeconfig",
                    args.kubeconfig,
                    "get",
                    "--raw",
                    proxy + "/build-info.json",
                ]
            )
            direct_html = runner(
                ["kubectl", "--kubeconfig", args.kubeconfig, "get", "--raw", proxy + "/"]
            )
        except Exception as exc:
            raise VerificationError("direct identity: replica endpoint unavailable") from exc
        identity(direct_build, direct_html, expected, "direct identity")

    smoke = [
        str(args.smoke_runner),
        "--base-url",
        base_url,
        "--expected-version",
        expected["version"],
        "--expected-revision",
        expected["revision"],
        "--expected-provider",
        provider,
    ]
    if provider == "token-place":
        smoke.extend(
            [
                "--expected-token-place-origin",
                configured["DSPACE_TOKEN_PLACE_URL"],
                "--expected-token-place-model",
                configured["DSPACE_TOKEN_PLACE_CHAT_MODEL"],
            ]
        )
    runner(smoke)
    return {
        "schemaVersion": 1,
        "environment": args.environment,
        "release": args.release,
        "namespace": args.namespace,
        "applicationVersion": expected["version"],
        "runtimeSourceRevision": expected["revision"],
        "frontendSourceRevision": expected["revision"],
        "defaultProvider": provider,
        "journeys": [{"name": "/", "passed": True}, {"name": "/chat", "passed": True}],
    }


def staging_gate(args: argparse.Namespace, runner: Runner = run) -> dict[str, Any]:
    """Validate finalized staging proof, its artifact binding, and current live revision."""
    candidate = release_manifest._object(args.manifest)
    evidence = release_manifest._object(args.staging_evidence)
    release_manifest.validate(candidate, False)
    release_manifest.validate(evidence, True)
    if candidate["environment"] != "prod" or evidence["environment"] != "staging":
        raise VerificationError(
            "manifest/evidence mismatch: prod candidate and staging final required"
        )
    mismatches = [field for field in IMMUTABLE_FIELDS if candidate[field] != evidence[field]]
    if mismatches:
        raise VerificationError("manifest/evidence mismatch: immutable release coordinates differ")
    helm = json_run(
        runner,
        [
            "helm",
            "--kubeconfig",
            args.kubeconfig,
            "status",
            "dspace",
            "--namespace",
            "dspace",
            "-o",
            "json",
        ],
        "staging drift",
    )
    if helm.get("version") != evidence["helmRevision"]:
        raise VerificationError("staging drift: Helm revision differs from finalized evidence")
    metadata = helm.get("chart", {}).get("metadata", {})
    if (
        helm.get("info", {}).get("status") != "deployed"
        or metadata.get("name") != "dspace"
        or metadata.get("version") != evidence["chartVersion"]
    ):
        raise VerificationError("staging drift: live Helm release/chart identity differs")
    approved = {field: evidence[field] for field in release_manifest.CANDIDATE_FIELDS}
    approved["recordType"] = "candidate"
    try:
        release_manifest.preflight(
            approved,
            release_manifest.IMAGE_REF,
            release_manifest.CHART_REF,
            args.oras,
            environment="staging",
            image_tag=evidence["imageTag"],
            chart_version=evidence["chartVersion"],
            runner=runner,
        )
    except release_manifest.ManifestError as exc:
        raise VerificationError("OCI coordinate: staging artifact provenance differs") from exc
    verify_args = argparse.Namespace(
        environment="staging",
        release="dspace",
        namespace="dspace",
        manifest=args.staging_evidence,
        smoke_runner=args.smoke_runner,
        config=args.staging_config,
        kubeconfig=args.kubeconfig,
    )
    proof = verify(verify_args, runner)
    return {
        "schemaVersion": 1,
        "stagingEvidence": "finalized",
        "helmRevision": evidence["helmRevision"],
        "verification": proof,
    }


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    sub = result.add_subparsers(dest="command", required=True)
    for name in ("capabilities", "verify"):
        command = sub.add_parser(name)
        command.add_argument("--environment", choices=("staging", "prod"), required=True)
        command.add_argument("--release", default="dspace")
        command.add_argument("--namespace", default="dspace")
        if name == "verify":
            command.add_argument("--manifest", type=Path, required=True)
            command.add_argument("--smoke-runner", type=Path, required=True)
            command.add_argument("--config", default="")
            command.add_argument("--kubeconfig", required=True)
            command.add_argument("--application-version")
            command.add_argument("--source-revision")
            command.add_argument("--provider")
    gate = sub.add_parser("staging-gate")
    gate.add_argument("--manifest", type=Path, required=True)
    gate.add_argument("--staging-evidence", type=Path, required=True)
    gate.add_argument("--smoke-runner", type=Path, required=True)
    gate.add_argument("--staging-config", default="")
    gate.add_argument("--kubeconfig", required=True)
    gate.add_argument("--oras", default=os.environ.get("SUGARKUBE_ORAS_COMMAND", "oras"))
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
        print(json.dumps(value, separators=(",", ":")))
    except (VerificationError, release_manifest.ManifestError, app_config.AppConfigError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
