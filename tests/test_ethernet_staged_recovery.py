"""Offline runtime/state-machine coverage, never a live K3s qualification."""

import copy
import importlib.util
import json
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "staged", ROOT / "scripts/ethernet_staged_recovery.py"
)
S = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(S)
Q = S.Q
SPEC = importlib.util.spec_from_file_location(
    "dual_fixture", ROOT / "tests/test_ethernet_dual_recovery.py"
)
D = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(D)
D.M = Q


class Backend(D.Backend):
    def __init__(self, e, c):
        super().__init__(e, c)
        self.mid = e["local_member_id"]
        self.boot = False
        self.events = []
        self.fail_stop = False

    def quiet(self):
        Q.require(not self.boot, "bootstrap still running")

    def start(self, fd):
        self.events.append("start")
        self.boot = True
        with self.c.mutex:
            self.c.active.add(self.mid)
        return 100 + int(self.mid)

    def alive(self):
        Q.require(self.boot, "bootstrap exited")

    def stop(self):
        self.events.append("stop")
        Q.require(not self.fail_stop, "bootstrap did not stop")
        with self.c.mutex:
            self.c.active.remove(self.mid)
        self.boot = False

    def retry_reads(self):
        pass

    def etcd(self, host, *args, input_text=None):
        with self.c.mutex:
            if host[2] not in self.c.active:
                raise S.ReadUnavailable("endpoint not yet available")
            self.c.quorum = len(self.c.active) >= 2
            return super().etcd(host, *args, input_text=input_text)

    def address_node(self, host, name, patch=None, status=False):
        with self.c.mutex:
            if host[2] not in self.c.active:
                raise S.ReadUnavailable("API unavailable")
            # API cannot become ready until this member's numeric URL is repaired.
            Q.require(
                self.c.members[host[2]]["peerURLs"][0] == f"https://{self.c.ips[host[2]]}:2380",
                "numeric URL gate",
            )
            node = self.c.nodes[name]
            if patch is not None:
                self.c.patches.append((self.mid, copy.deepcopy(patch)))
                for operation in patch[:-1]:
                    value = node
                    for key in operation["path"].strip("/").split("/"):
                        value = value[key.replace("~1", "/")]
                    Q.require(value == operation["value"], "patch conflict")
                if status:
                    node["status"]["addresses"] = copy.deepcopy(patch[-1]["value"])
                else:
                    node["metadata"]["annotations"]["k3s.io/internal-ip"] = patch[-1]["value"]
                node["metadata"]["resourceVersion"] = str(
                    int(node["metadata"]["resourceVersion"]) + 1
                )
            return copy.deepcopy(node)

    def normal_running(self):
        assert not self.boot and self.mid in self.c.active
        return {"MainPID": "200", "InvocationID": "normal"}

    def normal(self):
        with self.c.mutex:
            self.c.active.add(self.mid)
            self.c.nodes[f"pi{self.mid}"]["status"]["conditions"] = [
                {
                    "type": "Ready",
                    "status": "True",
                    "lastHeartbeatTime": datetime.now(timezone.utc).isoformat(),
                }
            ]


@pytest.fixture
def cluster(tmp_path, monkeypatch):
    # Synthetic state lives below pytest /tmp, not a root-owned installed state tree.
    monkeypatch.setattr(Q, "trusted_file", lambda _: None)
    c, old = D.recovery.__wrapped__(tmp_path)
    c.active, c.nodes, c.patches, c.mutex = set(), {}, [], threading.RLock()
    c.api = True
    result = []
    # Avoid real backoff in offline tests without changing Python's shared clock.
    monkeypatch.setattr(
        Q, "time", SimpleNamespace(sleep=lambda _: None, time=time.time, monotonic=time.monotonic)
    )
    for voter in old:
        b = Backend(voter.e, c)
        r = S.Recovery(voter.e, b, voter.path)
        mid = b.mid
        c.nodes[f"pi{mid}"] = {
            "metadata": {
                "name": f"pi{mid}",
                "uid": f"uid{mid}",
                "resourceVersion": "1",
                "annotations": {
                    "etcd.k3s.cattle.io/node-name": f"member{mid}",
                    "k3s.io/internal-ip": f"10.0.0.{mid}",
                },
            },
            "status": {
                "addresses": [
                    {"type": "InternalIP", "address": f"10.0.0.{mid}"},
                    {"type": "Hostname", "address": f"pi{mid}"},
                ],
                "conditions": [{"type": "Ready", "status": "False"}],
                "capacity": {"cpu": "4"},
            },
        }
        for member in r.e["members"]:
            c.markers[Q.KEY + "/enrollment/" + member["id"]] = r.marker(member)
        result.append(
            S.Coordinator(r, voter.path.parent / "staged.json", sleep=lambda _: time.sleep(0.001))
        )
    return c, result


@pytest.mark.parametrize("version", sorted(Q.VERSIONS))
def test_three_original_cold_starts_repair_before_serial_normal_handover(cluster, version):
    c, controllers = cluster
    for controller in controllers:
        controller.r.e["k3s_version"] = version
        for member in controller.r.e["members"]:
            c.markers[Q.KEY + "/enrollment/" + member["id"]] = controller.r.marker(member)

    def run(controller):
        assert controller.pre_start(99) == "normal-start-authorized"
        # No bootstrap child survives ExecStartPre.
        assert controller.b.events == ["start", "stop"] and not controller.b.boot
        assert c.owner == controller.record["token"]
        controller.b.normal()
        controller.post_start()
        return controller.record["phase"]

    with ThreadPoolExecutor(max_workers=3) as pool:
        assert list(pool.map(run, controllers)) == ["normal"] * 3
    assert c.owner is None and sorted(c.updates) == ["1", "2", "3"]
    assert len(c.patches) == 6
    for controller in controllers:
        mid = controller.b.mid
        node = c.nodes[f"pi{mid}"]
        assert node["metadata"]["uid"] == f"uid{mid}"
        assert node["status"]["capacity"] == {"cpu": "4"}
        assert node["status"]["addresses"][0]["address"] == c.ips[mid]
        assert c.members[mid]["peerURLs"] == Q.dual_urls(controller.r.local, c.ips[mid])


def test_unknown_handover_acquire_never_replayed(cluster):
    c, (controller, *_) = cluster
    c.active.update(("1", "2", "3"))
    controller.record = dict(
        member_id="1",
        cluster_id="100",
        ip="10.0.0.11",
        old_ip="10.0.0.1",
        **{"token": "owner"},
        phase="addresses-verified",
    )
    c.failure = "acquire"
    with pytest.raises(Q.Stop, match="unknown acquisition"):
        controller.handover()
    assert controller.record["phase"] == "handover-acquire-intent"
    writes = len(c.calls)
    with pytest.raises(Q.Stop, match="unfinished staged"):
        controller.pre_start(99)
    assert len(c.calls) == writes and c.owner == "owner"


def test_definitive_handover_contention_is_readable_wait(cluster):
    c, (controller, *_) = cluster
    c.active.update(("1", "2", "3"))
    c.owner = "other"
    controller.record = dict(**{"token": "owner"}, phase="addresses-verified")
    assert controller.handover() is False
    assert controller.record["phase"] == "waiting-for-handover" and c.owner == "other"


def test_membership_contention_waits_without_api_or_update(cluster):
    c, (controller, *_) = cluster
    c.active.update(("1", "2", "3"))
    c.owner = "other"
    Q.atomic_json(
        controller.r.path,
        dict(
            member_id="1",
            cluster_id="100",
            ip="10.0.0.11",
            **{"token": "mine"},
            phase="transport-pending",
            old_peer_urls=Q.dual_urls(controller.r.local, "10.0.0.1"),
            mutation_dispatched=False,
        ),
    )
    assert controller.membership() is False
    assert controller.r.previous()["phase"] == "waiting-for-lock"
    assert c.updates == [] and c.patches == []


def test_read_transport_refresh_never_clears_unknown_write():
    b = S.Backend({}, {})
    b.connections = {"peer": None}
    b.retry_reads()
    assert b.connections == {}
    b.write_failed = True
    with pytest.raises(Q.Stop, match="uncertain mutation"):
        b.retry_reads()


def test_runtime_start_uses_verified_service_environment(monkeypatch):
    b = S.Backend({}, {})
    monkeypatch.setenv("K3S_CLUSTER_RESET", "true")
    monkeypatch.setenv("NOTIFY_SOCKET", "/wrong")
    monkeypatch.setattr(b, "service_context", lambda: None)
    states = iter((False, True))
    monkeypatch.setattr(b, "process_executable", lambda *args, **kwargs: next(states))
    monkeypatch.setattr(S.time, "sleep", lambda _: None)
    monkeypatch.setattr(b, "quiet", lambda: None)
    monkeypatch.setattr(b, "config", lambda: None)
    monkeypatch.setattr(
        b,
        "command",
        lambda argv: (
            "ExecStart={ argv[]=/usr/local/bin/k3s server --server https://pi2.local:6443"
            " ; ignore_errors=no ; }"
            if argv[-1] == "--property=ExecStart"
            else "Environment=K3S_NODE_NAME=verified\nEnvironmentFiles="
        ),
    )
    calls = []
    monkeypatch.setattr(
        S.subprocess,
        "Popen",
        lambda argv, **kw: calls.append((argv, kw)) or SimpleNamespace(pid=9, poll=lambda: None),
    )
    assert b.start(7) == 9
    argv, kwargs = calls[0]
    assert argv[-1] == "--disable-agent=true"
    assert kwargs["pass_fds"] == (7,)
    assert kwargs["env"]["K3S_NODE_NAME"] == "verified"
    assert "K3S_CLUSTER_RESET" not in kwargs["env"] and "NOTIFY_SOCKET" not in kwargs["env"]


def test_stop_timeout_never_kills_or_authorizes_normal_start(monkeypatch):
    b = S.Backend({}, {})
    calls = []

    def wait(timeout):
        raise subprocess.TimeoutExpired("k3s", timeout)

    b.child = SimpleNamespace(
        poll=lambda: None, send_signal=lambda sig: calls.append(sig), wait=wait
    )
    with pytest.raises(Q.Stop, match="did not stop"):
        b.stop()
    assert calls == [S.signal.SIGTERM]


def test_hook_is_importable_with_isolated_python_and_no_ignored_poststart():
    result = subprocess.run(
        [
            __import__("sys").executable,
            "-I",
            str(ROOT / "scripts/ethernet_staged_recovery.py"),
            "hook",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    assert result.stdout == S.hook().decode()
    assert "ExecStartPost=-" not in result.stdout and "SendSIGKILL=no" in result.stdout


def completed(controller):
    """Seed only a fully verified prior incident, without live peers."""
    controller.record = dict(
        member_id="1",
        cluster_id="100",
        ip="10.0.0.11",
        old_ip="10.0.0.1",
        **{"token": "a" * 32},
        phase="normal",
    )
    Q.atomic_json(controller.path, controller.record)
    Q.atomic_json(
        controller.r.path, dict(member_id="1", cluster_id="100", ip="10.0.0.11", phase="complete")
    )
    Q.atomic_json(
        controller.r.address_journal,
        dict(
            member_id="1",
            cluster_id="100",
            node_uid="uid1",
            ip="10.0.0.11",
            old_ip="10.0.0.1",
            phase="verified",
        ),
    )


def test_completed_incident_allows_unchanged_cold_start_without_survivors(cluster):
    c, (controller, *_) = cluster
    completed(controller)
    assert not c.active
    assert controller.pre_start(99) == "unchanged"
    assert c.calls == [] and controller.b.events == []


def test_second_incident_preserves_previous_evidence_before_start(cluster, monkeypatch):
    c, (controller, *_) = cluster
    completed(controller)
    before = dict(
        staged=copy.deepcopy(controller.record),
        membership=json.loads(controller.r.path.read_text()),
        address=json.loads(controller.r.address_journal.read_text()),
    )
    c.ips["1"] = "10.0.0.21"

    def start(fd):
        archived = controller.path.parent / ("staged-archive-" + "a" * 32 + ".json")
        assert json.loads(archived.read_text()) == before
        raise Q.Stop("synthetic start failure")

    monkeypatch.setattr(controller.b, "start", start)
    with pytest.raises(Q.Stop, match="synthetic start failure"):
        controller.pre_start(99)
    assert controller.record["old_ip"] == "10.0.0.11"
    assert controller.record["phase"] == "bootstrap-start-intent"
    assert json.loads(controller.r.address_journal.read_text()) == before["address"]


def test_incomplete_incident_never_allows_second_change(cluster):
    c, (controller, *_) = cluster
    completed(controller)
    previous = json.loads(controller.r.path.read_text())
    previous["phase"] = "completion-pending"
    Q.atomic_json(controller.r.path, previous)
    c.ips["1"] = "10.0.0.21"
    with pytest.raises(Q.Stop, match="unfinished staged"):
        controller.pre_start(99)
    assert controller.b.events == []


def test_completion_service_uses_new_runtime_and_does_not_restart():
    service = S.completion_service().decode()
    assert str(S.RUNTIME) + " check-completion" in service
    assert " restart" not in service and str(Q.RUNTIME) not in service


@pytest.mark.parametrize(
    "route,write",
    [("/v3/maintenance/status", False), ("/v3/kv/txn", True), ("/v3/cluster/member/update", True)],
)
def test_adapter_failure_classification(monkeypatch, route, write):
    b = S.Backend({}, {})

    def fail(*args):
        raise Q.Stop("transport failure")

    monkeypatch.setattr(Q.Backend, "request", fail)
    with pytest.raises(Q.Stop):
        b.request("peer", route, {})
    assert b.write_failed is write


@pytest.mark.parametrize("patch", [None, [{"op": "test"}]])
def test_adapter_api_failure_classification(monkeypatch, patch):
    b = S.Backend({}, {})

    def fail(*args):
        raise Q.Stop("API failure")

    monkeypatch.setattr(Q.Backend, "address_node", fail)
    with pytest.raises(Q.Stop):
        b.address_node("peer", "node", patch)
    assert b.write_failed is (patch is not None)


def proc_tree(tmp_path, monkeypatch):
    proc = tmp_path / "proc"
    proc.mkdir()
    original = Path
    monkeypatch.setattr(
        S,
        "Path",
        lambda value: (
            tmp_path / str(value).lstrip("/") if str(value).startswith("/proc") else original(value)
        ),
    )
    return proc


@pytest.mark.parametrize("kind", ["quiet", "comm", "exe", "cmdline", "cgroup", "vanished"])
def test_quiescence_adapter_reads_process_evidence(tmp_path, monkeypatch, kind):
    monkeypatch.setattr(S.os, "getpid", lambda: 999999)
    proc = proc_tree(tmp_path, monkeypatch)
    entry = proc / "10"
    entry.mkdir()
    (proc / "non-numeric").mkdir()
    if kind != "vanished":
        (entry / "comm").write_text("containerd-shim" if kind == "comm" else "benign")
        (entry / "cmdline").write_bytes(b"/usr/bin/kubelet\0" if kind == "cmdline" else b"benign\0")
        (entry / "cgroup").write_text("0::/kubepods.slice" if kind == "cgroup" else "0::/other")
        (entry / "exe").symlink_to("/usr/bin/etcd" if kind == "exe" else "/usr/bin/benign")
    b = S.Backend({}, {})
    monkeypatch.setattr(b, "command", lambda _: "MainPID=0")
    if kind in ("quiet", "vanished"):
        b.quiet()
    else:
        with pytest.raises(Q.Stop, match="residual"):
            b.quiet()


def test_service_context_and_normal_process_identity(tmp_path, monkeypatch):
    proc = proc_tree(tmp_path, monkeypatch)
    (proc / "self").mkdir()
    (proc / "self/cgroup").write_text("0::/system.slice/k3s.service\n")
    (proc / "10").mkdir()
    executable = "/var/lib/rancher/k3s/data/" + "a" * 64 + "/bin/k3s"
    (proc / "10/exe").symlink_to(executable)
    (proc / "10/cmdline").write_bytes(b"k3s\0server\0")
    monkeypatch.setenv("INVOCATION_ID", "a" * 32)
    b = S.Backend({}, {"server_executable": executable})
    monkeypatch.setattr(
        b,
        "command",
        lambda _: f"ControlPID={S.os.getpid()}\n"
        "ControlGroup=/system.slice/k3s.service\nInvocationID=" + "a" * 32,
    )
    b.service_context()
    monkeypatch.setattr(
        b,
        "command",
        lambda _: "ActiveState=activating\nSubState=start-post\n"
        "MainPID=10\nInvocationID=" + "a" * 32 + "\nNRestarts=0",
    )
    assert b.normal_running()["MainPID"] == "10"
    (proc / "10/cmdline").write_bytes(b"k3s\0server\0--disable-agent=true")
    with pytest.raises(Q.Stop, match="agentless"):
        b.normal_running()


def test_child_resolver_mount_is_checked(tmp_path, monkeypatch):
    b = S.Backend({"resolver_view": {}}, {})
    b.child = SimpleNamespace(pid=42, poll=lambda: None)
    (tmp_path / "upstream-resolv.conf").write_text("original")
    calls = []
    dns = SimpleNamespace(
        STATE=tmp_path,
        resolver_text=lambda text: (text, "expected"),
        check_process_view=lambda *args: calls.append(args),
    )
    monkeypatch.setattr(b, "process_executable", lambda pid: True)
    monkeypatch.setattr(Q.Backend, "config", lambda _: None)
    monkeypatch.setattr(Q, "sibling", lambda _: dns)
    monkeypatch.setattr(b, "command", lambda _: "MainPID=17")
    b.config()
    assert calls == [(b.e, "42", "17", "expected")]


def test_staged_loaded_hook_and_pins(tmp_path, monkeypatch):
    path = tmp_path / "hook"
    path.write_bytes(S.hook())
    runtime = tmp_path / "runtime"
    runtime.write_bytes(b"original")
    monkeypatch.setattr(Q, "HOOK", path)
    monkeypatch.setattr(Q, "trusted_file", lambda _: None)
    b = S.Backend({}, {"runtime_sha256": {str(runtime): Q.digest(runtime.read_bytes())}})
    text = (
        "NeedDaemonReload=no\nDropInPaths=" + str(path) + "\nTimeoutStartUSec=15min\n"
        "TimeoutStopUSec=1min 15s\nSendSIGKILL=no\n"
        f"ExecStartPre={{ argv[]=/usr/bin/python3 -I {S.RUNTIME} pre-start"
        " ; ignore_errors=no ; }\n"
        f"ExecStartPost={{ argv[]=/usr/bin/python3 -I {S.RUNTIME} post-start"
        " ; ignore_errors=no ; }"
    )
    monkeypatch.setattr(b, "command", lambda _: text)
    b.recovery_hook_loaded()
    runtime.write_bytes(b"changed")
    with pytest.raises(Q.Stop, match="runtime identity"):
        b.recovery_hook_loaded()


def test_environment_files_are_parsed_without_ambient_values(tmp_path, monkeypatch):
    envfile = tmp_path / "environment"
    envfile.write_text('# comment\nK3S_NODE_NAME="from file"\n\n')
    b = S.Backend({}, {})
    monkeypatch.setattr(
        b,
        "command",
        lambda _: "Environment=K3S_NODE_NAME=first\nEnvironmentFiles="
        + str(envfile)
        + " (ignore_errors=yes)",
    )
    assert b.server_environment()["K3S_NODE_NAME"] == "from file"


def test_clean_stop_observes_child_exit_then_quiescence(monkeypatch):
    b = S.Backend({}, {})
    calls = []
    b.child = SimpleNamespace(
        poll=lambda: None,
        returncode=0,
        send_signal=lambda sig: calls.append(sig),
        wait=lambda timeout: calls.append(timeout),
    )
    monkeypatch.setattr(b, "quiet", lambda: calls.append("quiet"))
    b.stop()
    assert calls == [S.signal.SIGTERM, 60, "quiet"]


def test_explicit_opt_in_pins_all_runtime_dependencies(cluster, tmp_path, monkeypatch):
    _, (controller, *_) = cluster
    e = copy.deepcopy(controller.r.e)
    e["resolver_view"] = {}
    enrollment, opt_path = tmp_path / "enrollment", tmp_path / "opt"
    enrollment.write_text(json.dumps(e))
    monkeypatch.setattr(Q, "ENROLLMENT", enrollment)
    monkeypatch.setattr(S, "OPT_IN", opt_path)
    monkeypatch.setattr(Q, "trusted_file", lambda _: None)
    executable = "/var/lib/rancher/k3s/data/" + "a" * 64 + "/bin/k3s"
    paths = [
        executable,
        S.RUNTIME,
        Q.RUNTIME,
        "/usr/local/bin/k3s",
        Q.TRANSPORT,
        Q.DESCRIPTOR,
        Q.WAL_RUNTIME,
        S.RUNTIME.with_name("ethernet_mdns_resolver.py"),
    ]
    opt = dict(
        schema_version=1,
        cold_original_database_bootstrap=True,
        server_executable=executable,
        enrollment_sha256=Q.digest(enrollment.read_bytes()),
        runtime_sha256={str(path): "a" * 64 for path in paths},
    )
    opt_path.write_text(json.dumps(opt))
    assert S.load_opt_in() == (e, opt)
    del opt["runtime_sha256"][str(Q.DESCRIPTOR)]
    opt_path.write_text(json.dumps(opt))
    with pytest.raises(Q.Stop, match="runtimes must be pinned"):
        S.load_opt_in()


@pytest.mark.parametrize("phase", ["hook", "completion-service"])
def test_cli_artifact_outputs(monkeypatch, capsys, phase):
    monkeypatch.setattr(__import__("sys"), "argv", ["staged", phase])
    assert S.main() == 0
    assert "Managed by ethernet_staged_recovery.py" in capsys.readouterr().out


@pytest.mark.parametrize(
    "phase", ["pre-start", "post-start", "check-completion", "check-completion-normal"]
)
def test_cli_dispatch_without_host_execution(cluster, monkeypatch, phase):
    c, (controller, *_) = cluster
    b, r = controller.b, controller.r
    c.ips["1"] = r.e["local_ipv4"]
    b.child = None
    if phase == "check-completion-normal":
        completed(controller)
        c.ips["1"] = "10.0.0.11"
        phase = "check-completion"
    calls = []
    monkeypatch.setattr(S.os, "geteuid", lambda: 0)
    monkeypatch.setattr(S, "STATE", r.path.parent)
    monkeypatch.setattr(S, "load_opt_in", lambda: (r.e, {}))
    monkeypatch.setattr(Q, "private_state", lambda _: None)
    monkeypatch.setattr(S, "Backend", lambda *args: b)
    monkeypatch.setattr(S, "Recovery", lambda *args: r)
    monkeypatch.setattr(b, "service_context", lambda: calls.append("context"), raising=False)
    monkeypatch.setattr(b, "close", lambda: calls.append("close"), raising=False)
    monkeypatch.setattr(S.signal, "signal", lambda *args: None)
    monkeypatch.setattr(__import__("sys"), "argv", ["staged", phase])
    assert S.main() == 0
    assert calls[-1] == "close"


@pytest.mark.parametrize("cleanup_ok", [True, False])
@pytest.mark.parametrize("failure", ["signal", "shape"])
def test_cli_signal_cleanup_preserves_failure_phase(cluster, monkeypatch, cleanup_ok, failure):
    _, (controller, *_) = cluster
    b, r = controller.b, controller.r
    controller.record = dict(
        phase="bootstrap-running", member_id="1", cluster_id="100", **{"token": "a" * 32}
    )
    b.child = SimpleNamespace(poll=lambda: None)
    calls = []
    monkeypatch.setattr(S.os, "geteuid", lambda: 0)
    monkeypatch.setattr(S, "STATE", r.path.parent)
    monkeypatch.setattr(S, "load_opt_in", lambda: (r.e, {}))
    monkeypatch.setattr(Q, "private_state", lambda _: None)
    monkeypatch.setattr(S, "Backend", lambda *args: b)
    monkeypatch.setattr(S, "Recovery", lambda *args: r)
    monkeypatch.setattr(S, "Coordinator", lambda *args: controller)
    monkeypatch.setattr(b, "service_context", lambda: None, raising=False)
    monkeypatch.setattr(b, "close", lambda: calls.append("close"), raising=False)

    def stop():
        calls.append("stop")
        if not cleanup_ok:
            raise Q.Stop("stop unconfirmed")

    monkeypatch.setattr(b, "stop", stop)
    handlers = {}
    monkeypatch.setattr(S.signal, "signal", lambda sig, handler: handlers.update({sig: handler}))

    def fail(fd):
        if failure == "shape":
            raise AttributeError("malformed readiness condition")
        handlers[S.signal.SIGTERM](15, None)

    monkeypatch.setattr(controller, "pre_start", fail)
    monkeypatch.setattr(__import__("sys"), "argv", ["staged", "pre-start"])
    assert S.main() == 2
    assert controller.record["phase"] == (
        "cleanup-stopped" if cleanup_ok else "cleanup-stop-intent"
    )
    assert controller.record["failed_phase"] == "bootstrap-running"
    assert calls == ["stop", "close"]


def test_migration_interlock_is_read_only_and_fail_closed(tmp_path, monkeypatch):
    monkeypatch.setattr(S, "STATE", tmp_path)
    calls = []
    monkeypatch.setattr(Q, "migration_start_guard", lambda *args: calls.append(args), raising=False)
    backend = object()
    S.migration_guard(backend)
    assert calls == [(Q.ENROLLMENT, backend, tmp_path, "watch")]
    monkeypatch.delattr(Q, "migration_start_guard")
    (tmp_path / "migration-intent.json").write_text("{}")
    with pytest.raises(Q.Stop, match="migration state"):
        S.migration_guard(backend)


def test_loaded_journal_and_conflicting_archive_are_guarded(cluster):
    c, (controller, *_) = cluster
    completed(controller)
    restored = S.Coordinator(controller.r, controller.path)
    assert restored.record == controller.record
    c.ips["1"] = "10.0.0.21"
    archive = controller.path.parent / ("staged-archive-" + "a" * 32 + ".json")
    archive.write_text("{}")
    with pytest.raises(Q.Stop, match="archive conflicts"):
        restored.pre_start(99)


@pytest.mark.parametrize("phase", ["transport-pending", "completion-pending"])
def test_membership_read_unavailability_is_pollable(cluster, phase):
    _, (controller, *_) = cluster
    Q.atomic_json(
        controller.r.path, dict(member_id="1", cluster_id="100", phase=phase, ip="10.0.0.11")
    )
    assert controller.membership() is False
    controller.record = dict(ip="10.0.0.11", old_ip="10.0.0.1")
    assert controller.api() is False


def test_poststart_waits_for_fresh_readiness_without_releasing_early(cluster, monkeypatch):
    _, (controller, *_) = cluster
    controller.record = dict(phase="normal-start-intent", **{"token": "owner"})
    attempts, mutations = [], []

    def proof():
        attempts.append(1)
        if len(attempts) == 1:
            raise S.ReadinessPending("heartbeat not fresh")

    def release(token, release=False):
        assert len(attempts) == 2 and release
        mutations.append(token)
        return {"succeeded": True}

    def pending():
        pytest.fail("full-cluster completion must run only in the watcher")

    monkeypatch.setattr(controller, "normal_proof", proof)
    monkeypatch.setattr(controller.r, "owned", lambda _: None)
    monkeypatch.setattr(controller.r, "transaction", release)
    monkeypatch.setattr(controller.r, "post_start", pending)
    assert controller.post_start() == "completion-pending"
    assert mutations == ["owner"] and controller.record["phase"] == "normal"


def test_main_guard_is_executed_without_host_access(monkeypatch):
    import runpy

    monkeypatch.setattr(__import__("sys"), "argv", ["staged", "hook"])
    with pytest.raises(SystemExit) as exc:
        runpy.run_path(str(ROOT / "scripts/ethernet_staged_recovery.py"), run_name="__main__")
    assert exc.value.code == 0


def test_dangling_migration_intent_cannot_bypass_fence(tmp_path, monkeypatch):
    monkeypatch.setattr(S, "STATE", tmp_path)
    monkeypatch.delattr(Q, "migration_start_guard", raising=False)
    (tmp_path / "migration-intent.json").symlink_to(tmp_path / "missing")
    with pytest.raises(Q.Stop, match="migration state"):
        S.migration_guard(object())


def test_extracted_process_pin_distinguishes_initial_wrapper(tmp_path, monkeypatch):
    proc = proc_tree(tmp_path, monkeypatch)
    (proc / "10").mkdir()
    (proc / "10/exe").symlink_to("/usr/local/bin/k3s")
    b = S.Backend({}, {"server_executable": "/var/lib/rancher/k3s/data/" + "a" * 64 + "/bin/k3s"})
    assert b.process_executable(10, allow_wrapper=True) is False
    with pytest.raises(Q.Stop, match="internal executable"):
        b.process_executable(10)


@pytest.mark.parametrize(
    "failure",
    [
        "connection",
        "wrapped",
        "timeout",
        "unavailable",
        "identity",
        "tls",
        "http",
        "json",
        "unknown-write",
    ],
)
def test_node_get_retry_is_narrow_and_never_replays_patch(monkeypatch, failure):
    import ssl

    b = S.Backend({}, {})
    calls, sleeps = [], []
    monkeypatch.setattr(S.time, "sleep", sleeps.append)

    def request(self, host, node, patch=None, status=False):
        calls.append(patch)
        if failure == "identity":
            raise Q.Stop("identity differs")
        if failure == "tls":
            raise ssl.SSLCertVerificationError("wrong CA")
        if failure == "http":
            raise Q.Stop("Node API HTTP 403; no retry")
        if failure == "unavailable":
            raise Q.Stop("Node API HTTP 503; no retry")
        if failure == "json":
            raise Q.Stop("response invalid") from ValueError("bad JSON")
        if failure == "wrapped":
            raise Q.Stop("transport") from ConnectionResetError()
        if failure == "timeout":
            raise TimeoutError()
        raise ConnectionRefusedError()

    monkeypatch.setattr(Q.Backend, "address_node", request)
    patch = [{"op": "test"}] if failure == "unknown-write" else None
    with pytest.raises((Q.Stop, OSError)):
        b.address_node("peer", "node", patch)
    retry = failure in ("connection", "wrapped", "timeout", "unavailable")
    assert len(calls) == (3 if retry else 1)
    assert sleeps == ([2, 2] if retry else [])
    assert b.write_failed is (patch is not None)
    if patch:
        calls.clear()
        with pytest.raises(ConnectionRefusedError):
            b.address_node("peer", "node")
        assert calls == [None]


def test_survivor_preflight_and_readbacks_allow_delayed_reads(cluster, monkeypatch):
    c, coordinators = cluster
    delayed = []
    original = Backend.address_node
    counters = {}

    def read(self, host, name, patch=None, status=False):
        key = (self.mid, host)
        counters[key] = counters.get(key, 0) + 1
        if patch is None and host[2] != self.mid and counters[key] == 1:
            delayed.append(key)
            raise S.ReadUnavailable("survivor API warming up")
        return original(self, host, name, patch, status)

    monkeypatch.setattr(Backend, "address_node", read)

    def run(coordinator):
        assert coordinator.pre_start(99) == "normal-start-authorized"
        coordinator.b.normal()
        coordinator.post_start()

    with ThreadPoolExecutor(max_workers=3) as pool:
        list(pool.map(run, coordinators))
    assert len(delayed) == 6
    assert len(c.patches) == 6
    assert all(x.record["phase"] == "normal" for x in coordinators)


@pytest.mark.parametrize("failure", ["delay", "identity", "unexpected", "never", "intent"])
def test_survivor_readback_retries_only_known_old_address(cluster, monkeypatch, failure):
    c, (coordinator, *_) = cluster
    r, b = coordinator.r, coordinator.b
    ip, old = c.ips["1"], r.e["local_ipv4"]
    Q.atomic_json(r.address_journal, dict(phase="status-confirmed", old_ip=old))
    if failure == "intent":
        Q.atomic_json(r.address_journal, dict(phase="status-intent", old_ip=old))
    base = copy.deepcopy(c.nodes[r.local["hostname"].removesuffix(".local")])
    base["metadata"]["annotations"]["k3s.io/internal-ip"] = ip
    base["status"]["addresses"] = [{"type": "InternalIP", "address": ip}]
    calls, sleeps = [], []

    def read(host, name):
        calls.append(host)
        node = copy.deepcopy(base)
        if failure == "identity":
            node["metadata"]["uid"] = "wrong"
        elif failure == "unexpected":
            node["metadata"]["annotations"]["k3s.io/internal-ip"] = "10.1.1.1"
        elif failure == "never" or (failure == "delay" and len(calls) == 1):
            node["status"]["addresses"][0]["address"] = old
        return node

    monkeypatch.setattr(b, "address_node", read)
    monkeypatch.setattr(S.time, "sleep", sleeps.append)
    if failure == "delay":
        r.address_readback(ip)
        assert len(calls) == 3 and sleeps == [2]
    else:
        with pytest.raises(Q.Stop):
            r.address_readback(ip)
        assert len(calls) == (3 if failure == "never" else 0 if failure == "intent" else 1)


def test_api_final_local_get_transient_is_pollable(cluster, monkeypatch):
    c, (coordinator, *_) = cluster
    r = coordinator.r
    coordinator.record = dict(ip=c.ips["1"], old_ip=r.e["local_ipv4"])
    node = c.nodes["pi1"]
    monkeypatch.setattr(coordinator.b, "address_node", lambda *args: copy.deepcopy(node))

    def transient(*args):
        raise S.ReadUnavailable("last local GET delayed")

    monkeypatch.setattr(r, "address_proof", transient)
    assert coordinator.api() is False


def test_native_local_convergence_with_lagging_survivor_needs_no_prior_journal(
    cluster, monkeypatch
):
    c, (coordinator, *_) = cluster
    r, b = coordinator.r, coordinator.b
    ip, old = c.ips["1"], r.e["local_ipv4"]
    node = copy.deepcopy(c.nodes["pi1"])
    node["metadata"]["annotations"]["k3s.io/internal-ip"] = ip
    node["status"]["addresses"][0]["address"] = ip
    assert not r.address_journal.exists()
    monkeypatch.setattr(r, "address_proof", lambda *args: (r.host, copy.deepcopy(node)))
    calls = []

    def read(host, name):
        calls.append(host)
        fresh = copy.deepcopy(node)
        if len(calls) == 1:
            fresh["status"]["addresses"][0]["address"] = old
        return fresh

    monkeypatch.setattr(b, "address_node", read)
    monkeypatch.setattr(S.time, "sleep", lambda _: None)
    r.prepare_node_address(ip, old)
    assert len(calls) == 3
    assert not hasattr(r, "readback_baseline")
    assert json.loads(r.address_journal.read_text())["phase"] == "verified"
    assert c.patches == []


@pytest.mark.parametrize("journal", ["staged", "node"])
def test_dangling_recovery_journal_symlinks_refuse(cluster, journal):
    _, (coordinator, *_) = cluster
    if journal == "staged":
        coordinator.path.symlink_to(coordinator.path.parent / "missing")
        with pytest.raises(Q.Stop, match="symlink staged"):
            S.Coordinator(coordinator.r, coordinator.path)
    else:
        coordinator.r.address_journal.symlink_to(coordinator.path.parent / "missing")
        with pytest.raises(Q.Stop, match="symlink Node"):
            coordinator.r.address_readback("10.0.0.11")


def test_staged_native_session_retains_typed_transport(monkeypatch):
    b = S.Backend({"cluster_id": "100", "etcd_tls": {"ca": "pinned"}}, {})
    calls, modules = [], []
    transport = SimpleNamespace(Session=lambda *args: calls.append(args) or object())
    monkeypatch.setattr(Q, "sibling", lambda name: modules.append(name) or transport)
    monkeypatch.setattr(b, "connect_peer", lambda address: "bound-" + address)
    for _ in range(2):
        b.open_session("pi1.local", "10.0.0.11", {"id": "1"})
    assert modules == ["ethernet_etcd_grpc"]
    assert calls[0][:4] == ("pi1.local", "100", "1", {"ca": "pinned"})
    assert calls[0][4]() == "bound-10.0.0.11"


@pytest.mark.parametrize(
    "route,read",
    [
        ("/v3/maintenance/status", True),
        ("/v3/cluster/member/list", True),
        ("/v3/kv/range", True),
        ("/v3/kv/txn", False),
        ("/v3/cluster/member/update", False),
        ("unknown", False),
    ],
)
@pytest.mark.parametrize("failure", ["availability", "identity", "tls", "latched"])
def test_etcd_retry_type_is_read_only_and_cannot_clear_write_latch(
    monkeypatch, route, read, failure
):
    transport = Q.sibling("ethernet_etcd_grpc")
    b = S.Backend({}, {})
    b.transport = transport
    b.write_failed = failure == "latched"
    cause = (
        transport.Unavailable("known connection loss")
        if failure in ("availability", "latched")
        else transport.TransportError(failure)
    )
    calls = []

    def fail(*args):
        calls.append(args)
        raise Q.Stop("authenticated gRPC failed") from cause

    monkeypatch.setattr(Q.Backend, "request", fail)
    with pytest.raises(Q.Stop) as caught:
        b.request("pi1.local", route, {})
    assert isinstance(caught.value, S.ReadUnavailable) is (read and failure == "availability")
    assert len(calls) == 1  # Classification never replays the operation.
    if failure == "latched" or route in ("/v3/kv/txn", "/v3/cluster/member/update"):
        assert b.write_failed
        with pytest.raises(Q.Stop, match="uncertain mutation"):
            b.retry_reads()


def test_peer_handover_etcd_gap_during_api_preflight_does_not_latch(cluster, monkeypatch):
    c, coordinators = cluster
    stopped, observed = threading.Event(), threading.Event()
    original_stop, original_etcd = Backend.stop, Backend.etcd
    original_proof = S.Recovery.address_proof
    delayed = []

    def stop(self):
        original_stop(self)
        if self.mid == "1":
            stopped.set()
            assert observed.wait(5), "other voter never reached the paused endpoint"

    def etcd(self, host, *args, **kwargs):
        with self.c.mutex:
            if host[2] not in self.c.active:
                raise S.ReadUnavailable("known read-only connection loss")
            return original_etcd(self, host, *args, **kwargs)

    def proof(self, ip, old):
        if self.local["id"] == "2" and not delayed:
            delayed.append(True)
            assert stopped.wait(5), "first handover never stopped its child"
            try:
                return original_proof(self, ip, old)
            except S.ReadUnavailable:
                observed.set()
                raise
        return original_proof(self, ip, old)

    monkeypatch.setattr(Backend, "stop", stop)
    monkeypatch.setattr(Backend, "etcd", etcd)
    monkeypatch.setattr(S.Recovery, "address_proof", proof)

    def run(coordinator):
        assert coordinator.pre_start(99) == "normal-start-authorized"
        coordinator.b.normal()
        coordinator.post_start()

    with ThreadPoolExecutor(max_workers=3) as pool:
        list(pool.map(run, coordinators))
    assert observed.is_set()
    assert c.owner is None and sorted(c.updates) == ["1", "2", "3"]
    assert len(c.patches) == 6
    assert all(x.record["phase"] == "normal" for x in coordinators)


@pytest.mark.parametrize("failure", ["unavailable", "identity", "malformed"])
def test_api_etcd_poll_is_bounded_and_does_not_swallow_proof_failures(
    cluster, monkeypatch, failure
):
    c, (coordinator, *_) = cluster
    c.active.update(("1", "2", "3"))
    for member in c.members.values():
        member["peerURLs"][0] = f"https://{c.ips[str(member['ID'])]}:2380"
    coordinator.b.boot = True
    coordinator.record = dict(ip="10.0.0.11", old_ip="10.0.0.1")
    attempts, reconnects = [], []

    def proof(*args):
        attempts.append(True)
        if failure == "unavailable":
            raise S.ReadUnavailable("known read-only failure")
        raise Q.Stop(failure)

    monkeypatch.setattr(coordinator.r, "address_proof", proof)
    monkeypatch.setattr(coordinator.b, "retry_reads", lambda: reconnects.append(True))
    coordinator.clock = lambda: len(attempts) * 2
    coordinator.sleep = lambda _: None
    with pytest.raises(Q.Stop, match="deadline" if failure == "unavailable" else failure):
        coordinator.wait(coordinator.api, 3)
    assert len(attempts) == (2 if failure == "unavailable" else 1)
    assert len(reconnects) == (2 if failure == "unavailable" else 0)
    assert c.patches == [] and c.updates == []


@pytest.mark.parametrize("kind", ["absent", "valid", "dangling", "live", "directory", "fifo"])
@pytest.mark.parametrize("baseline", [True, False])
def test_prestart_admits_only_regular_address_evidence(cluster, monkeypatch, kind, baseline):
    import os

    c, (controller, *_) = cluster
    path = controller.r.address_journal
    ip = controller.r.e["local_ipv4"]
    if baseline:
        c.ips["1"] = ip
    target = path.parent / "target.json"
    target.write_text("unchanged target")
    if kind == "valid":
        Q.atomic_json(
            path,
            dict(
                phase="verified",
                ip=ip,
                old_ip=ip,
                member_id=controller.r.local["id"],
                cluster_id=controller.r.e["cluster_id"],
                node_uid=controller.r.local["node_uid"],
            ),
        )
    elif kind in ("dangling", "live"):
        path.symlink_to(target if kind == "live" else path.parent / "missing")
    elif kind == "directory":
        path.mkdir()
    elif kind == "fifo":
        os.mkfifo(path)
    before = path.lstat() if kind != "absent" else None
    reads = []
    monkeypatch.setattr(Q, "trusted_file", lambda p: reads.append(p))

    def stop_before_start():
        raise Q.Stop("reached cold admission")

    monkeypatch.setattr(controller.b, "quiet", stop_before_start)
    if kind in ("absent", "valid"):
        if baseline:
            assert controller.pre_start(99) == "unchanged"
        else:
            with pytest.raises(Q.Stop, match="reached cold admission"):
                controller.pre_start(99)
        assert reads == ([path] if kind == "valid" else [])
    else:
        with pytest.raises(Q.Stop, match="nonregular state evidence"):
            controller.pre_start(99)
        assert reads == []
        assert path.lstat() == before
    assert target.read_text() == "unchanged target"
    assert controller.b.events == [] and c.patches == [] and c.updates == []
    assert not controller.path.exists()


@pytest.mark.parametrize("kind", ["absent", "valid", "dangling", "live", "directory", "fifo"])
def test_prestart_archive_refuses_nonregular_evidence_without_replacement(
    cluster, monkeypatch, kind
):
    import os

    c, (controller, *_) = cluster
    completed(controller)
    c.ips["1"] = "10.0.0.21"
    archive = controller.path.parent / ("staged-archive-" + controller.record["token"] + ".json")
    bundle = dict(
        staged=controller.record,
        membership=controller.r.previous(),
        address=json.loads(controller.r.address_journal.read_text()),
    )
    target = archive.parent / "archive-target"
    target.write_text(json.dumps(bundle))
    if kind == "valid":
        Q.atomic_json(archive, bundle)
    elif kind in ("dangling", "live"):
        archive.symlink_to(target if kind == "live" else archive.parent / "missing")
    elif kind == "directory":
        archive.mkdir()
    elif kind == "fifo":
        os.mkfifo(archive)
    before = archive.lstat() if kind != "absent" else None

    def stop_before_start():
        raise Q.Stop("reached cold admission")

    monkeypatch.setattr(controller.b, "quiet", stop_before_start)
    with pytest.raises(
        Q.Stop, match="reached cold admission" if kind in ("absent", "valid") else "nonregular"
    ):
        controller.pre_start(99)
    if kind in ("absent", "valid"):
        assert json.loads(archive.read_text()) == bundle
    else:
        assert archive.lstat() == before
    assert json.loads(target.read_text()) == bundle
    assert controller.b.events == [] and c.patches == [] and c.updates == []
    assert json.loads(controller.path.read_text())["phase"] == "normal"


def test_regular_state_evidence_propagates_trust_refusal(tmp_path, monkeypatch):
    path = tmp_path / "evidence"
    path.write_text("{}")

    def refuse(candidate):
        assert candidate == path
        raise Q.Stop("untrusted owner")

    monkeypatch.setattr(Q, "trusted_file", refuse)
    with pytest.raises(Q.Stop, match="untrusted owner"):
        S.state_evidence(path)
    assert path.read_text() == "{}"


@pytest.mark.parametrize("kind", ["dangling", "live", "directory", "fifo"])
@pytest.mark.parametrize("baseline", [True, False])
def test_prestart_rejects_nonregular_membership_evidence_before_read_or_start(
    cluster, monkeypatch, kind, baseline
):
    import os

    c, (controller, *_) = cluster
    path = controller.r.path
    if baseline:
        c.ips["1"] = controller.r.e["local_ipv4"]
    target = path.parent / "membership-target"
    target.write_text("preserve original evidence")
    if kind in ("dangling", "live"):
        path.symlink_to(target if kind == "live" else path.parent / "missing")
    elif kind == "directory":
        path.mkdir()
    else:
        os.mkfifo(path)
    before = path.lstat()

    def unexpected_read():
        pytest.fail("membership evidence must be admitted before previous()")

    monkeypatch.setattr(controller.r, "previous", unexpected_read)
    with pytest.raises(Q.Stop, match="nonregular state evidence"):
        controller.pre_start(99)
    assert path.lstat() == before
    assert target.read_text() == "preserve original evidence"
    assert not controller.path.exists()
    assert controller.b.events == [] and c.patches == [] and c.updates == []


@pytest.mark.parametrize("phase", ["transport-pending", "completion-pending"])
@pytest.mark.parametrize("failure", ["availability", "identity", "address", "duplicate", "schema"])
def test_membership_polls_only_typed_availability(cluster, monkeypatch, phase, failure):
    _, (controller, *_) = cluster
    Q.atomic_json(controller.r.path, dict(member_id="1", cluster_id="100", phase=phase))
    calls, retries = [], []

    def proof(*args, **kwargs):
        calls.append(True)
        if failure == "availability":
            raise S.ReadUnavailable("read transport unavailable")
        raise Q.Stop(failure)

    monkeypatch.setattr(controller.r, "prove_transport", proof)
    monkeypatch.setattr(controller.r, "prove_etcd", proof)
    monkeypatch.setattr(controller.b, "retry_reads", lambda: retries.append(True))
    if failure == "availability":
        assert controller.membership() is False
        assert retries == [True]
    else:
        with pytest.raises(Q.Stop, match=failure):
            controller.membership()
        assert retries == []
    assert calls == [True]


@pytest.mark.parametrize("failure", ["availability", "readiness", "identity", "address", "schema"])
def test_normal_start_retries_only_explicit_pending_conditions(cluster, monkeypatch, failure):
    _, (controller, *_) = cluster
    controller.record = dict(phase="normal-start-intent", **{"token": "owner"})
    calls, retries, writes, sleeps = [], [], [], []

    def proof():
        calls.append(True)
        if failure == "availability":
            raise S.ReadUnavailable("read unavailable")
        if failure == "readiness":
            raise S.ReadinessPending("heartbeat pending")
        raise Q.Stop(failure)

    monkeypatch.setattr(controller, "normal_proof", proof)
    monkeypatch.setattr(controller.b, "retry_reads", lambda: retries.append(True))
    monkeypatch.setattr(controller.r, "transaction", lambda *args, **kwargs: writes.append(True))
    controller.clock = lambda: len(calls) * 121
    controller.sleep = sleeps.append
    with pytest.raises(
        Q.Stop, match="timed out" if failure in ("availability", "readiness") else failure
    ):
        controller.post_start()
    assert calls == [True] and writes == [] and sleeps == []
    assert retries == ([True] if failure == "availability" else [])
    assert controller.record["phase"] == "normal-start-intent"


@pytest.mark.parametrize(
    "status,mutation,latched",
    [
        (503, False, False),
        (503, True, False),
        (403, False, False),
        (403, True, False),
        (500, False, False),
        (500, True, False),
        (502, False, False),
        (504, False, False),
        (503, False, True),
    ],
)
def test_actual_http_producer_preserves_exact_503_retry_boundary(
    tmp_path, monkeypatch, status, mutation, latched
):
    config = tmp_path / "kubeconfig"
    config.write_text(
        json.dumps(
            {
                "clusters": [{"cluster": {"certificate-authority-data": Q.encode("CA")}}],
                "users": [
                    {
                        "user": {
                            "client-certificate-data": Q.encode("CERT"),
                            "client-key-data": Q.encode("KEY"),
                        }
                    }
                ],
            }
        )
    )
    b = S.Backend({"members": [{"hostname": "pi1.local"}], "kubeconfig": str(config)}, {})
    b.write_failed = latched
    calls, sleeps = [], []
    context = SimpleNamespace(
        load_cert_chain=lambda *args: None, wrap_socket=lambda raw, **kwargs: raw
    )
    monkeypatch.setattr(Q.ssl, "create_default_context", lambda **kwargs: context)
    monkeypatch.setattr(b, "resolve", lambda _: "10.0.0.11")
    monkeypatch.setattr(
        b, "connect_peer", lambda *args, **kwargs: SimpleNamespace(close=lambda: None)
    )
    monkeypatch.setattr(S.time, "sleep", sleeps.append)

    class Connection:
        def __init__(self, *args, **kwargs):
            pass

        def request(self, method, *args, **kwargs):
            calls.append(method)

        def getresponse(self):
            return SimpleNamespace(status=status, read=lambda size: b"{}")

        def close(self):
            pass

    monkeypatch.setattr(Q.http.client, "HTTPConnection", Connection)
    patch = [{"op": "test"}] if mutation else None
    with pytest.raises(Q.Stop) as caught:
        b.address_node("pi1.local", "pi1", patch)
    retry = status == 503 and not mutation and not latched
    assert isinstance(caught.value, S.ReadUnavailable) is retry
    assert len(calls) == (3 if retry else 1)
    assert sleeps == ([2, 2] if retry else [])
    if not retry:
        assert str(caught.value) == f"Node API HTTP {status}; no retry"
    assert b.write_failed is (mutation or latched)


@pytest.mark.parametrize("pending", [S.ReadUnavailable, S.ReadinessPending])
def test_pending_normal_proof_cannot_retry_or_release_after_unknown_write(
    cluster, monkeypatch, pending
):
    _, (controller, *_) = cluster
    controller.record = dict(phase="normal-start-intent", **{"token": "owner"})
    controller.b.write_failed = True

    def proof():
        raise pending("pending")

    monkeypatch.setattr(controller, "normal_proof", proof)
    monkeypatch.setattr(controller.b, "retry_reads", lambda: pytest.fail("must not refresh"))
    monkeypatch.setattr(
        controller.r, "transaction", lambda *args, **kwargs: pytest.fail("must not write")
    )
    controller.sleep = lambda _: pytest.fail("must not sleep")
    with pytest.raises(Q.Stop, match="uncertain mutation"):
        controller.post_start()
    assert controller.record["phase"] == "normal-start-intent"


def test_normal_handoffs_complete_only_via_completion_cli_and_propagate_errors(
    cluster, monkeypatch
):
    c, controllers = cluster

    def run(controller):
        controller.pre_start(99)
        controller.b.normal()
        assert controller.post_start() == "completion-pending"

    with ThreadPoolExecutor(max_workers=3) as pool:
        list(pool.map(run, controllers))
    controller = controllers[0]
    b, r = controller.b, controller.r
    assert r.previous()["phase"] == "completion-pending"
    b.child = None
    monkeypatch.setattr(S.os, "geteuid", lambda: 0)
    monkeypatch.setattr(S, "STATE", r.path.parent)
    monkeypatch.setattr(S, "load_opt_in", lambda: (r.e, {}))
    monkeypatch.setattr(Q, "private_state", lambda _: None)
    monkeypatch.setattr(S, "Backend", lambda *args: b)
    monkeypatch.setattr(S, "Recovery", lambda *args: r)
    monkeypatch.setattr(b, "close", lambda: None, raising=False)
    monkeypatch.setattr(S.signal, "signal", lambda *args: None)
    monkeypatch.setattr(__import__("sys"), "argv", ["staged", "check-completion"])
    assert S.main() == 0
    incident = r.previous()
    assert incident["phase"] == "verifying"
    incident["verified_at_monotonic"] -= 31
    Q.atomic_json(r.path, incident)
    assert S.main() == 0 and r.previous()["phase"] == "complete"
    assert controller.post_start() == "unchanged"

    def invariant():
        raise Q.Stop("completion identity changed")

    monkeypatch.setattr(r, "post_start", invariant)
    assert S.main() == 2


@pytest.mark.parametrize("process_bad", [False, True])
def test_normal_process_identity_precedes_ready_pending(cluster, monkeypatch, process_bad):
    c, (controller, *_) = cluster
    controller.record = dict(ip=c.ips["1"], normal_start_at=0)
    calls = []

    def running():
        calls.append("process")
        if process_bad:
            raise Q.Stop("normal process identity changed")

    monkeypatch.setattr(controller.b, "normal_running", running)
    monkeypatch.setattr(controller.r, "prove_etcd", lambda **kwargs: calls.append("etcd"))
    monkeypatch.setattr(controller.r, "address_readback", lambda ip: calls.append("readback"))
    monkeypatch.setattr(controller.b, "address_node", lambda *args: copy.deepcopy(c.nodes["pi1"]))
    with pytest.raises(Q.Stop, match="process identity" if process_bad else "not Ready") as caught:
        controller.normal_proof()
    assert isinstance(caught.value, S.ReadinessPending) is (not process_bad)
    assert calls == (["process"] if process_bad else ["process", "etcd", "readback"])


def test_changed_503_exception_text_is_not_a_retry_contract(monkeypatch):
    b = S.Backend({}, {})
    calls = []

    def response(*args):
        calls.append(True)
        raise Q.Stop("Node API HTTP 503; wording changed")

    monkeypatch.setattr(Q.Backend, "address_node", response)
    monkeypatch.setattr(S.time, "sleep", lambda _: pytest.fail("must not retry"))
    with pytest.raises(Q.Stop, match="wording changed") as caught:
        b.address_node("pi1.local", "pi1")
    assert not isinstance(caught.value, S.ReadUnavailable)
    assert calls == [True] and not b.write_failed
