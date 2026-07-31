import json
import subprocess
from argparse import Namespace
from pathlib import Path

import pytest

from scripts import dspace_runtime_verifier as verifier

SHA = "abcdef0123456789abcdef0123456789abcdef01"
DIGEST = "sha256:" + "1" * 64
SENTINEL = "SENTINEL_SECRET"


def manifest(tmp_path: Path, provider: str = "token-place") -> Path:
    path = tmp_path / "manifest.json"
    path.write_text(
        json.dumps(
            {
                "schemaVersion": 1,
                "app": "dspace",
                "applicationVersion": "3.1.0",
                "sourceRevision": SHA,
                "imageTag": "main-abcdef0",
                "imageDigest": DIGEST,
                "chartVersion": "3.1.0",
                "chartDigest": "sha256:" + "2" * 64,
                "semanticTag": "v3.1.0",
                "recordType": "candidate",
                "environment": "staging",
                "expectedDefaultChatProvider": provider,
                "approvedAt": "2026-07-30T00:00:00Z",
                "approvedBy": "release-test",
            }
        )
    )
    return path


def test_capabilities_schema_and_order(capsys: pytest.CaptureFixture[str]) -> None:
    assert (
        verifier.main(
            [
                "capabilities",
                "--environment",
                "staging",
                "--release",
                "dspace",
                "--namespace",
                "dspace",
            ]
        )
        == 0
    )
    value = json.loads(capsys.readouterr().out)
    assert list(value) == ["schemaVersion", "environment", "release", "namespace", "capabilities"]
    assert value["capabilities"] == verifier.CAPABILITIES


def test_values_expectations_use_ordered_overlay(tmp_path: Path) -> None:
    base = tmp_path / "base.yaml"
    overlay = tmp_path / "overlay.yaml"
    base.write_text(
        "env:\n- name: DSPACE_TOKEN_PLACE_URL\n  value: https://old.invalid\n- name: DSPACE_TOKEN_PLACE_CHAT_MODEL\n  value: old\n"
    )
    overlay.write_text(
        "env:\n- name: DSPACE_TOKEN_PLACE_URL\n  value: https://token.example\n- name: DSPACE_TOKEN_PLACE_CHAT_MODEL\n  value: current-model\n"
    )
    assert verifier.values_expectations([base, overlay]) == (
        "https://token.example",
        "current-model",
    )


def _verify_setup(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    provider: str = "token-place",
    rollback: bool = False,
    overrides: dict[str, object] | None = None,
) -> tuple[Namespace, list[list[str]]]:
    """Install a complete, mutable fake cluster and return verifier arguments."""
    override = overrides or {}
    smoke = tmp_path / "smoke"
    smoke.write_text("#!/bin/sh\nexit 0\n")
    smoke.chmod(0o700)
    canonical = "ghcr.io/democratizedspace/dspace:main-abcdef0"
    declared = f"{canonical}@{DIGEST}" if rollback else canonical

    def build(image: str = canonical, revision: str = SHA) -> str:
        return json.dumps(
            {
                "version": "3.1.0",
                "revision": revision,
                "shortRevision": revision[:7],
                "image": image,
            }
        )

    pods = []
    for number in range(2):
        name = f"dspace-{number + 1}"
        pods.append(
            {
                "metadata": {
                    "name": name,
                    "ownerReferences": [
                        {
                            "kind": "ReplicaSet",
                            "name": f"dspace-rs-{number + 1}",
                            "uid": f"rs-{number + 1}",
                            "controller": True,
                        }
                    ],
                },
                "spec": {"containers": [{"name": "dspace", "image": declared}]},
                "status": {
                    "phase": "Running",
                    "conditions": [{"type": "Ready", "status": "True"}],
                    "containerStatuses": [{"name": "dspace", "imageID": "containerd://" + DIGEST}],
                },
            }
        )
    pods = override.get("pods", pods)
    helm_statuses = iter(
        override.get(
            "helm_statuses",
            [
                {"chart": {"metadata": {"name": "dspace", "version": "3.1.0"}}, "version": 7},
                {"chart": {"metadata": {"name": "dspace", "version": "3.1.0"}}, "version": 7},
            ],
        )
    )
    direct_builds = override.get("direct_builds", {})
    direct_html = override.get("direct_html", {})
    public_build = override.get("public_build", build())
    public_html = override.get(
        "public_html", f'<meta name="dspace-build-revision" content="{SHA}">'
    )

    def command(argv: list[str]) -> str:
        if argv[0] == "helm":
            return json.dumps(next(helm_statuses))
        if "pods" in argv:
            return json.dumps({"items": pods})
        if "deployment" in argv:
            return json.dumps(
                {
                    "metadata": {
                        "name": "dspace",
                        "uid": "deploy-1",
                        "labels": {
                            "app.kubernetes.io/managed-by": "Helm",
                            "app.kubernetes.io/instance": "dspace",
                        },
                        "annotations": {
                            "meta.helm.sh/release-name": "dspace",
                            "meta.helm.sh/release-namespace": "dspace",
                        },
                    },
                    "spec": {
                        "template": {
                            "spec": {
                                "containers": [
                                    {
                                        "name": "dspace",
                                        "image": override.get("deployment_image", declared),
                                        "env": [
                                            {
                                                "name": "DSPACE_TOKEN_PLACE_URL",
                                                "value": "https://token.example",
                                            },
                                            {
                                                "name": "DSPACE_TOKEN_PLACE_CHAT_MODEL",
                                                "value": "model-a",
                                            },
                                        ],
                                    }
                                ]
                            }
                        }
                    },
                }
            )
        if "replicaset" in argv:
            name = argv[argv.index("replicaset") + 1]
            number = name.rsplit("-", 1)[-1]
            return json.dumps(
                {
                    "metadata": {
                        "name": name,
                        "uid": f"rs-{number}",
                        "ownerReferences": [
                            {
                                "kind": "Deployment",
                                "name": "dspace",
                                "uid": "deploy-1",
                                "controller": True,
                            }
                        ],
                    }
                }
            )
        pod_name = argv[-1].split("/pods/", 1)[1].split(":", 1)[0]
        failure = override.get("direct_failure")
        if failure == pod_name:
            raise verifier.VerificationError(SENTINEL)
        if argv[-1].endswith("build-info.json"):
            return direct_builds.get(pod_name, build())
        return direct_html.get(pod_name, f'<meta name="dspace-build-revision" content="{SHA}">')

    monkeypatch.setattr(verifier, "command", command)
    monkeypatch.setattr(
        verifier,
        "fetch",
        lambda url, origin: str(public_build if url.endswith(".json") else public_html).encode(),
    )
    monkeypatch.setattr(
        verifier.app_config, "load_config", lambda *args: {"SUGARKUBE_VALUES": "values.yaml"}
    )
    monkeypatch.setattr(verifier, "_resolve_host", lambda paths: "staging.example")
    monkeypatch.setattr(
        verifier, "values_expectations", lambda paths: ("https://token.example", "model-a")
    )
    seen: list[list[str]] = []

    def smoke_run(argv: list[str], **kwargs: object) -> object:
        seen.append(argv)
        return subprocess.CompletedProcess(
            argv,
            int(override.get("chat_returncode", 0)),
            str(override.get("chat_stdout", SENTINEL)),
            str(override.get("chat_stderr", SENTINEL)),
        )

    monkeypatch.setattr(verifier.subprocess, "run", smoke_run)
    return (
        Namespace(
            environment="staging",
            release="dspace",
            namespace="dspace",
            manifest=manifest(tmp_path, provider),
            application_version=None,
            source_revision=None,
            provider=None,
            config=None,
            host=None,
            smoke_runner=str(smoke),
            kubeconfig="kubeconfig",
            expected_helm_revision=None,
        ),
        seen,
    )


@pytest.mark.parametrize("provider,has_token_args", [("token-place", True), ("openai", False)])
@pytest.mark.parametrize("rollback", [False, True], ids=("standard", "rollback"))
@pytest.mark.parametrize(
    "runtime_image_id",
    ["containerd://" + DIGEST, "ghcr.io/democratizedspace/dspace@" + DIGEST],
    ids=("containerd", "pullable"),
)
def test_verify_uses_safe_exact_smoke_argv(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    provider: str,
    has_token_args: bool,
    rollback: bool,
    runtime_image_id: str,
) -> None:
    args, seen = _verify_setup(monkeypatch, tmp_path, provider=provider, rollback=rollback)
    # Exercise both supported imageID spellings through the complete verifier.
    original = verifier.command

    def command(argv: list[str]) -> str:
        value = original(argv)
        if "pods" in argv:
            payload = json.loads(value)
            for pod in payload["items"]:
                pod["status"]["containerStatuses"][0]["imageID"] = runtime_image_id
            return json.dumps(payload)
        return value

    monkeypatch.setattr(verifier, "command", command)
    result = verifier.verify(args)
    assert list(result) == list(verifier.RESULT_FIELDS)
    assert result["journeys"][-1] == {"name": "/chat", "passed": True}
    assert ("--expected-token-place-origin" in seen[-1]) is has_token_args
    assert SENTINEL not in json.dumps(result)


@pytest.mark.parametrize(
    "overrides,category",
    [
        (
            {"public_html": f'<meta name="dspace-build-revision" content="{SENTINEL}">'},
            "public identity",
        ),
        (
            {
                "direct_html": {
                    "dspace-2": f'<meta name="dspace-build-revision" content="{SENTINEL}">'
                }
            },
            "direct identity",
        ),
        ({"public_build": SENTINEL}, "public identity"),
        ({"direct_builds": {"dspace-2": SENTINEL}}, "direct identity"),
    ],
    ids=("public-marker", "direct-marker", "public-json", "direct-json"),
)
def test_verify_redacts_failed_http_identity(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    overrides: dict[str, object],
    category: str,
) -> None:
    args, _ = _verify_setup(monkeypatch, tmp_path, overrides=overrides)
    with pytest.raises(verifier.VerificationError) as raised:
        verifier.verify(args)
    assert str(raised.value) == category
    captured = capsys.readouterr()
    assert SENTINEL not in str(raised.value) + captured.out + captured.err


def test_same_origin_redirect_rejects_cross_origin_before_request() -> None:
    handler = verifier.SameOriginRedirect(("https", "staging.example"))
    with pytest.raises(verifier.VerificationError) as raised:
        handler.redirect_request(
            object(), object(), 302, SENTINEL, {}, "https://attacker.invalid/secret"
        )
    assert str(raised.value) == "public identity"
    assert SENTINEL not in str(raised.value)


def _pod_overrides(mutator) -> dict[str, object]:  # noqa: ANN001
    """Build the minimum two-pod override used by fail-closed replica tests."""
    canonical = "ghcr.io/democratizedspace/dspace:main-abcdef0"
    pods = []
    for number in range(2):
        pod = {
            "metadata": {
                "name": f"dspace-{number + 1}",
                "ownerReferences": [
                    {
                        "kind": "ReplicaSet",
                        "name": f"dspace-rs-{number + 1}",
                        "uid": f"rs-{number + 1}",
                        "controller": True,
                    }
                ],
            },
            "spec": {"containers": [{"name": "dspace", "image": canonical}]},
            "status": {
                "phase": "Running",
                "conditions": [{"type": "Ready", "status": "True"}],
                "containerStatuses": [{"name": "dspace", "imageID": "containerd://" + DIGEST}],
            },
        }
        pods.append(pod)
    mutator(pods[1])
    return {"pods": pods}


@pytest.mark.parametrize(
    "overrides,category",
    [
        (
            _pod_overrides(lambda pod: pod["status"].update({"phase": "Failed"})),
            "pod/replica identity",
        ),
        (
            _pod_overrides(lambda pod: pod["spec"]["containers"][0].update({"image": "wrong"})),
            "pod/replica identity",
        ),
        (
            _pod_overrides(
                lambda pod: pod["status"]["containerStatuses"][0].update(
                    {"imageID": "containerd://sha256:" + "2" * 64}
                )
            ),
            "pod/replica identity",
        ),
        ({"deployment_image": "ghcr.io/democratizedspace/dspace:wrong"}, "cluster identity"),
        ({"direct_failure": "dspace-2"}, "direct identity"),
    ],
    ids=(
        "one-unhealthy",
        "declared-image",
        "resolved-digest",
        "deployment-image",
        "direct-unreachable",
    ),
)
def test_verify_fails_closed_for_any_bad_replica_or_image(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    overrides: dict[str, object],
    category: str,
) -> None:
    args, _ = _verify_setup(monkeypatch, tmp_path, overrides=overrides)
    with pytest.raises(verifier.VerificationError) as raised:
        verifier.verify(args)
    assert str(raised.value) == category
    assert SENTINEL not in str(raised.value)


def test_verify_rejects_mixed_replica_and_public_direct_identity(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    mismatched = json.dumps({"version": "3.1.0", "revision": "f" * 40, "shortRevision": "fffffff"})
    args, _ = _verify_setup(
        monkeypatch,
        tmp_path,
        overrides={"direct_builds": {"dspace-2": mismatched}},
    )
    with pytest.raises(verifier.VerificationError, match="direct identity"):
        verifier.verify(args)

    args, _ = _verify_setup(monkeypatch, tmp_path)
    real_identity = verifier.identity

    def disagree(
        raw: bytes, version: str, revision: str, image: str, category: str
    ):  # noqa: ANN202
        value = real_identity(raw, version, revision, image, category)
        return (value[0], value[1], "different") if category == "public identity" else value

    monkeypatch.setattr(verifier, "identity", disagree)
    with pytest.raises(verifier.VerificationError, match="public identity"):
        verifier.verify(args)


def test_verify_redacts_nonzero_chat_output(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    args, _ = _verify_setup(
        monkeypatch,
        tmp_path,
        overrides={"chat_returncode": 9, "chat_stdout": SENTINEL, "chat_stderr": SENTINEL},
    )
    with pytest.raises(verifier.VerificationError) as raised:
        verifier.verify(args)
    assert str(raised.value) == "provider/chat smoke"
    captured = capsys.readouterr()
    assert SENTINEL not in str(raised.value) + captured.out + captured.err


@pytest.mark.parametrize(
    "overrides",
    [
        {"public_build": SENTINEL},
        {"chat_returncode": 9, "chat_stdout": SENTINEL, "chat_stderr": SENTINEL},
    ],
    ids=("http", "chat"),
)
def test_main_failure_record_redacts_http_and_chat_content(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    overrides: dict[str, object],
) -> None:
    args, _ = _verify_setup(monkeypatch, tmp_path, overrides=overrides)
    assert (
        verifier.main(
            [
                "verify",
                "--environment",
                args.environment,
                "--release",
                args.release,
                "--namespace",
                args.namespace,
                "--manifest",
                str(args.manifest),
                "--smoke-runner",
                args.smoke_runner,
                "--kubeconfig",
                args.kubeconfig,
            ]
        )
        == 2
    )
    captured = capsys.readouterr()
    assert SENTINEL not in captured.out + captured.err
    assert captured.out == ""
    assert captured.err.startswith("ERROR: DSPACE verification failed (")


def test_verify_detects_helm_change_during_chat(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    status = {"chart": {"metadata": {"name": "dspace", "version": "3.1.0"}}, "version": 7}
    changed = {**status, "version": 8}
    args, _ = _verify_setup(monkeypatch, tmp_path, overrides={"helm_statuses": [status, changed]})
    with pytest.raises(verifier.VerificationError) as raised:
        verifier.verify(args)
    assert str(raised.value) == "concurrent Helm change"


def test_missing_or_nonexecutable_runner_fails_safely(tmp_path: Path) -> None:
    args = Namespace(
        environment="staging",
        release="dspace",
        namespace="dspace",
        manifest=manifest(tmp_path),
        application_version=None,
        source_revision=None,
        provider=None,
        config=None,
        host="staging.example",
        smoke_runner=str(tmp_path / "missing"),
        kubeconfig="k",
    )
    with pytest.raises(verifier.VerificationError, match="provider/chat smoke"):
        verifier.verify(args)


def test_cli_rejects_unknown_fields() -> None:
    with pytest.raises(verifier.VerificationError):
        verifier.parser().parse_args(
            [
                "capabilities",
                "--environment",
                "staging",
                "--release",
                "dspace",
                "--namespace",
                "dspace",
                "--unknown",
            ]
        )


def test_main_never_echoes_unknown_argument_value(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert (
        verifier.main(
            [
                "capabilities",
                "--environment",
                "staging",
                "--release",
                "dspace",
                "--namespace",
                "dspace",
                "--unknown",
                "SENTINEL_SECRET",
            ]
        )
        == 2
    )
    captured = capsys.readouterr()
    assert "SENTINEL_SECRET" not in captured.out + captured.err


@pytest.mark.parametrize(
    "status,expected_revision,category",
    [
        (
            {"chart": {"metadata": {"name": "other", "version": "3.1.0"}}, "version": 7},
            None,
            "cluster identity",
        ),
        (
            {"chart": {"metadata": {"name": "dspace", "version": "3.0.0"}}, "version": 7},
            None,
            "cluster identity",
        ),
        (
            {"chart": {"metadata": {"name": "dspace", "version": "3.1.0"}}, "version": 0},
            None,
            "cluster identity",
        ),
        (
            {"chart": {"metadata": {"name": "dspace", "version": "3.1.0"}}, "version": 7},
            6,
            "staging drift",
        ),
    ],
)
def test_helm_identity_rejects_wrong_real_status_fields(
    monkeypatch: pytest.MonkeyPatch,
    status: dict[str, object],
    expected_revision: int | None,
    category: str,
) -> None:
    monkeypatch.setattr(verifier, "command", lambda argv: json.dumps(status))
    args = Namespace(
        kubeconfig="k",
        release="dspace",
        namespace="dspace",
        expected_helm_revision=expected_revision,
    )
    with pytest.raises(verifier.VerificationError, match=category):
        verifier.helm_identity(args, "3.1.0")


def test_helm_identity_accepts_real_status_schema(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        verifier,
        "command",
        lambda argv: json.dumps(
            {"chart": {"metadata": {"name": "dspace", "version": "3.1.0"}}, "version": 7}
        ),
    )
    args = Namespace(kubeconfig="k", release="dspace", namespace="dspace", expected_helm_revision=7)
    assert verifier.helm_identity(args, "3.1.0") == ("dspace", "3.1.0", 7)


def test_command_timeout_is_bounded_and_redacted(monkeypatch: pytest.MonkeyPatch) -> None:
    def timeout(*args: object, **kwargs: object) -> None:
        raise subprocess.TimeoutExpired(["kubectl", "SENTINEL_SECRET"], 15)

    monkeypatch.setattr(verifier.subprocess, "run", timeout)
    with pytest.raises(verifier.VerificationError) as raised:
        verifier.command(["kubectl", "SENTINEL_SECRET"])
    assert str(raised.value) == "cluster identity"
    assert "SENTINEL_SECRET" not in str(raised.value)


@pytest.mark.parametrize(
    "image_id",
    ["containerd://" + DIGEST, "registry.example/dspace@" + DIGEST],
)
def test_image_id_digest_accepts_established_runtime_forms(image_id: str) -> None:
    assert verifier.image_id_digest(image_id) == DIGEST


@pytest.mark.parametrize(
    "image_id",
    [
        "containerd://sha256:" + "1" * 63,
        "containerd://sha256:" + "A" * 64,
        "containerd://" + DIGEST + "-extra",
        "containerd://sha512:" + "1" * 64,
        None,
    ],
)
def test_image_id_digest_rejects_malformed_values_without_leaking(image_id: object) -> None:
    with pytest.raises(verifier.VerificationError) as raised:
        verifier.image_id_digest(image_id)
    assert str(raised.value) == "pod/replica identity"
    assert str(image_id) not in str(raised.value)


def test_image_id_digest_rejects_wrong_digest() -> None:
    assert verifier.image_id_digest("containerd://sha256:" + "2" * 64) != DIGEST


@pytest.mark.parametrize("controller", [None, False])
def test_controller_owner_requires_true_controller(controller: bool | None) -> None:
    owner = {"kind": "ReplicaSet", "name": "dspace-rs", "uid": "rs-1"}
    if controller is not None:
        owner["controller"] = controller
    with pytest.raises(verifier.VerificationError, match="pod/replica identity"):
        verifier.controller_owner([owner], "ReplicaSet")


@pytest.mark.parametrize(
    "annotation,value",
    [
        ("meta.helm.sh/release-name", None),
        ("meta.helm.sh/release-name", "other"),
        ("meta.helm.sh/release-namespace", None),
        ("meta.helm.sh/release-namespace", "other"),
    ],
)
def test_deployment_requires_matching_helm_annotations(annotation: str, value: str | None) -> None:
    metadata = {
        "name": "dspace",
        "uid": "deploy-1",
        "labels": {
            "app.kubernetes.io/managed-by": "Helm",
            "app.kubernetes.io/instance": "dspace",
        },
        "annotations": {
            "meta.helm.sh/release-name": "dspace",
            "meta.helm.sh/release-namespace": "dspace",
        },
    }
    if value is None:
        del metadata["annotations"][annotation]
    else:
        metadata["annotations"][annotation] = value
    with pytest.raises(verifier.VerificationError, match="cluster identity"):
        verifier.helm_deployment_uid(metadata, "dspace", "dspace")


@pytest.mark.parametrize(
    "payload,category",
    [
        ({"version": "wrong", "revision": SHA, "shortRevision": "abcdef0"}, "public identity"),
        ({"version": "3.1.0", "revision": "wrong", "shortRevision": "abcdef0"}, "public identity"),
        ({"version": "3.1.0", "revision": SHA, "shortRevision": "wrong"}, "public identity"),
        (
            {
                "version": "3.1.0",
                "revision": SHA,
                "shortRevision": "abcdef0",
                "image": f"ghcr.io/democratizedspace/dspace:main-abcdef0@{DIGEST}",
            },
            "public identity",
        ),
    ],
)
def test_build_identity_requires_canonical_coordinates(
    payload: dict[str, str], category: str
) -> None:
    with pytest.raises(verifier.VerificationError, match=category):
        verifier.identity(
            json.dumps(payload).encode(),
            "3.1.0",
            SHA,
            "ghcr.io/democratizedspace/dspace:main-abcdef0",
            category,
        )
