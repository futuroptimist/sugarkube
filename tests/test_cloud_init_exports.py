"""Ensure cloud-init auto-retries kubeconfig/node token exports."""

from __future__ import annotations

from pathlib import Path

USER_DATA = Path("scripts/cloud-init/user-data.yaml")


def _unit_section(text: str, unit: str) -> str:
    """Return the YAML snippet defining the requested unit."""

    header = f"/etc/systemd/system/{unit}"
    start = text.index(header)
    tail = text[start:]
    try:
        end = tail.index("\n  - path: ")
    except ValueError:
        end = len(tail)
    return tail[:end]


def test_export_watchers_configured() -> None:
    text = USER_DATA.read_text(encoding="utf-8")
    assert "/etc/systemd/system/sugarkube-export-kubeconfig.service" in text
    assert "/etc/systemd/system/sugarkube-export-kubeconfig.path" in text
    assert "/etc/systemd/system/sugarkube-export-node-token.service" in text
    assert "/etc/systemd/system/sugarkube-export-node-token.path" in text

    assert "PathExists=/etc/rancher/k3s/k3s.yaml" in text
    assert "PathExists=/var/lib/rancher/k3s/server/node-token" in text

    assert "systemctl, enable, --now, sugarkube-export-kubeconfig.path" in text
    assert "systemctl, enable, --now, sugarkube-export-node-token.path" in text
    assert "systemctl, start, sugarkube-export-kubeconfig.service" in text
    assert "systemctl, start, sugarkube-export-node-token.service" in text

    kubeconfig_service = _unit_section(text, "sugarkube-export-kubeconfig.service")
    node_token_service = _unit_section(text, "sugarkube-export-node-token.service")
    assert "RemainAfterExit=no" in kubeconfig_service
    assert "RemainAfterExit=no" in node_token_service
