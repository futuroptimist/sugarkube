#!/usr/bin/env python3
"""Read-only preflight for the separate DSPACE 3.1.0 staging receipt."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import selectors
import signal
import stat
import subprocess
import sys
import time
from pathlib import Path

CONTEXT = "sugar-staging"
REPOSITORY = "https://github.com/democratizedspace/dspace"
IMAGE = "ghcr.io/democratizedspace/dspace"
CHART = "ghcr.io/democratizedspace/charts/dspace"
IMAGE_MANIFEST = "application/vnd.oci.image.manifest.v1+json"
MANIFESTS = (IMAGE_MANIFEST, "application/vnd.docker.distribution.manifest.v2+json")
INDEXES = (
    "application/vnd.oci.image.index.v1+json",
    "application/vnd.docker.distribution.manifest.list.v2+json",
)
IMAGE_CONFIGS = (
    "application/vnd.oci.image.config.v1+json",
    "application/vnd.docker.container.image.v1+json",
)
HELM_CONFIG = "application/vnd.cncf.helm.config.v1+json"
HELM_CONTENT = "application/vnd.cncf.helm.chart.content.v1.tar+gzip"
HELM_PROVENANCE = "application/vnd.cncf.helm.chart.provenance.v1.prov"
PLATFORMS = ("amd64", "arm64")
SOURCE = "org.opencontainers.image.source"
REVISION = "org.opencontainers.image.revision"
VERSION = "org.opencontainers.image.version"
DIGEST = r"sha256:[a-f0-9]{64}"
SHA = r"[a-f0-9]{40}"
VERSION_PATTERN = r"(?:0|[1-9][0-9]*)(?:\.(?:0|[1-9][0-9]*)){2}"
RUN_ID = r"[1-9][0-9]{0,19}"
MAX_METADATA = 1024 * 1024
MAX_INPUT = 16 * 1024


class PreflightError(Exception):
    """An unchanged, non-sensitive diagnostic for a rejected preflight."""


def require(condition, code):
    if not condition:
        raise PreflightError(code)


def matches(value, pattern):
    return isinstance(value, str) and re.fullmatch(pattern, value) is not None


def fields(value, *expected):
    return isinstance(value, dict) and set(value) == set(expected)


def get(value, key):
    return value.get(key) if isinstance(value, dict) else None


def pairs_no_duplicates(pairs):
    value = dict(pairs)
    require(len(value) == len(pairs), "duplicate JSON field")
    return value


def invalid_constant(_value):
    raise PreflightError("invalid numeric JSON literal")


def parse(raw, limit):
    require(isinstance(raw, bytes) and 0 < len(raw) <= limit, "invalid metadata size")
    try:
        value = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=pairs_no_duplicates,
            parse_constant=invalid_constant,
        )
    except (ValueError, RecursionError):
        raise PreflightError("invalid JSON metadata") from None
    require(isinstance(value, dict), "expected a JSON object")
    return value


def content_digest(raw):
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def descriptors(value):
    return (
        fields(value, "digest", "configDigest")
        and matches(value["digest"], DIGEST)
        and matches(value["configDigest"], DIGEST)
    )


def valid_completion_time(value):
    if not matches(value, r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z"):
        return False
    try:
        # Python before 3.11 needs an explicit UTC offset instead of Z.
        dt.datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError:
        return False
    return True


def validate_inputs(receipt, approval, native_raw):
    require(
        fields(
            receipt,
            "schema",
            "environment",
            "app",
            "sourceRevision",
            "sourceTree",
            "applicationVersion",
            "image",
            "chart",
            "approvalRef",
            "evidenceType",
            "deploymentAuthorized",
        )
        and receipt["schema"] == "dspace-staging-coordinates-v1"
        and receipt["environment"] == "staging"
        and receipt["app"] == "dspace"
        and receipt["applicationVersion"] == "3.1.0"
        and receipt["evidenceType"] == "offline-oci-metadata-correlation"
        and receipt["deploymentAuthorized"] is False
        and matches(receipt["sourceRevision"], SHA)
        and matches(receipt["sourceTree"], SHA)
        and matches(receipt["approvalRef"], r"[A-Za-z0-9_-]{1,128}"),
        "invalid staging coordinate receipt",
    )
    image, chart = receipt["image"], receipt["chart"]
    require(
        fields(image, "repository", "digest", "platforms")
        and image["repository"] == IMAGE
        and matches(image["digest"], DIGEST)
        and fields(image["platforms"], "linux/amd64", "linux/arm64")
        and all(descriptors(entry) for entry in image["platforms"].values())
        and len({entry["digest"] for entry in image["platforms"].values()}) == 2
        and len({entry["configDigest"] for entry in image["platforms"].values()}) == 2
        and fields(chart, "repository", "version", "digest", "contentDigest")
        and chart["repository"] == "oci://" + CHART
        and matches(chart["version"], VERSION_PATTERN)
        and matches(chart["digest"], DIGEST)
        and matches(chart["contentDigest"], DIGEST),
        "invalid pinned staging OCI coordinates",
    )
    require(
        fields(
            approval,
            "schema",
            "environment",
            "approvalRef",
            "sourceRevision",
            "applicationVersion",
            "imageDigest",
            "chartVersion",
            "chartDigest",
            "nativeArtifactId",
            "nativeSummaryDigest",
            "nativeWorkflowSha",
            "nativeRunId",
            "nativeRunAttempt",
        )
        and approval["schema"] == "dspace-staging-preflight-approval-v1"
        and approval["environment"] == "staging"
        and approval["approvalRef"] == receipt["approvalRef"]
        and approval["sourceRevision"] == receipt["sourceRevision"]
        and approval["applicationVersion"] == receipt["applicationVersion"]
        and approval["imageDigest"] == image["digest"]
        and approval["chartVersion"] == chart["version"]
        and approval["chartDigest"] == chart["digest"]
        and matches(approval["nativeArtifactId"], RUN_ID)
        and matches(approval["nativeRunId"], RUN_ID)
        and matches(approval["nativeRunAttempt"], RUN_ID)
        and matches(approval["nativeWorkflowSha"], SHA)
        and matches(approval["nativeSummaryDigest"], DIGEST),
        "missing or mismatched independent staging approval",
    )
    native = parse(native_raw, MAX_INPUT)
    require(
        content_digest(native_raw) == approval["nativeSummaryDigest"]
        and fields(
            native,
            "schema",
            "image",
            "indexDigest",
            "sourceSha",
            "tree",
            "appVersion",
            "node",
            "runtimeVersion",
            "workflowSha",
            "runId",
            "runAttempt",
            "platforms",
            "publishedByThisRun",
            "verified",
            "completedAt",
        )
        and native["schema"] == "dspace-candidate-image-summary-v1"
        and native["publishedByThisRun"] is False
        and native["verified"] is True
        and native["image"] == IMAGE
        and native["indexDigest"] == image["digest"]
        and native["sourceSha"] == receipt["sourceRevision"]
        and native["tree"] == receipt["sourceTree"]
        and native["appVersion"] == receipt["applicationVersion"]
        and matches(native["node"], VERSION_PATTERN)
        and native["runtimeVersion"] == f"v3.1.0+{receipt['sourceRevision'][:7]}"
        and native["workflowSha"] == approval["nativeWorkflowSha"]
        and native["runId"] == approval["nativeRunId"]
        and native["runAttempt"] == approval["nativeRunAttempt"]
        and valid_completion_time(native["completedAt"])
        and fields(native["platforms"], *PLATFORMS)
        and all(
            native["platforms"][arch] == image["platforms"]["linux/" + arch] for arch in PLATFORMS
        ),
        "native verifier summary does not match the approved evidence",
    )
    return native


def command(argv, limit):
    """Bound subprocess output and elapsed time, and never expose command errors."""
    deadline = time.monotonic() + 40
    chunks = bytearray()
    try:
        with subprocess.Popen(
            argv,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        ) as proc:
            try:
                with selectors.DefaultSelector() as selector:
                    selector.register(proc.stdout, selectors.EVENT_READ)
                    while True:
                        remaining = deadline - time.monotonic()
                        require(remaining > 0 and selector.select(remaining), "read timed out")
                        chunk = os.read(proc.stdout.fileno(), 65536)
                        if not chunk:
                            break
                        chunks.extend(chunk)
                        require(len(chunks) <= limit, "read exceeded the output limit")
                require(
                    proc.wait(timeout=max(0, deadline - time.monotonic())) == 0,
                    "read-only command failed",
                )
            except BaseException:
                # The cluster identity helper itself may spawn kubectl.
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                raise
    except (OSError, subprocess.TimeoutExpired):
        raise PreflightError("read-only command failed or timed out") from None
    return bytes(chunks)


def verify_staging_context(read, home):
    kubeconfig = home / ".kube" / "config-sugarkube-staging"
    require(
        kubeconfig.is_file() and not kubeconfig.is_symlink(), "missing trusted staging kubeconfig"
    )
    target = str(kubeconfig)
    require(
        read(["kubectl", "--kubeconfig", target, "config", "current-context"], 128).strip()
        == CONTEXT.encode(),
        "staging context must be sugar-staging",
    )
    identity = Path(__file__).resolve().with_name("cluster_identity.py")
    require(
        read(
            [sys.executable, str(identity), "assert", "--kubeconfig", target, "--env", "staging"],
            128,
        ).strip()
        == b"staging",
        "connected cluster must identify as staging",
    )


def oci_object(read, repository, kind, digest):
    require(matches(digest, DIGEST), "invalid OCI descriptor digest")
    raw = read(["oras", kind, "fetch", "--output", "-", f"{repository}@{digest}"], MAX_METADATA)
    value = parse(raw, MAX_METADATA)
    require(content_digest(raw) == digest, "OCI metadata bytes do not match the pinned digest")
    return value


def verify_platforms(read, receipt, native):
    image = receipt["image"]
    index = oci_object(read, IMAGE, "manifest", image["digest"])
    manifests = index.get("manifests")
    require(
        index.get("schemaVersion") == 2
        and index.get("mediaType") in INDEXES
        and isinstance(manifests, list)
        and len(manifests) >= 2,
        "invalid runtime OCI index",
    )
    seen, runtime, attestations = set(), {}, []
    for descriptor in manifests:
        digest = get(descriptor, "digest")
        platform = get(descriptor, "platform")
        os_name, arch = get(platform, "os"), get(platform, "architecture")
        variant = get(platform, "variant")
        annotations = get(descriptor, "annotations")
        require(
            matches(digest, DIGEST)
            and digest not in seen
            and get(descriptor, "mediaType") in MANIFESTS,
            "invalid or duplicate OCI index descriptor",
        )
        seen.add(digest)
        if (
            os_name == arch == "unknown"
            and variant is None
            and get(annotations, "vnd.docker.reference.type") == "attestation-manifest"
        ):
            attestations.append(get(annotations, "vnd.docker.reference.digest"))
            continue
        require(
            os_name == "linux"
            and arch in PLATFORMS
            and arch not in runtime
            and (variant is None or (arch == "arm64" and variant == "v8")),
            "unexpected or duplicate runtime platform",
        )
        runtime[arch] = digest
    expected = {arch: image["platforms"]["linux/" + arch]["digest"] for arch in PLATFORMS}
    require(
        runtime == expected and all(target in runtime.values() for target in attestations),
        "runtime platform descriptors do not match the approved receipt",
    )
    for arch, digest in runtime.items():
        manifest = oci_object(read, IMAGE, "manifest", digest)
        config_digest = image["platforms"]["linux/" + arch]["configDigest"]
        descriptor = manifest.get("config")
        layers = manifest.get("layers")
        require(
            manifest.get("schemaVersion") == 2
            and manifest.get("mediaType") in MANIFESTS
            and get(descriptor, "mediaType") in IMAGE_CONFIGS
            and get(descriptor, "digest") == config_digest
            and isinstance(layers, list)
            and bool(layers)
            and all(matches(get(layer, "digest"), DIGEST) for layer in layers),
            "image config descriptor does not match the approved receipt",
        )
        config = oci_object(read, IMAGE, "blob", config_digest)
        image_config = config.get("config")
        envs = get(image_config, "Env")
        labels = get(image_config, "Labels")
        require(
            config.get("os") == "linux"
            and config.get("architecture") == arch
            and get(labels, SOURCE) == REPOSITORY
            and get(labels, REVISION) == receipt["sourceRevision"]
            and isinstance(envs, list)
            and all(isinstance(env, str) for env in envs)
            and [env for env in envs if env.startswith("NODE_VERSION=")]
            == [f"NODE_VERSION={native['node']}"]
            and [env for env in envs if env.startswith("DSPACE_VERSION=")]
            == [f"DSPACE_VERSION={native['runtimeVersion']}"]
            and get(image_config, "Volumes") in (None, {}),
            "image platform or source provenance mismatch",
        )


def verify_chart(read, receipt):
    chart = receipt["chart"]
    manifest = oci_object(read, CHART, "manifest", chart["digest"])
    descriptor = manifest.get("config")
    layers = manifest.get("layers")
    require(
        manifest.get("schemaVersion") == 2
        and ("mediaType" not in manifest or manifest["mediaType"] == IMAGE_MANIFEST)
        and get(descriptor, "mediaType") == HELM_CONFIG
        and isinstance(layers, list)
        and 1 <= len(layers) <= 2
        and all(
            get(layer, "mediaType") in (HELM_CONTENT, HELM_PROVENANCE)
            and matches(get(layer, "digest"), DIGEST)
            and type(get(layer, "size")) is int
            and layer["size"] > 0
            for layer in layers
        )
        and [layer["digest"] for layer in layers if layer["mediaType"] == HELM_CONTENT]
        == [chart["contentDigest"]],
        "invalid Helm OCI artifact or content descriptor",
    )
    config = oci_object(read, CHART, "blob", get(descriptor, "digest"))
    manifest_annotations, chart_annotations = manifest.get("annotations"), config.get("annotations")
    require(
        config.get("name") == "dspace"
        and config.get("version") == chart["version"]
        and config.get("appVersion") == receipt["applicationVersion"]
        and get(manifest_annotations, VERSION) == chart["version"]
        and get(chart_annotations, VERSION) == receipt["applicationVersion"]
        and get(chart_annotations, SOURCE) == REPOSITORY
        and get(chart_annotations, REVISION) == receipt["sourceRevision"]
        and all(
            key not in manifest_annotations or manifest_annotations[key] == expected
            for key, expected in ((SOURCE, REPOSITORY), (REVISION, receipt["sourceRevision"]))
        ),
        "Helm version or source provenance mismatch",
    )


def preflight(receipt, approval, native_raw, *, home, read=command):
    native = validate_inputs(receipt, approval, native_raw)
    verify_staging_context(read, home)
    verify_platforms(read, receipt, native)
    verify_chart(read, receipt)
    return {
        "schema": "sugarkube-dspace-staging-preflight-v1",
        "environment": "staging",
        "context": CONTEXT,
        "sourceRevision": receipt["sourceRevision"],
        "appVersion": receipt["applicationVersion"],
        "imageReference": f"{IMAGE}@{receipt['image']['digest']}",
        "chartReference": f"oci://{CHART}@{receipt['chart']['digest']}",
        "chartVersion": receipt["chart"]["version"],
        "chartContentDigest": receipt["chart"]["contentDigest"],
        "nativeSummaryDigest": approval["nativeSummaryDigest"],
        "deploymentAuthorized": False,
    }


def input_bytes(path):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as handle:
        require(stat.S_ISREG(os.fstat(handle.fileno()).st_mode), "expected a regular input file")
        raw = handle.read(MAX_INPUT + 1)
        require(len(raw) <= MAX_INPUT, "input file exceeds the size limit")
        return raw


class OneValue(argparse.Action):
    def __call__(self, parser, namespace, values, option_string=None):
        if getattr(namespace, self.dest, None) is not None:
            parser.error(f"{option_string} must be specified only once")
        setattr(namespace, self.dest, values)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("action", choices=["preflight"])
    parser.add_argument("--environment", required=True, choices=["staging"], action=OneValue)
    parser.add_argument("--receipt", required=True, type=Path, action=OneValue)
    parser.add_argument("--approval", required=True, type=Path, action=OneValue)
    parser.add_argument("--native-summary", required=True, type=Path, action=OneValue)
    args = parser.parse_args(argv)
    try:
        result = preflight(
            parse(input_bytes(args.receipt), MAX_INPUT),
            parse(input_bytes(args.approval), MAX_INPUT),
            input_bytes(args.native_summary),
            home=Path.home(),
        )
    except PreflightError as error:
        print(f"Staging coordinate preflight rejected: {error}", file=sys.stderr)
        return 1
    except (OSError, TypeError):
        print(
            "Staging coordinate preflight rejected: unreadable or invalid input.", file=sys.stderr
        )
        return 1
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
