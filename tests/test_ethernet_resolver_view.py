"""Directory resolver view checks; all files and IPC endpoints are disposable."""

import json
import os
import socket
from pathlib import Path

import pytest
from test_ethernet_mdns_resolver import DNS, ENROLLMENT


@pytest.fixture
def view(tmp_path, monkeypatch):
    host = tmp_path / "run/systemd/resolve"
    state = tmp_path / "run/sugarkube-ethernet-dns"
    etc = tmp_path / "etc"
    for directory in (host, state, etc):
        directory.mkdir(parents=True)
    (etc / "resolv.conf").symlink_to("../run/systemd/resolve/stub-resolv.conf")
    (host / "stub-resolv.conf").write_text("nameserver 127.0.0.53\nsearch original\n")
    (host / "resolv.conf").write_text("nameserver 192.0.2.53\nsearch original\n")
    monkeypatch.setattr(DNS, "HOST_RESOLV", etc / "resolv.conf")
    monkeypatch.setattr(DNS, "RESOLVED", host)
    monkeypatch.setattr(DNS, "STATE", state)
    # Model root ownership only inside this test's private directory, including when
    # pytest itself is unprivileged. Mode/type/inode checks still use real filesystem data.
    lstat = Path.lstat

    def root_owned(path):
        info = lstat(path)
        if path.is_relative_to(tmp_path):
            fields = list(info)
            fields[4] = 0
            return os.stat_result(fields)
        return info

    monkeypatch.setattr(Path, "lstat", root_owned)
    e = {
        **ENROLLMENT,
        "resolver_view": DNS.resolved_layout(),
        "pod_resolv_source": str(host / "resolv.conf"),
    }
    return e, host, state


def publish(e, host, state):
    DNS.publish_config(
        source=host / "stub-resolv.conf", state=state, pod_source=host / "resolv.conf", enrollment=e
    )


def test_directory_view_retains_identity_across_publication_and_restart(view):
    e, host, state = view
    DNS.initialize_view(e)
    identity = DNS.check_view(e)
    for search in (".", "localdomain"):
        DNS.atomic(host / "stub-resolv.conf", f"nameserver 127.0.0.53\nsearch {search}\n")
        DNS.atomic(host / "resolv.conf", f"nameserver 192.0.2.53\nsearch {search}\n")
        publish(e, host, state)
        assert (
            state / "resolved/stub-resolv.conf"
        ).read_text() == f"nameserver 127.0.0.55\nsearch {search}\n"
        assert (state / "kubelet-resolv.conf").read_bytes() == (host / "resolv.conf").read_bytes()
        DNS.initialize_view(e)
        assert DNS.check_view(e) == identity
    assert (host / "stub-resolv.conf").read_text().startswith("nameserver 127.0.0.53")


@pytest.mark.parametrize(
    "damage", ["symlink", "unknown", "unsafe-file", "unsafe-dir", "missing", "socket-type"]
)
def test_layout_refuses_unrecognized_or_unsafe_host_entries(view, damage):
    e, host, state = view
    if damage == "symlink":
        DNS.HOST_RESOLV.unlink()
        DNS.HOST_RESOLV.symlink_to("../run/systemd/resolve/resolv.conf")
    elif damage == "unknown":
        (host / "unrecognized").touch()
    elif damage == "unsafe-file":
        (host / "stub-resolv.conf").chmod(0o666)
    elif damage == "unsafe-dir":
        host.chmod(0o777)
    elif damage == "missing":
        (host / "resolv.conf").unlink()
    else:
        (host / "io.systemd.Resolve").touch()
    with pytest.raises((DNS.Unavailable, OSError)):
        DNS.initialize_view(e)
    assert not (state / "resolved").exists()


@pytest.mark.parametrize(
    "damage", ["view", "alias", "host", "link", "extra", "stub-symlink", "marker", "marker-mode"]
)
def test_drift_is_refused_without_repair_or_publication(view, damage):
    e, host, state = view
    DNS.initialize_view(e)
    marker = state / "view-identity.json"
    before = marker.read_bytes()
    if damage in ("view", "alias", "host"):
        target = {"view": state / "resolved", "alias": state / "host-resolved", "host": host}[
            damage
        ]
        target.rename(target.with_name(target.name + "-previous"))
        target.mkdir()
    elif damage == "link":
        target = state / "resolved/resolv.conf"
        target.unlink()
        target.symlink_to("/unexpected")
    elif damage == "extra":
        (state / "resolved/extra").touch()
    elif damage == "stub-symlink":
        target = state / "resolved/stub-resolv.conf"
        target.unlink()
        target.symlink_to(host / "stub-resolv.conf")
    elif damage == "marker":
        marker.write_text("{}")
    else:
        marker.chmod(0o666)
    damaged = marker.read_bytes()
    with pytest.raises((DNS.Unavailable, OSError)):
        DNS.initialize_view(e)
    with pytest.raises((DNS.Unavailable, OSError)):
        publish(e, host, state)
    assert marker.read_bytes() == damaged
    if damage != "marker":
        assert damaged == before


def test_partial_setup_cannot_be_silently_recreated(view, monkeypatch):
    e, host, state = view
    original = DNS.atomic

    def interrupted(path, value):
        if path.name == "view-identity.json":
            raise OSError("interrupted before identity publication")
        original(path, value)

    monkeypatch.setattr(DNS, "atomic", interrupted)
    with pytest.raises(OSError):
        DNS.initialize_view(e)
    monkeypatch.setattr(DNS, "atomic", original)
    with pytest.raises(DNS.Unavailable, match="unfinished"):
        DNS.initialize_view(e)


def test_compatibility_links_follow_recreated_socket_and_uplink(view, monkeypatch):
    e, host, state = view
    DNS.initialize_view(e)
    # Simulate the alias's pathname routing, not a kernel mount. Namespace integration
    # is tested separately; this test exercises real Unix socket replacement through links.
    monkeypatch.chdir(state.parent)
    alias = state / "host-resolved"
    alias.rmdir()
    alias.symlink_to(host)
    name = "io.systemd.Resolve"
    for iteration in range(2):
        endpoint = host / name
        if endpoint.exists():
            endpoint.unlink()
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as server:
            server.bind(os.path.relpath(endpoint))
            server.listen(1)
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
                client.settimeout(1)
                client.connect(os.path.relpath(state / "resolved" / name))
                connection, _ = server.accept()
                with connection:
                    connection.sendall(bytes([iteration]))
                    assert client.recv(1) == bytes([iteration])
    DNS.atomic(host / "resolv.conf", "nameserver 192.0.2.54\n")
    assert (state / "resolved/resolv.conf").read_bytes() == (host / "resolv.conf").read_bytes()


def test_rendering_is_scoped_and_preserves_existing_enrollments(monkeypatch):
    e = {**ENROLLMENT, "pod_resolv_source": str(DNS.POD_SOURCES[1])}
    old = DNS.service_files(e)
    assert b"RuntimeDirectoryPreserve" not in old[DNS.SERVICE]
    assert old[DNS.HOOK].count(b"BindReadOnlyPaths=") == 1
    e["resolver_view"] = {
        "kind": DNS.VIEW_KIND,
        "symlink": "../run/systemd/resolve/stub-resolv.conf",
        "uid": 991,
        "gid": 991,
    }
    new = DNS.service_files(e)
    assert b"RuntimeDirectoryPreserve=yes\n" in new[DNS.SERVICE]
    assert new[DNS.HOOK].count(b"BindReadOnlyPaths=") == 2
    assert b":/etc" not in new[DNS.HOOK]
    assert new[DNS.KUBELET_CONFIG] == old[DNS.KUBELET_CONFIG]
    assert json.loads(new[DNS.CONFIG])["resolver_view"] == e["resolver_view"]
    assert DNS.resolver_bindings(e)[0].split(":")[1] < DNS.resolver_bindings(e)[1].split(":")[1]
    for bad in ({}, {**e["resolver_view"], "kind": "unknown"}, {**e["resolver_view"], "uid": True}):
        with pytest.raises(DNS.Unavailable):
            DNS.service_files({**e, "resolver_view": bad})


@pytest.mark.parametrize(
    "damage",
    [
        None,
        "missing",
        "writable",
        "child",
        "identity",
        "namespace",
        "link",
        "content",
        "generation",
        "malformed",
    ],
)
def test_running_view_requires_real_mount_identity_and_exact_content(tmp_path, monkeypatch, damage):
    e = {**ENROLLMENT, "resolver_view": {"symlink": "../run/systemd/resolve/stub-resolv.conf"}}
    identity = {"view": {"inode": 10}, "host": {"inode": 20}}
    observations = []

    def check(enrollment, root):
        assert enrollment is e and str(root).endswith("proc/42/root")
        observations.append(root)
        return (
            {**identity, "changed": True}
            if damage == "generation" and len(observations) > 1
            else identity
        )

    original_path = Path

    def path(value):
        return tmp_path / str(value).lstrip("/")

    root = path("/proc/43/root")
    (root / "etc").mkdir(parents=True)
    (root / "etc/resolv.conf").symlink_to(
        "wrong" if damage == "link" else e["resolver_view"]["symlink"]
    )
    target = root / DNS.RESOLVED.relative_to("/")
    target.mkdir(parents=True)
    expected = "nameserver 127.0.0.55\nsearch localdomain\n"
    (target / "stub-resolv.conf").write_text("wrong" if damage == "content" else expected)
    for pid, ns in ((42, "mnt:[1]"), (43, "mnt:[1]" if damage == "namespace" else "mnt:[2]")):
        directory = path(f"/proc/{pid}/ns")
        directory.mkdir(parents=True)
        (directory / "mnt").symlink_to(ns)
    alias = str(DNS.STATE / "host-resolved")
    lines = [
        f"5 1 0:1 /source {DNS.RESOLVED} ro - tmpfs tmpfs rw",
        f"6 1 0:1 /host {alias} ro - tmpfs tmpfs rw",
    ]
    if damage == "missing":
        lines.pop()
    elif damage == "writable":
        lines[0] = lines[0].replace(" ro ", " rw ")
    elif damage == "child":
        lines.append(f"7 5 0:1 /other {DNS.RESOLVED}/stub-resolv.conf ro - tmpfs tmpfs rw")
    elif damage == "malformed":
        lines = ["invalid"]
    path("/proc/43/mountinfo").write_text("\n".join(lines))
    readlink = os.readlink
    monkeypatch.setattr(DNS, "Path", path)
    monkeypatch.setattr(
        DNS.os,
        "readlink",
        lambda value: readlink(path(value) if str(value).startswith("/proc/") else value),
    )
    monkeypatch.setattr(DNS, "check_view", check)

    def inspect(actual):
        if str(actual).endswith(alias):
            return identity["host"]
        assert actual == root / original_path(DNS.RESOLVED).relative_to("/")
        return {"inode": 999} if damage == "identity" else identity["view"]

    monkeypatch.setattr(DNS, "directory_identity", inspect)
    if damage:
        with pytest.raises(DNS.Unavailable):
            DNS.check_process_view(e, "43", "42", expected)
    else:
        DNS.check_process_view(e, "43", "42", expected)
        assert len(observations) == 2


@pytest.mark.parametrize("unsafe", [False, True])
def test_resolved_atomic_writer_temporary_file_is_not_a_new_ipc_entry(view, unsafe):
    e, host, state = view
    temporary = host / ".#stub-resolv.conf0123456789abcdef"
    temporary.write_text("incomplete")
    temporary.chmod(0o666 if unsafe else 0o600)
    if unsafe:
        with pytest.raises(DNS.Unavailable):
            DNS.initialize_view(e)
    else:
        DNS.initialize_view(e)
        assert {p.name for p in (state / "resolved").iterdir()} == DNS.RESOLVED_ENTRIES
        temporary.unlink()
        DNS.check_view(e)


def test_namespace_harness_cleans_up_when_child_cannot_launch(monkeypatch):
    import test_ethernet_resolver_namespace as harness

    resources = []
    create_socket = socket.socket

    def tracked_socket(*args, **kwargs):
        result = create_socket(*args, **kwargs)
        resources.append(result)
        return result

    def unavailable(*args, **kwargs):
        raise OSError("synthetic child launch failure; no command executed")

    monkeypatch.setattr(harness.os, "geteuid", lambda: 0)
    monkeypatch.setattr(harness.shutil, "which", lambda name: f"/not-executed/{name}")
    monkeypatch.setattr(harness.DNS, "initialize_view", lambda e: None)
    monkeypatch.setattr(harness.socket, "socket", tracked_socket)
    monkeypatch.setattr(harness.subprocess, "Popen", unavailable)
    with pytest.raises(OSError, match="synthetic child launch failure"):
        harness.test_private_namespace_host_replacement_and_generated_publication("directory")
    assert resources and all(sock.fileno() == -1 for sock in resources)


def test_main_initializes_and_refreshes_versioned_view(view, monkeypatch, tmp_path):
    import sys

    e, host, state = view
    config = tmp_path / "config.json"
    config.write_text(json.dumps(e))
    monkeypatch.setattr(sys, "argv", ["resolver", "--enrollment", str(config)])
    monkeypatch.setattr(DNS, "POD_SOURCES", (host / "resolv.conf",))
    original_stat = Path.stat

    def root_stat(path, *args, **kwargs):
        result = original_stat(path, *args, **kwargs)
        if path == state:
            fields = list(result)
            fields[4] = 0
            return os.stat_result(fields)
        return result

    monkeypatch.setattr(Path, "stat", root_stat)
    calls = []
    monkeypatch.setattr(DNS, "serve", lambda resolver, refresh: refresh())
    monkeypatch.setattr(DNS, "publish_config", lambda **kwargs: calls.append(kwargs))
    DNS.main()
    assert calls == [{"pod_source": host / "resolv.conf", "enrollment": e}]
    DNS.check_view(e)


def test_resolved_temporary_disappearing_during_enumeration_is_safe(view, monkeypatch):
    e, host, state = view
    temporary = host / ".#resolv.conf0123456789abcdef"
    temporary.touch(mode=0o600)
    lstat = Path.lstat

    def vanished(path):
        if path == temporary:
            temporary.unlink()
            raise FileNotFoundError(path)
        return lstat(path)

    monkeypatch.setattr(Path, "lstat", vanished)
    DNS.initialize_view(e)
    DNS.check_view(e)


def test_optional_ipc_socket_disappearing_during_enumeration_is_safe(view, monkeypatch):
    e, host, state = view
    endpoint = host / "io.systemd.Resolve"
    endpoint.touch()
    lstat = Path.lstat

    def vanished(path):
        if path == endpoint:
            endpoint.unlink()
            raise FileNotFoundError(path)
        return lstat(path)

    monkeypatch.setattr(Path, "lstat", vanished)
    DNS.initialize_view(e)
    DNS.check_view(e)
    assert (state / "resolved/io.systemd.Resolve").is_symlink()


@pytest.mark.parametrize("operation", ["initialize", "check"])
def test_changed_enrolled_layout_is_refused_before_mutation(view, operation):
    e, host, state = view
    DNS.initialize_view(e)

    def snapshot():
        return {
            str(p.relative_to(state)): (
                ("link", os.readlink(p)) if p.is_symlink() else ("file", p.read_bytes())
            )
            for p in state.rglob("*")
            if p.is_symlink() or p.is_file()
        }

    before = snapshot()
    # A valid but different owner descriptor must not silently enroll the current owner.
    changed = {**e, "resolver_view": {**e["resolver_view"], "uid": e["resolver_view"]["uid"] + 1}}
    fn = DNS.initialize_view if operation == "initialize" else DNS.check_view
    with pytest.raises(DNS.Unavailable, match="original resolver layout changed"):
        fn(changed)
    assert snapshot() == before


def test_stable_resolver_file_disappearing_during_enumeration_is_not_ignored(view, monkeypatch):
    e, host, state = view
    target = host / "stub-resolv.conf"
    lstat = Path.lstat

    def vanished(path):
        if path == target:
            target.unlink()
            raise FileNotFoundError(path)
        return lstat(path)

    monkeypatch.setattr(Path, "lstat", vanished)
    with pytest.raises(FileNotFoundError):
        DNS.initialize_view(e)
    assert not (state / "resolved").exists()
