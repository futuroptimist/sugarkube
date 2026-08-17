from copy import deepcopy
import json
import subprocess
from argparse import Namespace
from pathlib import Path

import pytest

from scripts import dspace_runtime_verifier as verifier

SHA = "abcdef0123456789abcdef0123456789abcdef01"
DIGEST = "sha256:" + "1" * 64
SENTINEL = "SENTINEL_SECRET"
RECOVERY_SHA = "1a31a569aff2dbeb238e8c2688b9e85140d2077d"
BUILD_TIMESTAMP = "2026-08-01T12:00:00Z"


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


def recovery_manifest(tmp_path: Path, **changes: object) -> Path:
    value = {
        **verifier.LEGACY_303_COORDINATES,
        "app": "dspace",
        "recordType": "candidate",
        "environment": "prod",
        "approvedAt": "2026-07-30T00:00:00Z",
        "approvedBy": "release-test",
        **changes,
    }
    path = tmp_path / "recovery.json"
    path.write_text(json.dumps(value))
    return path


def legacy_310_manifest(tmp_path: Path, **changes: object) -> Path:
    value = {
        **verifier.LEGACY_310_COORDINATES,
        "app": "dspace",
        "recordType": "candidate",
        "environment": "staging",
        "approvedAt": "2026-07-30T00:00:00Z",
        "approvedBy": "release-test",
        **changes,
    }
    path = tmp_path / "legacy-3.1.0.json"
    path.write_text(json.dumps(value))
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
    legacy: bool = False,
    legacy_310: bool = False,
) -> tuple[Namespace, list[list[str]]]:
    """Install a complete, mutable fake cluster and return verifier arguments."""
    if legacy and legacy_310:
        raise ValueError("legacy and legacy_310 are mutually exclusive")

    override = overrides or {}
    smoke = tmp_path / "smoke"
    smoke.write_text("#!/bin/sh\nexit 0\n")
    smoke.chmod(0o700)
    coordinates = (
        verifier.LEGACY_310_COORDINATES if legacy_310 else verifier.LEGACY_303_COORDINATES
    )
    is_legacy = legacy or legacy_310
    revision = str(coordinates["sourceRevision"]) if is_legacy else SHA
    digest = str(coordinates["imageDigest"]) if is_legacy else DIGEST
    image_tag = str(coordinates["imageTag"]) if is_legacy else "main-abcdef0"
    version = str(coordinates["applicationVersion"]) if is_legacy else "3.1.0"
    chart_version = str(coordinates["chartVersion"]) if is_legacy else "3.1.0"
    canonical = f"ghcr.io/democratizedspace/dspace:{image_tag}"
    declared = f"{canonical}@{digest}" if rollback else canonical

    def build(image: str = canonical, revision: str = SHA) -> str:
        return json.dumps(
            {
                "version": version,
                "revision": revision,
                "shortRevision": revision[:7],
                "buildTimestamp": BUILD_TIMESTAMP,
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
                "spec": {
                    "containers": [
                        {
                            "name": "dspace",
                            "image": declared,
                            "ports": [{"name": "http", "containerPort": 8080}],
                        }
                    ]
                },
                "status": {
                    "phase": "Running",
                    "conditions": [{"type": "Ready", "status": "True"}],
                    "containerStatuses": [{"name": "dspace", "imageID": "containerd://" + digest}],
                },
            }
        )
    pods = override.get("pods", pods)
    helm_statuses = iter(
        override.get(
            "helm_statuses",
            [
                {"chart": {"metadata": {"name": "dspace", "version": chart_version}}, "version": 7},
                {"chart": {"metadata": {"name": "dspace", "version": chart_version}}, "version": 7},
            ],
        )
    )
    helm_histories = iter(
        override.get(
            "helm_histories",
            [
                [{"revision": 7, "chart": f"dspace-{chart_version}"}],
                [{"revision": 7, "chart": f"dspace-{chart_version}"}],
            ],
        )
    )
    direct_builds = override.get("direct_builds", {})
    direct_html = override.get("direct_html", {})
    public_build = override.get("public_build", build())
    default_html = (
        "<!doctype html><html><head><title>DSPACE</title></head><body></body></html>"
        if is_legacy
        else f'<meta name="dspace-build-revision" content="{SHA}">'
    )
    public_html = override.get("public_html", default_html)
    legacy_build = json.dumps(
        {"gitSha": revision, "generatedAt": "2026-08-01T12:00:00Z", "source": "dspace"}
    )

    def command(argv: list[str]) -> str:
        if argv[0] == "helm":
            if "history" in argv:
                return json.dumps(next(helm_histories))
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
                                        "ports": override.get(
                                            "deployment_ports",
                                            [{"name": "http", "containerPort": 8080}],
                                        ),
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
        if argv[-1].endswith("build-meta.json"):
            return override.get("direct_meta", {}).get(pod_name, legacy_build)
        if argv[-1].endswith("build-info.json"):
            return direct_builds.get(pod_name, build())
        return direct_html.get(pod_name, default_html)

    monkeypatch.setattr(verifier, "command", command)
    monkeypatch.setattr(
        verifier,
        "fetch",
        lambda url, origin: str(
            override.get("public_meta", legacy_build)
            if url.endswith("build-meta.json")
            else public_build if url.endswith(".json") else public_html
        ).encode(),
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
    if legacy_310:
        manifest_path = legacy_310_manifest(tmp_path)
    elif legacy:
        manifest_path = recovery_manifest(tmp_path)
    else:
        manifest_path = manifest(tmp_path, provider)

    return (
        Namespace(
            environment="staging",
            release="dspace",
            namespace="dspace",
            manifest=manifest_path,
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


def test_verify_setup_rejects_conflicting_legacy_flags(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    with pytest.raises(ValueError, match="mutually exclusive"):
        _verify_setup(monkeypatch, tmp_path, legacy=True, legacy_310=True)


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
    contract_index = seen[-1].index("--identity-contract")
    assert seen[-1][contract_index + 1] == verifier.MODERN_IDENTITY_CONTRACT
    assert ("--expected-token-place-origin" in seen[-1]) is has_token_args
    assert SENTINEL not in json.dumps(result)


def test_derived_http_port_is_used_for_every_direct_request(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    args, _ = _verify_setup(monkeypatch, tmp_path)
    original = verifier.command
    proxy_urls: list[str] = []

    def command(argv: list[str]) -> str:
        if "--raw" in argv:
            proxy_urls.append(argv[-1])
        return original(argv)

    monkeypatch.setattr(verifier, "command", command)
    verifier.verify(args)
    assert len(proxy_urls) == 4
    assert all(":8080/proxy/" in url for url in proxy_urls)
    assert all(":3000/" not in url for url in proxy_urls)


def test_verify_refreshes_terminating_snapshot_before_direct_and_smoke(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    args, smoke_calls = _verify_setup(monkeypatch, tmp_path)
    original = verifier.command
    settled = json.loads(original(["kubectl", "get", "pods"]))["items"]
    terminating = deepcopy(settled[0])
    terminating["metadata"]["name"] = SENTINEL
    terminating["metadata"]["deletionTimestamp"] = "2026-08-01T09:34:43Z"
    snapshots = iter([settled + [terminating], settled])
    pod_fetches = 0
    direct_urls: list[str] = []
    sleeps: list[float] = []

    def command(argv: list[str]) -> str:
        nonlocal pod_fetches
        if "pods" in argv and "--raw" not in argv:
            pod_fetches += 1
            return json.dumps({"items": next(snapshots)})
        if "--raw" in argv:
            direct_urls.append(argv[-1])
        return original(argv)

    monkeypatch.setattr(verifier, "command", command)
    monkeypatch.setattr(verifier.time, "sleep", sleeps.append)

    verifier.verify(args)

    assert pod_fetches == 2
    assert sleeps == [verifier.POD_SETTLE_INTERVAL_SECONDS]
    assert len(direct_urls) == 4
    assert all(SENTINEL not in url for url in direct_urls)
    assert len(smoke_calls) == 1
    assert SENTINEL not in json.dumps(smoke_calls)


def test_verify_does_not_refresh_or_wait_for_settled_snapshot(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    args, _ = _verify_setup(monkeypatch, tmp_path)
    original = verifier.command
    pod_fetches = 0

    def command(argv: list[str]) -> str:
        nonlocal pod_fetches
        if "pods" in argv and "--raw" not in argv:
            pod_fetches += 1
        return original(argv)

    monkeypatch.setattr(verifier, "command", command)
    monkeypatch.setattr(
        verifier.time, "sleep", lambda _seconds: pytest.fail("settled pods must not sleep")
    )

    verifier.verify(args)

    assert pod_fetches == 1


def test_settle_selected_pods_times_out_without_filtering_or_leaking(
    capsys: pytest.CaptureFixture[str],
) -> None:
    payload = json.dumps(
        {
            "items": [
                {
                    "metadata": {
                        "name": SENTINEL,
                        "deletionTimestamp": SENTINEL,
                    }
                }
            ]
        }
    )
    fetches: list[list[str]] = []
    sleeps: list[float] = []
    times = iter([0.0, 0.0, verifier.POD_SETTLE_TIMEOUT_SECONDS])

    with pytest.raises(verifier.VerificationError) as raised:
        verifier.settle_selected_pods(
            ["kubectl", SENTINEL],
            runner=lambda argv: fetches.append(argv) or payload,
            monotonic=lambda: next(times),
            sleeper=sleeps.append,
        )

    assert str(raised.value) == "pod/replica identity"
    assert len(fetches) == 2
    assert sleeps == [verifier.POD_SETTLE_INTERVAL_SECONDS]
    captured = capsys.readouterr()
    assert SENTINEL not in str(raised.value) + captured.out + captured.err


def test_settle_selected_pods_preserves_runner_verification_error() -> None:
    def runner(_argv: list[str]) -> str:
        raise verifier.VerificationError("cluster identity")

    with pytest.raises(verifier.VerificationError) as raised:
        verifier.settle_selected_pods(["kubectl", "get", "pods"], runner=runner)

    assert str(raised.value) == "cluster identity"


def test_settle_selected_pods_rejects_non_string_runner_result() -> None:
    with pytest.raises(verifier.VerificationError) as raised:
        verifier.settle_selected_pods(
            ["kubectl", "get", "pods"], runner=lambda _argv: {"items": []}
        )

    assert str(raised.value) == "pod/replica identity"


def test_settle_selected_pods_rejects_non_object_pod_without_leaking(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(verifier.VerificationError) as raised:
        verifier.settle_selected_pods(
            ["kubectl", "get", "pods"],
            runner=lambda _argv: json.dumps({"items": [SENTINEL]}),
        )

    assert str(raised.value) == "pod/replica identity"
    captured = capsys.readouterr()
    assert SENTINEL not in str(raised.value) + captured.out + captured.err


@pytest.mark.parametrize("section", ["metadata", "spec", "status"])
def test_verify_rejects_malformed_active_pod_section_after_termination_settles(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    section: str,
) -> None:
    args, _ = _verify_setup(monkeypatch, tmp_path)
    original = verifier.command
    settled = json.loads(original(["kubectl", "get", "pods"]))["items"]
    terminating = deepcopy(settled[0])
    terminating["metadata"]["deletionTimestamp"] = "2026-08-01T09:34:43Z"
    bad_active = deepcopy(settled)
    bad_active[1][section] = SENTINEL
    snapshots = iter([settled + [terminating], bad_active])

    def command(argv: list[str]) -> str:
        if "pods" in argv and "--raw" not in argv:
            return json.dumps({"items": next(snapshots)})
        return original(argv)

    monkeypatch.setattr(verifier, "command", command)
    monkeypatch.setattr(verifier.time, "sleep", lambda _seconds: None)

    with pytest.raises(verifier.VerificationError) as raised:
        verifier.verify(args)

    assert str(raised.value) == "pod/replica identity"
    captured = capsys.readouterr()
    assert SENTINEL not in str(raised.value) + captured.out + captured.err


@pytest.mark.parametrize("field", ["conditions", "containers", "containerStatuses"])
@pytest.mark.parametrize(
    "bad_value", [None, SENTINEL, [SENTINEL]], ids=("none", "non-list", "non-dict")
)
def test_verify_rejects_malformed_active_pod_lists_after_termination_settles(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    field: str,
    bad_value: object,
) -> None:
    args, _ = _verify_setup(monkeypatch, tmp_path)
    original = verifier.command
    settled = json.loads(original(["kubectl", "get", "pods"]))["items"]
    terminating = deepcopy(settled[0])
    terminating["metadata"]["deletionTimestamp"] = "2026-08-01T09:34:43Z"
    bad_active = deepcopy(settled)
    section = "spec" if field == "containers" else "status"
    bad_active[1][section][field] = bad_value
    snapshots = iter([settled + [terminating], bad_active])

    def command(argv: list[str]) -> str:
        if "pods" in argv and "--raw" not in argv:
            return json.dumps({"items": next(snapshots)})
        return original(argv)

    monkeypatch.setattr(verifier, "command", command)
    monkeypatch.setattr(verifier.time, "sleep", lambda _seconds: None)

    with pytest.raises(verifier.VerificationError) as raised:
        verifier.verify(args)

    assert str(raised.value) == "pod/replica identity"
    captured = capsys.readouterr()
    assert SENTINEL not in str(raised.value) + captured.out + captured.err


@pytest.mark.parametrize(
    "mutator",
    [
        lambda pod: pod["status"].update({"conditions": []}),
        lambda pod: pod["spec"].update({"containers": []}),
        lambda pod: pod["metadata"].update({"ownerReferences": []}),
        lambda pod: pod["status"]["containerStatuses"][0].update(
            {"imageID": "containerd://sha256:" + "2" * 64}
        ),
    ],
    ids=("unready", "malformed", "incorrect-owner", "wrong-digest"),
)
def test_verify_still_rejects_bad_active_pod_after_termination_settles(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, mutator
) -> None:  # noqa: ANN001
    args, _ = _verify_setup(monkeypatch, tmp_path)
    original = verifier.command
    settled = json.loads(original(["kubectl", "get", "pods"]))["items"]
    terminating = deepcopy(settled[0])
    terminating["metadata"]["deletionTimestamp"] = "2026-08-01T09:34:43Z"
    bad_active = deepcopy(settled)
    mutator(bad_active[1])
    snapshots = iter([settled + [terminating], bad_active])

    def command(argv: list[str]) -> str:
        if "pods" in argv and "--raw" not in argv:
            return json.dumps({"items": next(snapshots)})
        return original(argv)

    monkeypatch.setattr(verifier, "command", command)
    monkeypatch.setattr(verifier.time, "sleep", lambda _seconds: None)

    with pytest.raises(verifier.VerificationError) as raised:
        verifier.verify(args)
    assert str(raised.value) == "pod/replica identity"


@pytest.mark.parametrize(
    "ports",
    [
        [],
        [{"name": "other", "containerPort": 8080}],
        [{"name": "http", "containerPort": 8080}, {"name": "http", "containerPort": 8081}],
        [{"name": "http", "containerPort": "8080"}],
        [{"name": "http", "containerPort": True}],
        [{"name": "http", "containerPort": 0}],
        [{"name": "http", "containerPort": 65536}],
    ],
    ids=("missing", "wrong-name", "duplicate", "string", "boolean", "zero", "too-large"),
)
def test_deployment_http_port_fails_closed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, ports: list[dict[str, object]]
) -> None:
    args, _ = _verify_setup(monkeypatch, tmp_path, overrides={"deployment_ports": ports})
    with pytest.raises(verifier.VerificationError, match="cluster identity"):
        verifier.verify(args)


@pytest.mark.parametrize("container", [None, {}, {"ports": None}])
def test_named_http_port_rejects_malformed_container(container: object) -> None:
    with pytest.raises(verifier.VerificationError) as raised:
        verifier.named_http_port(container, "cluster identity")
    assert str(raised.value) == "cluster identity"


def test_pod_http_port_must_match_deployment(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    overrides = _pod_overrides(
        lambda pod: pod["spec"]["containers"][0]["ports"][0].update({"containerPort": 8081})
    )
    args, _ = _verify_setup(monkeypatch, tmp_path, overrides=overrides)
    with pytest.raises(verifier.VerificationError, match="pod/replica identity"):
        verifier.verify(args)


def test_exact_recovery_uses_legacy_contract_and_truthful_journeys(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    args, seen = _verify_setup(monkeypatch, tmp_path, legacy=True, provider="openai")
    result = verifier.verify(args)
    contract_index = seen[-1].index("--identity-contract")
    assert seen[-1][contract_index + 1] == verifier.LEGACY_IDENTITY_CONTRACT
    assert result["journeys"] == [
        {"name": "/build-meta.json", "passed": True},
        {"name": "/", "passed": True},
        {"name": "/chat", "passed": True},
    ]


@pytest.mark.parametrize(
    "coordinates",
    [verifier.LEGACY_302_COORDINATES, verifier.LEGACY_303_COORDINATES],
    ids=["chart-3.0.2", "chart-3.0.3"],
)
def test_exact_recovery_coordinates_use_legacy_contract(coordinates: dict[str, object]) -> None:
    assert (
        verifier.identity_contract(dict(coordinates))
        == verifier.LEGACY_IDENTITY_CONTRACT
    )


def test_exact_310_token_place_uses_legacy_contract_and_truthful_journeys(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    args, seen = _verify_setup(monkeypatch, tmp_path, legacy_310=True)
    result = verifier.verify(args)
    smoke_argv = seen[-1]
    assert (
        smoke_argv[smoke_argv.index("--identity-contract") + 1] == verifier.LEGACY_IDENTITY_CONTRACT
    )
    assert smoke_argv[smoke_argv.index("--expected-provider") + 1] == "token-place"
    assert (
        smoke_argv[smoke_argv.index("--expected-token-place-origin") + 1] == "https://token.example"
    )
    assert smoke_argv[smoke_argv.index("--expected-token-place-model") + 1] == "model-a"
    assert result["journeys"] == [
        {"name": "/build-meta.json", "passed": True},
        {"name": "/", "passed": True},
        {"name": "/chat", "passed": True},
    ]


@pytest.mark.parametrize(
    "coordinates",
    [verifier.LEGACY_302_COORDINATES, verifier.LEGACY_303_COORDINATES],
    ids=["chart-3.0.2", "chart-3.0.3"],
)
@pytest.mark.parametrize("field", list(verifier.LEGACY_303_COORDINATES))
def test_any_recovery_coordinate_drift_prevents_legacy_selection(
    coordinates: dict[str, object],
    field: str,
) -> None:
    candidate = dict(coordinates)
    candidate[field] = "different"
    assert verifier.identity_contract(candidate) == verifier.MODERN_IDENTITY_CONTRACT


@pytest.mark.parametrize("field", list(verifier.LEGACY_310_COORDINATES))
def test_any_310_coordinate_drift_prevents_legacy_selection(field: str) -> None:
    candidate = dict(verifier.LEGACY_310_COORDINATES)
    candidate[field] = "different"
    assert verifier.identity_contract(candidate) == verifier.MODERN_IDENTITY_CONTRACT


def test_unrelated_modern_manifest_uses_modern_contract(tmp_path: Path) -> None:
    candidate = json.loads(manifest(tmp_path).read_text())
    assert verifier.identity_contract(candidate) == verifier.MODERN_IDENTITY_CONTRACT


def test_modern_identity_failure_never_requests_legacy_surface(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    args, _ = _verify_setup(monkeypatch, tmp_path, overrides={"direct_builds": {"dspace-1": "{"}})
    original = verifier.command
    paths: list[str] = []

    def command(argv: list[str]) -> str:
        if "--raw" in argv:
            paths.append(argv[-1])
        return original(argv)

    monkeypatch.setattr(verifier, "command", command)
    with pytest.raises(verifier.VerificationError, match="direct identity"):
        verifier.verify(args)
    assert paths and all("build-meta.json" not in path for path in paths)


@pytest.mark.parametrize(
    "payload",
    [
        b"{",
        b"x" * (1024 * 1024 + 1),
        b"\xff" + SENTINEL.encode(),
        b"[" * 2000 + SENTINEL.encode() + b"]" * 2000,
        json.dumps(
            {"gitSha": "wrong", "generatedAt": "2026-08-01T12:00:00Z", "source": "x"}
        ).encode(),
        json.dumps({"gitSha": RECOVERY_SHA, "generatedAt": "", "source": "x"}).encode(),
        json.dumps({"gitSha": RECOVERY_SHA, "generatedAt": "not-a-date", "source": "x"}).encode(),
        json.dumps(
            {
                "gitSha": RECOVERY_SHA,
                "generatedAt": "2026-08-01T12:00:00",
                "source": SENTINEL,
            }
        ).encode(),
        json.dumps(
            {"gitSha": RECOVERY_SHA, "generatedAt": "2026-08-01T12:00:00Z", "source": ""}
        ).encode(),
        json.dumps(
            {
                "gitSha": RECOVERY_SHA,
                "generatedAt": "2026-08-01T12:00:00Z",
                "source": "x",
                "extra": SENTINEL,
            }
        ).encode(),
    ],
    ids=(
        "malformed",
        "oversized",
        "invalid-utf8",
        "deeply-nested",
        "wrong-sha",
        "empty-time",
        "bad-time",
        "timezone-naive",
        "empty-source",
        "unsafe-shape",
    ),
)
def test_legacy_identity_rejects_bad_payloads_without_leaking(payload: bytes) -> None:
    with pytest.raises(verifier.VerificationError) as raised:
        verifier.legacy_identity(payload, RECOVERY_SHA, "direct identity")
    assert str(raised.value) == "direct identity"
    assert SENTINEL not in str(raised.value)


@pytest.mark.parametrize("category", ["direct identity", "public identity"])
@pytest.mark.parametrize(
    "payload",
    [b"<html>" + b"x" * (1024 * 1024) + SENTINEL.encode(), b"\xff" + SENTINEL.encode()],
    ids=("oversized", "invalid-utf8"),
)
def test_root_document_rejects_unsafe_payload_without_leaking(
    payload: bytes, category: str
) -> None:
    with pytest.raises(verifier.VerificationError) as raised:
        verifier.root_document(payload, category)
    assert str(raised.value) == category
    assert SENTINEL not in str(raised.value)


@pytest.mark.parametrize(
    "overrides,category",
    [
        (
            {
                "direct_meta": {
                    "dspace-2": json.dumps(
                        {
                            "gitSha": RECOVERY_SHA,
                            "generatedAt": "2026-08-02T12:00:00Z",
                            "source": "dspace",
                        }
                    )
                }
            },
            "pod/replica identity",
        ),
        (
            {
                "public_meta": json.dumps(
                    {
                        "gitSha": RECOVERY_SHA,
                        "generatedAt": "2026-08-02T12:00:00Z",
                        "source": "dspace",
                    }
                )
            },
            "public identity",
        ),
        ({"direct_html": {"dspace-1": ""}}, "direct identity"),
        ({"public_html": ""}, "public identity"),
        ({"direct_html": {"dspace-1": '{"status":"ok"}'}}, "direct identity"),
        ({"direct_html": {"dspace-1": "DSPACE is running"}}, "direct identity"),
        ({"public_html": '{"status":"ok"}'}, "public identity"),
        ({"public_html": "DSPACE is running"}, "public identity"),
    ],
    ids=(
        "replica-disagreement",
        "public-disagreement",
        "empty-direct-root",
        "empty-public-root",
        "json-direct-root",
        "plain-text-direct-root",
        "json-public-root",
        "plain-text-public-root",
    ),
)
def test_legacy_agreement_and_root_evidence_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    overrides: dict[str, object],
    category: str,
) -> None:
    args, _ = _verify_setup(monkeypatch, tmp_path, legacy=True, overrides=overrides)
    with pytest.raises(verifier.VerificationError, match=category):
        verifier.verify(args)


@pytest.mark.parametrize(
    "overrides,category",
    [
        (
            {
                "direct_meta": {
                    "dspace-1": json.dumps(
                        {
                            "gitSha": RECOVERY_SHA,
                            "generatedAt": "2026-08-01T12:00:00Z",
                            "source": "dspace",
                        }
                    )
                }
            },
            "direct identity",
        ),
        (
            {
                "public_meta": json.dumps(
                    {
                        "gitSha": verifier.LEGACY_310_COORDINATES["sourceRevision"],
                        "generatedAt": "2026-08-01T12:00:00Z",
                        "source": "dspace",
                        "extra": True,
                    }
                )
            },
            "public identity",
        ),
        (
            {
                "direct_meta": {
                    "dspace-2": json.dumps(
                        {
                            "gitSha": verifier.LEGACY_310_COORDINATES["sourceRevision"],
                            "generatedAt": "2026-08-02T12:00:00Z",
                            "source": "dspace",
                        }
                    )
                }
            },
            "pod/replica identity",
        ),
    ],
    ids=("wrong-sha", "extra-field", "replica-disagreement"),
)
def test_310_legacy_metadata_failures_remain_rejected(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    overrides: dict[str, object],
    category: str,
) -> None:
    args, _ = _verify_setup(monkeypatch, tmp_path, legacy_310=True, overrides=overrides)
    with pytest.raises(verifier.VerificationError, match=category):
        verifier.verify(args)


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


def test_same_origin_redirect_rejects_cross_origin_before_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    handler = verifier.SameOriginRedirect(("https", "staging.example"))
    redirected = False

    def redirect(*args: object) -> None:
        nonlocal redirected
        redirected = True

    monkeypatch.setattr(verifier.urllib.request.HTTPRedirectHandler, "redirect_request", redirect)
    with pytest.raises(verifier.VerificationError) as raised:
        handler.redirect_request(
            object(), object(), 302, SENTINEL, {}, "https://attacker.invalid/secret"
        )
    assert str(raised.value) == "public identity"
    assert SENTINEL not in str(raised.value)
    assert redirected is False


def test_same_origin_redirect_preserves_user_agent() -> None:
    handler = verifier.SameOriginRedirect(("https", "staging.example"))
    request = verifier.urllib.request.Request(
        "https://staging.example/build-meta.json",
        headers={"User-Agent": verifier.PUBLIC_HTTP_USER_AGENT},
    )

    redirected = handler.redirect_request(
        request, object(), 302, "Found", {}, "https://staging.example/build-meta.json?current=1"
    )

    assert redirected is not None
    assert redirected.full_url == "https://staging.example/build-meta.json?current=1"
    assert redirected.get_header("User-agent") == verifier.PUBLIC_HTTP_USER_AGENT


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
            "spec": {
                "containers": [
                    {
                        "name": "dspace",
                        "image": canonical,
                        "ports": [{"name": "http", "containerPort": 8080}],
                    }
                ]
            },
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
    mismatched = json.dumps(
        {
            "version": "3.1.0",
            "revision": "f" * 40,
            "shortRevision": "fffffff",
            "buildTimestamp": BUILD_TIMESTAMP,
        }
    )
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
        return (
            (*value[:2], "2026-08-02T12:00:00Z", value[3])
            if category == "public identity"
            else value
        )

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


def test_verify_detects_helm_change_during_chat_with_history_fallback(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    args, _ = _verify_setup(
        monkeypatch,
        tmp_path,
        overrides={
            "helm_statuses": [{"version": 7}, {"version": 8}],
            "helm_histories": [
                [{"revision": 7, "chart": "dspace-3.1.0"}],
                [{"revision": 8, "chart": "dspace-3.1.0"}],
            ],
        },
    )
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


@pytest.mark.parametrize("chart", [pytest.param("omitted", id="omitted"), None, {"metadata": None}])
def test_helm_identity_uses_exact_current_history_when_status_omits_chart(
    monkeypatch: pytest.MonkeyPatch, chart: object
) -> None:
    status = {
        "config": {},
        "info": {"status": "deployed"},
        "manifest": "redacted",
        "name": "dspace",
        "namespace": "dspace",
        "version": 26,
    }
    if chart != "omitted":
        status["chart"] = chart
    history = [
        {
            "revision": 26,
            "chart": "dspace-3.0.2",
            "app_version": "3.0.1",
            "status": "deployed",
            "description": "matching invocation",
        }
    ]
    history_calls = 0

    def command(argv):
        nonlocal history_calls
        if "history" in argv:
            history_calls += 1
            return json.dumps(history)
        return json.dumps(status)

    monkeypatch.setattr(verifier, "command", command)
    args = Namespace(
        kubeconfig="k", release="dspace", namespace="dspace", expected_helm_revision=26
    )
    assert verifier.helm_identity(args, "3.0.2") == ("dspace", "3.0.2", 26)
    assert history_calls == 1


@pytest.mark.parametrize(
    "status,history",
    [
        ({"version": 26}, []),
        ({"version": 26}, [{"revision": 25, "chart": "dspace-3.0.2"}]),
        (
            {"version": 26},
            [
                {"revision": 26, "chart": "dspace-3.0.2"},
                {"revision": 26, "chart": "dspace-3.0.2"},
            ],
        ),
        ({"version": 26}, [{"revision": 26, "chart": "dspace-3.0.1"}]),
        ({"version": True}, [{"revision": 1, "chart": "dspace-3.0.2"}]),
        ({"version": 26}, {"revision": 26, "chart": "dspace-3.0.2"}),
        ({"version": 26}, [{"revision": "26", "chart": "SENTINEL_SECRET"}]),
        ({"version": 26, "chart": "invalid"}, [{"revision": 26, "chart": "dspace-3.0.2"}]),
    ],
)
def test_helm_identity_history_fallback_fails_closed_and_redacted(
    monkeypatch: pytest.MonkeyPatch, status: object, history: object
) -> None:
    monkeypatch.setattr(
        verifier,
        "command",
        lambda argv: json.dumps(history if "history" in argv else status),
    )
    args = Namespace(
        kubeconfig="k", release="dspace", namespace="dspace", expected_helm_revision=26
    )
    with pytest.raises(verifier.VerificationError) as raised:
        verifier.helm_identity(args, "3.0.2")
    assert str(raised.value) == "cluster identity"
    assert SENTINEL not in str(raised.value)


def test_helm_identity_history_fallback_preserves_expected_revision_drift(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        verifier,
        "command",
        lambda argv: json.dumps(
            [{"revision": 26, "chart": "dspace-3.0.2"}] if "history" in argv else {"version": 26}
        ),
    )
    args = Namespace(
        kubeconfig="k", release="dspace", namespace="dspace", expected_helm_revision=25
    )
    with pytest.raises(verifier.VerificationError, match="staging drift"):
        verifier.helm_identity(args, "3.0.2")


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
    payload["buildTimestamp"] = BUILD_TIMESTAMP
    with pytest.raises(verifier.VerificationError, match=category):
        verifier.identity(
            json.dumps(payload).encode(),
            "3.1.0",
            SHA,
            "ghcr.io/democratizedspace/dspace:main-abcdef0",
            category,
        )


def modern_build_payload(**changes: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "version": "3.1.0",
        "revision": SHA,
        "shortRevision": SHA[:7],
        "buildTimestamp": BUILD_TIMESTAMP,
    }
    payload.update(changes)
    return payload


@pytest.mark.parametrize(
    "timestamp",
    [BUILD_TIMESTAMP, "2026-08-01T12:00:00.123Z"],
    ids=("seconds", "milliseconds"),
)
def test_modern_identity_accepts_canonical_timestamp(timestamp: str) -> None:
    image = "ghcr.io/democratizedspace/dspace:main-abcdef0"
    assert verifier.identity(
        json.dumps(modern_build_payload(buildTimestamp=timestamp)).encode(),
        "3.1.0",
        SHA,
        image,
        "direct identity",
    ) == ("3.1.0", SHA, timestamp, image)


@pytest.mark.parametrize(
    "timestamp",
    [
        "",
        1,
        "2" * 41,
        "2026-08-01T12:00:00Z\n",
        "2026-02-30T12:00:00Z",
        "2026-08-01T12:00:00",
        "2026-08-01T12:00:00+00:00",
        "2026-08-01T12:00:00.1Z",
        "2026-08-01T12:00:00.1234Z",
        "2026-08-01t12:00:00Z",
        "2026-08-01T24:00:00Z",
        "2026-08-01T24:00:00.000Z",
    ],
    ids=(
        "empty",
        "nonstring",
        "oversized",
        "control-character",
        "malformed-calendar",
        "timezone-naive",
        "utc-offset",
        "one-fractional-digit",
        "four-fractional-digits",
        "parseable-noncanonical",
        "next-day-seconds",
        "next-day-milliseconds",
    ),
)
def test_modern_identity_rejects_invalid_timestamp_without_leaking(timestamp: object) -> None:
    with pytest.raises(verifier.VerificationError) as raised:
        verifier.identity(
            json.dumps(modern_build_payload(buildTimestamp=timestamp)).encode(),
            "3.1.0",
            SHA,
            "ghcr.io/democratizedspace/dspace:main-abcdef0",
            "direct identity",
        )
    assert str(raised.value) == "direct identity"


def test_modern_identity_requires_timestamp_and_rejects_extra_field() -> None:
    missing = modern_build_payload()
    del missing["buildTimestamp"]
    for payload in (missing, modern_build_payload(unexpected=SENTINEL)):
        with pytest.raises(verifier.VerificationError) as raised:
            verifier.identity(
                json.dumps(payload).encode(),
                "3.1.0",
                SHA,
                "ghcr.io/democratizedspace/dspace:main-abcdef0",
                "public identity",
            )
        assert str(raised.value) == "public identity"
        assert SENTINEL not in str(raised.value)


def test_modern_identity_optional_image_behavior_is_unchanged() -> None:
    image = "ghcr.io/democratizedspace/dspace:main-abcdef0"
    with_image = modern_build_payload(image=image)
    without_image = modern_build_payload()
    for payload in (with_image, without_image):
        assert verifier.identity(
            json.dumps(payload).encode(), "3.1.0", SHA, image, "direct identity"
        ) == ("3.1.0", SHA, BUILD_TIMESTAMP, image)


def test_modern_identity_rejects_null_image_without_leaking() -> None:
    payload = modern_build_payload(image=None)
    with pytest.raises(verifier.VerificationError) as raised:
        verifier.identity(
            json.dumps(payload).encode(),
            "3.1.0",
            SHA,
            "ghcr.io/democratizedspace/dspace:main-abcdef0",
            "direct identity",
        )
    assert str(raised.value) == "direct identity"


def test_modern_identity_rejects_mismatched_image_without_leaking(
    capsys: pytest.CaptureFixture[str],
) -> None:
    payload = modern_build_payload(image=SENTINEL)
    with pytest.raises(verifier.VerificationError) as raised:
        verifier.identity(
            json.dumps(payload).encode(),
            "3.1.0",
            SHA,
            "ghcr.io/democratizedspace/dspace:main-abcdef0",
            "direct identity",
        )
    assert str(raised.value) == "direct identity"
    captured = capsys.readouterr()
    assert SENTINEL not in str(raised.value) + captured.out + captured.err


def test_modern_identity_accepts_exact_dspace_311_payload() -> None:
    revision = "22f506e07e0b5abfd0cf756e9c5827c0458fb4b2"
    image = "ghcr.io/democratizedspace/dspace:main-22f506e"
    timestamp = "2026-08-15T19:38:47.123Z"
    payload = modern_build_payload(
        version="3.1.1",
        revision=revision,
        shortRevision=revision[:7],
        image=image,
        buildTimestamp=timestamp,
    )
    assert verifier.identity(
        json.dumps(payload).encode(), "3.1.1", revision, image, "direct identity"
    ) == ("3.1.1", revision, timestamp, image)


@pytest.mark.parametrize(
    "overrides,category",
    [
        (
            {
                "direct_builds": {
                    "dspace-2": json.dumps(
                        modern_build_payload(buildTimestamp="2026-08-02T12:00:00Z")
                    )
                }
            },
            "pod/replica identity",
        ),
        (
            {
                "public_build": json.dumps(
                    modern_build_payload(buildTimestamp="2026-08-02T12:00:00Z")
                )
            },
            "public identity",
        ),
    ],
    ids=("replica-timestamp", "public-timestamp"),
)
def test_verify_rejects_modern_timestamp_disagreement(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    overrides: dict[str, object],
    category: str,
) -> None:
    differing_timestamp = "2026-08-02T12:00:00Z"
    args, _ = _verify_setup(monkeypatch, tmp_path, overrides=overrides)
    with pytest.raises(verifier.VerificationError) as raised:
        verifier.verify(args)
    assert str(raised.value) == category
    captured = capsys.readouterr()
    assert differing_timestamp not in str(raised.value) + captured.out + captured.err


def test_command_success_and_nonzero_failure_are_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        verifier.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 0, "safe output", ""),
    )
    assert verifier.command(["kubectl", "get", "pods"]) == "safe output"

    monkeypatch.setattr(
        verifier.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args[0], 1, SENTINEL.encode(), SENTINEL.encode()
        ),
    )
    with pytest.raises(verifier.VerificationError) as raised:
        verifier.command(["kubectl", SENTINEL])
    assert str(raised.value) == "cluster identity"
    assert SENTINEL not in str(raised.value)


class _Response:
    def __enter__(self) -> "_Response":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self, limit: int) -> bytes:
        assert limit == 1024 * 1024 + 1
        return b"bounded"


@pytest.mark.parametrize(
    ("origin", "category"),
    [(None, "direct identity"), (("https", "dspace.example"), "public identity")],
)
@pytest.mark.parametrize("path", ["/build-meta.json", "/"], ids=("identity", "root"))
def test_fetch_success_and_network_failures_are_bounded(
    monkeypatch: pytest.MonkeyPatch,
    origin: tuple[str, str] | None,
    category: str,
    path: str,
) -> None:
    url = f"https://dspace.example{path}"

    class Opener:
        def open(self, request: verifier.urllib.request.Request, timeout: int) -> _Response:
            assert timeout == 15
            assert request.full_url == url
            assert dict(request.header_items()) == {
                "User-agent": verifier.PUBLIC_HTTP_USER_AGENT,
            }
            return _Response()

    monkeypatch.setattr(verifier.urllib.request, "build_opener", lambda *args: Opener())
    assert verifier.fetch(url, origin) == b"bounded"

    class BrokenOpener:
        def open(self, request: verifier.urllib.request.Request, timeout: int) -> _Response:
            assert request.get_header("User-agent") == verifier.PUBLIC_HTTP_USER_AGENT
            raise verifier.urllib.error.URLError(SENTINEL)

    monkeypatch.setattr(verifier.urllib.request, "build_opener", lambda *args: BrokenOpener())
    with pytest.raises(verifier.VerificationError) as raised:
        verifier.fetch(url, origin)
    assert str(raised.value) == category
    assert SENTINEL not in str(raised.value)


@pytest.mark.parametrize(
    ("call", "category"),
    [
        (
            lambda: verifier.identity(b"x" * (1024 * 1024 + 1), "v", SHA, "image", "identity"),
            "identity",
        ),
        (
            lambda: verifier.identity(
                json.dumps(
                    {"version": "v", "revision": SHA, "shortRevision": SHA[:7], "extra": SENTINEL}
                ).encode(),
                "v",
                SHA,
                "image",
                "identity",
            ),
            "identity",
        ),
        (lambda: verifier.marker(b"x" * (1024 * 1024 + 1), SHA, "frontend"), "frontend"),
        (lambda: verifier.marker(b"\xff", SHA, "frontend"), "frontend"),
    ],
)
def test_identity_payload_bounds_are_redacted(call: object, category: str) -> None:
    with pytest.raises(verifier.VerificationError) as raised:
        call()  # type: ignore[operator]
    assert str(raised.value) == category
    assert SENTINEL not in str(raised.value)


@pytest.mark.parametrize("contents", ["{", "env: []\n"])
def test_values_expectations_rejects_invalid_or_incomplete_values(
    tmp_path: Path, contents: str
) -> None:
    values = tmp_path / "values.yaml"
    values.write_text(contents)
    with pytest.raises(verifier.VerificationError, match="manifest/evidence mismatch"):
        verifier.values_expectations([values])


def test_load_manifest_and_helm_status_fail_with_bounded_categories(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    invalid = tmp_path / "manifest.json"
    invalid.write_text(SENTINEL)
    with pytest.raises(verifier.VerificationError) as raised:
        verifier.load_manifest(invalid)
    assert str(raised.value) == "manifest/evidence mismatch"
    assert SENTINEL not in str(raised.value)

    monkeypatch.setattr(verifier, "command", lambda argv: SENTINEL)
    args = Namespace(kubeconfig="k", release="dspace", namespace="dspace")
    with pytest.raises(verifier.VerificationError) as raised:
        verifier.helm_identity(args, "3.1.0")
    assert str(raised.value) == "cluster identity"
    assert SENTINEL not in str(raised.value)


def test_resolve_host_accepts_only_a_bounded_hostname(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(verifier, "command", lambda argv: "dspace.example\n")
    assert verifier._resolve_host([]) == "dspace.example"

    monkeypatch.setattr(verifier, "command", lambda argv: f"bad/{SENTINEL}")
    with pytest.raises(verifier.VerificationError) as raised:
        verifier._resolve_host([])
    assert str(raised.value) == "manifest/evidence mismatch"
    assert SENTINEL not in str(raised.value)


@pytest.mark.parametrize(
    ("call", "category"),
    [
        (lambda: verifier.controller_owner(None, "ReplicaSet"), "pod/replica identity"),
        (lambda: verifier.helm_deployment_uid(None, "dspace", "dspace"), "cluster identity"),
    ],
)
def test_kubernetes_metadata_types_fail_closed(call: object, category: str) -> None:
    with pytest.raises(verifier.VerificationError, match=category):
        call()  # type: ignore[operator]


def test_fetch_preserves_bounded_redirect_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    class Opener:
        def open(self, request: verifier.urllib.request.Request, timeout: int) -> _Response:
            assert request.get_header("User-agent") == verifier.PUBLIC_HTTP_USER_AGENT
            raise verifier.VerificationError("public identity")

    monkeypatch.setattr(verifier.urllib.request, "build_opener", lambda *args: Opener())
    with pytest.raises(verifier.VerificationError, match="public identity"):
        verifier.fetch("https://dspace.example/build-info.json", ("https", "dspace.example"))


def test_main_maps_config_errors_to_bounded_failure(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(
        verifier,
        "verify",
        lambda args: (_ for _ in ()).throw(verifier.app_config.AppConfigError(SENTINEL)),
    )
    result = verifier.main(
        [
            "verify",
            "--environment",
            "staging",
            "--release",
            "dspace",
            "--namespace",
            "dspace",
            "--manifest",
            "manifest.json",
            "--kubeconfig",
            "kubeconfig",
        ]
    )
    assert result == 2
    captured = capsys.readouterr()
    assert "manifest/evidence mismatch" in captured.err
    assert SENTINEL not in captured.out + captured.err
