"""Hermetic contract tests for the DSPACE runtime verifier."""

from __future__ import annotations

import json
import subprocess
import urllib.error
from argparse import Namespace
from pathlib import Path
from typing import Callable

import pytest

from scripts import dspace_runtime_verifier as verifier

SHA = "abcdef0123456789abcdef0123456789abcdef01"
DIGEST = "sha256:" + "1" * 64


def helm_metadata(uid: str) -> dict:
    return {
        "uid": uid,
        "labels": {
            "app.kubernetes.io/name": "dspace",
            "app.kubernetes.io/instance": "dspace",
            "app.kubernetes.io/managed-by": "Helm",
        },
        "annotations": {
            "meta.helm.sh/release-name": "dspace",
            "meta.helm.sh/release-namespace": "dspace",
        },
    }


def workload_metadata(uid: str) -> dict:
    return {
        "uid": uid,
        "labels": {
            "app.kubernetes.io/name": "dspace",
            "app.kubernetes.io/instance": "dspace",
        },
    }


def runtime_fixture(
    tmp_path: Path,
) -> tuple[Namespace, dict, list[list[str]], Callable[[list[str]], str]]:
    smoke = tmp_path / "smoke"
    smoke.write_text("#!/bin/sh\n", encoding="utf-8")
    smoke.chmod(0o755)
    metadata = helm_metadata("deployment-uid")
    metadata.update({"name": "dspace", "generation": 4})
    deployment = {
        "metadata": metadata,
        "spec": {
            "replicas": 1,
            "template": {
                "spec": {
                    "containers": [
                        {
                            "name": "dspace",
                            "image": f"{verifier.IMAGE_REF}:main-abcdef0",
                            "ports": [{"name": "http", "containerPort": 8080, "protocol": "TCP"}],
                            "env": [],
                        }
                    ]
                }
            },
        },
        "status": {
            "observedGeneration": 4,
            "updatedReplicas": 1,
            "readyReplicas": 1,
            "availableReplicas": 1,
            "unavailableReplicas": 0,
        },
    }
    rs_metadata = workload_metadata("rs-uid")
    rs_metadata.update(
        {
            "name": "dspace-rs",
            "ownerReferences": [
                {
                    "kind": "Deployment",
                    "name": "dspace",
                    "uid": "deployment-uid",
                    "controller": True,
                }
            ],
        }
    )
    pod_metadata = workload_metadata("pod-uid")
    pod_metadata.update(
        {
            "name": "dspace-0",
            "ownerReferences": [
                {
                    "kind": "ReplicaSet",
                    "name": "dspace-rs",
                    "uid": "rs-uid",
                    "controller": True,
                }
            ],
        }
    )
    pod = {
        "metadata": pod_metadata,
        "spec": {"containers": [{"name": "dspace", "image": f"{verifier.IMAGE_REF}:main-abcdef0"}]},
        "status": {
            "phase": "Running",
            "conditions": [{"type": "Ready", "status": "True"}],
            "containerStatuses": [{"name": "dspace", "imageID": "repo@" + DIGEST}],
        },
    }
    state = {
        "deployment": deployment,
        "replicasets": [{"kind": "ReplicaSet", "metadata": rs_metadata}],
        "pods": [pod],
    }
    calls: list[list[str]] = []
    build = json.dumps({"version": "3.2.0", "revision": SHA, "shortRevision": SHA[:7]})

    def runner(command: list[str]) -> str:
        calls.append(command)
        if command[0] == "helm":
            return json.dumps(
                {
                    "name": "dspace",
                    "namespace": "dspace",
                    "version": 7,
                    "info": {"status": "deployed"},
                    "chart": {"metadata": {"name": "dspace", "version": "3.2.0"}},
                }
            )
        if "deployment" in command:
            return json.dumps(state["deployment"])
        if "pods" in command:
            return json.dumps({"items": state["pods"]})
        if "replicasets" in command:
            return json.dumps({"items": state["replicasets"]})
        return (
            build
            if command[-1].endswith("build-info.json")
            else f'<meta name="dspace-build-revision" content="{SHA}">'
        )

    args = Namespace(
        environment="staging",
        release="dspace",
        namespace="dspace",
        application_version="3.2.0",
        source_revision=SHA,
        provider="openai",
        image_tag="main-abcdef0",
        image_digest=DIGEST,
        host="example.test",
        chart_version="3.2.0",
        helm_revision=7,
        values=[],
        smoke_runner=smoke,
        kubeconfig="fixture",
    )
    return args, state, calls, runner


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
    assert value == {
        "schemaVersion": 1,
        "environment": "staging",
        "release": "dspace",
        "namespace": "dspace",
        "capabilities": [
            "applicationVersion",
            "runtimeSourceRevision",
            "frontendSourceRevision",
            "defaultProvider",
            "publicJourneys",
        ],
    }


def test_values_chain_uses_last_reviewed_token_place_values(tmp_path: Path) -> None:
    base = tmp_path / "base.yaml"
    overlay = tmp_path / "overlay.yaml"
    base.write_text(
        "env:\n  - name: DSPACE_TOKEN_PLACE_URL\n    value: https://old.invalid\n", encoding="utf-8"
    )
    overlay.write_text(
        "env:\n  - name: DSPACE_TOKEN_PLACE_URL\n    value: https://staging.token.place\n"
        "  - name: DSPACE_TOKEN_PLACE_CHAT_MODEL\n    value: reviewed-model\n"
        "  - name: UNRELATED_SETTING\n    value: ignored-value\n",
        encoding="utf-8",
    )
    assert verifier.environment_values([base, overlay]) == {
        "DSPACE_TOKEN_PLACE_URL": "https://staging.token.place",
        "DSPACE_TOKEN_PLACE_CHAT_MODEL": "reviewed-model",
    }


@pytest.mark.parametrize("provider", ["token-place", "openai"])
def test_smoke_is_exact_argv_and_child_output_is_suppressed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, provider: str
) -> None:
    smoke = tmp_path / "smoke"
    smoke.write_text("#!/bin/sh\n", encoding="utf-8")
    smoke.chmod(0o755)
    values = tmp_path / "values.yaml"
    values.write_text(
        "env:\n  - name: DSPACE_TOKEN_PLACE_URL\n    value: https://token.place\n"
        "  - name: DSPACE_TOKEN_PLACE_CHAT_MODEL\n    value: model-from-values\n",
        encoding="utf-8",
    )
    calls: list[list[str]] = []
    runner_calls: list[list[str]] = []

    class Completed:
        returncode = 0
        stdout = "SENTINEL_SECRET"
        stderr = "SENTINEL_SECRET"

    monkeypatch.setattr(
        verifier.subprocess, "run", lambda command, **_kwargs: calls.append(command) or Completed()
    )
    build = json.dumps({"version": "3.2.0", "revision": SHA, "shortRevision": SHA[:7]}).encode()
    html = f'<meta name="dspace-build-revision" content="{SHA}">'.encode()
    pod = {
        "metadata": {
            **workload_metadata("pod-uid"),
            "name": "dspace-0",
            "ownerReferences": [
                {
                    "kind": "ReplicaSet",
                    "name": "dspace-rs",
                    "uid": "rs-uid",
                    "controller": True,
                }
            ],
        },
        "spec": {
            "containers": [
                {"name": "dspace", "image": "ghcr.io/democratizedspace/dspace:main-abcdef0"}
            ]
        },
        "status": {
            "phase": "Running",
            "conditions": [{"type": "Ready", "status": "True"}],
            "containerStatuses": [{"name": "dspace", "imageID": "repo@" + DIGEST}],
        },
    }

    def runner(command: list[str]) -> str:
        runner_calls.append(command)
        if command[0] == "helm":
            return json.dumps(
                {
                    "name": "dspace",
                    "namespace": "dspace",
                    "version": 7,
                    "info": {"status": "deployed"},
                    "chart": {"metadata": {"name": "dspace", "version": "3.2.0"}},
                }
            )
        if "pods" in command:
            return json.dumps({"items": [pod]})
        if "replicasets" in command:
            return json.dumps(
                {
                    "items": [
                        {
                            "kind": "ReplicaSet",
                            "metadata": {
                                **workload_metadata("rs-uid"),
                                "name": "dspace-rs",
                                "ownerReferences": [
                                    {
                                        "kind": "Deployment",
                                        "name": "dspace",
                                        "uid": "deployment-uid",
                                        "controller": True,
                                    }
                                ],
                            },
                        },
                    ]
                }
            )
        if "deployment" in command:
            return json.dumps(
                {
                    "metadata": {
                        **helm_metadata("deployment-uid"),
                        "name": "dspace",
                        "generation": 4,
                    },
                    "spec": {
                        "replicas": 1,
                        "template": {
                            "spec": {
                                "containers": [
                                    {
                                        "name": "dspace",
                                        "image": "ghcr.io/democratizedspace/dspace:main-abcdef0",
                                        "ports": [{"name": "http", "containerPort": 8080}],
                                        "env": [
                                            {
                                                "name": "DSPACE_TOKEN_PLACE_URL",
                                                "value": "https://token.place",
                                            },
                                            {
                                                "name": "DSPACE_TOKEN_PLACE_CHAT_MODEL",
                                                "value": "model-from-values",
                                            },
                                        ],
                                    }
                                ]
                            }
                        },
                    },
                    "status": {
                        "observedGeneration": 4,
                        "updatedReplicas": 1,
                        "readyReplicas": 1,
                        "availableReplicas": 1,
                        "unavailableReplicas": 0,
                    },
                }
            )
        return (
            json.dumps(json.loads(build))
            if command[-1].endswith("build-info.json")
            else html.decode()
        )

    args = Namespace(
        environment="staging",
        release="dspace",
        namespace="dspace",
        application_version="3.2.0",
        source_revision=SHA,
        provider=provider,
        image_tag="main-abcdef0",
        image_digest=DIGEST,
        host="example.test",
        chart_version="3.2.0",
        helm_revision=7,
        values=[values],
        smoke_runner=smoke,
        kubeconfig="fixture",
    )
    result = verifier.verify(
        args, runner, lambda url, _origin: build if url.endswith(".json") else html
    )
    assert result["journeys"][-1] == {"name": "/chat", "passed": True}
    smoke_call = calls[-1]
    assert smoke_call[0] == str(smoke)
    proxy_calls = [call for call in runner_calls if "--raw" in call]
    assert len(proxy_calls) == 2
    assert all("--request-timeout=15s" in call for call in proxy_calls)
    assert all(":8080/proxy" in call[-1] for call in proxy_calls)
    assert all(":3000/proxy" not in call[-1] for call in proxy_calls)
    if provider == "token-place":
        assert smoke_call[-4:] == [
            "--expected-token-place-origin",
            "https://token.place",
            "--expected-token-place-model",
            "model-from-values",
        ]
    else:
        assert not any("token-place" in item for item in smoke_call)
    assert "SENTINEL_SECRET" not in json.dumps(result)


def test_identity_and_frontend_mismatches_are_bounded() -> None:
    with pytest.raises(verifier.VerificationError, match="version or revision mismatch"):
        verifier.identity(
            b'{"version":"wrong","revision":"x","shortRevision":"x"}',
            "3.2.0",
            SHA,
            "main-abcdef0",
            "public identity",
        )
    with pytest.raises(verifier.VerificationError, match="frontend revision marker mismatch"):
        verifier.marker(b"secret response without marker", SHA, "direct identity")


@pytest.mark.parametrize(
    "ports",
    [
        [],
        [{"name": "other", "containerPort": 8080}],
        [{"name": "http", "containerPort": "8080"}],
        [{"name": "http", "containerPort": 8080, "protocol": "UDP"}],
        [
            {"name": "http", "containerPort": 8080},
            {"name": "http", "containerPort": 8081},
        ],
    ],
)
def test_live_http_port_shapes_fail_closed(tmp_path: Path, monkeypatch, ports) -> None:
    args, state, _calls, runner = runtime_fixture(tmp_path)
    state["deployment"]["spec"]["template"]["spec"]["containers"][0]["ports"] = ports
    monkeypatch.setattr(
        verifier.subprocess, "run", lambda *_args, **_kwargs: pytest.fail("smoke executed")
    )
    with pytest.raises(verifier.VerificationError, match="invalid named http port"):
        verifier.verify(args, runner, lambda url, _origin: _public_body(url))


@pytest.mark.parametrize(
    ("path", "value", "message"),
    [
        (("spec", "replicas"), 0, "rollout"),
        (("status", "observedGeneration"), 3, "rollout"),
        (("status", "updatedReplicas"), 0, "rollout"),
        (("status", "readyReplicas"), 0, "rollout"),
        (("status", "availableReplicas"), 0, "rollout"),
        (("status", "unavailableReplicas"), 1, "rollout"),
        (
            ("spec", "template", "spec", "containers", 0, "image"),
            f"{verifier.IMAGE_REF}:wrong",
            "image identity",
        ),
    ],
)
def test_deployment_drift_and_incomplete_rollout_fail_closed(
    tmp_path: Path, path, value, message
) -> None:
    args, state, _calls, runner = runtime_fixture(tmp_path)
    target = state["deployment"]
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    with pytest.raises(verifier.VerificationError, match=message):
        verifier.verify(args, runner, lambda url, _origin: _public_body(url))


@pytest.mark.parametrize("owner_level", ["deployment", "replicaset", "pod"])
def test_forged_owner_uids_fail_closed(tmp_path: Path, owner_level: str) -> None:
    args, state, _calls, runner = runtime_fixture(tmp_path)
    if owner_level == "deployment":
        state["deployment"]["metadata"]["annotations"]["meta.helm.sh/release-name"] = "forged"
    elif owner_level == "replicaset":
        state["replicasets"][0]["metadata"]["ownerReferences"][0]["uid"] = "forged"
    else:
        state["pods"][0]["metadata"]["ownerReferences"][0]["uid"] = "forged"
    with pytest.raises(verifier.VerificationError, match="unowned|not owned"):
        verifier.verify(args, runner, lambda url, _origin: _public_body(url))


@pytest.mark.parametrize("workload", ["replicaset", "pod"])
def test_workload_selector_labels_fail_closed(tmp_path: Path, workload: str) -> None:
    args, state, _calls, runner = runtime_fixture(tmp_path)
    key = "replicasets" if workload == "replicaset" else "pods"
    state[key][0]["metadata"]["labels"]["app.kubernetes.io/instance"] = "forged"
    with pytest.raises(verifier.VerificationError, match="not owned"):
        verifier.verify(args, runner, lambda url, _origin: _public_body(url))


@pytest.mark.parametrize("workload", ["replicaset", "pod"])
@pytest.mark.parametrize("owner_shape", [[], "malformed", None])
def test_missing_or_malformed_controller_reference_is_bounded(
    tmp_path: Path, workload: str, owner_shape
) -> None:
    args, state, _calls, runner = runtime_fixture(tmp_path)
    key = "replicasets" if workload == "replicaset" else "pods"
    state[key][0]["metadata"]["ownerReferences"] = owner_shape
    with pytest.raises(verifier.VerificationError, match="not owned"):
        verifier.verify(args, runner, lambda url, _origin: _public_body(url))


@pytest.mark.parametrize("workload", ["replicaset", "pod"])
def test_duplicate_controller_reference_fails_closed(tmp_path: Path, workload: str) -> None:
    args, state, _calls, runner = runtime_fixture(tmp_path)
    key = "replicasets" if workload == "replicaset" else "pods"
    references = state[key][0]["metadata"]["ownerReferences"]
    references.append(dict(references[0]))
    with pytest.raises(verifier.VerificationError, match="not owned"):
        verifier.verify(args, runner, lambda url, _origin: _public_body(url))


@pytest.mark.parametrize("workload", ["replicaset", "pod"])
def test_wrong_controller_name_fails_closed(tmp_path: Path, workload: str) -> None:
    args, state, _calls, runner = runtime_fixture(tmp_path)
    key = "replicasets" if workload == "replicaset" else "pods"
    state[key][0]["metadata"]["ownerReferences"][0]["name"] = "forged"
    with pytest.raises(verifier.VerificationError, match="not owned"):
        verifier.verify(args, runner, lambda url, _origin: _public_body(url))


def test_pod_owned_by_unknown_replicaset_fails_closed(tmp_path: Path) -> None:
    args, state, _calls, runner = runtime_fixture(tmp_path)
    state["pods"][0]["metadata"]["ownerReferences"][0].update(
        {"name": "unknown", "uid": "unknown-uid"}
    )
    with pytest.raises(verifier.VerificationError, match="not owned"):
        verifier.verify(args, runner, lambda url, _origin: _public_body(url))


def test_missing_observed_replica_fails_closed(tmp_path: Path) -> None:
    args, state, _calls, runner = runtime_fixture(tmp_path)
    state["pods"] = []
    with pytest.raises(verifier.VerificationError, match="replica count"):
        verifier.verify(args, runner, lambda url, _origin: _public_body(url))


def test_direct_proxy_failure_is_bounded_and_classified(tmp_path: Path) -> None:
    args, _state, calls, base_runner = runtime_fixture(tmp_path)

    def runner(command: list[str]) -> str:
        if "--raw" in command:
            raise OSError("SENTINEL_SECRET")
        return base_runner(command)

    with pytest.raises(verifier.VerificationError, match="^direct identity: endpoint") as caught:
        verifier.verify(args, runner, lambda url, _origin: _public_body(url))
    assert "SENTINEL_SECRET" not in str(caught.value)
    assert not any(":3000/proxy" in part for call in calls for part in call)


def _public_body(url: str) -> bytes:
    if url.endswith(".json"):
        return json.dumps({"version": "3.2.0", "revision": SHA, "shortRevision": SHA[:7]}).encode()
    return f'<meta name="dspace-build-revision" content="{SHA}">'.encode()


def test_command_adapters_return_bounded_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        verifier.subprocess,
        "run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess([], 1, "secret", "secret"),
    )
    with pytest.raises(verifier.VerificationError, match="kubectl command failed"):
        verifier.run(["kubectl", "secret"])

    monkeypatch.setattr(
        verifier.subprocess, "run", lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError())
    )
    with pytest.raises(verifier.VerificationError, match="could not execute"):
        verifier.run(["kubectl"])

    with pytest.raises(verifier.VerificationError, match="valid JSON"):
        verifier.json_run(lambda _command: "not-json secret", ["helm"], "cluster identity")


class _Response:
    def __init__(self, url: str, body: bytes = b"ok") -> None:
        self.url, self.body = url, body

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def geturl(self) -> str:
        return self.url

    def read(self, _limit: int) -> bytes:
        return self.body


def test_public_fetch_is_bounded_and_same_origin() -> None:
    assert (
        verifier.fetch(
            "https://dspace.test/build-info.json",
            "https://dspace.test",
            lambda *_args, **_kwargs: _Response("https://dspace.test/final"),
        )
        == b"ok"
    )
    with pytest.raises(verifier.VerificationError, match="crossed"):
        verifier.fetch(
            "https://dspace.test/",
            "https://dspace.test",
            lambda *_a, **_k: _Response("https://evil.test/"),
        )
    with pytest.raises(verifier.VerificationError, match="unreachable"):
        verifier.fetch(
            "https://dspace.test/",
            "https://dspace.test",
            lambda *_a, **_k: (_ for _ in ()).throw(urllib.error.URLError("secret")),
        )


@pytest.mark.parametrize(
    ("raw", "message"),
    [
        (b"x" * 1_048_577, "bounded limit"),
        (b"not-json", "malformed"),
        (b"[]", "malformed"),
        (
            json.dumps({"version": "3.2.0", "revision": SHA, "shortRevision": "wrong"}).encode(),
            "short revision",
        ),
        (
            json.dumps(
                {"version": "3.2.0", "revision": SHA, "shortRevision": SHA[:7], "image": "wrong"}
            ).encode(),
            "image coordinate",
        ),
    ],
)
def test_identity_rejects_each_untrusted_public_shape(raw: bytes, message: str) -> None:
    with pytest.raises(verifier.VerificationError, match=message):
        verifier.identity(raw, "3.2.0", SHA, "main-abcdef0", "public identity")


def test_marker_and_values_failures_are_bounded(tmp_path: Path) -> None:
    with pytest.raises(verifier.VerificationError, match="bounded limit"):
        verifier.marker(b"x" * 1_048_577, SHA, "public identity")
    with pytest.raises(verifier.VerificationError, match="values chain is unreadable"):
        verifier.environment_values([tmp_path / "missing.yaml"])
    with pytest.raises(verifier.VerificationError, match="missing named"):
        verifier.application_container({})


def test_verify_rejects_non_executable_runner_before_cluster_access(tmp_path: Path) -> None:
    args = Namespace(smoke_runner=tmp_path / "missing")
    with pytest.raises(verifier.VerificationError, match="existing executable"):
        verifier.verify(args, lambda _command: pytest.fail("cluster command executed"))


def test_verify_main_reports_bounded_failure(monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    monkeypatch.setattr(
        verifier, "verify", lambda _args: (_ for _ in ()).throw(verifier.VerificationError("safe"))
    )
    argv = [
        "verify",
        "--environment",
        "staging",
        "--release",
        "dspace",
        "--namespace",
        "dspace",
        "--application-version",
        "3.2.0",
        "--source-revision",
        SHA,
        "--provider",
        "openai",
        "--image-tag",
        "main-abcdef0",
        "--image-digest",
        DIGEST,
        "--chart-version",
        "3.2.0",
        "--host",
        "dspace.test",
        "--smoke-runner",
        str(Path("runner")),
        "--kubeconfig",
        "fixture",
    ]
    assert verifier.main(argv) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "ERROR: safe\n"
