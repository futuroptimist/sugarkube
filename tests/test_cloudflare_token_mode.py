from __future__ import annotations

import copy
from typing import Any, Dict

from scripts.force_cloudflare_token_mode import (
    CONFIG_FILE_NAME,
    CONFIG_MOUNT_PATH,
    CONFIG_VOLUME_NAME,
    RUN_COMMAND,
    TOKEN_ENV_NAME,
    build_configmap,
    patch_deployment,
)


def _deployment_fixture() -> Dict[str, Any]:
    return {
        "apiVersion": "apps/v1",
        "kind": "Deployment",
        "metadata": {"name": "cloudflare-tunnel", "namespace": "cloudflare"},
        "spec": {
            "template": {
                "spec": {
                    "containers": [
                        {
                            "name": "cloudflare-tunnel",
                            "env": [
                                {"name": "TUNNEL_CRED_FILE", "value": "/etc/cloudflared/creds/credentials.json"}
                            ],
                            "volumeMounts": [
                                {"name": "creds", "mountPath": "/etc/cloudflared/creds"},
                                {"name": "config", "mountPath": "/etc/cloudflared/config"},
                            ],
                        }
                    ],
                    "volumes": [
                        {"name": "creds", "secret": {"secretName": "tunnel-credentials"}},
                        {"name": "config", "configMap": {"name": "cloudflare-tunnel"}},
                    ],
                }
            }
        },
    }


def test_configmap_removes_credentials_file() -> None:
    configmap = build_configmap("example-tunnel")
    config_yaml = configmap["data"][CONFIG_FILE_NAME]
    assert "credentials-file" not in config_yaml
    assert "tunnel: \"example-tunnel\"" in config_yaml
    assert "metrics: 0.0.0.0:2000" in config_yaml


def test_patch_deployment_enforces_token_mode() -> None:
    deployment = _deployment_fixture()
    patched = patch_deployment(copy.deepcopy(deployment))

    pod_spec = patched["spec"]["template"]["spec"]
    container = pod_spec["containers"][0]

    env_names = [env["name"] for env in container["env"]]
    assert env_names[0] == TOKEN_ENV_NAME
    assert any(env.get("name") == "TUNNEL_CRED_FILE" for env in container["env"]) is False

    assert container["command"] == ["/bin/sh", "-c"]
    assert container["args"] == [RUN_COMMAND]

    mount_names = [vm["name"] for vm in container["volumeMounts"]]
    assert mount_names[0] == CONFIG_VOLUME_NAME
    assert all("cred" not in name for name in mount_names)
    assert any(vm["mountPath"] == CONFIG_MOUNT_PATH for vm in container["volumeMounts"])

    volume_names = [vol["name"] for vol in pod_spec["volumes"]]
    assert volume_names[0] == CONFIG_VOLUME_NAME
    assert all("cred" not in name for name in volume_names)
    assert pod_spec["volumes"][0]["configMap"]["name"] == "cloudflare-tunnel"
