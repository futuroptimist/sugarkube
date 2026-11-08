"""Offline reboot intent/boot transition tests. No host reboot or systemd calls."""

import copy
import importlib.util
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "staged_tests", ROOT / "tests/test_ethernet_staged_recovery.py"
)
D = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(D)
S, Q = D.S, D.Q
SPEC = importlib.util.spec_from_file_location("reboot", ROOT / "scripts/ethernet_reboot_handoff.py")
R = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(R)
BOOT_A = "a" * 8 + "-aaaa-aaaa-aaaa-" + "a" * 12
BOOT_B = "b" * 8 + "-bbbb-bbbb-bbbb-" + "b" * 12
BOOT_C = "c" * 8 + "-cccc-cccc-cccc-" + "c" * 12


@pytest.fixture
def fleet(tmp_path, monkeypatch):
    cluster, coordinators = D.cluster.__wrapped__(tmp_path, monkeypatch)
    monkeypatch.setattr(Q, "trusted_file", lambda _: None)
    now = [0]
    monkeypatch.setattr(R, "time", SimpleNamespace(monotonic=lambda: now[0]))
    handoffs = []
    for coordinator in coordinators:
        b = coordinator.b
        b.current_boot = BOOT_A
        b.requests = []
        b.service = {"state": "running", "invocation": "original"}
        monkeypatch.setattr(b, "boot_id", lambda b=b: b.current_boot, raising=False)
        monkeypatch.setattr(
            b, "reboot_admission", lambda b=b: copy.deepcopy(b.service), raising=False
        )
        monkeypatch.setattr(
            b, "request_reboot", lambda b=b: b.requests.append("reboot"), raising=False
        )
        monkeypatch.setattr(
            b,
            "running_network",
            lambda ip, old: {"configured_ip": old, "network_sha256": "a" * 64},
            raising=False,
        )
        opt = {"enrollment_sha256": "e" * 64}
        handoff = R.Handoff(Q, coordinator.r, b, opt, coordinator.path.parent)
        coordinator.handoff = handoff
        handoffs.append(handoff)
    return cluster, coordinators, handoffs, now


def request_all(handoffs, now):
    for handoff in handoffs:
        assert handoff.watch() == "observing-running-address"
    now[0] += 31
    for handoff in handoffs:
        assert handoff.watch().startswith("reboot-request-accepted")
        assert handoff.record["phase"] == "reboot-requested"


def test_all_three_reboot_once_then_original_cold_recovery(fleet):
    c, coordinators, handoffs, now = fleet
    request_all(handoffs, now)
    for handoff in handoffs:
        with pytest.raises(Q.Stop, match="original boot"):
            handoff.before_start()
        with pytest.raises(Q.Stop, match="latched"):
            handoff.watch()
        assert handoff.b.requests == ["reboot"]
        handoff.b.current_boot = BOOT_B
        handoff.before_start()
        assert handoff.record["phase"] == "cold-authorized"
        # No staged start exists yet, so repeated quiet pre-side-effect proof is safe.
        handoff.before_start()

    def run(coordinator):
        assert coordinator.pre_start(99) == "normal-start-authorized"
        assert not coordinator.b.boot
        coordinator.b.normal()
        coordinator.post_start()

    with ThreadPoolExecutor(max_workers=3) as pool:
        list(pool.map(run, coordinators))
    for handoff in handoffs:
        with pytest.raises(Q.Stop, match="already consumed"):
            handoff.before_start()
        handoff.watch()
        incident = handoff.r.previous()
        if incident["phase"] == "verifying":
            incident["verified_at_monotonic"] -= 31
            Q.atomic_json(handoff.r.path, incident)
        assert handoff.watch() == "complete"
        assert handoff.record["phase"] == "complete"
        assert (
            handoff.record["staged_id"]
            == json.loads((handoff.state / "staged.json").read_text())["token"]
        )
        assert handoff.record["membership_id"] == handoff.r.previous()["token"]
        handoff.before_start()
        assert handoff.b.requests == ["reboot"]
    assert sorted(c.updates) == ["1", "2", "3"] and c.owner is None


def test_uncertain_reboot_request_never_replays_but_new_boot_can_recover(fleet, monkeypatch):
    _, _, (handoff, *_), now = fleet
    handoff.watch()
    now[0] = 31

    def uncertain():
        handoff.b.requests.append("reboot")
        raise Q.Stop("request outcome unknown")

    monkeypatch.setattr(handoff.b, "request_reboot", uncertain)
    with pytest.raises(Q.Stop, match="outcome unknown"):
        handoff.watch()
    assert handoff.record["phase"] == "reboot-dispatch-intent"
    with pytest.raises(Q.Stop, match="latched"):
        handoff.watch()
    assert handoff.b.requests == ["reboot"]
    handoff.b.current_boot = BOOT_B
    handoff.before_start()
    assert handoff.record["phase"] == "cold-authorized"


@pytest.mark.parametrize(
    "failure", ["address", "residual", "second-boot", "membership", "staged", "node"]
)
def test_new_boot_is_not_sufficient_authorization(fleet, monkeypatch, failure):
    c, _, (handoff, *_), now = fleet
    request_all([handoff], now)
    handoff.b.current_boot = BOOT_B
    if failure == "address":
        c.ips["1"] = "10.0.0.99"
    elif failure == "residual":

        def residual():
            raise Q.Stop("residual runtime")

        monkeypatch.setattr(handoff.b, "quiet", residual)
    elif failure == "second-boot":
        handoff.before_start()
        handoff.b.current_boot = BOOT_C
    elif failure == "membership":
        Q.atomic_json(
            handoff.r.path, dict(member_id="1", cluster_id="100", phase="membership-intent")
        )
    elif failure == "staged":
        Q.atomic_json(handoff.state / "staged.json", dict(phase="bootstrap-start-intent"))
    else:
        Q.atomic_json(handoff.r.address_journal, dict(phase="status-intent"))
    with pytest.raises(Q.Stop):
        handoff.before_start()
    assert handoff.b.requests == ["reboot"]


def seed_complete(handoff):
    handoff.record = dict(
        id="a" * 32,
        member_id="1",
        cluster_id="100",
        enrollment_sha256="e" * 64,
        origin_boot_id=BOOT_A,
        recovery_boot_id=BOOT_B,
        ip="10.0.0.11",
        old_ip="10.0.0.1",
        phase="complete",
        staged_id="b" * 32,
        membership_id="c" * 32,
    )
    handoff.b.current_boot = BOOT_B
    handoff.save("complete")
    Q.atomic_json(
        handoff.r.path,
        dict(
            member_id="1", cluster_id="100", ip="10.0.0.11", phase="complete", **{"token": "c" * 32}
        ),
    )
    Q.atomic_json(
        handoff.state / "staged.json",
        dict(
            member_id="1",
            cluster_id="100",
            ip="10.0.0.11",
            phase="normal",
            membership_id="c" * 32,
            **{"token": "b" * 32},
        ),
    )
    Q.atomic_json(
        handoff.r.address_journal,
        dict(member_id="1", cluster_id="100", ip="10.0.0.11", phase="verified", node_uid="uid1"),
    )


def test_later_completed_incident_archives_bound_evidence(fleet):
    c, _, (handoff, *_), now = fleet
    seed_complete(handoff)
    before = copy.deepcopy(handoff.record)
    c.ips["1"] = "10.0.0.21"
    handoff.watch()
    now[0] = 31
    handoff.watch()
    assert (
        json.loads((handoff.state / ("reboot-archive-" + "a" * 32 + ".json")).read_text()) == before
    )
    assert handoff.record["old_ip"] == "10.0.0.11"
    assert handoff.record["origin_boot_id"] == BOOT_B
    assert handoff.b.requests == ["reboot"]
    with pytest.raises(Q.Stop, match="latched"):
        handoff.watch()


@pytest.mark.parametrize(
    "failure", ["same-boot", "archive", "unlinked-stage", "unlinked-membership"]
)
def test_replay_and_unrelated_completion_never_authorize(fleet, failure):
    c, _, (handoff, *_), now = fleet
    seed_complete(handoff)
    if failure.startswith("unlinked"):
        handoff.save("cold-authorized")
        path = handoff.state / "staged.json" if failure == "unlinked-stage" else handoff.r.path
        record = json.loads(path.read_text())
        record["token"] = "d" * 32
        Q.atomic_json(path, record)
        with pytest.raises(Q.Stop):
            handoff.watch()
    else:
        if failure == "same-boot":
            handoff.record["origin_boot_id"] = BOOT_B
        else:
            (handoff.state / ("reboot-archive-" + "a" * 32 + ".json")).write_text("{}")
        c.ips["1"] = "10.0.0.21"
        handoff.watch()
        now[0] = 31
        with pytest.raises(Q.Stop):
            handoff.watch()
    assert handoff.b.requests == []


def test_debounce_restarts_on_flap_clock_or_boot_change(fleet):
    c, _, (handoff, *_), now = fleet
    assert handoff.watch() == "observing-running-address"
    now[0] = 10
    assert handoff.watch() == "observing-running-address"
    assert json.loads(handoff.observation.read_text())["monotonic"] == 0
    c.ips["1"] = "10.0.0.12"
    now[0] = 20
    assert handoff.watch() == "observing-running-address"
    handoff.b.current_boot = BOOT_B
    now[0] = 60
    assert handoff.watch() == "observing-running-address"
    now[0] = 1
    assert handoff.watch() == "observing-running-address"
    assert handoff.b.requests == []


def test_handoff_loading_verifies_identity(fleet):
    _, _, (handoff, *_), now = fleet
    handoff.before_start()
    request_all([handoff], now)
    loaded = R.Handoff(Q, handoff.r, handoff.b, handoff.opt, handoff.state)
    assert loaded.record == handoff.record
    bad = dict(handoff.record, member_id="2")
    Q.atomic_json(handoff.path, bad)
    with pytest.raises(Q.Stop, match="identity changed"):
        R.Handoff(Q, handoff.r, handoff.b, handoff.opt, handoff.state)


@pytest.mark.parametrize(
    "state", ["running", "inactive", "failed", "activating", "wrong-pid", "job", "jobs"]
)
def test_systemd_admission_adapter(monkeypatch, state):
    b = S.Backend({}, {})
    values = dict(
        ActiveState="active",
        SubState="running",
        MainPID="10",
        ControlPID="0",
        Job="",
        InvocationID="a" * 32,
        NeedDaemonReload="no",
        KillMode="process",
        Delegate="yes",
    )
    if state in ("inactive", "failed"):
        values.update(
            ActiveState=state, SubState="dead" if state == "inactive" else "failed", MainPID="0"
        )
    elif state == "activating":
        values.update(ActiveState="activating", SubState="start-pre")
    elif state == "wrong-pid":
        values["MainPID"] = "0"
    elif state == "job":
        values["Job"] = "42"
    calls = []
    monkeypatch.setattr(b, "process_executable", lambda pid: calls.append(pid))

    def command(argv):
        if argv[-1] == "--version":
            return "systemd 255 (255.4-1ubuntu8)\nfeatures"
        if "list-jobs" in argv:
            return "42 k3s.service start running" if state == "jobs" else ""
        return "\n".join(key + "=" + value for key, value in values.items())

    monkeypatch.setattr(b, "command", command)
    if state in ("running", "inactive", "failed"):
        assert b.reboot_admission() == values
        assert calls == (["10"] if state == "running" else [])
    else:
        with pytest.raises(Q.Stop):
            b.reboot_admission()


def test_reboot_adapter_dispatches_only_nonforce_request(monkeypatch):
    b = S.Backend({}, {})
    calls = []
    monkeypatch.setattr(b, "command", lambda argv: calls.append(argv))
    b.request_reboot()
    assert calls == [
        ["/usr/bin/systemctl", "--no-block", "--no-wall", "--check-inhibitors=yes", "reboot"]
    ]


def test_boot_identity_adapter_reads_kernel_source(tmp_path, monkeypatch):
    path = tmp_path / "boot_id"
    path.write_text(BOOT_A + "\n")
    monkeypatch.setattr(S, "Path", lambda value: path)
    b = S.Backend({}, {})
    assert b.boot_id() == BOOT_A
    path.write_text("invalid")
    with pytest.raises(Q.Stop, match="boot identity"):
        b.boot_id()


def test_disabled_mode_cannot_ignore_pending_handoff(tmp_path, monkeypatch):
    monkeypatch.setattr(S, "STATE", tmp_path)
    assert S.reboot_handoff(None, None, {}) is None
    (tmp_path / "reboot-handoff.json").symlink_to(tmp_path / "missing")
    with pytest.raises(Q.Stop, match="without its explicit opt-in"):
        S.reboot_handoff(None, None, {})


def test_module_import_follows_pinned_backend_validation(fleet, monkeypatch):
    _, _, (handoff, *_), _ = fleet
    calls = []
    monkeypatch.setattr(S, "STATE", handoff.state)
    monkeypatch.setattr(handoff.b, "config", lambda: calls.append("validate"))

    def sibling(name):
        assert calls == ["validate"] and name == "ethernet_reboot_handoff"
        return R

    monkeypatch.setattr(Q, "sibling", sibling)
    result = S.reboot_handoff(handoff.r, handoff.b, dict(handoff.opt, reboot_handoff={}))
    assert result.record is None


@pytest.mark.parametrize("prior", ["none", "complete"])
def test_enabled_reboot_mode_preserves_unrelated_cold_incidents(fleet, prior):
    _, _, (handoff, *_), _ = fleet
    if prior == "complete":
        handoff.record = {"phase": "complete"}
    handoff.bind_staged({"ip": "10.0.0.99"})
    assert handoff.record is None if prior == "none" else handoff.record == {"phase": "complete"}


@pytest.mark.parametrize("tamper", [None, "parent", "child", "invocation", "job", "artifact"])
def test_only_exact_current_timer_job_is_exempt(tmp_path, monkeypatch, tamper):
    proc = D.proc_tree(tmp_path, monkeypatch)
    (proc / "self").mkdir()
    (proc / "42").mkdir()
    expected = f"/usr/bin/timeout 180s /usr/bin/python3 -I {S.RUNTIME} watch-running"
    (proc / "42/exe").symlink_to("/usr/bin/timeout")
    (proc / "42/cmdline").write_bytes(b"\0".join(arg.encode() for arg in expected.split()) + b"\0")
    (proc / "self/cmdline").write_bytes(
        b"\0".join(arg.encode() for arg in expected.split()[2:]) + b"\0"
    )
    (proc / "self/cgroup").write_text("0::/system.slice/sugarkube-ethernet-recovery.service\n")
    monkeypatch.setattr(S.os, "getppid", lambda: 42)
    monkeypatch.setenv("INVOCATION_ID", "a" * 32)
    service = tmp_path / "watcher.service"
    service.write_bytes(S.running_service())
    monkeypatch.setattr(Q, "WATCH_SERVICE", service)
    monkeypatch.setattr(Q, "trusted_file", lambda _: None)
    values = dict(
        Type="oneshot",
        User="root",
        MainPID="42",
        ControlPID="0",
        ActiveState="activating",
        SubState="start",
        Job="17",
        ControlGroup="/system.slice/sugarkube-ethernet-recovery.service",
        InvocationID="a" * 32,
        NeedDaemonReload="no",
        DropInPaths="",
        ExecStart="{ argv[]=" + expected + " ; ignore_errors=no ; }",
    )
    if tamper == "parent":
        values["MainPID"] = "43"
    elif tamper == "child":
        (proc / "self/cmdline").write_bytes(b"other\0")
    elif tamper == "invocation":
        values["InvocationID"] = "b" * 32
    elif tamper == "job":
        values["Job"] = "18"
    elif tamper == "artifact":
        service.write_text("wrong")
    b = S.Backend({}, {})
    monkeypatch.setattr(b, "command", lambda _: "\n".join(k + "=" + v for k, v in values.items()))
    if tamper:
        with pytest.raises(Q.Stop):
            b.own_watcher_job("17")
    else:
        b.own_watcher_job("17")


def test_timer_owned_job_admission_uses_plain_systemd255_output(monkeypatch):
    b = S.Backend({}, {})
    values = dict(
        ActiveState="failed",
        SubState="failed",
        MainPID="0",
        ControlPID="0",
        Job="",
        InvocationID="",
        NeedDaemonReload="no",
        KillMode="process",
        Delegate="yes",
    )

    def command(argv):
        if "--version" in argv:
            return "systemd 255 (255.4)"
        if "list-jobs" in argv:
            assert argv == [
                "/usr/bin/systemctl",
                "list-jobs",
                "--no-legend",
                "--no-pager",
                "--plain",
                "--full",
            ]
            return "17 sugarkube-ethernet-recovery.service start running\n"
        return "\n".join(k + "=" + v for k, v in values.items())

    calls = []
    monkeypatch.setattr(b, "command", command)
    monkeypatch.setattr(b, "own_watcher_job", lambda job: calls.append(job))
    assert b.reboot_admission() == values
    assert calls == ["17"]


def test_opt_in_requires_reboot_tools_and_explicit_scope(fleet, tmp_path, monkeypatch):
    _, coordinators, _, _ = fleet
    e = copy.deepcopy(coordinators[0].r.e)
    e["resolver_view"] = {}
    enrollment = tmp_path / "enrollment"
    enrollment.write_text(json.dumps(e))
    optfile = tmp_path / "opt"
    monkeypatch.setattr(Q, "ENROLLMENT", enrollment)
    monkeypatch.setattr(S, "OPT_IN", optfile)
    executable = "/var/lib/rancher/k3s/data/" + "a" * 64 + "/bin/k3s"
    paths = [
        S.RUNTIME,
        Q.RUNTIME,
        Q.TRANSPORT,
        Q.DESCRIPTOR,
        Q.WAL_RUNTIME,
        executable,
        "/usr/local/bin/k3s",
        "/usr/bin/systemctl",
        "/usr/bin/timeout",
        S.RUNTIME.with_name("ethernet_mdns_resolver.py"),
        S.RUNTIME.with_name("ethernet_reboot_handoff.py"),
    ]
    opt = dict(
        schema_version=1,
        cold_original_database_bootstrap=True,
        server_executable=executable,
        enrollment_sha256=Q.digest(enrollment.read_bytes()),
        runtime_sha256={str(path): "a" * 64 for path in paths},
        reboot_handoff=dict(schema_version=1, whole_host_reboot=True, systemd_major=255),
    )
    optfile.write_text(json.dumps(opt))
    assert S.load_opt_in() == (e, opt)
    malformed = dict(opt, runtime_sha256=list(opt["runtime_sha256"]))
    optfile.write_text(json.dumps(malformed))
    with pytest.raises(Q.Stop, match="must be pinned"):
        S.load_opt_in()
    opt["reboot_handoff"]["whole_host_reboot"] = False
    optfile.write_text(json.dumps(opt))
    with pytest.raises(Q.Stop, match="whole-host reboot"):
        S.load_opt_in()


@pytest.mark.parametrize("phase", ["running-service", "watch-running", "pre-start"])
def test_cli_reboot_routes_keep_baseline_entry_points(fleet, monkeypatch, phase):
    c, coordinators, handoffs, _ = fleet
    coordinator, handoff = coordinators[0], handoffs[0]
    b, r = coordinator.b, coordinator.r
    c.ips["1"] = r.e["local_ipv4"]
    b.child = None
    calls = []
    monkeypatch.setattr(S.os, "geteuid", lambda: 0)
    monkeypatch.setattr(S, "STATE", r.path.parent)
    monkeypatch.setattr(S, "load_opt_in", lambda: (r.e, {}))
    monkeypatch.setattr(Q, "private_state", lambda _: None)
    monkeypatch.setattr(S, "Backend", lambda *args: b)
    monkeypatch.setattr(S, "Recovery", lambda *args: r)
    monkeypatch.setattr(b, "service_context", lambda: None, raising=False)
    monkeypatch.setattr(b, "close", lambda: None, raising=False)
    monkeypatch.setattr(S.signal, "signal", lambda *args: None)
    monkeypatch.setattr(handoff, "before_start", lambda: calls.append("before"))
    monkeypatch.setattr(handoff, "watch", lambda: calls.append("watch") or "unchanged")
    monkeypatch.setattr(S, "reboot_handoff", lambda *args: handoff)
    monkeypatch.setattr(__import__("sys"), "argv", ["staged", phase])
    assert S.main() == 0
    assert calls == (
        [] if phase == "running-service" else ["before"] if phase == "pre-start" else ["watch"]
    )


def test_unchanged_address_does_not_request_reboot(fleet):
    c, _, (handoff, *_), _ = fleet
    c.ips["1"] = handoff.r.e["local_ipv4"]
    assert handoff.watch() == "unchanged"
    assert handoff.b.requests == [] and not handoff.path.exists()


@pytest.mark.parametrize("migration", ["unfinished", "complete"])
def test_running_cli_obeys_read_only_shared_migration_guard(fleet, monkeypatch, migration):
    _, coordinators, handoffs, _ = fleet
    coordinator, handoff = coordinators[0], handoffs[0]
    b, r = coordinator.b, coordinator.r
    b.child = None
    calls = []
    monkeypatch.setattr(S.os, "geteuid", lambda: 0)
    monkeypatch.setattr(S, "STATE", r.path.parent)
    monkeypatch.setattr(S, "load_opt_in", lambda: (r.e, {}))
    monkeypatch.setattr(Q, "private_state", lambda _: None)
    monkeypatch.setattr(S, "Backend", lambda *args: b)
    monkeypatch.setattr(S, "Recovery", lambda *args: r)
    monkeypatch.setattr(b, "close", lambda: None, raising=False)
    monkeypatch.setattr(S.signal, "signal", lambda *args: None)

    def guard(enrollment, backend, state, phase):
        assert enrollment == Q.ENROLLMENT and backend is b and state == r.path.parent
        assert phase == "watch"
        calls.append("guard")
        if migration == "unfinished":
            raise Q.Stop("unfinished migration")

    monkeypatch.setattr(Q, "migration_start_guard", guard, raising=False)
    monkeypatch.setattr(S, "reboot_handoff", lambda *args: handoff)
    monkeypatch.setattr(handoff, "watch", lambda: calls.append("watch") or "observing")
    monkeypatch.setattr(__import__("sys"), "argv", ["staged", "watch-running"])
    assert S.main() == (2 if migration == "unfinished" else 0)
    assert calls == (["guard"] if migration == "unfinished" else ["guard", "watch"])
    assert b.requests == []


@pytest.mark.parametrize("shape", ["old", "current", "wrong", "mixed", "symlink"])
def test_running_network_accepts_only_exact_old_or_current_yaml(tmp_path, monkeypatch, shape):
    path = tmp_path / "network.yaml"
    current, old = "10.0.0.11", "10.0.0.1"
    address = (
        old
        if shape == "old"
        else current if shape in ("current", "mixed", "symlink") else "10.0.0.99"
    )
    content = (
        f'# Managed by configure_k3s_node_ip.sh\nnode-ip: "{address}"\nflannel-iface: "eth0"\n'
    )
    if shape == "mixed":
        content += 'node-ip: "10.0.0.1"\n'
    if shape == "symlink":
        target = tmp_path / "target"
        target.write_text(content)
        path.symlink_to(target)
    else:
        path.write_text(content)
    e = dict(interface="eth0", local_member_id="1", members=[dict(id="1", hostname="pi1.local")])
    b = S.Backend(e, {})
    monkeypatch.setattr(S, "Path", lambda _: path)
    monkeypatch.setattr(Q, "Path", lambda _: path)
    monkeypatch.setattr(
        Q, "trusted_file", lambda p: Q.require(not p.is_symlink(), "untrusted symlink")
    )
    monkeypatch.setattr(b, "config", lambda: None)
    monkeypatch.setattr(b, "address", lambda: current)
    monkeypatch.setattr(b, "resolve", lambda _: current)
    before = path.read_bytes()
    if shape in ("old", "current"):
        assert b.running_network(current, old)["configured_ip"] == address
        if shape == "old":
            with pytest.raises(Q.Stop, match="does not match current"):
                b.network(current)
        else:
            b.network(current)
    else:
        with pytest.raises(Q.Stop):
            b.running_network(current, old)
    assert path.read_bytes() == before


def test_new_boot_requires_refreshed_current_network_yaml(fleet, tmp_path, monkeypatch):
    _, _, (handoff, *_), now = fleet
    request_all([handoff], now)
    handoff.b.current_boot = BOOT_B
    path = tmp_path / "network.yaml"
    original_path = Q.Path
    monkeypatch.setattr(
        Q,
        "Path",
        lambda value: (
            path if str(value).endswith("20-sugarkube-network.yaml") else original_path(value)
        ),
    )
    monkeypatch.setattr(handoff.b, "network", lambda ip: Q.Backend.network(handoff.b, ip))
    path.write_text(
        '# Managed by configure_k3s_node_ip.sh\nnode-ip: "10.0.0.1"\nflannel-iface: "eth0"\n'
    )
    with pytest.raises(Q.Stop, match="does not match current"):
        handoff.before_start()
    assert handoff.record["phase"] == "reboot-requested"
    path.write_text(
        '# Managed by configure_k3s_node_ip.sh\nnode-ip: "10.0.0.11"\nflannel-iface: "eth0"\n'
    )
    handoff.before_start()
    assert handoff.record["phase"] == "cold-authorized"


@pytest.mark.parametrize(
    "change", ["turnover", "running", "failed", "queued", "start-pre", "config", "from-running"]
)
def test_auto_restart_turnover_binds_final_snapshot(fleet, monkeypatch, change):
    _, _, (handoff, *_), now = fleet
    b = handoff.b
    b.service = dict(
        ActiveState="activating",
        SubState="auto-restart",
        MainPID="0",
        ControlPID="0",
        Job="",
        Restart="always",
        InvocationID="a" * 32,
    )
    if change == "from-running":
        b.service.update(ActiveState="active", SubState="running", MainPID="10")
    assert handoff.watch() == "observing-running-address"
    now[0] = 31

    def sample(ip):
        b.service["InvocationID"] = "b" * 32
        if change in ("queued", "start-pre"):
            b.service["SubState"] = "auto-restart-queued" if change == "queued" else change
        elif change == "running":
            b.service.update(ActiveState="active", SubState="running", MainPID="10")
        elif change == "failed":
            b.service.update(ActiveState="failed", SubState="failed")
        elif change == "from-running":
            b.service.update(ActiveState="activating", SubState="auto-restart", MainPID="0")
        elif change == "config":
            b.service["Restart"] = "no"

    monkeypatch.setattr(b, "stable_address", sample)
    if change == "turnover":
        assert handoff.watch().startswith("reboot-request-accepted")
        assert handoff.record["service"] == b.service
        assert handoff.record["service"]["InvocationID"] == "b" * 32
        with pytest.raises(Q.Stop, match="original boot"):
            handoff.before_start()
        with pytest.raises(Q.Stop, match="latched"):
            handoff.watch()
        assert b.requests == ["reboot"]
    else:
        with pytest.raises(Q.Stop, match="host changed"):
            handoff.watch()
        assert b.requests == [] and not handoff.path.exists()


@pytest.mark.parametrize(
    "tamper", ["", "restart", "main", "control", "job", "queued", "start-pre", "running"]
)
def test_exact_auto_restart_adapter(monkeypatch, tamper):
    b = S.Backend({}, {})
    state = dict(
        ActiveState="activating",
        SubState="auto-restart",
        Restart="always",
        MainPID="0",
        ControlPID="0",
        Job="",
        InvocationID="a" * 32,
        NeedDaemonReload="no",
        KillMode="process",
        Delegate="yes",
    )
    changes = {
        "restart": ("Restart", "no"),
        "main": ("MainPID", "10"),
        "control": ("ControlPID", "10"),
        "job": ("Job", "17"),
        "queued": ("SubState", "auto-restart-queued"),
        "start-pre": ("SubState", "start-pre"),
        "running": ("SubState", "running"),
    }
    if tamper:
        key, value = changes[tamper]
        state[key] = value

    def command(argv):
        if "--version" in argv:
            return "systemd 255 (255.4)"
        if "list-jobs" in argv:
            return ""
        assert "Restart" in argv[-1]
        return "\n".join(k + "=" + v for k, v in state.items())

    monkeypatch.setattr(b, "command", command)
    if tamper:
        with pytest.raises(Q.Stop):
            b.reboot_admission()
    else:
        assert b.reboot_admission() == state


def test_prestart_nonblocking_lease_then_durable_same_boot_fence(fleet, monkeypatch):
    _, coordinators, handoffs, now = fleet
    coordinator, handoff = coordinators[0], handoffs[0]
    b, r = coordinator.b, coordinator.r
    b.child = None
    monkeypatch.setattr(S.os, "geteuid", lambda: 0)
    monkeypatch.setattr(S, "STATE", r.path.parent)
    monkeypatch.setattr(S, "load_opt_in", lambda: (r.e, {}))
    monkeypatch.setattr(Q, "private_state", lambda _: None)
    monkeypatch.setattr(S, "Backend", lambda *args: b)
    monkeypatch.setattr(S, "Recovery", lambda *args: r)
    monkeypatch.setattr(b, "service_context", lambda: None, raising=False)
    monkeypatch.setattr(b, "close", lambda: None, raising=False)
    monkeypatch.setattr(S.signal, "signal", lambda *args: None)
    monkeypatch.setattr(S, "reboot_handoff", lambda *args: handoff)
    monkeypatch.setattr(__import__("sys"), "argv", ["staged", "pre-start"])
    for name in ("lock", "bootstrap.lock"):
        with (r.path.parent / name).open("a") as held:
            S.fcntl.flock(held.fileno(), S.fcntl.LOCK_EX | S.fcntl.LOCK_NB)
            assert S.main() == 2
        assert not b.boot and b.requests == []
    request_all([handoff], now)
    assert S.main() == 2
    assert not b.boot and b.requests == ["reboot"]


def test_ordinary_cold_recovery_completes_through_running_watcher(fleet, monkeypatch):
    c, coordinators, handoffs, _ = fleet

    def run(coordinator):
        assert coordinator.pre_start(99) == "normal-start-authorized"
        coordinator.b.normal()
        coordinator.post_start()

    with ThreadPoolExecutor(max_workers=3) as pool:
        list(pool.map(run, coordinators))
    for handoff in handoffs:
        assert handoff.record is None and handoff.b.requests == []
        handoff.watch()
        incident = handoff.r.previous()
        if incident["phase"] == "verifying":
            incident["verified_at_monotonic"] -= 31
            Q.atomic_json(handoff.r.path, incident)
        assert handoff.watch() == "complete"
        assert handoff.watch() == "unchanged"
        assert handoff.record is None and handoff.b.requests == []

    def invariant():
        raise Q.Stop("completion identity changed")

    monkeypatch.setattr(handoff.r, "post_start", invariant)
    with pytest.raises(Q.Stop, match="completion identity changed"):
        handoff.watch()


@pytest.mark.parametrize(
    "field", ["phase", "member_id", "cluster_id", "token", "membership_id", "ip"]
)
def test_ordinary_completion_rejects_mismatched_staged_evidence(fleet, field):
    _, coordinators, (handoff, *_), _ = fleet
    D.completed(coordinators[0])
    staged = json.loads(coordinators[0].path.read_text())
    staged["membership_id"] = "b" * 32
    incident = handoff.r.previous()
    incident.update(
        member_id=handoff.r.local["id"], cluster_id=handoff.r.e["cluster_id"], **{"token": "b" * 32}
    )
    Q.atomic_json(handoff.r.path, incident)
    staged[field] = "wrong"
    Q.atomic_json(coordinators[0].path, staged)
    with pytest.raises(Q.Stop):
        handoff.watch()
    assert handoff.b.requests == []


@pytest.mark.parametrize("value", [[], {"monotonic": "bad"}, {"monotonic": float("nan")}])
def test_malformed_debounce_refuses_without_dispatch(fleet, value):
    _, _, (handoff, *_), _ = fleet
    handoff.observation.write_text(json.dumps(value))
    with pytest.raises(Q.Stop, match="invalid debounce"):
        handoff.watch()
    assert not handoff.path.exists() and handoff.b.requests == []
