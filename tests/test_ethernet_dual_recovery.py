"""Three original voters recovering independently while their API is unavailable."""

import copy
import importlib.util
import json
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location(
    "quorum_dual", Path(__file__).resolve().parents[1] / "scripts/ethernet_quorum_recover.py"
)
M = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(M)


class Cluster:
    def __init__(self):
        self.members = {
            str(i): {
                "ID": str(i),
                "name": f"member{i}",
                "peerURLs": [f"https://10.0.0.{i}:2380", f"https://pi{i}.local:2380"],
            }
            for i in range(1, 4)
        }
        self.ips = {str(i): f"10.0.0.{i+10}" for i in range(1, 4)}
        self.owner, self.failure, self.quorum = None, None, False
        self.updates, self.calls, self.api = [], [], False
        self.markers = {}


class Backend:
    def __init__(self, e, cluster):
        self.e, self.c = e, cluster
        self.enrolling = False
        self.config_bad = False

    def config(self):
        M.require(not self.config_bad, "database/config identity changed")

    def network(self, ip):
        assert ip == self.address()

    def address(self):
        return self.c.ips[self.e["local_member_id"]]

    def resolve(self, host):
        return self.c.ips[host[2]]

    def stable_address(self, ip):
        assert self.address() == ip

    def refresh(self):
        pass

    def transport_running(self):
        return True

    def running(self):
        return {"MainPID": "123", "InvocationID": "stable", "NRestarts": "0"}

    def peer_tls(self, host):
        M.require(self.c.failure != "peer-tls", "peer SAN mismatch")

    def workloads(self, host):
        M.require(self.c.failure != "workloads", "workload completion pending")

    def node(self, host, name):
        self.c.calls.append("API")
        M.require(self.c.api, "API/Node completion unavailable")
        mid = host[2]
        ip = self.c.ips[mid]
        return {
            "metadata": {
                "uid": "uid" + mid,
                "annotations": {
                    "etcd.k3s.cattle.io/node-name": "member" + mid,
                    "k3s.io/internal-ip": ip,
                },
            },
            "status": {
                "addresses": [{"type": "InternalIP", "address": ip}],
                "conditions": [{"type": "Ready", "status": "True"}],
            },
        }

    def etcd(self, host, *args, input_text=None):
        self.c.calls.append(args)
        M.require(self.c.quorum, "no quorum yet")
        mid = host[2]
        if args == ("endpoint", "status"):
            return [{"Status": {"header": {"cluster_id": "100", "member_id": mid}}}]
        if args == ("endpoint", "health"):
            return [{"health": True}]
        if args == ("member", "list"):
            return {
                "header": {"cluster_id": "100"},
                "members": copy.deepcopy(list(self.c.members.values())),
            }
        if args == ("get", M.KEY):
            return {"kvs": [{"value": M.encode(self.c.owner)}] if self.c.owner else []}
        if args[0] == "get":
            value = self.c.markers.get(args[1])
            return {"kvs": [{"value": M.encode(value)}] if value else []}
        if args == ("txn",):
            payload = json.loads(input_text)
            key = M.base64.b64decode(payload["compare"][0]["key"]).decode()
            if key != M.KEY:
                if key in self.c.markers:
                    return {"succeeded": False}
                self.c.markers[key] = M.base64.b64decode(
                    payload["success"][0]["request_put"]["value"]
                ).decode()
                M.require(self.c.failure != "marker", "unknown marker outcome")
                return {"succeeded": True}
            release = payload["compare"][0]["target"] == "VALUE"
            if not release:
                if self.c.owner:
                    return {"succeeded": False}
                self.c.owner = M.base64.b64decode(
                    payload["success"][0]["request_put"]["value"]
                ).decode()
                M.require(self.c.failure != "acquire", "unknown acquisition")
            else:
                incident_owner = M.base64.b64decode(payload["compare"][0]["value"]).decode()
                assert self.c.owner == incident_owner
                self.c.owner = None
                M.require(self.c.failure != "release", "unknown release")
            return {"succeeded": True}
        assert args[:2] == ("member", "update")
        target = str(int(args[2], 16))
        assert target == self.e["local_member_id"]
        self.c.updates.append(target)
        if self.c.failure != "before-update":
            self.c.members[target]["peerURLs"] = args[3].removeprefix("--peer-urls=").split(",")
        M.require(
            self.c.failure not in ("after-update", "before-update"), "unknown membership update"
        )
        return {"header": {"cluster_id": "100", "member_id": mid}}


@pytest.fixture
def recovery(tmp_path):
    cluster = Cluster()
    result = []
    for mid in ("1", "2", "3"):
        e = {
            "schema_version": 2,
            "armed": True,
            "k3s_version": "v1.35.4+k3s1",
            "interface": "eth0",
            "cluster_id": "100",
            "local_member_id": mid,
            "local_ipv4": f"10.0.0.{mid}",
            "verified_backup": True,
            "files": {"/synthetic": "0" * 64},
            "members": [
                {
                    "id": str(i),
                    "name": f"member{i}",
                    "hostname": f"pi{i}.local",
                    "node_uid": f"uid{i}",
                }
                for i in range(1, 4)
            ],
            "completion_https_urls": ["https://application.example/health"],
        }
        directory = tmp_path / mid
        directory.mkdir()
        result.append(M.DualRecovery(e, Backend(e, cluster), directory / "incident.json"))
    return cluster, result


def test_all_three_start_before_quorum_then_repair_before_api(recovery):
    cluster, voters = recovery
    for voter in voters:
        assert voter.pre_start() == "one-start-authorized"
    assert cluster.calls == [] and cluster.owner is None
    cluster.quorum = True
    for voter in voters:
        assert voter.watch() == "completion-pending"
        assert cluster.owner is None
        assert "API" not in cluster.calls
        with pytest.raises(M.Stop, match="completion unavailable"):
            voter.post_start()
        cluster.calls.clear()
    assert cluster.updates == ["1", "2", "3"]
    for mid, member in cluster.members.items():
        assert member["ID"] == mid and member["peerURLs"] == [
            f"https://10.0.0.{int(mid)+10}:2380",
            f"https://pi{mid}.local:2380",
        ]
    cluster.api = True
    for voter in voters:
        assert voter.post_start() == "verifying"
        incident = voter.previous()
        incident["verified_at_monotonic"] -= 31
        M.atomic_json(voter.path, incident)
        assert voter.post_start() == "complete"


def test_definitive_false_cas_waits_without_dispatch_or_lock_takeover(recovery):
    cluster, voters = recovery
    voter = voters[0]
    voter.pre_start()
    cluster.quorum, cluster.owner = True, "other-original-member"
    assert voter.watch() == "waiting-for-lock"
    saved = voter.previous()
    assert saved["mutation_dispatched"] is False
    assert voter.watch() == "waiting-for-lock"
    assert cluster.updates == [] and cluster.owner == "other-original-member"
    cluster.owner = None  # The owner releases, never a timeout/lease takeover.
    assert voter.watch() == "completion-pending"
    assert cluster.updates == ["1"] and cluster.owner is None


@pytest.mark.parametrize("failure", ["acquire", "before-update", "after-update", "release"])
def test_unknown_outcomes_stay_latched_without_watcher_replay(recovery, failure):
    cluster, voters = recovery
    voter = voters[0]
    voter.pre_start()
    cluster.quorum, cluster.failure = True, failure
    with pytest.raises(M.Stop, match="unknown"):
        voter.watch()
    saved, calls = voter.path.read_bytes(), copy.deepcopy(cluster.calls)
    cluster.failure = None
    with pytest.raises(M.Stop, match="latched"):
        voter.watch()
    assert voter.path.read_bytes() == saved and cluster.calls == calls
    if failure == "before-update":
        with pytest.raises(M.Stop, match="not confirmed"):
            voter.resume()
        assert cluster.updates == ["1"] and cluster.owner is not None
    else:
        assert voter.resume() == "completion-pending"
        assert cluster.updates == ["1"] and cluster.owner is None


def test_interrupted_restart_preserves_unknown_membership_intent(recovery):
    cluster, voters = recovery
    voter = voters[0]
    voter.pre_start()
    cluster.quorum, cluster.failure = True, "after-update"
    with pytest.raises(M.Stop):
        voter.watch()
    intent = voter.previous()
    cluster.quorum = False
    assert voter.resume_transport() == "operator-restart-requested"
    assert voter.pre_start() == "one-start-authorized"
    assert voter.previous()["phase"] == intent["phase"] == "membership-intent"
    with pytest.raises(M.Stop, match="unfinished"):
        voter.pre_start()
    cluster.quorum, cluster.failure = True, None
    assert voter.resume() == "completion-pending"
    assert cluster.updates == ["1"]


def test_database_or_second_address_change_never_restarts_or_mutates(recovery):
    cluster, voters = recovery
    voter = voters[0]
    voter.b.config_bad = True
    with pytest.raises(M.Stop, match="identity changed"):
        voter.pre_start()
    assert not voter.path.exists()
    voter.b.config_bad = False
    voter.pre_start()
    saved = voter.path.read_bytes()
    cluster.quorum = True
    cluster.ips["1"] = "10.0.0.99"
    with pytest.raises(M.Stop, match="address changed"):
        voter.watch()
    assert voter.path.read_bytes() == saved and cluster.updates == []


def test_unarmed_cluster_cannot_start_after_address_change(recovery):
    cluster, voters = recovery
    voter = voters[0]
    voter.e["armed"] = False
    with pytest.raises(M.Stop, match="not armed"):
        voter.pre_start()
    assert not voter.path.exists() and not cluster.calls


def prepare_enrollment(cluster, voters):
    cluster.quorum = cluster.api = True
    for voter in voters:
        voter.e["armed"] = False
        mid = voter.local["id"]
        cluster.ips[mid] = voter.e["local_ipv4"]
        cluster.members[mid]["peerURLs"] = [f"https://{cluster.ips[mid]}:2380"]


def test_healthy_rolling_dual_enrollment_arms_only_after_all_three(recovery):
    cluster, voters = recovery
    prepare_enrollment(cluster, voters)
    for index, voter in enumerate(voters):
        assert voter.enroll_peer() == "peer-enrolled"
        voter.e["dual_enrolled"] = True
        assert cluster.owner is None
        if index < 2:
            with pytest.raises(M.Stop):
                voter.arm()
    for voter in voters:
        assert voter.arm() == "armed"
        voter.e["armed"] = True
        assert voter.pre_start() == "unchanged"
    assert cluster.updates == ["1", "2", "3"]
    assert len(cluster.markers) == 3


def test_wrong_peer_tls_cannot_enroll_or_mutate(recovery):
    cluster, voters = recovery
    prepare_enrollment(cluster, voters)
    cluster.failure = "peer-tls"
    with pytest.raises(M.Stop, match="SAN mismatch"):
        voters[0].enroll_peer()
    assert cluster.updates == [] and cluster.owner is None and not voters[0].path.exists()


@pytest.mark.parametrize("failure", ["after-update", "marker"])
def test_interrupted_enrollment_requires_explicit_readback_not_replay(recovery, failure):
    cluster, voters = recovery
    prepare_enrollment(cluster, voters)
    voter = voters[0]
    cluster.failure = failure
    with pytest.raises(M.Stop, match="unknown"):
        voter.enroll_peer()
    before = voter.path.read_bytes()
    cluster.failure = None
    with pytest.raises(M.Stop):
        voter.enroll_peer()
    assert voter.path.read_bytes() == before
    assert voter.enroll_peer(resume=True) == "peer-enrolled"
    assert cluster.updates == ["1"] and cluster.owner is None


def test_native_client_url_publication_does_not_change_membership_identity(recovery):
    cluster, voters = recovery
    voter = voters[0]
    voter.pre_start()
    cluster.quorum, cluster.failure = True, "after-update"
    with pytest.raises(M.Stop, match="unknown"):
        voter.watch()
    for member in cluster.members.values():
        member["clientURLs"] = ["https://10.0.0.99:2379"]
    cluster.failure = None
    assert voter.resume() == "completion-pending"
    assert cluster.updates == ["1"] and cluster.owner is None


@pytest.mark.parametrize("drift", ["peer", "name", "role", "identity"])
def test_other_member_drift_blocks_unknown_update_resumption(recovery, drift):
    cluster, voters = recovery
    voter = voters[0]
    voter.pre_start()
    cluster.quorum, cluster.failure = True, "after-update"
    with pytest.raises(M.Stop):
        voter.watch()
    saved = voter.path.read_bytes()
    member = cluster.members["2"]
    if drift == "peer":
        member["peerURLs"][0] = "https://10.0.0.92:2380"
    elif drift == "name":
        member["name"] = "replacement"
    elif drift == "role":
        member["isLearner"] = True
    else:
        member["ID"] = "99"
    cluster.failure = None
    with pytest.raises(M.Stop):
        voter.resume()
    assert voter.path.read_bytes() == saved
    assert cluster.updates == ["1"] and cluster.owner is not None


@pytest.mark.parametrize("failure", ["stale-status", "wrong-uid", "workloads"])
def test_completion_failure_leaves_lock_free_for_remaining_members(recovery, failure):
    cluster, voters = recovery
    voter = voters[0]
    voter.pre_start()
    cluster.quorum = cluster.api = True
    assert voter.watch() == "completion-pending"
    original = voter.b.node

    def changed_node(host, name):
        node = original(host, name)
        if failure == "stale-status":
            node["status"]["addresses"][0]["address"] = "10.0.0.1"
        if failure == "wrong-uid":
            node["metadata"]["uid"] = "replacement"
        return node

    voter.b.node = changed_node
    cluster.failure = failure
    with pytest.raises(M.Stop):
        voter.post_start()
    assert voter.previous()["phase"] == "completion-pending"
    assert cluster.owner is None
    cluster.failure = None
    for other in voters[1:]:
        other.pre_start()
        assert other.watch() == "completion-pending"
    assert cluster.updates == ["1", "2", "3"] and cluster.owner is None


@pytest.mark.parametrize(
    "url",
    [
        "https://user:example@app.example/health",
        "https://@app.example/health",
        "https://:example@app.example/health",
        "http://app.example/health",
        "https://10.0.0.1/health",
        "https://app.example:6443/health",
        "https://app.example/health?secret=example",
    ],
)
def test_completion_url_rejects_credentials_and_control_plane_targets(recovery, url):
    _, voters = recovery
    enrollment = copy.deepcopy(voters[0].e)
    enrollment["completion_https_urls"] = [url]
    with pytest.raises(M.Stop):
        M.validate_enrollment(enrollment)


def interleave_acquisition(voter, change, *, release=None):
    """Finish another owner's action before our acquisition response, without threads."""
    original = voter.b.etcd
    fired = False

    def interleaved(host, *args, input_text=None):
        nonlocal fired
        if args == ("txn",):
            payload = json.loads(input_text)
            if payload["compare"][0]["target"] == "VERSION" and not fired:
                fired = True
                change()
            elif payload["compare"][0]["target"] == "VALUE" and release:
                return release(original, host, args, input_text)
        return original(host, *args, input_text=input_text)

    voter.b.etcd = interleaved


def concurrent_peer_completion(cluster):
    cluster.members["2"]["peerURLs"] = [
        "https://10.0.0.12:2380",
        "https://pi2.local:2380",
    ]


def test_known_concurrent_completion_releases_then_reproves_on_next_invocation(recovery):
    cluster, voters = recovery
    voter = voters[0]
    voter.pre_start()
    cluster.quorum = True
    interleave_acquisition(voter, lambda: concurrent_peer_completion(cluster))
    assert voter.watch() == "waiting-for-lock"
    assert cluster.owner is None and cluster.updates == []
    assert voter.previous()["mutation_dispatched"] is False
    assert sum(call == ("txn",) for call in cluster.calls) == 2
    cluster.calls.clear()
    assert voter.watch() == "completion-pending"
    assert ("endpoint", "health") in cluster.calls
    assert cluster.updates == ["1"] and cluster.owner is None


@pytest.mark.parametrize("drift", ["locator", "name", "role", "identity", "local"])
def test_unexpected_concurrent_membership_never_releases_or_mutates(recovery, drift):
    cluster, voters = recovery
    voter = voters[0]
    voter.pre_start()
    cluster.quorum = True

    def change():
        concurrent_peer_completion(cluster)
        member = cluster.members["2"]
        if drift == "locator":
            member["peerURLs"][0] = "https://10.0.0.99:2380"
        elif drift == "name":
            member["name"] = "replacement"
        elif drift == "role":
            member["isLearner"] = True
        elif drift == "identity":
            member["ID"] = "99"
        else:
            cluster.members["1"]["peerURLs"][0] = "https://10.0.0.11:2380"

    interleave_acquisition(voter, change)
    with pytest.raises(M.Stop):
        voter.watch()
    assert voter.previous()["phase"] == "lock-owned"
    assert voter.previous()["mutation_dispatched"] is False
    assert cluster.owner is not None and cluster.updates == []
    assert sum(call == ("txn",) for call in cluster.calls) == 1


@pytest.mark.parametrize("outcome", ["false", "unknown-before", "unknown-after"])
def test_pre_mutation_release_not_confirmed_never_retries_or_clears(recovery, outcome):
    cluster, voters = recovery
    voter = voters[0]
    voter.pre_start()
    cluster.quorum = True

    def release(original, host, args, input_text):
        if outcome == "false":
            cluster.owner = "different-owner"
            return {"succeeded": False}
        if outcome == "unknown-after":
            original(host, *args, input_text=input_text)
        raise M.Stop("unknown release result")

    interleave_acquisition(voter, lambda: concurrent_peer_completion(cluster), release=release)
    with pytest.raises(M.Stop):
        voter.watch()
    assert voter.previous()["phase"] == "pre-mutation-release-intent"
    assert voter.previous()["mutation_dispatched"] is False
    saved = voter.path.read_bytes()
    calls = copy.deepcopy(cluster.calls)
    with pytest.raises(M.Stop, match="latched"):
        voter.watch()
    assert cluster.calls == calls and voter.path.read_bytes() == saved
    # Even explicit resume cannot treat a no-mutation release as completion.
    with pytest.raises(M.Stop):
        voter.resume()
    assert voter.path.read_bytes() == saved and cluster.updates == []
    if outcome == "false":
        assert cluster.owner == "different-owner"
    elif outcome == "unknown-before":
        assert cluster.owner == voter.previous()["token"]
    else:
        assert cluster.owner is None


def test_unknown_acquisition_during_concurrent_progress_never_releases(recovery):
    cluster, voters = recovery
    voter = voters[0]
    voter.pre_start()
    cluster.quorum, cluster.failure = True, "acquire"
    interleave_acquisition(voter, lambda: concurrent_peer_completion(cluster))
    with pytest.raises(M.Stop, match="unknown acquisition"):
        voter.watch()
    assert voter.previous()["phase"] == "lock-acquire-intent"
    assert voter.previous()["mutation_dispatched"] is False
    saved = voter.path.read_bytes()
    cluster.failure = None
    with pytest.raises(M.Stop, match="latched"):
        voter.watch()
    assert voter.path.read_bytes() == saved and cluster.owner is not None
    assert cluster.updates == []
    assert sum(call == ("txn",) for call in cluster.calls) == 1
