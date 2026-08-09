"""Offline safety contract for the staging Cloudflare WAN drill."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / "scripts/cloudflare_wan_dependency_loss_drill.sh"
REVISION = "a" * 40
IMAGE = (
    "cloudflare/cloudflared:2026.7.3@sha256:"
    "e39ee8da81ad5e05d77f38d2f51c60ca51bf2a8450ac3abab50c17fdb91d91bf"
)


def _pod(name: str, uid: str, node: str) -> dict:
    return {
        "metadata": {
            "name": name,
            "uid": uid,
            "labels": {
                "app.kubernetes.io/name": "cloudflare-tunnel",
                "app.kubernetes.io/instance": "cloudflare-tunnel",
            },
        },
        "spec": {"nodeName": node},
        "status": {
            "phase": "Running",
            "conditions": [{"type": "Ready", "status": "True"}],
            "containerStatuses": [{"imageID": IMAGE, "restartCount": 0}],
        },
    }


def _run(tmp_path: Path, *, mode: str = "ok", args: list[str] | None = None):
    bindir = tmp_path / "bin"
    bindir.mkdir()
    pods = [_pod("cf-a", "uid-a", "node-a"), _pod("cf-b", "uid-b", "node-b")]
    deployment = {
        "metadata": {
            "labels": {
                "app.kubernetes.io/managed-by": "Helm",
                "app.kubernetes.io/name": "cloudflare-tunnel",
                "app.kubernetes.io/instance": "cloudflare-tunnel",
            }
        },
        "spec": {"replicas": 2, "template": {"spec": {"containers": [{"image": IMAGE}]}}},
    }
    (tmp_path / "fixture.json").write_text(json.dumps({"pods": pods, "deployment": deployment}))
    dispatcher = bindir / "dispatch"
    dispatcher.write_text(r"""#!/usr/bin/env python3
import json, os, pathlib, sys
cmd=pathlib.Path(sys.argv[0]).name; args=" ".join(sys.argv[1:]); mode=os.environ["MODE"]
fixture=json.load(open(os.environ["FIXTURE"]))
open(os.environ["AUDIT"], "a").write(cmd+" "+args+"\n")
if cmd=="git":
  if args=="rev-parse HEAD": print("b"*40 if mode=="revision" else "a"*40)
  elif "status --porcelain" in args: print(" M dirty" if mode=="dirty" else "")
elif cmd=="helm":
  rev="3" if mode=="helm" else "2"
  print(json.dumps([{"name":"cloudflare-tunnel","status":"deployed","revision":rev,"chart":"cloudflare-tunnel-0.3.2"}]))
elif cmd=="kubectl":
  if args=="config current-context": print("wrong" if mode=="context" else "sugar-staging")
  elif "get deployment" in args:
    if mode=="image":
      container=fixture["deployment"]["spec"]["template"]["spec"]["containers"][0]
      container["image"]="wrong"
    print(json.dumps(fixture["deployment"]))
  elif "get pods" in args:
    if mode=="pods": fixture["pods"].pop()
    if mode=="same-node": fixture["pods"][1]["spec"]["nodeName"]="node-a"
    print(json.dumps({"items":fixture["pods"]}))
  elif "query?query=" in args:
    if "ALERTS" in args: value="1" if mode=="alert" else "0"
    else: value="2"
    print(json.dumps({"data":{"result":[{"value":[0,value]}]}}))
  else: raise SystemExit("unexpected kubectl: "+args)
elif cmd=="curl":
  print("503" if mode=="endpoint" else "200", end="")
else: raise SystemExit("unexpected command "+cmd)
""")
    dispatcher.chmod(0o755)
    for command in ("git", "helm", "kubectl", "curl"):
        (bindir / command).symlink_to(dispatcher)
    audit = tmp_path / "audit"
    env = os.environ | {
        "PATH": f"{bindir}:{os.environ['PATH']}",
        "MODE": mode,
        "FIXTURE": str(tmp_path / "fixture.json"),
        "AUDIT": str(audit),
    }
    command = ["bash", str(HELPER), "--env", "staging", "--revision", REVISION]
    command.extend(args or [])
    result = subprocess.run(command, text=True, capture_output=True, env=env)
    return result, audit.read_text() if audit.exists() else ""


def test_dry_run_performs_no_mutation(tmp_path: Path):
    result, audit = _run(tmp_path)
    assert result.returncode == 0, result.stderr
    assert "DRY-RUN" in result.stdout
    assert "delete" not in audit and "apply" not in audit and "patch" not in audit
    assert "systemd-run" not in audit and "nft" not in audit
    assert "secret" not in audit


def test_non_staging_rejected_before_commands(tmp_path: Path):
    result, _ = _run(tmp_path, args=["--env", "prod"])
    assert result.returncode != 0
    assert "staging-only" in result.stderr


@pytest.mark.parametrize(
    ("mode", "message"),
    [
        ("context", "context must"),
        ("revision", "--revision must"),
        ("dirty", "worktree must be clean"),
        ("helm", "revision 2"),
        ("image", "immutable image"),
        ("pods", "exactly two Ready"),
        ("same-node", "distinct nodes"),
        ("alert", "active Cloudflare alert"),
        ("endpoint", "unhealthy approved endpoint"),
    ],
)
def test_preflight_failures_are_closed(tmp_path: Path, mode: str, message: str):
    result, audit = _run(tmp_path, mode=mode)
    assert result.returncode != 0
    assert message in result.stderr
    assert "systemd-run" not in audit and "nft" not in audit


def test_execute_requires_exact_confirmation_and_node_executor(tmp_path: Path):
    result, _ = _run(tmp_path, args=["--execute"])
    assert result.returncode != 0
    assert "exact typed operator confirmation" in result.stderr


def test_process_preserving_exact_cleanup_and_watchdog_contract():
    text = HELPER.read_text()
    assert "crictl pods --namespace cloudflare --name '^$pod$'" in text
    assert 'labels["io.kubernetes.pod.uid"]==$uid' in text
    assert "systemd-run --quiet" in text
    assert text.index("systemd-run --quiet") < text.index("nft add table")
    assert "nft delete table inet $owner" in text
    assert "flush" not in text and "delete pod" not in text
    assert "NetworkPolicy" not in text


def test_failure_signal_recovery_and_evidence_contract_is_sanitized():
    text = HELPER.read_text()
    assert "trap 'exit 130' INT" in text and "trap 'exit 143' TERM" in text
    assert "installed+=(1)" in text  # partial setup cleans only successfully installed tables
    assert "unchanged restarts, NotReady, and zero HA connections" in text
    assert "same-process recovery with four HA connections each" in text
    assert "secret tunnel-token" in text
    assert "-o jsonpath=" in text
    assert "secret tunnel-token -o json" not in text
    assert "secret-metadata-before.tsv" in text
    assert "tunnel-token -o yaml" not in text


def test_old_network_policy_contract_is_documented_as_inconclusive():
    docs = (ROOT / "docs" / "cloudflare_tunnel.md").read_text()
    assert "NetworkPolicy-only drill is also not acceptable" in docs
    assert "implementation-defined" in docs
    assert "dependency-loss test was **inconclusive**, not passing" in docs
