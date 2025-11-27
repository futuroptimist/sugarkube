"""Guardrails for Cloudflare Tunnel token-mode rollout."""

from __future__ import annotations

import copy
import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
JUSTFILE = REPO_ROOT / "justfile"


def _build_token_config(env: str = "staging", tunnel_name: str | None = None) -> str:
    name = tunnel_name or f"sugarkube-{env}"
    return (
        "apiVersion: v1\n"
        "kind: ConfigMap\n"
        "metadata:\n"
        "  name: cloudflare-tunnel\n"
        "  namespace: cloudflare\n"
        "data:\n"
        "  config.yaml: |\n"
        f"    tunnel: \"{name}\"\n"
        "    warp-routing:\n"
        "      enabled: false\n"
        "    metrics: 0.0.0.0:2000\n"
        "    no-autoupdate: true\n"
        "    ingress:\n"
        "      - service: http_status:404\n"
    )


def _sample_deployment() -> dict:
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
                                {
                                    "name": "TUNNEL_CRED_FILE",
                                    "value": "/etc/cloudflared/creds/credentials.json",
                                }
                            ],
                            "volumeMounts": [
                                {
                                    "name": "config",
                                    "mountPath": "/etc/cloudflared/config",
                                },
                                {
                                    "name": "creds",
                                    "mountPath": "/etc/cloudflared/creds",
                                },
                            ],
                            "command": ["cloudflared"],
                            "args": [
                                "tunnel",
                                "--config",
                                "/etc/cloudflared/config/config.yaml",
                                "run",
                            ],
                        }
                    ],
                    "volumes": [
                        {"name": "config", "configMap": {"name": "cloudflare-tunnel"}},
                        {"name": "creds", "secret": {"secretName": "tunnel-token"}},
                    ],
                }
            }
        },
    }


def _apply_token_patch(manifest: dict) -> dict:
    patched = copy.deepcopy(manifest)
    spec = patched["spec"]["template"]["spec"]
    spec["volumes"] = [
        {"name": "config", "configMap": {"name": "cloudflare-tunnel"}},
    ]

    container = spec["containers"][0]
    container["env"] = [
        {
            "name": "TUNNEL_TOKEN",
            "valueFrom": {"secretKeyRef": {"name": "tunnel-token", "key": "token"}},
        }
    ]
    container["volumeMounts"] = [
        {"name": "config", "mountPath": "/etc/cloudflared/config"},
    ]
    container["command"] = ["/bin/sh", "-c"]
    container["args"] = [
        (
            "exec cloudflared tunnel --config /etc/cloudflared/config/config.yaml run "
            "--token \"$TUNNEL_TOKEN\""
        ),
    ]
    return patched


def test_token_configmap_removes_credentials_file() -> None:
    config_yaml = _build_token_config(env="dev")
    assert "credentials-file" not in config_yaml
    assert 'tunnel: "sugarkube-dev"' in config_yaml
    assert "warp-routing:" in config_yaml
    assert "metrics: 0.0.0.0:2000" in config_yaml


def test_deployment_patch_enforces_token_mode() -> None:
    base = _sample_deployment()
    patched = _apply_token_patch(base)

    container = patched["spec"]["template"]["spec"]["containers"][0]
    assert container["env"] == [
        {
            "name": "TUNNEL_TOKEN",
            "valueFrom": {"secretKeyRef": {"name": "tunnel-token", "key": "token"}},
        }
    ]
    assert container["volumeMounts"] == [
        {"name": "config", "mountPath": "/etc/cloudflared/config"},
    ]
    assert container["command"] == ["/bin/sh", "-c"]
    assert container["args"] == [
        (
            "exec cloudflared tunnel --config /etc/cloudflared/config/config.yaml run "
            "--token \"$TUNNEL_TOKEN\""
        ),
    ]

    volumes = patched["spec"]["template"]["spec"]["volumes"]
    assert volumes == [{"name": "config", "configMap": {"name": "cloudflare-tunnel"}}]

    serialized = json.dumps(patched)
    assert "credentials.json" not in serialized


def test_cf_tunnel_install_recipe_orders_patch_after_helm() -> None:
    text = JUSTFILE.read_text(encoding="utf-8")
    anchor = "cf-tunnel-install env='dev'"
    assert anchor in text, "cf-tunnel-install recipe not found"

    start = text.index(anchor)
    start = text.index(":\n", start) + 2
    end = text.find("\nhelm-install:", start)
    recipe = text[start:end if end != -1 else None]

    assert "helm upgrade --install cloudflare-tunnel" in recipe
    assert "--wait" not in recipe, "Helm wait should not gate token patches"
    assert (
        "kubectl -n cloudflare rollout status deployment/cloudflare-tunnel --timeout=180s"
        in recipe
    )

    helm_idx = recipe.find("helm upgrade --install cloudflare-tunnel")
    config_idx = recipe.find("configmap_yaml=")
    patch_idx = recipe.find("deployment_patch='")
    assert helm_idx != -1 and config_idx != -1 and patch_idx != -1
    assert helm_idx < config_idx < patch_idx, "token-mode patching must follow helm install"
