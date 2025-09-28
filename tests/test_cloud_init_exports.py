"""Ensure cloud-init auto-retries kubeconfig/node token exports."""

from __future__ import annotations

from pathlib import Path

USER_DATA = Path("scripts/cloud-init/user-data.yaml")


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
