"""Offline safety-contract tests for the Cloudflare WAN dependency-loss drill."""

from __future__ import annotations

import json
import os
import re
import shutil
import signal
import subprocess
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DRILL = ROOT / "scripts" / "cloudflare_wan_dependency_loss_drill.sh"
TEXT = DRILL.read_text()


CONFIRM = "DISRUPT STAGING CLOUDFLARE WAN FOR SAME-PROCESS RECOVERY"


class StatefulDrillHarness:
    """Run the real helper against one stateful, entirely offline command shim."""

    def __init__(self, tmp_path: Path, **overrides: object) -> None:
        self.root = tmp_path
        self.state = tmp_path / "state.json"
        self.log = tmp_path / "commands.jsonl"
        self.evidence = tmp_path / "evidence"
        state = {
            "context": "sugar-staging", "revision": "approved", "dirty": False,
            "image_ok": True, "helm_revision": 2, "pod_count": 2,
            "obs_revision": 10, "obs_deployed_entries": 1, "obs_revision_after_cleanup": None,
            "same_node": False, "alerts": 0, "endpoint": 200,
            "sandbox_fail": False, "collision": False, "install_fail": -1,
            "crictl_paths": ["/usr/local/bin/crictl"],
            "restart": [0, 0], "tables": [False, False], "watchdogs": [False, False],
            "ready_connections": [0, 0], "ready_malformed": -1, "metrics_targets_during": 2,
            "deployment_change": False, "restart_during": -1, "uid_during": -1,
            "block_long_sleep": False, "secret": "SENTINEL-SECRET-MUST-NOT-LEAK",
        }
        state.update(overrides)
        self.state.write_text(json.dumps(state))
        shim = tmp_path / "shim.py"
        shim.write_text(_STATEFUL_SHIM)
        shim.chmod(0o755)
        for name in ("git", "kubectl", "helm", "just", "ruby", "curl", "date", "sleep"):
            (tmp_path / name).symlink_to(shim)
        node = tmp_path / "node-executor"
        node.symlink_to(shim)
        self.env = {
            "PATH": f"{tmp_path}:/usr/bin:/bin",
            "HARNESS_STATE": str(self.state),
            "HARNESS_LOG": str(self.log),
            "CF_DRILL_APPROVED_REVISION": "approved",
            "CF_DRILL_EXPECTED_OBSERVABILITY_REVISION": "10",
            "CF_DRILL_NODE_EXECUTOR": str(node),
        }

    def start(self, wrapper: list[str] | None = None) -> subprocess.Popen[str]:
        return subprocess.Popen(
            [*(wrapper or []), "bash", str(DRILL), "--execute", f"--confirm={CONFIRM}",
             f"--evidence-dir={self.evidence}"], cwd=ROOT, env=os.environ | self.env,
            text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            start_new_session=True,
        )

    def wait_for_disruption(self, timeout: float = 20) -> None:
        """Block until both owner tables are installed and the observation sleep is active."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            state = self.current()
            if state.get("sleeping") and state.get("tables") == [True, True]:
                return
            time.sleep(.02)
        raise AssertionError("helper never reached the disrupted observation window")

    def run(self, *, confirmation: str = CONFIRM, timeout: float = 30) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["bash", str(DRILL), "--execute", f"--confirm={confirmation}",
             f"--evidence-dir={self.evidence}"], cwd=ROOT, env=os.environ | self.env,
            text=True, capture_output=True, timeout=timeout,
        )

    def commands(self) -> list[dict[str, object]]:
        if not self.log.exists():
            return []
        return [entry for line in self.log.read_text().splitlines()
                if "tool" in (entry := json.loads(line))]

    def events(self) -> list[dict[str, object]]:
        if not self.log.exists():
            return []
        return [entry for line in self.log.read_text().splitlines()
                if "event" in (entry := json.loads(line))]

    def current(self) -> dict[str, object]:
        # The shim rewrites state.json (non-atomically) on nearly every
        # subprocess invocation, so a concurrent read can catch a
        # truncated-but-not-yet-written file. A fixed 100ms budget resolves
        # this locally but is not always enough on a loaded/throttled CI
        # runner, so retry on a longer wall-clock budget with backoff
        # instead of a small fixed attempt count.
        deadline = time.monotonic() + 2.0
        delay = 0.002
        while time.monotonic() < deadline:
            try:
                return json.loads(self.state.read_text())
            except (json.JSONDecodeError, FileNotFoundError):
                time.sleep(delay)
                delay = min(delay * 1.5, 0.05)
        raise AssertionError("state shim did not leave valid JSON")


_STATEFUL_SHIM = r'''#!/usr/bin/env python3
import json, os, pathlib, re, sys, time, urllib.parse
state_path = pathlib.Path(os.environ["HARNESS_STATE"])
log_path = pathlib.Path(os.environ["HARNESS_LOG"])
name, args = pathlib.Path(sys.argv[0]).name, sys.argv[1:]
state = json.loads(state_path.read_text())
with log_path.open("a") as stream:
    stream.write(json.dumps({"tool": name, "args": args}) + "\n")
def event(kind, **values):
    with log_path.open("a") as stream: stream.write(json.dumps({"event":kind, **values}) + "\n")
def save(): state_path.write_text(json.dumps(state))
def out(value): print(value, end="" if str(value).endswith("\n") else "\n")
image = "cloudflare/cloudflared:2026.7.3@sha256:e39ee8da81ad5e05d77f38d2f51c60ca51bf2a8450ac3abab50c17fdb91d91bf"
if name == "git":
    if "status" in args: out(" M dirty" if state["dirty"] else "")
    else: out(state["revision"])
elif name == "helm":
    if "list" in args: out(json.dumps([{"name":"cloudflare-tunnel","status":"deployed","chart":"cloudflare-tunnel-0.3.2"}]))
    elif "cloudflare-tunnel" in args: out(json.dumps([{"status":"deployed","revision":state["helm_revision"]}]))
    else:
        state["obs_history_calls"] = state.get("obs_history_calls", 0) + 1
        revision = state["obs_revision"]
        if state["obs_history_calls"] > 1 and state["obs_revision_after_cleanup"] is not None:
            revision = state["obs_revision_after_cleanup"]
        entries = [{"status":"deployed","revision":revision} for _ in range(state["obs_deployed_entries"])]
        out(json.dumps(entries)); save()
elif name == "just": sys.exit(0)
elif name == "ruby":
    for i in range(16): out(f"https://endpoint-{i}.test")
elif name == "curl": event("endpoint", response=state["endpoint"]); out(str(state["endpoint"]))
elif name == "date": out("20260809T000000Z")
elif name == "sleep":
    if state["block_long_sleep"] and args and int(args[0]) > 30:
        state["sleeping"] = True; save()
        while True: time.sleep(.05)
elif name == "kubectl":
    joined = " ".join(args)
    if "current-context" in joined: out(state["context"])
    elif "get deployment" in joined:
        used = image if state["image_ok"] else "cloudflare/cloudflared:wrong"
        disrupted = any(state["tables"])
        labels={"app.kubernetes.io/managed-by":"Helm","app.kubernetes.io/name":"cloudflare-tunnel","app.kubernetes.io/instance":"cloudflare-tunnel"}
        if state["deployment_change"] and state.get("was_disrupted"): labels["changed"]="true"
        out(json.dumps({"metadata":{"uid":"deployment-uid","resourceVersion":"2" if state.get("was_disrupted") else "1","generation":1,"labels":labels,"annotations":{}},"spec":{"replicas":2,"template":{"spec":{"containers":[{"image":used,"readinessProbe":{"httpGet":{"path":"/ready","port":2000}}}]}}},"status":{"observedGeneration":1}}))
    elif "get pods" in joined:
        items=[]
        for i in range(state["pod_count"]):
            disrupted = i < 2 and state["tables"][i]
            restart = state["restart"][i] if i < 2 else 0
            if disrupted and state["restart_during"] == i: restart += 1
            uid = f"replacement-{i+1}" if disrupted and state["uid_during"] == i else f"uid-{i+1}"
            items.append({"metadata":{"name":f"connector-{i+1}","uid":uid,"labels":{"app.kubernetes.io/name":"cloudflare-tunnel","app.kubernetes.io/instance":"cloudflare-tunnel"}},"spec":{"nodeName":"node-1" if state["same_node"] else f"node-{i+1}","containers":[{"image":image}]},"status":{"phase":"Running","conditions":[{"type":"Ready","status":"False" if disrupted else "True"}],"containerStatuses":[{"restartCount":restart}]}})
        out(json.dumps({"items":items}))
        event("pods", uids=[p["metadata"]["uid"] for p in items], restarts=[p["status"]["containerStatuses"][0]["restartCount"] for p in items], ready=[p["status"]["conditions"][0]["status"] for p in items])
    elif "get secret" in joined:
        event("secret_request", command=joined)
        if ".data" in joined or "-o json " in joined or "-o yaml" in joined: out(state["secret"]); sys.exit(91)
        out("secret-uid\t12\t2026-08-09T00:00:00Z")
    elif "get --raw" in joined:
        query=urllib.parse.unquote(joined)
        if "ALERTS" in query: value=state["alerts"]
        elif "sum(cloudflared" in query: value=2 if all(state["tables"]) else 8
        elif "count(up" in query: value=state["metrics_targets_during"] if all(state["tables"]) else 2
        else: value=2
        event("prometheus", query=query, value=value)
        out(json.dumps({"data":{"result":[{"value":[0,str(value)]}]}}))
elif name == "node-executor":
    node, command=args[0],args[1]; idx=int(node[-1])-1
    cross_process_read = re.compile(
        r"(?:(?<!sudo )/usr/bin/readlink|(?<![/\w])readlink) /proc/(?!self(?:/|$))"
    )
    if cross_process_read.search(command):
        event("unprivileged_cross_process_readlink", node=node, command=command)
        sys.exit(1)
    if "test -x" in command:
        sys.exit(0 if "/usr/local/bin/crictl" in state["crictl_paths"] else 1)
    if "crictl pods --name" in command and "inspectp" not in command:
        if state["sandbox_fail"]: out("ambiguous\nsecond"); sys.exit(0)
        out(("a" if idx == 0 else "b")*12)
    elif command.startswith("sudo /usr/local/bin/crictl inspectp"):
        out(json.dumps({"status":{"labels":{"io.kubernetes.pod.uid":f"uid-{idx+1}"}},"info":{"pid":101+idx}}))
    elif command.startswith("sudo /usr/bin/readlink /proc/"):
        out(f"net:[{1001+idx}]")
    elif "http://127.0.0.1:2000/ready" in command:
        if state["ready_malformed"] == idx: out("not-json"); sys.exit(0)
        connected = state["ready_connections"][idx] if state["tables"][idx] else 4
        out(json.dumps({"httpStatus":503 if connected == 0 else 200,"readyConnections":connected}))
    elif "systemd-run" in command:
        state["watchdogs"][idx]=True; save(); event("watchdog", node=node, verified=False)
    elif "systemctl is-active" in command:
        if not state["watchdogs"][idx]: sys.exit(3)
        event("watchdog", node=node, verified=True)
        out(str(501+idx))
    elif "add table inet" in command:
        state["tables"][idx]=True; state["was_disrupted"]=True; save(); event("table", node=node, present=True)
        if state["install_fail"] == idx: sys.exit(44)
    elif "delete table inet" in command:
        state["tables"][idx]=False; save(); event("table", node=node, present=False); out("")
    elif "list ruleset" in command:
        if state["collision"]: sys.exit(1)
        sys.exit(0)
save()
'''


def run(*args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(DRILL), *args],
        cwd=ROOT,
        env=os.environ | (env or {}),
        text=True,
        capture_output=True,
    )


def test_shell_is_valid() -> None:
    subprocess.run(["bash", "-n", str(DRILL)], check=True)


def test_dry_run_performs_no_mutation_or_external_preflight(tmp_path: Path) -> None:
    marker = tmp_path / "called"
    bomb = tmp_path / "date"
    bomb.write_text(f"#!/bin/sh\ntouch {marker}\nprintf 20260809T000000Z\n")
    bomb.chmod(0o755)
    result = run(env={"PATH": f"{tmp_path}:/usr/bin:/bin"})
    assert result.returncode == 0
    assert "PLAN ONLY" in result.stdout
    assert not marker.exists(), "dry-run should not even invoke cluster/node stubs"


def test_help_distinguishes_offline_manual_and_execution_requirements() -> None:
    result = run("--help")
    assert result.returncode == 0
    assert (
        "default offline plan requires no approval coordinates or cluster/node tools"
        in result.stdout
    )
    assert "Both --manual-node-plan and --execute require:" in result.stdout
    assert "CF_DRILL_APPROVED_REVISION" in result.stdout
    assert "CF_DRILL_EXPECTED_OBSERVABILITY_REVISION" in result.stdout
    assert "Execution additionally requires the exact confirmation and:" in result.stdout
    assert "CF_DRILL_NODE_EXECUTOR" in result.stdout


@pytest.mark.parametrize("mode", ["manual", "execute"])
def test_live_modes_require_explicit_observability_revision(
    tmp_path: Path, mode: str,
) -> None:
    env = manual_plan_environment(tmp_path)
    env.pop("CF_DRILL_EXPECTED_OBSERVABILITY_REVISION")
    args = ["--manual-node-plan"] if mode == "manual" else ["--execute", f"--confirm={CONFIRM}"]
    result = run(*args, env=env)
    assert result.returncode != 0
    assert "CF_DRILL_EXPECTED_OBSERVABILITY_REVISION is required" in result.stderr


@pytest.mark.parametrize("value", ["", "0", "-1", "+10", "01", " 10", "10 ", "ten", "10x"])
def test_live_modes_reject_noncanonical_observability_revision(
    tmp_path: Path, value: str,
) -> None:
    env = manual_plan_environment(tmp_path)
    env["CF_DRILL_EXPECTED_OBSERVABILITY_REVISION"] = value
    result = run("--manual-node-plan", env=env)
    assert result.returncode != 0
    assert "canonical positive decimal integer" in result.stderr
    assert not (tmp_path / "node-executor-called").exists()


def manual_plan_environment(
    tmp_path: Path, *, context: str = "sugar-staging", obs_revision: int = 10,
    obs_deployed_entries: int = 1,
) -> dict[str, str]:
    image = TEXT.split("readonly EXPECTED_IMAGE='", 1)[1].split("'", 1)[0]
    deployment = {
        "metadata": {"labels": {"app.kubernetes.io/managed-by": "Helm", "app.kubernetes.io/name": "cloudflare-tunnel", "app.kubernetes.io/instance": "cloudflare-tunnel"}},
        "spec": {"replicas": 2, "template": {"spec": {"containers": [{"image": image, "readinessProbe": {"httpGet": {"path": "/ready", "port": 2000}}}]}}},
        "status": {"observedGeneration": 1},
    }
    pods = {"items": []}
    for number in (1, 2):
        pods["items"].append({
            "metadata": {"name": f"connector-{number}", "uid": f"uid-{number}", "labels": {"app.kubernetes.io/name": "cloudflare-tunnel", "app.kubernetes.io/instance": "cloudflare-tunnel"}},
            "spec": {"nodeName": f"node-{number}", "containers": [{"image": image}]},
            "status": {"phase": "Running", "conditions": [{"type": "Ready", "status": "True"}], "containerStatuses": [{"restartCount": 0}]},
        })

    def stub(name: str, body: str) -> None:
        path = tmp_path / name
        path.write_text("#!/bin/sh\nset -eu\n" + body)
        path.chmod(0o755)

    stub("git", "case \"$*\" in *status*) exit 0;; *rev-parse*) echo approved;; esac\n")
    obs_history = json.dumps(
        [{"status": "deployed", "revision": obs_revision}] * obs_deployed_entries
    )
    stub("helm", f"case \"$*\" in *' list '*) printf '%s\\n' '[{{\"name\":\"cloudflare-tunnel\",\"status\":\"deployed\",\"chart\":\"cloudflare-tunnel-0.3.2\"}}]';; *cloudflare-tunnel*) printf '%s\\n' '[{{\"status\":\"deployed\",\"revision\":2}}]';; *) printf '%s\\n' {json.dumps(obs_history)};; esac\n")
    stub("kubectl", f"case \"$*\" in *current-context*) echo {context};; *'get deployment'*) printf '%s\\n' {json.dumps(json.dumps(deployment))};; *'get pods'*) printf '%s\\n' {json.dumps(json.dumps(pods))};; *'get secret'*) printf 'secret-uid\\t12\\t2026-08-09T00:00:00Z\\n';; *ALERTS*) printf '%s\\n' '{{\"data\":{{\"result\":[{{\"value\":[0,\"0\"]}}]}}}}';; *get\\ --raw*) printf '%s\\n' '{{\"data\":{{\"result\":[{{\"value\":[0,\"2\"]}}]}}}}';; esac\n")
    stub("just", "exit 0\n")
    stub("ruby", "i=1; while [ $i -le 16 ]; do echo https://endpoint-$i.test; i=$((i+1)); done\n")
    stub("curl", "printf 200\n")
    stub("date", "printf 20260809T000000Z\n")
    return {
        "PATH": f"{tmp_path}:/usr/bin:/bin",
        "CF_DRILL_APPROVED_REVISION": "approved",
        "CF_DRILL_EXPECTED_OBSERVABILITY_REVISION": str(obs_revision),
    }


def test_manual_node_plan_runs_read_only_preflights_and_renders_exact_ordered_commands(tmp_path: Path) -> None:
    result = run("--manual-node-plan", env=manual_plan_environment(tmp_path))
    assert result.returncode == 0, result.stderr
    lines = result.stdout.splitlines()
    watchdogs = [i for i, line in enumerate(lines) if line.startswith("WATCHDOG ")]
    disruptions = [i for i, line in enumerate(lines) if line.startswith("DISRUPTION ")]
    cleanups = [i for i, line in enumerate(lines) if line.startswith("CLEANUP ")]
    assert len(watchdogs) == len(disruptions) == len(cleanups) == 2
    assert max(watchdogs) < min(disruptions)
    assert max(disruptions) < min(cleanups)
    assert "verify both watchdog commands successfully before running either DISRUPTION" in result.stdout
    assert "After the observation window, run both CLEANUP commands." in result.stdout
    assert "If either DISRUPTION command fails or you abort after any disruption, immediately run both CLEANUP commands." in result.stdout
    for number in (1, 2):
        associated = [line for line in lines if f"node=node-{number}" in line]
        assert len(associated) == 3
        assert all(f"pod=connector-{number}" in line and f"uid=uid-{number}" in line for line in associated)
        assert all("crictl\\ pods" in line and "inspectp" in line and "readlink" in line for line in associated)
        assert all("/usr/local/bin/crictl" in line for line in associated)
    assert all("systemctl" in lines[i] and "MainPID" in lines[i] for i in disruptions)
    assert all("delete\\ table\\ inet" in lines[i] and "list\\ ruleset" in lines[i] and "length\\ ==\\ 0" in lines[i] for i in cleanups)
    assert "BLOCKED: manual-node plan only; the drill was not executed and has not passed." in result.stdout
    assert "Observability Helm revision: expected=10 observed=10" in result.stdout


def test_only_approved_crictl_path_is_encoded_in_the_helper() -> None:
    obsolete = "/usr/bin/" + "crictl"
    assert "readonly CRICTL='/usr/local/bin/crictl'" in TEXT
    assert obsolete not in TEXT
    assert "command -v crictl" not in TEXT
    assert "sudo crictl" not in TEXT
    assert 'test -x ${CRICTL}' in TEXT


def test_manual_commands_expand_the_immutable_crictl_path(tmp_path: Path) -> None:
    result = run("--manual-node-plan", env=manual_plan_environment(tmp_path))
    assert result.returncode == 0, result.stderr
    command_records = [
        line for line in result.stdout.splitlines()
        if line.startswith(("WATCHDOG ", "DISRUPTION ", "CLEANUP "))
    ]
    assert len(command_records) == 6
    assert all("/usr/local/bin/crictl" in command for command in command_records)
    assert all(r"sudo\ /usr/bin/readlink\ /proc/" in command for command in command_records)


def test_later_matching_observability_revision_needs_no_source_change(tmp_path: Path) -> None:
    result = run(
        "--manual-node-plan",
        env=manual_plan_environment(tmp_path, obs_revision=42),
    )
    assert result.returncode == 0, result.stderr
    assert "expected=42 observed=42" in result.stdout


def test_observability_revision_mismatch_fails_before_node_executor(tmp_path: Path) -> None:
    env = manual_plan_environment(tmp_path, obs_revision=10)
    env["CF_DRILL_EXPECTED_OBSERVABILITY_REVISION"] = "11"
    result = run("--manual-node-plan", env=env)
    assert result.returncode != 0
    assert "expected 11; observed 10" in result.stderr
    assert "WATCHDOG " not in result.stdout


@pytest.mark.parametrize("deployed_entries", [0, 2])
def test_observability_history_requires_exactly_one_deployed_entry(
    tmp_path: Path, deployed_entries: int,
) -> None:
    env = manual_plan_environment(
        tmp_path, obs_revision=10, obs_deployed_entries=deployed_entries
    )
    env["CF_DRILL_EXPECTED_OBSERVABILITY_REVISION"] = "10"
    result = run("--manual-node-plan", env=env)
    assert result.returncode != 0
    assert "exactly one deployed entry" in result.stderr
    assert "WATCHDOG " not in result.stdout


def test_manual_node_plan_preflight_failure_emits_no_actionable_commands(tmp_path: Path) -> None:
    result = run("--manual-node-plan", env=manual_plan_environment(tmp_path, context="wrong-context"))
    assert result.returncode != 0
    assert not any(record in result.stdout for record in ("WATCHDOG ", "DISRUPTION ", "CLEANUP "))


def test_execute_without_node_adapter_renders_plan_then_fails_closed(tmp_path: Path) -> None:
    result = run(
        "--execute",
        "--confirm=DISRUPT STAGING CLOUDFLARE WAN FOR SAME-PROCESS RECOVERY",
        env=manual_plan_environment(tmp_path),
    )
    assert result.returncode != 0
    assert result.stdout.count("WATCHDOG ") == 2
    assert "execution remains blocked" in result.stderr


def test_non_staging_is_rejected_before_any_mutation() -> None:
    result = run("--env=prod")
    assert result.returncode != 0
    assert "staging-only" in result.stderr


def test_operator_confirmation_is_enforced_before_preflight() -> None:
    result = run("--execute", "--confirm=no")
    assert result.returncode != 0
    assert "confirmation must exactly equal" in result.stderr


@pytest.mark.parametrize(
    "needle",
    [
        'EXPECTED_CONTEXT=sugar-staging',
        "git status --porcelain",
        "CF_DRILL_APPROVED_REVISION",
        "EXPECTED_HELM_REVISION=2",
        "EXPECTED_IMAGE=",
        "exactly two Ready, exactly labelled connector pods",
        "connector pods must be on distinct nodes",
        "Prometheus targets are unhealthy",
        "a Cloudflare alert is active",
        "approved staging endpoint manifest must contain exactly 16 URLs",
    ],
)
def test_preflight_fail_closed_guards_are_present(needle: str) -> None:
    assert needle in TEXT


def test_wrong_context_revision_image_helm_and_ambiguous_pods_are_guarded() -> None:
    assert "context must be" in TEXT
    assert "repository revision is not approved" in TEXT
    assert "immutable image is not approved" in TEXT
    assert "Cloudflare Helm revision must be 2" in TEXT
    assert "exactly two Ready" in TEXT


def test_exact_network_namespace_resolution_is_required() -> None:
    assert "${CRICTL} inspectp" in TEXT
    assert 'io.kubernetes.pod.uid' in TEXT
    assert "sudo /usr/bin/readlink /proc/${pid}/ns/net" in TEXT
    assert "cannot prove exact pod network namespace identity" in TEXT


def test_cross_process_namespace_reads_always_use_authorized_sudo_path() -> None:
    reads = re.findall(r"(?:sudo )?(?:/usr/bin/)?readlink /proc/[^ )\"']+/ns/net", TEXT)
    assert reads
    cross_process_reads = [read for read in reads if "/proc/self/ns/net" not in read]
    assert cross_process_reads
    assert all(read.startswith("sudo /usr/bin/readlink ") for read in cross_process_reads)
    assert "/usr/bin/readlink /proc/self/ns/net" in reads
    assert "sudo /usr/bin/readlink /proc/self/ns/net" not in TEXT


def test_owner_collision_is_refused() -> None:
    collision = TEXT.split('collision_check="', 1)[1].split('"\n', 1)[0]
    assert "nft -j list ruleset" in collision
    assert 'ruleset=\\"\\$(' in collision
    assert "length == 0" in collision
    assert "owner table absence could not be proven" in TEXT


def test_watchdogs_are_installed_on_both_nodes_before_disruption() -> None:
    watchdog = TEXT.index("# A transient host service survives")
    install = TEXT.index('install="test ', watchdog)
    assert "for i in 0 1; do" in TEXT[watchdog:install]
    assert "systemd-run" in TEXT[watchdog:install]
    assert "/usr/bin/nsenter" in TEXT[watchdog:install]
    assert "/proc/self/ns/net" in TEXT[watchdog:install]
    assert "/usr/bin/systemctl is-active --quiet" in TEXT[watchdog:install]
    assert "/usr/bin/systemctl show --property MainPID --value" in TEXT[watchdog:install]
    assert "/proc/${watchdog_pid}/ns/net" in TEXT[watchdog:install]
    assert "sudo /usr/bin/readlink /proc/${watchdog_pid}/ns/net" in TEXT[watchdog:install]


@pytest.mark.parametrize(
    ("active", "main_pid", "watchdog_netns", "expected"),
    [
        (False, "41", "net:[100]", "inactive"),
        (True, "0", "net:[100]", "pid"),
        (True, "", "net:[100]", "pid"),
        (True, "41", "net:[999]", "netns"),
        (True, "41", "net:[100]", "ok"),
    ],
)
def test_stateful_watchdog_stub_fails_closed(
    tmp_path: Path, active: bool, main_pid: str, watchdog_netns: str, expected: str
) -> None:
    """Exercise the ordered remote contract without contacting a node or cluster."""
    state = tmp_path / "state.json"
    stub = tmp_path / "node-executor"
    state.write_text(json.dumps({"active": active, "pid": main_pid, "netns": watchdog_netns}))
    stub.write_text(
        "#!/bin/sh\n"
        f"state={state!s}\n"
        "cmd=$2\n"
        "printf '%s\\n' \"$cmd\" >> \"$state.audit\"\n"
        "case $cmd in\n"
        "  *systemd-run*) exit 0;;\n"
        f"  *is-active*) {'exit 0' if active else 'exit 3'};;\n"
        f"  *MainPID*) printf '%s\\n' {main_pid!r};;\n"
        f"  *'/proc/{main_pid}/ns/net'*) printf '%s\\n' {watchdog_netns!r};;\n"
        "  *'nft add table'*) printf mutation >> \"$state.mutated\";;\n"
        "esac\n"
    )
    stub.chmod(0o755)
    result = subprocess.run(
        [
            "bash", "-c",
            'set -e; x=$1; "$x" n "systemd-run"; '
            '"$x" n "systemctl is-active"; p=$("$x" n "MainPID"); '
            '[[ $p =~ ^[1-9][0-9]*$ ]] || exit 20; '
            '[[ $("$x" n "/proc/$p/ns/net") == "net:[100]" ]] || exit 21; '
            '"$x" n "nft add table"',
            "test", str(stub),
        ], capture_output=True, text=True,
    )
    mutated = (tmp_path / "state.json.mutated").exists()
    assert mutated is (expected == "ok")
    assert (result.returncode == 0) is (expected == "ok")


@pytest.mark.parametrize(
    ("query_ok", "present", "success"),
    [(False, False, False), (True, True, False), (True, False, True)],
)
def test_stateful_cleanup_stub_requires_successful_absence_query(
    tmp_path: Path, query_ok: bool, present: bool, success: bool
) -> None:
    nft = tmp_path / "nft"
    nft.write_text(
        "#!/bin/sh\n"
        "case \"$*\" in\n"
        "  *delete*) exit 0;;\n"
        f"  *list\\ ruleset*) {'exit 2' if not query_ok else 'printf %s ' + repr(json.dumps({'nftables': [{'table': {'family': 'inet', 'name': 'owner'}}] if present else []}))};;\n"
        "esac\n"
    )
    nft.chmod(0o755)
    result = subprocess.run(
        ["bash", "-c", f"'{nft}' delete table inet owner || true; ruleset=\"$('{nft}' -j list ruleset)\" && printf '%s\\n' \"$ruleset\" | jq -e --arg table owner '[.nftables[]?.table? | select(.family==\"inet\" and .name==$table)] | length == 0' >/dev/null"],
        capture_output=True, text=True,
    )
    assert (result.returncode == 0) is success


def test_cleanup_proof_does_not_depend_on_remote_pipefail() -> None:
    for marker in ('    command="', '  delete_and_prove="'):
        command = TEXT.split(marker, 1)[1].split("\n", 1)[0]
        assert 'ruleset=\\"\\$(' in command
        assert 'printf \'%s\\\\n\' \\"\\${ruleset}\\" | /usr/bin/jq' in command


def test_watchdog_fails_closed_on_query_failure_or_present_table() -> None:
    watchdog = TEXT.split("printf -v watchdog_body", 1)[1].split("\n", 1)[0]
    assert 'ruleset=\\"\\$(/usr/sbin/nft -j list ruleset)\\" || exit 71' in watchdog
    assert "length == 0" in watchdog


def test_manual_cleanup_prints_successful_absence_proof() -> None:
    manual = TEXT.split("manual_cleanup() {", 1)[1].split("\n}", 1)[0]
    assert "nft -j list ruleset" in manual
    assert "length == 0" in manual


def test_preflight_pod_evidence_records_image_and_numeric_restart_count() -> None:
    construction = TEXT.split('--argjson pods "$(for i in 0 1; do ', 1)[1].split(
        "; done | jq -s .)", 1
    )[0]
    assert '--argjson restartCount "${pod_restarts[$i]}"' in construction
    assert '--arg image "${EXPECTED_IMAGE}"' in construction
    assert "restartCount:$restartCount,image:$image" in construction

    record = subprocess.run(
        [
            "jq", "-n", "--argjson", "restartCount", "7", "--arg", "image",
            "cloudflare/cloudflared:test@sha256:approved",
            "{restartCount:$restartCount,image:$image}",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    assert json.loads(record.stdout) == {
        "restartCount": 7,
        "image": "cloudflare/cloudflared:test@sha256:approved",
    }


def test_one_node_setup_failure_cleans_the_installed_node() -> None:
    attempted = TEXT.index('attempted_indices+=("${i}")')
    install = TEXT.index('node_exec "${pod_nodes[$i]}" "${install}"', attempted)
    assert attempted < install, "ambiguous installation attempts must be tracked first"
    assert "trap 'cleanup $?' EXIT" in TEXT
    assert "cleanup 1" in TEXT[install : install + 200]


def test_failed_normal_cleanup_remains_tracked_for_exit_retry() -> None:
    normal_cleanup = TEXT.index("declare -a cleanup_retry_indices=()")
    failure = TEXT.index('cleanup_retry_indices+=("${i}")', normal_cleanup)
    preserve = TEXT.index('attempted_indices=("${cleanup_retry_indices[@]}")', failure)
    abort = TEXT.index("automated exact cleanup could not be proven", preserve)
    assert failure < preserve < abort


def test_nft_table_name_is_short_and_does_not_embed_owner() -> None:
    table_function = TEXT.split("table_for() {", 1)[1].split("\n}", 1)[0]
    assert "sha256sum" in table_function
    assert "cfwd_" in table_function
    assert '${owner//-/_}' not in table_function


def test_lifecycle_contract_is_checked_before_disruption() -> None:
    deployment_check = TEXT.index('has("livenessProbe") | not')
    watchdogs = TEXT.index("# A transient host service survives")
    assert deployment_check < watchdogs
    assert '.readinessProbe.httpGet.path=="/ready"' in TEXT
    assert ".readinessProbe.httpGet.port==2000" in TEXT


def test_interruption_requires_same_uids_and_restart_counts() -> None:
    assert "did not prove same-process NotReady and zero ready connections" in TEXT
    interruption = TEXT.split("deadline=$((SECONDS+90))", 1)[1].split(
        'sleep "${DISRUPTION_SECONDS}"', 1
    )[0]
    assert ".metadata.uid==$u0" in interruption
    assert "restartCount" in interruption
    assert 'status=="False"' in interruption


def test_deployment_fingerprint_excludes_resource_version_and_status() -> None:
    fingerprint = TEXT.split('deployment_fingerprint="', 1)[1].split('"\n', 1)[0]
    assert "resourceVersion" not in fingerprint
    assert "status" not in fingerprint
    assert "labels" in fingerprint and "annotations" in fingerprint and "spec" in fingerprint
    assert "Deployment observedGeneration does not match unchanged generation" in TEXT


def test_accidental_restart_is_rejected() -> None:
    assert TEXT.count("status.containerStatuses[].restartCount") >= 3
    assert "same-process" in TEXT


def test_timeout_and_signals_run_cleanup() -> None:
    assert "DISRUPTION_SECONDS=180" in TEXT
    assert "RECOVERY_SECONDS=300" in TEXT
    assert "trap 'exit 130' INT" in TEXT
    assert "trap 'exit 143' TERM" in TEXT
    assert "sleep 240" in TEXT


def test_only_exact_table_deletion_is_used_without_broad_flush() -> None:
    assert "nft delete table inet ${table}" in TEXT
    for forbidden in ("nft flush", "iptables -F", "iptables --flush", "delete ruleset"):
        assert forbidden not in TEXT


def test_recovery_requires_same_pods_and_four_connections_each() -> None:
    assert "same-pod recovery with unchanged restart counts" in TEXT
    assert "cloudflared_tunnel_ha_connections" in TEXT
    assert ">= 4" in TEXT


def test_secret_values_are_never_requested_or_printed() -> None:
    assert "get secret tunnel-token -o jsonpath='{.metadata" in TEXT
    for forbidden in (".data.token", "-o yaml", "get secret tunnel-token -o json\n", "base64 -d"):
        assert forbidden not in TEXT


def test_actual_helper_completes_stateful_interruption_and_recovery(tmp_path: Path) -> None:
    harness = StatefulDrillHarness(tmp_path)
    result = harness.run()
    assert result.returncode == 0, result.stderr
    commands = harness.commands()
    node_commands = [entry["args"][1] for entry in commands if entry["tool"] == "node-executor"]
    watchdogs = [i for i, command in enumerate(node_commands) if "systemd-run --unit" in command]
    installs = [i for i, command in enumerate(node_commands) if "add table inet" in command]
    deletes = [command for command in node_commands if "delete table inet" in command]
    assert len(watchdogs) == len(installs) == len(deletes) == 2
    assert not any(
        event.get("event") == "unprivileged_cross_process_readlink" for event in harness.events()
    )
    assert max(watchdogs) < min(installs)
    assert all("list ruleset" in command for command in deletes)
    assert harness.current()["tables"] == [False, False]
    events = harness.events()
    verified = [i for i, event in enumerate(events) if event.get("event") == "watchdog" and event.get("verified") is True]
    installed = [i for i, event in enumerate(events) if event.get("event") == "table" and event.get("present") is True]
    assert len(verified) == len(installed) == 2 and max(verified) < min(installed)
    pod_events = [event for event in events if event.get("event") == "pods"]
    assert any(event["ready"] == ["False", "False"] for event in pod_events)
    assert pod_events[-1]["ready"] == ["True", "True"]
    assert all(event["uids"] == ["uid-1", "uid-2"] and event["restarts"] == [0, 0] for event in pod_events)
    assert any("sum(cloudflared" in str(event["query"]) and event["value"] == 2 for event in events if event.get("event") == "prometheus")
    assert sum(entry["tool"] == "just" for entry in commands) == 2
    assert len([event for event in events if event.get("event") == "endpoint"]) == 32
    preflight = json.loads((harness.evidence / "preflight.json").read_text())
    assert preflight["observabilityRevision"] == {"expected": "10", "observed": "10"}
    assert "observability revision expected=10 observed=10" in result.stdout
    assert [pod["restartCount"] for pod in preflight["pods"]] == [0, 0]
    assert all(pod["image"].startswith("cloudflare/cloudflared:") for pod in preflight["pods"])
    observations = [json.loads(line) for line in (harness.evidence / "interruption-observations.jsonl").read_text().splitlines()]
    assert observations[-1]["readiness"] == [{"httpStatus": 503, "readyConnections": 0}] * 2
    assert observations[-1]["prometheusTargetCount"] == 2
    assert observations[-1]["haConnections"] == 2
    assert (harness.evidence / "recovery-metrics.json").exists()


@pytest.mark.parametrize(
    ("override", "message"),
    [
        ({"ready_connections": [1, 0]}, "zero ready connections"),
        ({"ready_malformed": 1}, "readiness endpoint was unavailable or malformed"),
        ({"metrics_targets_during": 1}, "Prometheus target became unavailable"),
        ({"restart_during": 0}, "connector UID/restart set changed"),
        ({"uid_during": 1}, "connector UID/restart set changed"),
        ({"deployment_change": True}, "Deployment desired state or ownership changed"),
    ],
)
def test_interruption_and_invariance_fail_closed(tmp_path: Path, override: dict[str, object], message: str) -> None:
    harness = StatefulDrillHarness(tmp_path, **override)
    result = harness.run()
    assert result.returncode != 0
    assert message in result.stderr
    if harness.evidence.exists():
        assert (harness.evidence / "interruption-observations.jsonl").exists()


def test_execution_commands_use_only_the_approved_crictl_path(tmp_path: Path) -> None:
    harness = StatefulDrillHarness(tmp_path)
    result = harness.run()
    assert result.returncode == 0, result.stderr
    node_commands = [
        entry["args"][1]
        for entry in harness.commands()
        if entry["tool"] == "node-executor"
    ]
    crictl_commands = [command for command in node_commands if "crictl" in command]
    assert crictl_commands
    assert all("/usr/local/bin/crictl" in command for command in crictl_commands)
    assert any("test -x /usr/local/bin/crictl" in command for command in node_commands)
    assert any("crictl pods --name" in command for command in node_commands)
    assert any("crictl inspectp" in command and "list ruleset" in command
               for command in node_commands)
    assert any("crictl inspectp" in command and "systemd-run" in command
               for command in node_commands)
    assert any("crictl inspectp" in command and "add table inet" in command
               for command in node_commands)
    assert any("crictl inspectp" in command and "delete table inet" in command
               for command in node_commands)
    guarded_phases = [
        command for command in node_commands
        if "/proc/" in command
        and any(
            marker in command
            for marker in ("list ruleset", "systemd-run", "add table inet", "delete table inet")
        )
    ]
    assert guarded_phases
    assert all("sudo /usr/bin/readlink /proc/" in command for command in guarded_phases)

    automatic_cleanup = TEXT.split("\ncleanup() {", 1)[1].split("\n}", 1)[0]
    manual_cleanup = TEXT.split("\nmanual_cleanup() {", 1)[1].split("\n}", 1)[0]
    assert "sudo ${CRICTL} inspectp" in automatic_cleanup
    assert "sudo ${CRICTL} inspectp" in manual_cleanup
    assert "sudo /usr/bin/readlink /proc/" in automatic_cleanup
    assert "sudo /usr/bin/readlink /proc/" in manual_cleanup


def test_legacy_only_crictl_fails_before_any_followup_command(tmp_path: Path) -> None:
    legacy_path = "/usr/bin/" + "crictl"
    harness = StatefulDrillHarness(tmp_path, crictl_paths=[legacy_path])
    result = harness.run()
    assert result.returncode != 0
    assert "required remote binary path missing" in result.stderr
    node_commands = [
        entry["args"][1]
        for entry in harness.commands()
        if entry["tool"] == "node-executor"
    ]
    assert node_commands == [
        next(command for command in node_commands
             if "test -x /usr/local/bin/crictl" in command)
    ]
    assert not any(
        event.get("event") in {"watchdog", "table"} for event in harness.events()
    )
    assert harness.current()["tables"] == [False, False]
    assert harness.current()["watchdogs"] == [False, False]


@pytest.mark.parametrize("expected", ["", "0", "-1", "+10", "01", " 10", "ten"])
def test_invalid_coordinate_never_invokes_node_executor(
    tmp_path: Path, expected: str,
) -> None:
    harness = StatefulDrillHarness(tmp_path)
    harness.env["CF_DRILL_EXPECTED_OBSERVABILITY_REVISION"] = expected
    result = harness.run()
    assert result.returncode != 0
    assert not any(entry["tool"] == "node-executor" for entry in harness.commands())


def test_revision_mismatch_never_invokes_node_executor(tmp_path: Path) -> None:
    harness = StatefulDrillHarness(tmp_path, obs_revision=11)
    result = harness.run()
    assert result.returncode != 0
    assert "expected 10; observed 11" in result.stderr
    assert not any(entry["tool"] == "node-executor" for entry in harness.commands())


@pytest.mark.parametrize("observed", ["10", 10.5])
def test_invalid_observed_revision_type_never_reaches_disruption(
    tmp_path: Path, observed: object,
) -> None:
    harness = StatefulDrillHarness(tmp_path, obs_revision=observed)
    result = harness.run()
    assert result.returncode != 0
    assert "positive integer-valued JSON number" in result.stderr
    assert not any(entry["tool"] == "node-executor" for entry in harness.commands())
    assert not any(
        event.get("event") in {"watchdog", "table"} for event in harness.events()
    )


def test_post_cleanup_observability_revision_drift_is_rejected(tmp_path: Path) -> None:
    harness = StatefulDrillHarness(tmp_path, obs_revision_after_cleanup=11)
    result = harness.run()
    assert result.returncode != 0
    assert "post-cleanup observability Helm revision mismatch" in result.stderr
    assert harness.current()["tables"] == [False, False]


@pytest.mark.parametrize(
    ("override", "message"),
    [
        ({"context": "production"}, "context must be"),
        ({"revision": "wrong"}, "revision is not approved"),
        ({"dirty": True}, "worktree must be clean"),
        ({"image_ok": False}, "immutable image is not approved"),
        ({"helm_revision": 3}, "Helm revision must be 2"),
        ({"pod_count": 3}, "exactly two Ready"),
        ({"same_node": True}, "distinct nodes"),
        ({"alerts": 1}, "alert is active"),
        ({"endpoint": 503}, "unhealthy endpoint"),
        ({"sandbox_fail": True}, "cannot resolve one exact sandbox"),
        ({"collision": True}, "owner table absence could not be proven"),
    ],
)
def test_actual_helper_preflights_fail_closed(
    tmp_path: Path, override: dict[str, object], message: str
) -> None:
    harness = StatefulDrillHarness(tmp_path, **override)
    result = harness.run()
    assert result.returncode != 0
    assert message in result.stderr
    assert not any(
        "add table inet" in entry["args"][1]
        for entry in harness.commands() if entry["tool"] == "node-executor"
    )


def test_actual_helper_rejects_confirmation_without_external_calls(tmp_path: Path) -> None:
    harness = StatefulDrillHarness(tmp_path)
    result = harness.run(confirmation="no")
    assert result.returncode != 0
    assert "confirmation must exactly equal" in result.stderr
    assert {entry["tool"] for entry in harness.commands()} <= {"date"}


def test_ambiguous_second_install_attempt_cleans_every_possible_node(tmp_path: Path) -> None:
    harness = StatefulDrillHarness(tmp_path, install_fail=1)
    result = harness.run()
    assert result.returncode != 0
    commands = harness.commands()
    cleanup_nodes = {
        entry["args"][0] for entry in commands
        if entry["tool"] == "node-executor" and "delete table inet" in entry["args"][1]
    }
    assert cleanup_nodes == {"node-1", "node-2"}
    assert harness.current()["tables"] == [False, False]


def test_sigterm_after_disruption_runs_exact_cleanup(tmp_path: Path) -> None:
    harness = StatefulDrillHarness(tmp_path, block_long_sleep=True)
    process = harness.start()
    harness.wait_for_disruption()
    os.killpg(process.pid, signal.SIGTERM)
    stdout, stderr = process.communicate(timeout=10)
    assert process.returncode == 143, (stdout, stderr)
    assert harness.current()["tables"] == [False, False]
    deletes = [entry["args"][1] for entry in harness.commands()
               if entry["tool"] == "node-executor" and "delete table inet" in entry["args"][1]]
    assert len(deletes) == 2
    assert all("list ruleset" in command and "flush" not in command for command in deletes)


def test_sigint_after_disruption_runs_exact_cleanup(tmp_path: Path) -> None:
    harness = StatefulDrillHarness(tmp_path, block_long_sleep=True)
    process = harness.start()
    harness.wait_for_disruption()
    os.killpg(process.pid, signal.SIGINT)
    stdout, stderr = process.communicate(timeout=10)
    assert process.returncode == 130, (stdout, stderr)
    assert harness.current()["tables"] == [False, False]
    deletes = [entry["args"][1] for entry in harness.commands()
               if entry["tool"] == "node-executor" and "delete table inet" in entry["args"][1]]
    assert len(deletes) == 2
    assert all("list ruleset" in command and "flush" not in command for command in deletes)


def test_external_timeout_after_disruption_runs_exact_cleanup(tmp_path: Path) -> None:
    timeout_bin = shutil.which("timeout")
    assert timeout_bin, "coreutils timeout is required to exercise a real external timeout"
    harness = StatefulDrillHarness(tmp_path, block_long_sleep=True)
    # The timeout wrapper -- not the test -- delivers the terminating signal when the bound expires.
    process = harness.start(wrapper=[timeout_bin, "--signal=TERM", "--kill-after=5", "8"])
    harness.wait_for_disruption()
    stdout, stderr = process.communicate(timeout=30)
    # coreutils timeout reports 124 when it fires the bound, distinct from the helper's 143 signal exit.
    assert process.returncode == 124, (stdout, stderr)
    assert process.poll() is not None, "helper process was left orphaned"
    assert harness.current()["tables"] == [False, False]
    transitions = [(event["node"], event["present"]) for event in harness.events() if event.get("event") == "table"]
    assert transitions == [("node-1", True), ("node-2", True), ("node-2", False), ("node-1", False)]
    deletes = [entry["args"][1] for entry in harness.commands()
               if entry["tool"] == "node-executor" and "delete table inet" in entry["args"][1]]
    assert len(deletes) == 2
    assert all("list ruleset" in command and "flush" not in command for command in deletes)


def test_actual_helper_rejects_accidental_restart(tmp_path: Path) -> None:
    harness = StatefulDrillHarness(tmp_path, restart=[1, 0])
    # The changed count becomes the baseline, so change it only after disruption.
    process = harness.start()
    deadline = time.monotonic() + 20
    changed = False
    while time.monotonic() < deadline:
        state = harness.current()
        if state["tables"] == [True, True]:
            state["restart"][0] = 2
            harness.state.write_text(json.dumps(state))
            changed = True
            break
        time.sleep(.01)
    stdout, stderr = process.communicate(timeout=5)
    assert changed, "helper never installed both disruption tables"
    assert process.returncode != 0, stdout
    assert "UID/restart set changed" in stderr
    assert harness.current()["tables"] == [False, False]


def test_secret_metadata_only_and_sentinel_never_leaks(tmp_path: Path) -> None:
    harness = StatefulDrillHarness(tmp_path)
    result = harness.run()
    material = result.stdout + result.stderr + harness.log.read_text()
    material += "".join(path.read_text() for path in harness.evidence.iterdir())
    assert "SENTINEL-SECRET-MUST-NOT-LEAK" not in material
    secret_calls = [entry for entry in harness.commands() if entry["tool"] == "kubectl" and "secret" in entry["args"]]
    assert len(secret_calls) == 2
    assert all(".metadata.uid" in " ".join(entry["args"]) and ".data" not in " ".join(entry["args"]) for entry in secret_calls)
    assert "NetworkPolicy" not in result.stdout


def test_evidence_is_sanitized_and_outside_repository_by_default() -> None:
    assert "${HOME}/operator-evidence/" in TEXT
    assert "secretMetadata" in TEXT
    assert "umask 077" in TEXT


def test_networkpolicy_only_approach_is_not_a_pass_contract() -> None:
    assert "NetworkPolicy" not in TEXT
    docs = (ROOT / "docs" / "cloudflare_tunnel.md").read_text()
    assert "implementation-defined" in docs
    assert "inconclusive dependency-loss test" in docs
    assert "A policy alone is not required or\n   expected to make `/ready` false" in docs


def test_node_execution_does_not_weaken_authentication() -> None:
    assert "StrictHostKeyChecking=no" not in TEXT
    assert "sshpass" not in TEXT
    assert "authorized_keys" not in TEXT
    assert "CF_DRILL_NODE_EXECUTOR" in TEXT


@pytest.mark.parametrize("arguments", [[], ["env=staging"]])
def test_recipe_defaults_to_staging_plan(
    arguments: list[str], ensure_just_available: Path,
) -> None:
    result = subprocess.run(
        ["just", "cf-tunnel-wan-dependency-loss-drill", *arguments],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=30,
    )

    assert result.returncode == 0, result.stderr
    assert "PLAN ONLY -- no cluster or node command was run." in result.stdout
    assert "--env=env=staging" not in result.stdout + result.stderr


def test_recipe_accepts_multiword_confirmation(
    ensure_just_available: Path,
) -> None:
    result = subprocess.run(
        [
            "just",
            "cf-tunnel-wan-dependency-loss-drill",
            "env=staging",
            "--manual-node-plan",
            "--execute",
            f"--confirm={CONFIRM}",
            "--evidence-dir=/tmp/evidence-marker",
            "--help",
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=30,
    )

    output = result.stdout + result.stderr
    assert result.returncode == 0, output
    assert "Usage:" in output
    assert "unknown argument" not in output.lower()
    assert "--env=env=staging" not in output


def test_recipe_forwards_helper_arguments_once_and_unchanged(
    tmp_path: Path, ensure_just_available: Path,
) -> None:
    arguments = [
        "env=staging",
        "--manual-node-plan",
        "--execute",
        f"--confirm={CONFIRM}",
        "--evidence-dir=/tmp/evidence-marker",
    ]
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    helper = scripts / "cloudflare_wan_dependency_loss_drill.sh"
    helper.write_text("#!/usr/bin/env bash\nprintf '%s\\n' \"$@\"\n")
    helper.chmod(0o755)
    justfile = shutil.copy(ROOT / "justfile", tmp_path / "justfile")
    result = subprocess.run(
        [
            "just",
            "--justfile",
            str(justfile),
            "cf-tunnel-wan-dependency-loss-drill",
            *arguments,
        ],
        cwd=tmp_path,
        text=True,
        capture_output=True,
        timeout=30,
    )

    assert result.returncode == 0, result.stderr
    forwarded = result.stdout.splitlines()
    assert forwarded == arguments
    assert forwarded.count(f"--confirm={CONFIRM}") == 1
    assert "--env=env=staging" not in forwarded
    recipe = (ROOT / "justfile").read_text()
    assert recipe.count('scripts/cloudflare_wan_dependency_loss_drill.sh "$@"') == 1
