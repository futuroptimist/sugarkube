"""Offline planner tests: fabricated evidence is not K3s qualification."""

import copy
import importlib.util
import io
import json
import socket
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "migration_plan", ROOT / "scripts/ethernet_migration_plan.py"
)
M = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(M)
FIXTURES = ROOT / "tests/fixtures/ethernet_migration"


def record(digest=None, kind="file", mode=0o644, digest_kind="raw-sha256"):
    return {
        "sha256": digest,
        "digest_kind": "none" if digest is None else digest_kind,
        "kind": kind,
        "uid": 0,
        "gid": 0,
        "mode": mode,
    }


def synthetic_kubeconfig():
    return {
        "apiVersion": "v1",
        "kind": "Config",
        "preferences": {},
        "clusters": [
            {
                "name": "default",
                "cluster": {
                    "server": "https://127.0.0.1:6443",
                    "certificate-authority-data": "synthetic-ca",
                },
            }
        ],
        "contexts": [{"name": "default", "context": {"cluster": "default", "user": "default"}}],
        "current-context": "default",
        "users": [
            {
                "name": "default",
                "user": {
                    "client-certificate-data": "synthetic-certificate-A",
                    "client-key-data": "synthetic-private-material-A",
                },
            }
        ],
    }


def sample():
    catalog = M.parse(M.CATALOG.read_bytes())
    e = {
        "schema_version": 2,
        "k3s_version": "v1.35.4+k3s1",
        "interface": "eth0",
        "local_ipv4": "192.0.2.1",
        "cluster_id": "100",
        "local_member_id": "1",
        "verified_backup": True,
        "armed": True,
        "dual_enrolled": True,
        "pod_resolv_source": "/run/systemd/resolve/resolv.conf",
        "local_database": {
            "member_id": "1",
            "cluster_id": "100",
            "device": 1,
            "inode": 42,
            "name_sha256": M.sha(b"member1"),
        },
        "machine_id_sha256": "a" * 64,
        "systemd_sha256": "b" * 64,
        "yaml_fragments": [],
        "completion_https_urls": ["https://workload.example.test"],
        "kubeconfig": "/etc/rancher/k3s/k3s.yaml",
        "etcd_tls": {
            "ca": "/var/lib/rancher/k3s/server/tls/etcd/server-ca.crt",
            "cert": "/var/lib/rancher/k3s/server/tls/etcd/client.crt",
            "key": "/var/lib/rancher/k3s/server/tls/etcd/client.key",
        },
        "members": [
            {"id": str(i), "name": f"member{i}", "hostname": f"pi{i}.local", "node_uid": f"uid{i}"}
            for i in range(1, 4)
        ],
    }
    view = {**M.VIEW, "uid": 0, "gid": 0}
    artifacts = M.artifacts(catalog, e, "source", view)
    e["files"] = {
        p: h
        for p, h in artifacts.items()
        if p
        in {
            M.CONFIG,
            "/usr/local/libexec/sugarkube/ethernet_mdns_resolver.py",
            "/etc/systemd/system/sugarkube-ethernet-dns.service",
            "/etc/systemd/system/k3s.service.d/25-sugarkube-resolver.conf",
            "/etc/rancher/k3s/config.yaml.d/21-sugarkube-resolver.yaml",
        }
    }
    for path in [
        e["kubeconfig"],
        e["etcd_tls"]["ca"],
        "/var/lib/rancher/k3s/server/tls/etcd/peer-ca.crt",
        "/etc/rancher/k3s/sugarkube-network-prestart.sh",
        "/etc/systemd/system/k3s.service.d/20-sugarkube-network.conf",
    ]:
        e["files"][path] = "c" * 64
    e["files"]["/etc/rancher/k3s/optional.env"] = None
    e["files"][e["kubeconfig"]] = M.kubeconfig_inventory_digest(synthetic_kubeconfig())
    members = {}
    for member in e["members"]:
        mid = member["id"]
        address = f"192.0.2.{mid}"
        marker = {
            "schema_version": 2,
            "cluster_id": "100",
            "member_id": mid,
            "node_uid": member["node_uid"],
            "hostname": member["hostname"],
            "k3s_version": e["k3s_version"],
            "roster_sha256": M.sha(json.dumps(e["members"], sort_keys=True).encode()),
        }
        members[mid] = {k: member[k] for k in ("name", "hostname", "node_uid")}
        members[mid].update(
            node_name=f"pi{mid}",
            ipv4=address,
            internal_ip=address,
            annotation_ip=address,
            ready=True,
            learner=False,
            peer_urls=[f"https://{address}:2380", f"https://pi{mid}.local:2380"],
            marker_sha256=M.sha(json.dumps(marker, sort_keys=True).encode()),
        )
    raw = json.dumps(e, sort_keys=True)
    incident = {
        "token": M.sha(b"synthetic-journal-marker")[:32],
        "phase": "complete",
        "created_at": 1,
        "kind": "enrollment",
        "transport": "not-needed",
        "ip": e["local_ipv4"],
        "member_id": "1",
        "cluster_id": "100",
        "mutation_dispatched": False,
        "old_peer_urls": members["1"]["peer_urls"],
    }
    journal = json.dumps(incident, sort_keys=True)
    state = {
        "/etc/rancher/k3s/sugarkube-recovery.json": record(M.sha(raw.encode())),
        "/var/lib/sugarkube/ethernet-recovery/incident.json": record(M.sha(journal.encode())),
        "/var/lib/sugarkube/ethernet-recovery/node-address.json": record(None, "absent"),
    }
    observed = {
        p: record(
            h,
            "absent" if h is None else "file",
            digest_kind=M.KUBECONFIG_DIGEST_KIND if p == e["kubeconfig"] else "raw-sha256",
        )
        for p, h in {**e["files"], **artifacts}.items()
    }
    parents = {str(parent) for p in {*observed, *state} for parent in Path(p).parents}
    parents.update({"/run", "/run/systemd"})
    digest = M.sha(M.canonical(members))
    return {
        "schema_version": 1,
        "source_revision": catalog["revisions"]["source"],
        "capture_id": "d" * 64,
        "enrollment_json": raw,
        "observed": observed,
        "identity": {
            k: e[k]
            for k in ("machine_id_sha256", "systemd_sha256", "local_database", "k3s_version")
        },
        "state_metadata": state,
        "directories": {p: record(None, "directory", 0o755) for p in parents},
        "layout": {
            "descriptor": view,
            "runtime_view_absent": True,
            "directory": record(None, "directory", 0o755),
            "entries": {
                name: record(
                    None if name.startswith("io.") else "e" * 64,
                    "socket" if name.startswith("io.") else "file",
                    0o666 if name.startswith("io.") else 0o644,
                )
                for name in (
                    "resolv.conf",
                    "stub-resolv.conf",
                    "io.systemd.Resolve",
                    "io.systemd.Resolve.Monitor",
                )
            },
        },
        "health": {
            "capture_id": "d" * 64,
            "cluster_id": "100",
            "members": members,
            "lock_absent": True,
            "responders": {
                mid: {
                    "cluster_id": "100",
                    "member_id": mid,
                    "members_sha256": digest,
                    "linearizable_read": True,
                    "peer_tls_verified": True,
                    "api_verified": True,
                    "membership_intent": "none",
                    "node_address_intent": "none",
                }
                for mid in members
            },
        },
        "backup": {
            "capture_id": "d" * 64,
            "cluster_id": "100",
            "enrollment_sha256": M.sha(raw.encode()),
            "members_sha256": digest,
            "snapshot_sha256": "f" * 64,
            "original_bundle_sha256": "a" * 64,
            "verified": True,
        },
        "journals": {"incident_json": journal, "node_address_json": None},
        "quiescence": {"timer_paused": True, "controller_idle": True, "mutation_state": "none"},
    }


@pytest.fixture
def evidence():
    return sample()


def update_enrollment(bundle, key, value):
    e = json.loads(bundle["enrollment_json"])
    e[key] = value
    bundle["enrollment_json"] = json.dumps(e, sort_keys=True)
    digest = M.sha(bundle["enrollment_json"].encode())
    bundle["state_metadata"]["/etc/rancher/k3s/sugarkube-recovery.json"]["sha256"] = digest
    bundle["backup"]["enrollment_sha256"] = digest


def update_journal(bundle, **changes):
    incident = json.loads(bundle["journals"]["incident_json"])
    incident.update(changes)
    bundle["journals"]["incident_json"] = json.dumps(incident, sort_keys=True)
    bundle["state_metadata"]["/var/lib/sugarkube/ethernet-recovery/incident.json"]["sha256"] = (
        M.sha(bundle["journals"]["incident_json"].encode())
    )


def test_valid_deterministic_read_only_plan(evidence, monkeypatch):
    before = copy.deepcopy(evidence)

    def forbidden(*args, **kwargs):
        pytest.fail("planner attempted an external operation")

    monkeypatch.setattr(subprocess, "run", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setattr(socket, "socket", forbidden)
    monkeypatch.setattr(Path, "write_bytes", forbidden)
    monkeypatch.setattr(Path, "write_text", forbidden)
    result = M.plan(evidence)
    assert result == M.plan(json.loads(json.dumps(evidence, sort_keys=True)))
    assert evidence == before
    assert result["eligible_for_plan"] is True
    assert result["authorized_to_execute"] is False
    assert len(result["transitions"]) == 5
    assert result["old_descriptor"] is None
    assert {t["path"] for t in result["transitions"]} == {
        M.CONFIG,
        "/usr/local/libexec/sugarkube/ethernet_mdns_resolver.py",
        "/usr/local/libexec/sugarkube/ethernet-quorum-recover.py",
        "/etc/systemd/system/sugarkube-ethernet-dns.service",
        "/etc/systemd/system/k3s.service.d/25-sugarkube-resolver.conf",
    }


@pytest.mark.parametrize("label", ["source", "target"])
def test_known_rendered_bytes(label, evidence):
    catalog = M.parse(M.CATALOG.read_bytes())
    e = M.parse(evidence["enrollment_json"])
    artifacts = M.artifacts(catalog, e, label, evidence["layout"]["descriptor"])
    for fixture in FIXTURES.glob(f"{label}-*"):
        name = fixture.name.removeprefix(label + "-")
        path = next(p for p in artifacts if Path(p).name == name)
        assert artifacts[path] == M.sha(fixture.read_bytes())
    if label == "target":
        for path, digest in catalog["artifacts"][label]["runtime_sha256"].items():
            name = Path(path).name.replace(
                "ethernet-quorum-recover.py", "ethernet_quorum_recover.py"
            )
            historical = FIXTURES / ("target-" + Path(path).name)
            source = historical if historical.exists() else ROOT / "scripts" / name
            assert M.sha(source.read_bytes()) == digest


@pytest.mark.parametrize(
    "path,value",
    [
        (("source_revision",), "unknown"),
        (("schema_version",), True),
        (("extra",), "unknown"),
        (("backup", "verified"), False),
        (("backup", "snapshot_sha256"), ""),
        (("backup", "cluster_id"), "101"),
        (("backup", "capture_id"), "b" * 64),
        (("health", "lock_absent"), False),
        (("health", "responders", "1", "linearizable_read"), False),
        (("health", "responders", "2", "api_verified"), False),
        (("health", "responders", "3", "members_sha256"), "a" * 64),
        (("health", "members", "1", "node_uid"), "replacement"),
        (("health", "members", "1", "peer_urls"), ["https://192.0.2.1:2380"]),
        (("health", "members", "1", "annotation_ip"), "192.0.2.20"),
        (("health", "members", "1", "ready"), False),
        (("health", "members", "1", "marker_sha256"), "b" * 64),
        (("health", "members", "1", "learner"), True),
        (("identity", "machine_id_sha256"), "a" * 63),
        (("quiescence", "mutation_state"), "unknown"),
        (("quiescence", "controller_idle"), False),
        (("quiescence", "timer_paused"), False),
        (("layout", "runtime_view_absent"), False),
        (("layout", "descriptor", "symlink"), "/run/systemd/resolve/stub-resolv.conf"),
        (("layout", "descriptor", "uid"), True),
        (("layout", "entries", "resolv.conf", "kind"), "symlink"),
        (("layout", "entries", "resolv.conf", "mode"), 0o666),
        (("layout", "directory", "mode"), 0o777),
        (("directories", "/etc", "kind"), "symlink"),
        (("directories", "/run/systemd", "kind"), "symlink"),
        (("directories", "/run", "uid"), 1000),
        (("directories", "/etc", "uid"), 1000),
        (("observed", M.CONFIG, "sha256"), "b" * 64),
        (("observed", M.CONFIG, "kind"), "absent"),
        (("observed", M.CONFIG, "mode"), 0o666),
        (
            (
                "observed",
                "/etc/systemd/system/k3s.service.d/30-sugarkube-quorum-recovery.conf",
                "sha256",
            ),
            "a" * 64,
        ),
        (
            ("observed", "/usr/local/libexec/sugarkube/ethernet-quorum-recover.py", "sha256"),
            "a" * 64,
        ),
        (
            ("state_metadata", "/var/lib/sugarkube/ethernet-recovery/incident.json", "kind"),
            "symlink",
        ),
        (("journals", "node_address_json"), '{"phase":"verified"}'),
    ],
)
def test_rejection_matrix(evidence, path, value):
    cursor = evidence
    for key in path[:-1]:
        cursor = cursor[key]
    cursor[path[-1]] = value
    with pytest.raises(M.Refused):
        M.plan(evidence)


@pytest.mark.parametrize(
    "key,value",
    [
        ("schema_version", 1),
        ("armed", False),
        ("dual_enrolled", False),
        ("resolver_view", None),
        ("unknown", "secret"),
        ("pod_resolv_source", "/etc/resolv.conf"),
        ("k3s_version", "other"),
        ("verified_backup", False),
        ("local_database", {}),
        ("completion_https_urls", ["https://user:secret@example.test"]),
        ("completion_https_urls", ["https://192.0.2.1"]),
        ("interface", "wlan0"),
    ],
)
def test_enrollment_refusals(evidence, key, value):
    update_enrollment(evidence, key, value)
    with pytest.raises(M.Refused):
        M.plan(evidence)


@pytest.mark.parametrize("key", ["id", "name", "hostname", "node_uid"])
def test_duplicate_identities(evidence, key):
    members = json.loads(evidence["enrollment_json"])["members"]
    members[1][key] = members[0][key]
    update_enrollment(evidence, "members", members)
    with pytest.raises(M.Refused, match="duplicate"):
        M.plan(evidence)


@pytest.mark.parametrize(
    "path", ["relative", "/etc/../etc/x", "//etc/x", "/etc//x", "/etc/x/", "/etc/./x"]
)
def test_ambiguous_paths(evidence, path):
    files = json.loads(evidence["enrollment_json"])["files"]
    files[path] = "a" * 64
    update_enrollment(evidence, "files", files)
    with pytest.raises(M.Refused, match="path"):
        M.plan(evidence)


@pytest.mark.parametrize(
    "phase",
    ["membership-intent", "release-intent", "enrollment-marker-intent", "verifying", "unknown"],
)
def test_interrupted_journals(evidence, phase):
    update_journal(evidence, phase=phase)
    with pytest.raises(M.Refused, match="unresolved"):
        M.plan(evidence)


def test_completed_mutation_consistency(evidence):
    members = evidence["health"]["members"]
    before = {
        mid: {"ID": mid, "name": row["name"], "isLearner": False, "peerURLs": row["peer_urls"]}
        for mid, row in members.items()
    }
    before["1"]["peerURLs"] = members["1"]["peer_urls"][:1]
    update_journal(
        evidence,
        mutation_dispatched=True,
        before_members=before,
        desired_peer_urls=members["1"]["peer_urls"],
        old_peer_urls=before["1"]["peerURLs"],
    )
    assert M.plan(evidence)["eligible_for_plan"]
    before["2"]["name"] = "replacement"
    update_journal(evidence, before_members=before)
    with pytest.raises(M.Refused, match="inconsistent"):
        M.plan(evidence)


@pytest.mark.parametrize(
    "key",
    [
        "backup",
        "health",
        "journals",
        "state_metadata",
        "directories",
        "observed",
        "layout",
        "identity",
    ],
)
def test_missing_evidence(evidence, key):
    del evidence[key]
    with pytest.raises(M.Refused):
        M.plan(evidence)


def test_secret_non_disclosure(evidence, capsys, monkeypatch):
    secret = M.sha(b"private-journal-material")[:32]
    update_journal(evidence, **{"token": secret})
    assert secret not in json.dumps(M.plan(evidence))
    update_journal(evidence, phase=secret)
    monkeypatch.setattr(
        M.sys, "stdin", type("Input", (), {"buffer": io.BytesIO(json.dumps(evidence).encode())})()
    )
    assert M.main(["-"]) == 2
    assert secret not in capsys.readouterr().out


@pytest.mark.parametrize("raw", ['{"a":1,"a":2}', '{"a":NaN}', "{", '"bad"'])
def test_malformed_json(raw):
    with pytest.raises(M.Refused):
        M.plan(M.parse(raw))


def test_cli_read_only_and_no_apply(evidence, tmp_path):
    source = tmp_path / "capture.json"
    source.write_text(json.dumps(evidence))
    before = source.read_bytes()
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts/ethernet_migration_plan.py"), str(source)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert json.loads(result.stdout)["authorized_to_execute"] is False
    assert source.read_bytes() == before
    assert list(tmp_path.iterdir()) == [source]
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts/ethernet_migration_plan.py"), "--apply", str(source)],
        capture_output=True,
    )
    assert result.returncode == 2


def test_sample_fixture_matches_documented_contract():
    assert M.parse((FIXTURES / "synthetic-capture.json").read_bytes()) == sample()


@pytest.mark.parametrize(
    "path",
    [
        ("quiescence", "controller_idle"),
        ("quiescence", "timer_paused"),
        ("health", "responders", "1", "api_verified"),
    ],
)
def test_boolean_schema_drift(evidence, path):
    cursor = evidence
    for key in path[:-1]:
        cursor = cursor[key]
    cursor[path[-1]] = 1
    with pytest.raises(M.Refused):
        M.plan(evidence)


def test_catalog_is_pinned(evidence, tmp_path, monkeypatch):
    catalog = M.parse(M.CATALOG.read_bytes())
    catalog["revisions"]["target"] = "operator-target"
    replacement = tmp_path / "manifest.json"
    replacement.write_text(json.dumps(catalog))
    monkeypatch.setattr(M, "CATALOG", replacement)
    with pytest.raises(M.Refused, match="catalog"):
        M.plan(evidence)


def test_plan_never_reads_paths_in_capture(evidence, monkeypatch):
    read = Path.open

    def restricted(path, *args, **kwargs):
        assert path == M.CATALOG
        assert kwargs.get("mode", args[0] if args else None) == "rb"
        return read(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", restricted)
    assert M.plan(evidence)["eligible_for_plan"]


def test_enrollment_commitment_changes_only_allowed_fields(evidence):
    original = M.parse(evidence["enrollment_json"])
    planned = copy.deepcopy(original)
    result = M.plan(evidence)
    planned["resolver_view"] = result["new_descriptor"]
    for transition in result["transitions"]:
        if transition["enrolled_fingerprint"]:
            planned["files"][transition["path"]] = transition["new_sha256"]
    assert result["new_enrollment_canonical_sha256"] == M.sha(M.canonical(planned))
    assert result["old_enrollment_sha256"] == M.sha(evidence["enrollment_json"].encode())
    assert result["journals_sha256"] == M.sha(M.canonical(evidence["journals"]))


@pytest.mark.parametrize(
    "key,value",
    [
        ("created_at", True),
        ("created_at", -1),
        ("token", "unknown"),
        ("unknown", True),
        ("cluster_id", "200"),
        ("member_id", "2"),
        ("mutation_dispatched", "unknown"),
    ],
)
def test_unknown_or_inconsistent_journal(evidence, key, value):
    update_journal(evidence, **{key: value})
    with pytest.raises(M.Refused):
        M.plan(evidence)


def test_cli_error_redacts_path(capsys):
    assert M.main(["/missing/private-secret-name"]) == 2
    assert "private-secret-name" not in capsys.readouterr().out


def test_cli_success(evidence, monkeypatch, capsys):
    monkeypatch.setattr(
        M.sys, "stdin", type("Input", (), {"buffer": io.BytesIO(json.dumps(evidence).encode())})()
    )
    assert M.main(["-"]) == 0
    assert json.loads(capsys.readouterr().out) == M.plan(evidence)


def test_cli_size_limit(monkeypatch, capsys):
    monkeypatch.setattr(
        M.sys, "stdin", type("Input", (), {"buffer": io.BytesIO(b" " * (8 * 1024 * 1024 + 1))})()
    )
    assert M.main(["-"]) == 2
    assert "size limit" in capsys.readouterr().out


def test_malformed_nested_evidence_is_redacted(evidence):
    evidence["layout"]["entries"]["resolv.conf"] = None
    with pytest.raises(M.Refused, match="malformed or unsupported captured evidence"):
        M.plan(evidence)


def test_file_entrypoint_preserves_capture(evidence, tmp_path, monkeypatch, capsys):
    import runpy

    source = tmp_path / "capture.json"
    source.write_text(json.dumps(evidence))
    before = source.read_bytes()
    script = ROOT / "scripts/ethernet_migration_plan.py"
    monkeypatch.setattr(M.sys, "argv", [str(script), str(source)])
    with pytest.raises(SystemExit) as result:
        runpy.run_path(str(script), run_name="__main__")
    assert result.value.code == 0
    assert json.loads(capsys.readouterr().out) == M.plan(evidence)
    assert source.read_bytes() == before
    assert list(tmp_path.iterdir()) == [source]


def test_kubeconfig_inventory_normalizes_only_rotating_leaves(evidence):
    config = synthetic_kubeconfig()
    original = copy.deepcopy(config)
    normalized = copy.deepcopy(config)
    normalized["users"][0]["user"] = {
        "client-certificate-data": "rotating-client-credential",
        "client-key-data": "rotating-client-credential",
    }
    expected_bytes = json.dumps(normalized, sort_keys=True).encode()
    digest = M.kubeconfig_inventory_digest(config)
    assert digest == M.sha(expected_bytes)
    assert digest != M.sha(M.canonical(normalized))
    assert digest != M.sha(expected_bytes + b"\n")
    assert digest != M.sha(json.dumps(config, sort_keys=True).encode())
    assert config == original
    config["users"][0]["user"] = {
        "client-certificate-data": "synthetic-certificate-B",
        "client-key-data": "synthetic-private-material-B",
    }
    assert M.kubeconfig_inventory_digest(config) == digest
    e = M.parse(evidence["enrollment_json"])
    assert e["files"][e["kubeconfig"]] == digest
    result = M.plan(evidence)
    assert e["kubeconfig"] not in {t["path"] for t in result["transitions"]}
    for material in original["users"][0]["user"].values():
        assert material not in json.dumps(result)


@pytest.mark.parametrize(
    "field,value",
    [
        ("server", "https://replacement.example.test:6443"),
        ("certificate-authority-data", "replacement-ca"),
    ],
)
def test_kubeconfig_trust_changes_remain_pinned(evidence, field, value):
    config = synthetic_kubeconfig()
    config["clusters"][0]["cluster"][field] = value
    e = M.parse(evidence["enrollment_json"])
    evidence["observed"][e["kubeconfig"]]["sha256"] = M.kubeconfig_inventory_digest(config)
    with pytest.raises(M.Refused, match="modified or missing"):
        M.plan(evidence)


@pytest.mark.parametrize("kind", ["raw-sha256", "unknown", None])
def test_kubeconfig_digest_semantics_are_explicit(evidence, kind):
    path = M.parse(evidence["enrollment_json"])["kubeconfig"]
    evidence["observed"][path]["digest_kind"] = kind
    with pytest.raises(M.Refused, match="fingerprint semantics"):
        M.plan(evidence)


def test_raw_kubeconfig_hash_is_not_an_inventory_fingerprint(evidence):
    path = M.parse(evidence["enrollment_json"])["kubeconfig"]
    evidence["observed"][path]["sha256"] = M.sha(json.dumps(synthetic_kubeconfig()).encode())
    with pytest.raises(M.Refused, match="modified or missing"):
        M.plan(evidence)


@pytest.mark.parametrize(
    "damage",
    [
        "missing",
        "multiple-contexts",
        "trust-override",
        "wrong-context",
        "wrong-user",
        "missing-users",
        "external-credentials",
        "empty-credential",
        "not-json",
    ],
)
def test_kubeconfig_helper_refuses_unsupported_input_without_disclosure(damage):
    config = synthetic_kubeconfig()
    if damage == "missing":
        del config["clusters"]
    elif damage == "multiple-contexts":
        config["contexts"].append(copy.deepcopy(config["contexts"][0]))
    elif damage == "trust-override":
        config["clusters"][0]["cluster"]["insecure-skip-tls-verify"] = True
    elif damage == "wrong-context":
        config["current-context"] = "private-material"
    elif damage == "wrong-user":
        config["contexts"][0]["context"]["user"] = "private-material"
    elif damage == "missing-users":
        config["users"] = []
    elif damage == "external-credentials":
        config["users"][0]["user"] = {"client-key": "/private-material"}
    elif damage == "empty-credential":
        config["users"][0]["user"]["client-key-data"] = ""
    else:
        config["preferences"] = object()
    with pytest.raises(M.Refused) as result:
        M.kubeconfig_inventory_digest(config)
    assert "private-material" not in str(result.value)


def test_historical_database_record_is_admitted_and_preserved(evidence):
    enrollment = M.parse(evidence["enrollment_json"])
    database = enrollment["local_database"]
    assert database == {
        "member_id": "1",
        "cluster_id": "100",
        "device": 1,
        "inode": 42,
        "name_sha256": M.sha(b"member1"),
    }
    result = M.plan(evidence)
    preserved = {**enrollment, "files": dict(enrollment["files"])}
    for transition in result["transitions"]:
        preserved["files"].pop(transition["path"], None)
    assert result["preserved_enrollment_sha256"] == M.sha(M.canonical(preserved))
    assert evidence["identity"]["local_database"] == database
    assert result["authorized_to_execute"] is False


@pytest.mark.parametrize(
    "field,value",
    [
        ("member_id", "2"),
        ("cluster_id", "101"),
        ("name_sha256", M.sha(b"member1\n")),
        ("device", -1),
        ("device", True),
        ("device", "1"),
        ("inode", 0),
        ("inode", False),
        ("inode", "42"),
        ("inode", 42.0),
    ],
)
def test_database_record_rejects_invalid_identity(evidence, field, value):
    database = M.parse(evidence["enrollment_json"])["local_database"]
    database[field] = value
    update_enrollment(evidence, "local_database", database)
    with pytest.raises(M.Refused, match="database"):
        M.plan(evidence)


@pytest.mark.parametrize("field", ["device", "inode", "name_sha256", "unknown"])
def test_database_schema_drift_is_refused(evidence, field):
    database = M.parse(evidence["enrollment_json"])["local_database"]
    if field == "unknown":
        database[field] = "unrecognized"
    else:
        del database[field]
    update_enrollment(evidence, "local_database", database)
    with pytest.raises(M.Refused, match="database identity schema"):
        M.plan(evidence)


@pytest.mark.parametrize(
    "field,value",
    [
        ("device", 2),
        ("inode", 43),
        ("member_id", "2"),
        ("cluster_id", "101"),
        ("name_sha256", M.sha(b"other")),
        ("device", True),
        ("inode", 42.0),
    ],
)
def test_captured_database_drift_is_refused(evidence, field, value):
    evidence["identity"]["local_database"][field] = value
    with pytest.raises(M.Refused, match="captured machine/database/systemd"):
        M.plan(evidence)


@pytest.mark.parametrize(
    "raw,diagnostic",
    [
        ('{"private-value":1,"private-value":2}', "duplicate JSON key"),
        ('{"private-value":NaN}', "nonfinite JSON number"),
        ('{"private-value":Infinity}', "nonfinite JSON number"),
        ('{"private-value":-Infinity}', "nonfinite JSON number"),
        ('{"private-value":', "invalid or ambiguous JSON"),
    ],
)
def test_json_refusal_diagnostics_remain_specific_and_redacted(raw, diagnostic):
    with pytest.raises(M.Refused) as result:
        M.parse(raw)
    assert str(result.value) == diagnostic


@pytest.mark.parametrize(
    "arguments", [[], ["--apply", "private-value"], ["capture.json", "private-value"]]
)
def test_cli_argument_refusals_are_json_and_redacted(arguments, capsys):
    assert M.main(arguments) == 2
    output = capsys.readouterr()
    assert not output.err
    assert json.loads(output.out) == {
        "eligible_for_plan": False,
        "authorized_to_execute": False,
        "diagnostic": "invalid command-line arguments",
    }
    assert "private-value" not in output.out
