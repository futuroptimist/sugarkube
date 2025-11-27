#!/usr/bin/env python3
"""Helpers to enforce token-mode Cloudflare Tunnel deployments."""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Dict, List

CONFIG_VOLUME_NAME = "cloudflare-tunnel-config"
CONFIG_MOUNT_PATH = "/etc/cloudflared/config"
CONFIG_FILE_NAME = "config.yaml"
TOKEN_ENV_NAME = "TUNNEL_TOKEN"
RUN_COMMAND = (
    "exec cloudflared tunnel --config /etc/cloudflared/config/config.yaml run --token \"$"
    "TUNNEL_TOKEN\""
)


def build_configmap(tunnel_name: str, namespace: str = "cloudflare") -> Dict[str, Any]:
    """Return a ConfigMap dict for token-mode cloudflared."""

    config_yaml = (
        f"tunnel: \"{tunnel_name}\"\n"
        "warp-routing:\n"
        "  enabled: false\n"
        "metrics: 0.0.0.0:2000\n"
        "no-autoupdate: true\n"
        "ingress:\n"
        "  - service: http_status:404\n"
    )

    return {
        "apiVersion": "v1",
        "kind": "ConfigMap",
        "metadata": {"name": "cloudflare-tunnel", "namespace": namespace},
        "data": {CONFIG_FILE_NAME: config_yaml},
    }


def _select_container(containers: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Choose the cloudflare-tunnel container (or fallback to the first)."""

    for container in containers:
        if container.get("name") == "cloudflare-tunnel":
            return container
    return containers[0]


def _filter_non_credential_entries(entries: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Remove map entries where the name hints at credentials usage."""

    filtered: List[Dict[str, Any]] = []
    for entry in entries:
        name = entry.get("name", "")
        if "cred" in name.lower():
            continue
        filtered.append(entry)
    return filtered


def patch_deployment(deployment: Dict[str, Any]) -> Dict[str, Any]:
    """Rewrite a deployment manifest to enforce token-mode cloudflared."""

    template = deployment.setdefault("spec", {}).setdefault("template", {})
    pod_spec = template.setdefault("spec", {})
    containers = pod_spec.setdefault("containers", [])
    if not containers:
        raise ValueError("Deployment must contain at least one container")

    container = _select_container(containers)

    existing_env = [
        env
        for env in container.get("env", [])
        if env.get("name") != TOKEN_ENV_NAME and "cred" not in env.get("name", "").lower()
    ]
    token_env = {
        "name": TOKEN_ENV_NAME,
        "valueFrom": {"secretKeyRef": {"name": "tunnel-token", "key": "token"}},
    }
    container["env"] = [token_env, *existing_env]

    container["command"] = ["/bin/sh", "-c"]
    container["args"] = [RUN_COMMAND]

    volume_mounts = _filter_non_credential_entries(container.get("volumeMounts", []))
    volume_mounts = [vm for vm in volume_mounts if vm.get("name") != CONFIG_VOLUME_NAME]
    volume_mounts.insert(
        0,
        {
            "name": CONFIG_VOLUME_NAME,
            "mountPath": CONFIG_MOUNT_PATH,
            "readOnly": True,
        },
    )
    container["volumeMounts"] = volume_mounts

    volumes = _filter_non_credential_entries(pod_spec.get("volumes", []))
    volumes = [vol for vol in volumes if vol.get("name") != CONFIG_VOLUME_NAME]
    volumes.insert(
        0,
        {
            "name": CONFIG_VOLUME_NAME,
            "configMap": {
                "name": "cloudflare-tunnel",
                "items": [{"key": CONFIG_FILE_NAME, "path": CONFIG_FILE_NAME}],
            },
        },
    )
    pod_spec["volumes"] = volumes

    return deployment


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Force token-mode cloudflared manifests")
    subparsers = parser.add_subparsers(dest="command", required=True)

    cm_parser = subparsers.add_parser("configmap", help="emit a ConfigMap JSON")
    cm_parser.add_argument("--tunnel-name", required=True, help="Cloudflare tunnel name")
    cm_parser.add_argument(
        "--namespace",
        default="cloudflare",
        help="Namespace for the ConfigMap (default: cloudflare)",
    )

    patch_parser = subparsers.add_parser(
        "patch-deployment", help="patch deployment JSON from stdin"
    )
    patch_parser.add_argument(
        "--stdin",
        action="store_true",
        help="Read the deployment JSON from stdin (default behavior)",
    )

    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv or sys.argv[1:])

    if args.command == "configmap":
        cm = build_configmap(args.tunnel_name, args.namespace)
        json.dump(cm, sys.stdout)
        return 0

    if args.command == "patch-deployment":
        deployment = json.load(sys.stdin)
        patched = patch_deployment(deployment)
        json.dump(patched, sys.stdout)
        return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
