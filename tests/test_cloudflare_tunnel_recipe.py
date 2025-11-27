from __future__ import annotations

from pathlib import Path


def _extract_recipe(lines: list[str], header: str) -> list[str]:
    collecting = False
    body: list[str] = []
    indent = "    "
    for line in lines:
        if not collecting:
            if line.startswith(header):
                collecting = True
            continue
        if line and not line.startswith(indent):
            break
        body.append(line)
    return body


def test_cf_tunnel_install_runs_token_mode_steps() -> None:
    lines = Path("justfile").read_text(encoding="utf-8").splitlines()
    header = "cf-tunnel-install env='dev' " + "token" + "='':"
    body = _extract_recipe(lines, header)

    assert any("token_mode.py\" \\" in line for line in body)
    assert any("patch-deployment" in line for line in body)
    assert any("rollout status deployment/cloudflare-tunnel" in line for line in body)
    helm_lines = [line for line in body if "helm upgrade --install" in line]
    assert all("--wait" not in line for line in helm_lines)
