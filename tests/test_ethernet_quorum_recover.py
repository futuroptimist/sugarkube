"""Offline failure-safety tests for opt-in, single-member quorum recovery."""

import base64
import copy
import importlib.util
import json
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/ethernet_quorum_recover.py"
SPEC = importlib.util.spec_from_file_location("quorum_recover", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


@pytest.fixture
def enrollment():
    return {
        "schema_version": 1,
        "k3s_version": "v1.35.4+k3s1",
        "interface": "eth0",
        "local_ipv4": "10.0.0.10",
        "cluster_id": "100",
        "local_member_id": "1",
        "verified_backup": True,
        "files": {"/synthetic": "0" * 64},
        "members": [
            {
                "id": str(i + 1),
                "name": f"member{i}",
                "hostname": f"pi{i}.local",
                "node_uid": f"uid{i}",
            }
            for i in range(3)
        ],
    }


class FakeBackend:
    def __init__(self, e):
        self.e = e
        self.ip = "10.0.0.20"
        self.calls = []
        self.owner = None
        self.fail = None
        self.members = [
            {"ID": i + 1, "name": f"member{i}", "peerURLs": [f"https://10.0.0.{10+i}:2380"]}
            for i in range(3)
        ]
        self.object = {
            "metadata": {
                "uid": "uid0",
                "annotations": {
                    "etcd.k3s.cattle.io/node-name": "member0",
                    "k3s.io/internal-ip": self.ip,
                },
            },
            "status": {
                "addresses": [{"type": "InternalIP", "address": self.ip}],
                "conditions": [{"type": "Ready", "status": "True"}],
            },
        }

    def config(self):
        if self.fail == "config":
            raise MODULE.Stop("changed configuration")

    def network(self, ip):
        pass

    def running(self):
        return {"MainPID": "123", "InvocationID": "0" * 32, "NRestarts": "0"}

    def address(self):
        return self.ip

    def resolve(self, host):
        if self.fail == "mdns":
            return "10.0.0.250"
        return self.ip if host == "pi0.local" else "10.0.0." + str(10 + int(host[2]))

    def node(self, host, name):
        return copy.deepcopy(self.object)

    def etcd(self, host, *args, input_text=None):
        self.calls.append((host, args))
        if self.fail == "command":
            raise MODULE.Stop("authentication/timeout failure")
        if args == ("member", "list"):
            return {"header": {"cluster_id": 100}, "members": copy.deepcopy(self.members)}
        if args == ("endpoint", "status"):
            member = 99 if self.fail == "identity" else int(host[2]) + 1
            cluster = 999 if self.fail == "cluster" else 100
            return [{"Status": {"header": {"cluster_id": cluster, "member_id": member}}}]
        if args == ("endpoint", "health"):
            return [{"health": self.fail != "quorum"}]
        if args == ("txn",):
            payload = json.loads(input_text)
            compare = payload["compare"][0]
            if compare["target"] == "VERSION":
                if self.owner is not None:
                    return {"succeeded": False}
                self.owner = base64.b64decode(
                    payload["success"][0]["request_put"]["value"]
                ).decode()
            else:
                if base64.b64decode(compare["value"]).decode() != self.owner:
                    return {"succeeded": False}
                self.owner = None
            return {"succeeded": True}
        if args == ("get", MODULE.KEY):
            return {
                "kvs": [
                    {"value": MODULE.encode("other" if self.fail == "ownership" else self.owner)}
                ]
            }
        assert args[:2] == ("member", "update")
        assert args[2] == "1"  # Never update either surviving member.
        self.members[0]["peerURLs"] = [args[3].removeprefix("--peer-urls=")]
        if self.fail == "address_after_update":
            self.ip = "10.0.0.21"
        if self.fail == "unknown_update":
            raise MODULE.Stop("timeout after server committed update")
        return {"header": {"cluster_id": 100}}


def complete(recovery):
    assert recovery.post_start() == "verifying"
    saved = json.loads(recovery.path.read_text())
    saved["verified_at_monotonic"] -= 31
    recovery.path.write_text(json.dumps(saved))
    return recovery.post_start()


def updates(backend):
    return [args for _, args in backend.calls if args[:2] == ("member", "update")]


def test_repair_preserves_members_and_replay_is_blocked(enrollment, tmp_path):
    backend = FakeBackend(enrollment)
    original = copy.deepcopy(backend.members)
    recovery = MODULE.Recovery(enrollment, backend, tmp_path / "incident.json")
    assert recovery.pre_start() == "one-start-authorized"
    assert len(updates(backend)) == 1
    assert backend.members[1:] == original[1:]
    assert [m["ID"] for m in backend.members] == [m["ID"] for m in original]
    assert backend.members[0]["peerURLs"] == ["https://10.0.0.20:2380"]
    with pytest.raises(MODULE.Stop, match="unfinished"):
        recovery.pre_start()
    assert len(updates(backend)) == 1
    assert complete(recovery) == "complete"
    assert backend.owner is None
    backend.calls.clear()
    assert recovery.pre_start() == "unchanged"
    assert not backend.calls  # Cold restart does not require an existing quorum.
    assert recovery.post_start() == "unchanged"


def test_unchanged_voters_can_cold_start_without_quorum(enrollment, tmp_path):
    backend = FakeBackend(enrollment)
    backend.ip = enrollment["local_ipv4"]
    backend.fail = "quorum"
    recovery = MODULE.Recovery(enrollment, backend, tmp_path / "incident.json")
    assert recovery.pre_start() == "unchanged"
    assert recovery.post_start() == "unchanged"
    assert backend.calls == []


@pytest.mark.parametrize("failure", ["config", "mdns", "identity", "cluster", "quorum", "command"])
def test_unproven_identity_or_quorum_cannot_mutate(enrollment, tmp_path, failure):
    backend = FakeBackend(enrollment)
    original = copy.deepcopy(backend.members)
    backend.fail = failure
    recovery = MODULE.Recovery(enrollment, backend, tmp_path / "incident.json")
    with pytest.raises(MODULE.Stop):
        recovery.pre_start()
    assert backend.members == original
    assert not updates(backend)
    assert not recovery.path.exists()


@pytest.mark.parametrize("failure", ["held", "ownership", "unknown_update", "address_after_update"])
def test_failed_incident_stays_latched_without_blind_retry(enrollment, tmp_path, failure):
    backend = FakeBackend(enrollment)
    if failure == "held":
        backend.owner = "another-host"
    else:
        backend.fail = failure
    recovery = MODULE.Recovery(enrollment, backend, tmp_path / "incident.json")
    with pytest.raises(MODULE.Stop):
        recovery.pre_start()
    assert recovery.path.exists()
    previous_calls = list(backend.calls)
    with pytest.raises(MODULE.Stop, match="unfinished"):
        recovery.pre_start()
    assert backend.calls == previous_calls
    assert len(updates(backend)) == (
        1 if failure in ("unknown_update", "address_after_update") else 0
    )
    assert backend.owner is not None


def test_stale_node_status_prevents_completion_without_patch(enrollment, tmp_path):
    backend = FakeBackend(enrollment)
    recovery = MODULE.Recovery(enrollment, backend, tmp_path / "incident.json")
    assert recovery.pre_start() == "one-start-authorized"
    backend.object["status"]["addresses"][0]["address"] = "10.0.0.10"
    before = copy.deepcopy(backend.object)
    with pytest.raises(MODULE.Stop, match="status has not converged"):
        recovery.post_start()
    assert backend.object == before
    assert backend.owner is not None
    backend.object["status"]["addresses"][0]["address"] = backend.ip
    assert complete(recovery) == "complete"


@pytest.mark.parametrize("change", ["uid", "name", "learner", "unknown_member", "external_url"])
def test_membership_and_node_binding_changes_are_refused(enrollment, tmp_path, change):
    backend = FakeBackend(enrollment)
    if change == "uid":
        backend.object["metadata"]["uid"] = "replacement"
    elif change == "name":
        backend.members[0]["name"] = "replacement"
    elif change == "learner":
        backend.members[1]["isLearner"] = True
    elif change == "unknown_member":
        backend.members[1]["ID"] = 99
    else:
        backend.members[0]["peerURLs"] = ["https://pi0.local:2380"]
    recovery = MODULE.Recovery(enrollment, backend, tmp_path / "incident.json")
    with pytest.raises(MODULE.Stop):
        recovery.pre_start()
    assert not updates(backend)


def test_failed_journal_write_prevents_cluster_mutation(enrollment, tmp_path, monkeypatch):
    backend = FakeBackend(enrollment)
    recovery = MODULE.Recovery(enrollment, backend, tmp_path / "incident.json")

    def fail(*args):
        raise OSError("disk full")

    monkeypatch.setattr(MODULE, "atomic_json", fail)
    with pytest.raises(OSError):
        recovery.pre_start()
    assert backend.owner is None
    assert not updates(backend)


def test_watcher_debounces_and_requests_exactly_one_restart(enrollment, tmp_path, monkeypatch):
    backend = FakeBackend(enrollment)
    backend.active = lambda: True
    refreshed = []
    backend.refresh = lambda: refreshed.append(True)
    recovery = MODULE.Recovery(enrollment, backend, tmp_path / "incident.json")
    clock = [1000]
    monkeypatch.setattr(MODULE.time, "time", lambda: clock[0])
    assert recovery.watch() == "observing"
    clock[0] += 10
    assert recovery.watch() == "observing"
    assert not updates(backend)
    clock[0] += 21
    assert recovery.watch() == "restart-requested"
    assert refreshed == [True]
    with pytest.raises(MODULE.Stop, match="unfinished"):
        recovery.watch()
    assert recovery.pre_start() == "one-start-authorized"
    with pytest.raises(MODULE.Stop, match="unfinished"):
        recovery.pre_start()
    assert len(updates(backend)) == 1
    # Completion can retry after Node status catches up, without another restart/update.
    backend.object["status"]["addresses"][0]["address"] = "10.0.0.10"
    with pytest.raises(MODULE.Stop):
        recovery.watch()
    backend.object["status"]["addresses"][0]["address"] = backend.ip
    assert recovery.watch() == "verifying"
    assert complete(recovery) == "complete"
    assert len(updates(backend)) == 1


def test_watcher_lease_flap_resets_stability_window(enrollment, tmp_path, monkeypatch):
    backend = FakeBackend(enrollment)
    backend.active = lambda: True
    backend.refresh = lambda: None
    recovery = MODULE.Recovery(enrollment, backend, tmp_path / "incident.json")
    clock = [1000]
    monkeypatch.setattr(MODULE.time, "time", lambda: clock[0])
    assert recovery.watch() == "observing"
    backend.ip = enrollment["local_ipv4"]
    clock[0] += 15
    assert recovery.watch() == "unchanged"
    backend.ip = "10.0.0.20"
    clock[0] += 20
    assert recovery.watch() == "observing"
    assert not updates(backend)


def test_gateway_pins_tls_identity_and_never_reconnects(enrollment, monkeypatch):
    from types import SimpleNamespace

    enrollment["etcd_tls"] = {
        "ca": "/synthetic/ca",
        "cert": "/synthetic/cert",
        "key": "/synthetic/key",
    }
    tls_calls = []
    raw = SimpleNamespace(close=lambda: tls_calls.append("raw-closed"))
    context = SimpleNamespace(
        load_cert_chain=lambda *args: tls_calls.append(args),
        wrap_socket=lambda sock, server_hostname: tls_calls.append(server_hostname) or raw,
    )
    monkeypatch.setattr(MODULE.ssl, "create_default_context", lambda **kw: context)
    monkeypatch.setattr(MODULE.socket, "create_connection", lambda *a, **kw: raw)
    responses = [
        {"header": {"cluster_id": "100", "member_id": "2"}},
        {"header": {"cluster_id": "100", "member_id": "999"}},
    ]

    class Connection:
        sock = None

        def request(self, *args):
            tls_calls.append(args)

        def getresponse(self):
            return SimpleNamespace(
                status=200, read=lambda size: json.dumps(responses.pop(0)).encode()
            )

        def close(self):
            self.sock = None

    connection = Connection()
    monkeypatch.setattr(MODULE.http.client, "HTTPConnection", lambda *a, **kw: connection)
    backend = MODULE.Backend(enrollment)
    backend.resolve = lambda host: "10.0.0.11"
    backend.connect_peer = lambda address: raw
    assert backend.request("pi1.local", "/v3/kv/range", {})["header"]["member_id"] == "2"
    assert "pi1.local" in tls_calls
    assert ("/synthetic/cert", "/synthetic/key") in tls_calls
    with pytest.raises(MODULE.Stop, match="identity mismatch"):
        backend.request("pi1.local", "/v3/kv/range", {})
    with pytest.raises(MODULE.Stop, match="no automatic reconnect"):
        backend.request("pi1.local", "/v3/kv/range", {})


def test_backend_inventory_pins_all_inputs_and_rejects_overrides(enrollment, tmp_path, monkeypatch):
    real_path = Path

    def redirected(value):
        value = str(value)
        if value.startswith(("/etc/", "/var/lib/")):
            return tmp_path / value.lstrip("/")
        return real_path(value)

    monkeypatch.setattr(MODULE, "Path", redirected)
    monkeypatch.setattr(MODULE, "trusted_file", lambda path: None)
    for filename, content in {
        "/etc/machine-id": "synthetic-machine",
        "/etc/rancher/k3s/config.yaml": (
            "write-kubeconfig-mode: '0644'\nserver: https://pi1.local:6443\n"
        ),
        "/etc/rancher/k3s/config.yaml.d/10-tls.yaml": "tls-san: [pi0.local]\n",
        "/etc/systemd/system/k3s.service.env": ("K3S_URL='https://pi1.local:6443'\n"),
        "/etc/rancher/k3s/sugarkube-network-prestart.sh": "synthetic-helper",
        MODULE.NETWORK_HOOK: "synthetic-hook",
        "/etc/rancher/k3s/k3s.yaml": (
            "clusters:\n  - name: default\n    cluster:\n"
            "      certificate-authority-data: synthetic-ca\n      server: https://127.0.0.1:6443\n"
            "contexts:\n  - name: default\n    context: {cluster: default, user: default}\n"
            "current-context: default\nusers:\n  - name: default\n    user:\n"
            "      client-certificate-data: synthetic-cert\n      client-key-data: synthetic-key\n"
        ),
        "/etc/ca": "synthetic-ca",
        "/etc/cert": "synthetic-cert",
        "/etc/key": "synthetic-key",
    }.items():
        path = redirected(filename)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    redirected("/var/lib/rancher/k3s/server/db/etcd/member").mkdir(parents=True)
    enrollment.update(
        {
            "kubeconfig": "/etc/rancher/k3s/k3s.yaml",
            "etcd_tls": {"ca": "/etc/ca", "cert": "/etc/cert", "key": "/etc/key"},
        }
    )
    backend = MODULE.Backend(enrollment)
    command = ["/usr/local/bin/k3s server --server https://pi1.local:6443"]

    def output(argv, input_text=None):
        if argv[-1] == "--version":
            return "k3s version v1.35.4+k3s1 (synthetic)\n"
        return (
            f"ExecStart={{ path=/usr/local/bin/k3s ; argv[]={command[0]} ; "
            "ignore_errors=no ; pid=42 }\n"
            "Environment=K3S_KUBECONFIG_MODE=0644\n"
            "EnvironmentFiles=/etc/systemd/system/k3s.service.env (ignore_errors=yes)\n"
            f"DropInPaths={MODULE.NETWORK_HOOK}\n"
        )

    backend.command = output
    enrollment.update(backend.inventory())
    assert "/etc/systemd/system/k3s.service.env" in enrollment["files"]
    assert "/etc/key" not in enrollment["files"]
    backend.config()
    redirected("/etc/cert").write_text("renewed-client-certificate")
    redirected("/etc/key").write_text("renewed-client-key")
    backend.config()  # Native leaf renewal does not strand a future normal reboot.
    kubeconfig = redirected("/etc/rancher/k3s/k3s.yaml")
    original = kubeconfig.read_text()
    for override in ("insecure-skip-tls-verify: true", "proxy-url: http://untrusted"):
        kubeconfig.write_text(
            original.replace("    cluster:\n", f"    cluster:\n      {override}\n")
        )
        with pytest.raises(MODULE.Stop, match="insecure/proxy"):
            backend.inventory()
    kubeconfig.write_text(original)
    redirected("/etc/ca").write_text("changed-trust-root")
    with pytest.raises(MODULE.Stop, match="trust material changed"):
        backend.config()
    command[0] += " --node-ip=10.0.0.1"
    with pytest.raises(MODULE.Stop, match="CLI override"):
        backend.inventory()
    command[0] = "/usr/local/bin/k3s server --server=https://10.0.0.11:6443"
    with pytest.raises(MODULE.Stop, match="join target"):
        backend.inventory()
    command[0] = "/usr/local/bin/k3s server"
    redirected("/etc/rancher/k3s/config.yaml").write_text("node-ip: 10.0.0.1\n")
    with pytest.raises(MODULE.Stop, match="network/reset override"):
        backend.inventory()


def test_backend_address_discovery_commands_are_bounded(enrollment, tmp_path, monkeypatch):
    import subprocess
    from types import SimpleNamespace

    backend = MODULE.Backend(enrollment)
    executed = []

    def execute(argv, **kwargs):
        executed.append((argv, kwargs))
        assert kwargs["timeout"] == 12 and kwargs["check"]
        assert set(kwargs["env"]) == {"PATH", "ETCDCTL_API"}
        return SimpleNamespace(stdout="ok")

    monkeypatch.setattr(MODULE.subprocess, "run", execute)
    assert backend.command(["synthetic"]) == "ok"

    def failure(*args, **kwargs):
        raise subprocess.TimeoutExpired("do-not-echo", 12)

    monkeypatch.setattr(MODULE.subprocess, "run", failure)
    with pytest.raises(MODULE.Stop, match="bounded authenticated"):
        backend.command(["synthetic"])
    responses = [
        json.dumps([{"addr_info": [{"local": "10.0.0.20", "scope": "global"}]}]),
        "pi0.local\t10.0.0.20\n",
        "10.0.0.20 STREAM pi0.local\n10.0.0.20 DGRAM\n",
        "pi0.local\t10.0.0.21\n",
        "10.0.0.21 STREAM pi0.local\n",
    ]
    backend.command = lambda *a, **k: responses.pop(0)
    assert backend.address() == "10.0.0.20"
    assert backend.resolve("pi0.local") == "10.0.0.20"
    with pytest.raises(MODULE.Stop, match="address changed"):
        backend.resolve("pi0.local")
    backend.command = lambda *a, **k: json.dumps([{"addr_info": []}])
    with pytest.raises(MODULE.Stop, match="primary Ethernet"):
        backend.address()
    commands = []
    backend.command = lambda argv, **kw: commands.append(argv) or "active"
    backend.refresh()
    assert backend.active()
    backend.restart()
    backend.restart(operator=True)
    assert commands[-2][2] == "try-restart" and commands[-1][2] == "restart"
    enrollment["kubeconfig"] = "/synthetic/kubeconfig"
    backend.resolve = lambda host: "10.0.0.11"
    backend.command = lambda argv: commands.append(argv) or "{}"
    assert backend.node("pi1.local", "pi0") == {}
    assert "--server=https://10.0.0.11:6443" in commands[-1]
    assert "--tls-server-name=pi1.local" in commands[-1]


def test_gateway_routes_are_limited_to_approved_operations(enrollment):
    backend = MODULE.Backend(enrollment)
    requests = []
    backend.request = lambda host, route, payload: requests.append((route, payload)) or {
        "header": {}
    }
    backend.etcd("pi1.local", "member", "list")
    backend.etcd("pi1.local", "member", "update", "a", "--peer-urls=https://10.0.0.20:2380")
    backend.etcd("pi1.local", "endpoint", "status")
    assert backend.etcd("pi1.local", "endpoint", "health") == [{"health": True}]
    backend.etcd("pi1.local", "get", MODULE.KEY)
    backend.etcd("pi1.local", "txn", input_text='{"compare": []}')
    assert requests[1] == (
        "/v3/cluster/member/update",
        {"ID": "10", "peerURLs": ["https://10.0.0.20:2380"]},
    )
    assert requests[3][1]["serializable"] is False
    with pytest.raises(MODULE.Stop, match="unsupported"):
        backend.etcd("pi1.local", "member", "remove", "1")


@pytest.mark.parametrize(
    "failure,after_write",
    [(None, False)]
    + [
        (name, after)
        for name in ("RUNTIME", "WATCH_SERVICE", "WATCH_TIMER", "ENROLLMENT", "HOOK")
        for after in (False, True)
    ],
)
def test_explicit_enrollment_installs_inactive_units_only(
    enrollment, tmp_path, monkeypatch, failure, after_write
):
    backend = FakeBackend(enrollment)
    backend.ip = enrollment["local_ipv4"]
    inventory = {
        "files": enrollment["files"],
        "machine_id_sha256": "0" * 64,
        "systemd_sha256": "1" * 64,
        "yaml_fragments": [],
    }
    backend.inventory = lambda: copy.deepcopy(inventory)

    def node(host, name):
        i = int(name[2])
        ip = f"10.0.0.{10+i}"
        return {
            "metadata": {
                "uid": f"uid{i}",
                "annotations": {
                    "etcd.k3s.cattle.io/node-name": f"member{i}",
                    "k3s.io/internal-ip": ip,
                },
            },
            "status": {"addresses": [{"type": "InternalIP", "address": ip}]},
        }

    backend.node = node
    monkeypatch.setattr(MODULE, "Backend", lambda e: backend)
    monkeypatch.setattr(MODULE, "trusted_file", lambda path: None)
    paths = {
        key: tmp_path / key
        for key in ["RUNTIME", "HOOK", "WATCH_SERVICE", "WATCH_TIMER", "ENROLLMENT"]
    }
    for key, path in paths.items():
        monkeypatch.setattr(MODULE, key, path)
    request = tmp_path / "request.json"
    request.write_text(json.dumps(enrollment))
    written = []
    real_write = MODULE.atomic_write

    def write(path, content):
        if failure and path == paths[failure] and not after_write:
            raise OSError("injected enrollment interruption")
        real_write(path, content)
        written.append(path)
        if path == paths["HOOK"]:
            # Simulate reboot discovery at the instant the hook becomes visible.
            assert all(paths[key].is_file() for key in paths)
            assert json.loads(paths["ENROLLMENT"].read_text())["local_ipv4"] == "10.0.0.10"
        if failure and path == paths[failure] and after_write:
            raise OSError("injected enrollment interruption")

    monkeypatch.setattr(MODULE, "atomic_write", write)
    if failure:
        with pytest.raises(OSError, match="injected enrollment"):
            MODULE.enroll(request, paths["ENROLLMENT"])
        assert paths["HOOK"].exists() == (failure == "HOOK" and after_write)
        assert not updates(backend) and backend.owner is None
        return
    assert "not reloaded or enabled" in MODULE.enroll(request, paths["ENROLLMENT"])
    assert written[-1] == paths["HOOK"]
    assert paths["RUNTIME"].read_bytes() == SCRIPT.read_bytes()
    assert "ExecStartPre=" in paths["HOOK"].read_text()
    assert "ExecStartPost=-" in paths["HOOK"].read_text()
    assert "OnUnitInactiveSec=30s" in paths["WATCH_TIMER"].read_text()
    saved = json.loads(paths["ENROLLMENT"].read_text())
    assert saved["local_ipv4"] == "10.0.0.10"
    assert not updates(backend) and backend.owner is None
    before = paths["ENROLLMENT"].read_bytes()
    with pytest.raises(MODULE.Stop, match="existing enrollment"):
        MODULE.enroll(request, paths["ENROLLMENT"])
    assert paths["ENROLLMENT"].read_bytes() == before


def test_operator_resume_requires_reconciled_status_and_ownership(enrollment, tmp_path):
    backend = FakeBackend(enrollment)
    recovery = MODULE.Recovery(enrollment, backend, tmp_path / "incident.json")
    assert recovery.pre_start() == "one-start-authorized"
    backend.object["status"]["addresses"][0]["address"] = "10.0.0.10"
    with pytest.raises(MODULE.Stop, match="must be reconciled"):
        recovery.resume()
    backend.object["status"]["addresses"][0]["address"] = backend.ip
    assert recovery.resume() == "operator-restart-requested"
    assert json.loads(recovery.path.read_text())["operator_resumes"] == 1
    assert recovery.pre_start() == "one-start-authorized"
    assert complete(recovery) == "complete"
    assert len(updates(backend)) == 1  # Resume did not issue another membership update.


def test_connection_uses_only_enrolled_ethernet_and_closes_on_failure(enrollment, monkeypatch):
    from types import SimpleNamespace

    calls = []
    raw = SimpleNamespace(
        settimeout=lambda n: calls.append(("timeout", n)),
        setsockopt=lambda *args: calls.append(("interface", args[-1])),
        bind=lambda address: calls.append(("bind", address)),
        connect=lambda address: calls.append(("connect", address)),
        close=lambda: calls.append(("closed",)),
    )
    monkeypatch.setattr(MODULE.socket, "socket", lambda *a: raw)
    backend = MODULE.Backend(enrollment)
    backend.address = lambda: "10.0.0.20"
    assert backend.connect_peer("10.0.0.11") is raw
    assert ("interface", b"eth0\0") in calls
    assert ("bind", ("10.0.0.20", 0)) in calls
    assert ("connect", ("10.0.0.11", 2379)) in calls

    def fail(*args):
        raise OSError("unreachable")

    raw.connect = fail
    with pytest.raises(OSError):
        backend.connect_peer("10.0.0.11")
    assert calls[-1] == ("closed",)


def test_failed_tls_handshake_cannot_issue_request(enrollment, monkeypatch):
    from types import SimpleNamespace

    enrollment["etcd_tls"] = {"ca": "synthetic", "cert": "synthetic", "key": "synthetic"}
    closed = []
    raw = SimpleNamespace(close=lambda: closed.append(True))

    def fail(*args, **kwargs):
        raise MODULE.ssl.SSLError("untrusted peer")

    context = SimpleNamespace(load_cert_chain=lambda *a: None, wrap_socket=fail)
    monkeypatch.setattr(MODULE.ssl, "create_default_context", lambda **kw: context)
    backend = MODULE.Backend(enrollment)
    backend.resolve = lambda host: "10.0.0.11"
    backend.connect_peer = lambda address: raw
    with pytest.raises(MODULE.ssl.SSLError):
        backend.request("pi1.local", "/v3/kv/range", {})
    assert closed == [True] and not backend.connections


def test_network_snapshot_must_match_current_address(enrollment, tmp_path, monkeypatch):
    path = tmp_path / "network.yaml"
    monkeypatch.setattr(MODULE, "Path", lambda value: path)
    backend = MODULE.Backend(enrollment)
    path.write_text(
        '# Managed by configure_k3s_node_ip.sh\nnode-ip: "10.0.0.20"\nflannel-iface: "eth0"\n'
    )
    backend.network("10.0.0.20")
    with pytest.raises(MODULE.Stop, match="does not match"):
        backend.network("10.0.0.21")


def test_atomic_journal_replace_failure_preserves_previous_record(tmp_path, monkeypatch):
    path = tmp_path / "incident.json"
    path.write_text('{"phase":"reserved"}')

    def fail(*args):
        raise OSError("replace failed")

    monkeypatch.setattr(MODULE.os, "replace", fail)
    with pytest.raises(OSError):
        MODULE.atomic_json(path, {"phase": "complete"})
    assert path.read_text() == '{"phase":"reserved"}'
    assert list(tmp_path.iterdir()) == [path]


@pytest.mark.parametrize(
    "uid,mode,symlink",
    [(0, 0o600, False), (1000, 0o600, False), (0, 0o622, False), (0, 0o600, True)],
)
def test_enrollment_and_state_permissions_are_enforced(uid, mode, symlink, monkeypatch):
    from types import SimpleNamespace

    path = SimpleNamespace(
        lstat=lambda: SimpleNamespace(st_uid=uid, st_mode=mode),
        is_symlink=lambda: symlink,
        exists=lambda: True,
        is_dir=lambda: True,
        mkdir=lambda **kwargs: None,
        parents=[],
    )
    monkeypatch.setattr(MODULE, "install_directory", lambda path, mode: MODULE.trusted_file(path))
    if uid == 0 and mode == 0o600 and not symlink:
        MODULE.trusted_file(path)
        MODULE.private_state(path)
    else:
        with pytest.raises(MODULE.Stop):
            MODULE.trusted_file(path)
        with pytest.raises(MODULE.Stop):
            MODULE.private_state(path)


@pytest.mark.parametrize(
    "phase,action",
    [
        ("watch", "restart-requested"),
        ("resume", "operator-restart-requested"),
        ("post-start", "complete"),
        ("pre-start", "unchanged"),
    ],
)
def test_cli_releases_lock_before_requesting_restart(
    enrollment, tmp_path, monkeypatch, capsys, phase, action
):
    import fcntl
    import sys
    from types import SimpleNamespace

    path = tmp_path / "enrollment.json"
    path.write_text(json.dumps(enrollment))
    state = tmp_path / "state"
    monkeypatch.setattr(MODULE.os, "geteuid", lambda: 0)
    monkeypatch.setattr(MODULE, "trusted_file", lambda p: None)
    monkeypatch.setattr(MODULE, "private_state", lambda p: p.mkdir(mode=0o700))
    restarts = []

    def restart(operator=False):
        with (state / "lock").open("a") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            restarts.append(operator)

    monkeypatch.setattr(MODULE, "Backend", lambda e: SimpleNamespace(restart=restart))
    monkeypatch.setattr(
        MODULE,
        "Recovery",
        lambda *args: SimpleNamespace(
            pre_start=lambda: action,
            post_start=lambda: action,
            watch=lambda: action,
            resume=lambda: action,
        ),
    )
    monkeypatch.setattr(
        sys, "argv", [str(SCRIPT), phase, "--enrollment", str(path), "--state-dir", str(state)]
    )
    assert MODULE.main() == 0
    assert capsys.readouterr().out.strip() == action
    assert restarts == {"watch": [False], "resume": [True]}.get(phase, [])


def test_cli_enrollment_and_malformed_input_fail_safely(tmp_path, monkeypatch, capsys):
    import sys

    path = tmp_path / "request.json"
    path.write_text("do-not-echo malformed private input")
    monkeypatch.setattr(MODULE.os, "geteuid", lambda: 0)
    monkeypatch.setattr(MODULE, "trusted_file", lambda p: None)
    monkeypatch.setattr(sys, "argv", [str(SCRIPT), "watch", "--enrollment", str(path)])
    assert MODULE.main() == 2
    assert "do-not-echo" not in capsys.readouterr().out
    monkeypatch.setattr(MODULE, "enroll", lambda request, dest: "enrolled-inactive")
    monkeypatch.setattr(sys, "argv", [str(SCRIPT), "enroll", "--request", str(path)])
    assert MODULE.main() == 0
    assert capsys.readouterr().out.strip() == "enrolled-inactive"
    monkeypatch.setattr(sys, "argv", [str(SCRIPT), "enroll"])
    assert MODULE.main() == 2
    assert "explicit healthy-time" in capsys.readouterr().out


def test_actual_entrypoint_requires_root_without_network(monkeypatch, capsys):
    import runpy
    import sys

    monkeypatch.setattr(MODULE.os, "geteuid", lambda: 1000)
    monkeypatch.setattr(sys, "argv", [str(SCRIPT), "watch"])
    with pytest.raises(SystemExit) as result:
        runpy.run_path(str(SCRIPT), run_name="__main__")
    assert result.value.code == 2
    assert "root-owned" in capsys.readouterr().out


def test_process_restart_during_verification_keeps_incident_latched(enrollment, tmp_path):
    backend = FakeBackend(enrollment)
    recovery = MODULE.Recovery(enrollment, backend, tmp_path / "incident.json")
    assert recovery.pre_start() == "one-start-authorized"
    assert recovery.post_start() == "verifying"
    backend.running = lambda: {"MainPID": "456", "InvocationID": "1" * 32, "NRestarts": "1"}
    with pytest.raises(MODULE.Stop, match="restarted during"):
        recovery.post_start()
    assert backend.owner is not None
    with pytest.raises(MODULE.Stop, match="unfinished"):
        recovery.pre_start()


def test_backend_running_requires_active_service_identity(enrollment):
    backend = MODULE.Backend(enrollment)
    backend.command = (
        lambda argv: "ActiveState=active\nMainPID=123\nInvocationID=" + "a" * 32 + "\nNRestarts=2\n"
    )
    assert backend.running()["MainPID"] == "123"
    backend.command = (
        lambda argv: "ActiveState=activating\nMainPID=123\nInvocationID="
        + "a" * 32
        + "\nNRestarts=2\n"
    )
    with pytest.raises(MODULE.Stop, match="active service"):
        backend.running()


def test_operator_can_resume_confirmed_update_before_first_start(enrollment, tmp_path):
    backend = FakeBackend(enrollment)
    backend.fail = "unknown_update"
    backend.object["metadata"]["annotations"]["k3s.io/internal-ip"] = "10.0.0.10"
    backend.object["status"]["addresses"][0]["address"] = "10.0.0.10"
    recovery = MODULE.Recovery(enrollment, backend, tmp_path / "incident.json")
    with pytest.raises(MODULE.Stop):
        recovery.pre_start()
    backend.fail = None
    assert recovery.resume() == "operator-restart-requested"
    assert len(updates(backend)) == 1
    assert recovery.pre_start() == "one-start-authorized"


@pytest.mark.parametrize("start_mode", ["boot", "watch"])
def test_disposable_etcd_preserves_identity_and_data(tmp_path, monkeypatch, start_mode):
    """Real TLS/consensus/member-update protocol; K3s/systemd/Node API remain synthetic."""
    import http.client
    import os
    import socket
    import ssl
    import subprocess
    import time
    import urllib.request
    import uuid

    binary = os.environ.get("SUGARKUBE_TEST_ETCD_BINARY")
    if not binary:
        # TODO: Provide the pinned disposable etcd binary to exercise real protocol recovery.
        # Root cause: Ordinary local environments may not have a compatible etcd executable.
        # Estimated fix: Set SUGARKUBE_TEST_ETCD_BINARY; ordinary PR CI provisions it.
        pytest.skip("set SUGARKUBE_TEST_ETCD_BINARY for disposable etcd protocol tests")
    ca, key, cert = (tmp_path / name for name in ("ca.crt", "tls.key", "tls.crt"))
    subnet = uuid.uuid4().bytes
    ips = [f"127.{subnet[0]}.{subnet[1]}.{i}" for i in range(10, 15)]
    for ip in ips:
        for port in (2379, 2380):
            with socket.socket() as probe:
                probe.bind((ip, port))  # Never attach to an existing local service.

    def openssl(*args):
        subprocess.run(["openssl", *args], check=True, capture_output=True, timeout=15)

    openssl(
        "req",
        "-x509",
        "-newkey",
        "rsa:2048",
        "-nodes",
        "-keyout",
        str(tmp_path / "ca.key"),
        "-out",
        str(ca),
        "-days",
        "1",
        "-subj",
        "/CN=disposable-k339-ca",
    )
    openssl(
        "req",
        "-newkey",
        "rsa:2048",
        "-nodes",
        "-keyout",
        str(key),
        "-out",
        str(tmp_path / "tls.csr"),
        "-subj",
        "/CN=disposable-k339",
    )
    (tmp_path / "extensions").write_text(
        "subjectAltName=DNS:pi0.local,DNS:pi1.local,DNS:pi2.local,IP:127.0.0.1,"
        + ",".join("IP:" + ip for ip in ips)
        + "\nextendedKeyUsage=serverAuth,clientAuth\n"
    )
    openssl(
        "x509",
        "-req",
        "-in",
        str(tmp_path / "tls.csr"),
        "-CA",
        str(ca),
        "-CAkey",
        str(tmp_path / "ca.key"),
        "-CAcreateserial",
        "-out",
        str(cert),
        "-days",
        "1",
        "-extfile",
        str(tmp_path / "extensions"),
    )
    context = ssl.create_default_context(cafile=str(ca))
    context.load_cert_chain(str(cert), str(key))
    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({}), urllib.request.HTTPSHandler(context=context)
    )
    cluster = ",".join(f"n{i}=https://{ip}:2380" for i, ip in enumerate(ips[:3]))
    processes = []

    def start(index, address):
        with (tmp_path / f"{index}-{address}.log").open("w") as log:
            process = subprocess.Popen(
                [
                    binary,
                    "--name",
                    f"n{index}",
                    "--data-dir",
                    str(tmp_path / f"db{index}"),
                    "--listen-client-urls",
                    f"https://{address}:2379",
                    "--advertise-client-urls",
                    f"https://{address}:2379",
                    "--listen-peer-urls",
                    f"https://{address}:2380",
                    "--initial-advertise-peer-urls",
                    f"https://{address}:2380",
                    "--initial-cluster",
                    cluster,
                    "--initial-cluster-token",
                    "disposable-k339",
                    "--cert-file",
                    str(cert),
                    "--key-file",
                    str(key),
                    "--trusted-ca-file",
                    str(ca),
                    "--client-cert-auth",
                    "--peer-cert-file",
                    str(cert),
                    "--peer-key-file",
                    str(key),
                    "--peer-trusted-ca-file",
                    str(ca),
                    "--peer-client-cert-auth",
                    "--log-level",
                    "error",
                ],
                stdout=log,
                stderr=log,
                env={k: v for k, v in os.environ.items() if "proxy" not in k.lower()},
            )
        processes.append(process)
        return process

    def request(address, route, payload):
        req = urllib.request.Request(
            f"https://{address}:2379{route}",
            json.dumps(payload).encode(),
            {"Content-Type": "application/json"},
        )
        with opener.open(req, timeout=2) as response:
            return json.load(response)

    def ready(address):
        deadline = time.monotonic() + 20
        while True:
            try:
                return request(address, "/v3/kv/range", {"key": MODULE.encode("test-marker")})
            except (OSError, http.client.HTTPException):
                if time.monotonic() >= deadline:
                    raise
                time.sleep(0.1)

    try:
        initial = [start(i, ip) for i, ip in enumerate(ips[:3])]
        for ip in ips[:3]:
            ready(ip)
        membership = request(ips[1], "/v3/cluster/member/list", {})
        members = sorted(membership["members"], key=lambda value: value["name"])
        e = {
            "schema_version": 1,
            "k3s_version": "v1.35.4+k3s1",
            "interface": "eth0",
            "local_ipv4": ips[0],
            "cluster_id": str(membership["header"]["cluster_id"]),
            "local_member_id": str(members[0]["ID"]),
            "verified_backup": True,
            "files": {"/synthetic": "0" * 64},
            "members": [
                {
                    "id": str(value["ID"]),
                    "name": value["name"],
                    "hostname": f"pi{i}.local",
                    "node_uid": f"uid{i}",
                }
                for i, value in enumerate(members)
            ],
            "etcd_tls": {"ca": str(ca), "cert": str(cert), "key": str(key)},
        }
        request(
            ips[1],
            "/v3/kv/put",
            {"key": MODULE.encode("test-marker"), "value": MODULE.encode("persistent-data")},
        )

        class LocalBackend(MODULE.Backend):
            current_ip = ips[3]

            def config(self):
                pass  # This test does not claim real systemd/K3s configuration validation.

            def network(self, ip):
                assert ip == self.current_ip

            def refresh(self):
                pass  # The installed refresh hook has separate reboot/installation regressions.

            def active(self):
                return True

            def running(self):
                return {
                    "MainPID": str(replacement.pid),
                    "InvocationID": "synthetic",
                    "NRestarts": "0",
                }

            def address(self):
                return self.current_ip

            def resolve(self, host):
                return self.current_ip if host == "pi0.local" else ips[int(host[2])]

            def connect_peer(self, address):
                return socket.create_connection((address, 2379), timeout=2)

            def node(self, host, name):
                return {
                    "metadata": {
                        "uid": "uid0",
                        "annotations": {
                            "etcd.k3s.cattle.io/node-name": "n0",
                            "k3s.io/internal-ip": self.current_ip,
                        },
                    },
                    "status": {
                        "addresses": [{"type": "InternalIP", "address": self.current_ip}],
                        "conditions": [{"type": "Ready", "status": "True"}],
                    },
                }

        # Real certificate hostname rejection, before any recovery mutation.
        bad = copy.deepcopy(e)
        bad["members"][1]["hostname"] = "wrong.local"
        untrusted = LocalBackend(bad)
        untrusted.resolve = lambda host: ips[1]
        with pytest.raises(ssl.SSLCertVerificationError):
            untrusted.request("wrong.local", "/v3/kv/range", {"key": MODULE.encode("test-marker")})
        backend = LocalBackend(e)
        recovery = MODULE.Recovery(e, backend, tmp_path / "incident.json")
        if start_mode == "boot":
            initial[0].terminate()
            initial[0].wait(timeout=10)
            assert recovery.pre_start() == "one-start-authorized"
        else:
            assert recovery.watch() == "observing"
            observation = tmp_path / "observation.json"
            observed = json.loads(observation.read_text())
            observed["time"] -= 31
            observation.write_text(json.dumps(observed))
            assert recovery.watch() == "restart-requested"
            initial[0].terminate()
            initial[0].wait(timeout=10)
            assert recovery.pre_start() == "one-start-authorized"
        with pytest.raises(MODULE.Stop, match="unfinished"):
            recovery.pre_start()
        replacement = start(0, ips[3])  # Same database directory and persisted identity.
        ready(ips[3])
        assert recovery.post_start() == "verifying"
        time.sleep(31)  # Real stable-process verification interval in this protocol test.
        assert recovery.post_start() == "complete"
        assert recovery.pre_start() == "unchanged"
        marker = ready(ips[3])
        assert base64.b64decode(marker["kvs"][0]["value"]) == b"persistent-data"
        final = request(ips[1], "/v3/cluster/member/list", {})
        assert {str(value["ID"]) for value in final["members"]} == {
            value["id"] for value in e["members"]
        }
        assert next(v for v in final["members"] if v["name"] == "n0")["peerURLs"] == [
            f"https://{ips[3]}:2380"
        ]
        # Loss of both survivors cannot authorize another mutation/start or alter the journal.
        before = recovery.path.read_bytes()
        for process in initial[1:]:
            process.terminate()
            process.wait(timeout=10)
        backend.current_ip = ips[4]
        with pytest.raises((MODULE.Stop, OSError, http.client.HTTPException)):
            recovery.pre_start()
        assert recovery.path.read_bytes() == before
    finally:
        for process in processes:
            if process.poll() is None:
                process.terminate()
        for process in processes:
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)


def test_mutable_parent_directory_cannot_supply_root_credentials():
    from types import SimpleNamespace

    parent = SimpleNamespace(
        lstat=lambda: SimpleNamespace(st_uid=1000, st_mode=0o755), is_symlink=lambda: False
    )
    path = SimpleNamespace(
        lstat=lambda: SimpleNamespace(st_uid=0, st_mode=0o600),
        is_symlink=lambda: False,
        parents=[parent],
    )
    with pytest.raises(MODULE.Stop, match="parent directory"):
        MODULE.trusted_file(path)
    parent.lstat = lambda: SimpleNamespace(st_uid=0, st_mode=0o755)
    MODULE.trusted_file(path)


def test_new_install_directories_have_fixed_modes_and_durable_parent_entries(tmp_path, monkeypatch):
    import os
    import stat

    checked, synced = [], []
    monkeypatch.setattr(MODULE, "trusted_file", lambda path: checked.append(path))
    real_sync = os.fsync

    def sync(fd):
        synced.append(Path(os.readlink(f"/proc/self/fd/{fd}")))
        real_sync(fd)

    monkeypatch.setattr(MODULE.os, "fsync", sync)
    destination = tmp_path / "libexec" / "sugarkube"
    previous_umask = os.umask(0)
    try:
        MODULE.install_directory(destination)
    finally:
        os.umask(previous_umask)
    assert checked == [tmp_path, destination.parent, destination]
    assert synced == [
        tmp_path,
        tmp_path.parent,
        destination.parent,
        tmp_path,
        destination,
        destination.parent,
    ]
    assert stat.S_IMODE(destination.stat().st_mode) == 0o755
    assert stat.S_IMODE(destination.parent.stat().st_mode) == 0o755
    state = destination / "state"
    MODULE.install_directory(state, mode=0o700)
    assert stat.S_IMODE(state.stat().st_mode) == 0o700
    assert synced[-2:] == [state, destination]


@pytest.mark.parametrize(
    "uid,mode,symlink,is_directory",
    [
        (1000, 0o755, False, True),
        (0, 0o777, False, True),
        (0, 0o775, False, True),
        (0, 0o755, True, True),
        (0, 0o644, False, False),
    ],
)
def test_install_directory_rejects_untrusted_existing_paths(uid, mode, symlink, is_directory):
    from types import SimpleNamespace

    path = SimpleNamespace(
        exists=lambda: True,
        is_symlink=lambda: symlink,
        is_dir=lambda: is_directory,
        lstat=lambda: SimpleNamespace(st_uid=uid, st_mode=mode),
        parents=[],
    )
    with pytest.raises(MODULE.Stop):
        MODULE.install_directory(path)


def test_directory_persistence_failure_prevents_child_creation(tmp_path, monkeypatch):
    monkeypatch.setattr(MODULE, "trusted_file", lambda path: None)

    def fail(fd):
        raise OSError("directory persistence failed")

    monkeypatch.setattr(MODULE.os, "fsync", fail)
    with pytest.raises(OSError, match="persistence failed"):
        MODULE.install_directory(tmp_path / "libexec" / "sugarkube")
    assert not (tmp_path / "libexec" / "sugarkube").exists()
