"""Unprivileged orchestration tests; no guest, service, mount or network operations."""

import hashlib
import io
import json
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest
from test_resolver_qualification import DIRECTORY, load


def wheel_bytes(pure=True):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        archive.writestr("example/__init__.py", "VALUE = 42\n")
        archive.writestr("example.dist-info/WHEEL", f"Root-Is-Purelib: {str(pure).lower()}\n")
    return stream.getvalue()


@pytest.fixture
def builder(monkeypatch, tmp_path):
    module = load("build_resolver_bundle")
    content = wheel_bytes()
    item = {
        "file": "wheels/example.whl",
        "url": "https://files.pythonhosted.org/example.whl",
        "bytes": len(content),
        "sha256": hashlib.sha256(content).hexdigest(),
    }
    manifest = {"packages": [item]}
    commit = "a" * 40
    files = {
        "scripts/qualification/resolver-python-dependencies.json": None,
        "scripts/qualification/resolver_offline_prepare.py": (
            DIRECTORY / "resolver_offline_prepare.py"
        ).read_bytes(),
    }
    calls = []

    def git(args, **kwargs):
        calls.append(args)
        assert args[:3] == ["git", "-C", str(tmp_path)]
        if args[3] == "rev-parse":
            return commit + "\n"
        assert args[3] == "show" and args[4].startswith(commit + ":")
        name = args[4].split(":", 1)[1]
        return json.dumps(manifest).encode() if name.endswith(".json") else files[name]

    def download(url, timeout):
        assert url == item["url"] and timeout == 30
        response = io.BytesIO(content)
        response.url = url
        return response

    monkeypatch.setattr(module, "FILES", tuple(files))
    monkeypatch.setattr(module.subprocess, "check_output", git)
    monkeypatch.setattr(module, "urlopen", download)
    return module, manifest, commit, calls


def test_bundle_is_deterministic_and_all_payloads_are_checksummed(builder, tmp_path):
    module, manifest, commit, calls = builder
    first, second = tmp_path / "first.tgz", tmp_path / "second.tgz"
    module.build(tmp_path, commit, first)
    module.build(tmp_path, commit, second)
    assert first.read_bytes() == second.read_bytes()
    with tarfile.open(first) as archive:
        members = archive.getmembers()
        assert all(m.uid == m.gid == m.mtime == 0 for m in members)
        assert not any("__pycache__" in m.name for m in members)
        files = {
            m.name.removeprefix("resolver-lifecycle-bundle/"): archive.extractfile(m).read()
            for m in members
            if m.isfile()
        }
    checksums = files.pop("SHA256SUMS").decode().splitlines()
    assert len(checksums) == len(files)
    for record in checksums:
        digest, name = record.split("  ", 1)
        assert digest == hashlib.sha256(files[name]).hexdigest()
    assert files["deps/example/__init__.py"] == b"VALUE = 42\n"
    assert json.loads(files["bundle-manifest.json"])["source_commit"] == commit
    assert len(calls) == 2 * (1 + len(module.FILES))


@pytest.mark.parametrize(
    "failure",
    ["commit", "existing", "resolved", "scheme", "host", "path", "redirect", "size", "hash"],
)
def test_builder_rejects_untrusted_inputs_without_publishing(
    builder, tmp_path, monkeypatch, failure
):
    module, manifest, commit, calls = builder
    output = tmp_path / "bundle.tgz"
    item = manifest["packages"][0]
    if failure == "commit":
        commit = "main"
    elif failure == "existing":
        output.write_bytes(b"preserve")
    elif failure == "resolved":
        monkeypatch.setattr(module.subprocess, "check_output", lambda *a, **k: "b" * 40)
    elif failure in ("scheme", "host"):
        item["url"] = (
            "http://files.pythonhosted.org/x"
            if failure == "scheme"
            else "https://example.invalid/x"
        )
    elif failure == "path":
        item["file"] = "../outside.whl"
    elif failure == "redirect":

        def redirected(*args, **kwargs):
            response = io.BytesIO(b"untrusted")
            response.url = "https://example.invalid/x"
            return response

        monkeypatch.setattr(module, "urlopen", redirected)
    elif failure == "size":
        item["bytes"] += 1
    else:
        item["sha256"] = "0" * 64
    with pytest.raises(ValueError):
        module.build(tmp_path, commit, output)
    assert output.read_bytes() == b"preserve" if failure == "existing" else not output.exists()
    if failure in ("commit", "existing"):
        assert calls == []


@pytest.mark.parametrize("failure", ["existing", "outside", "absolute", "native"])
def test_offline_preparation_refuses_before_destination_mutation(tmp_path, failure):
    module = load("resolver_offline_prepare")
    destination = tmp_path / "deps"
    (tmp_path / "wheels").mkdir()
    wheel = tmp_path / "wheels/example.whl"
    content = wheel_bytes(pure=failure != "native")
    if failure == "absolute":
        buffer = io.BytesIO(content)
        with zipfile.ZipFile(buffer, "a") as archive:
            archive.writestr("/escape", "never")
        content = buffer.getvalue()
    wheel.write_bytes(content)
    item = {
        "file": "outside.whl" if failure == "outside" else "wheels/example.whl",
        "sha256": hashlib.sha256(content).hexdigest(),
    }
    (tmp_path / "python-dependencies.json").write_text(json.dumps({"packages": [item]}))
    if failure == "existing":
        destination.mkdir()
        (destination / "keep").write_text("untouched")
    with pytest.raises(AssertionError):
        module.prepare(tmp_path, destination)
    assert (
        (destination / "keep").read_text() == "untouched"
        if failure == "existing"
        else not destination.exists()
    )


@pytest.fixture
def supervisor(monkeypatch, tmp_path):
    monkeypatch.syspath_prepend(str(DIRECTORY))
    module = load("resolver_oneshot")
    root = tmp_path / "host"
    root.mkdir()

    def path(value):
        value = Path(value)
        return root / str(value).lstrip("/") if value.is_absolute() else value

    for name, content in {
        "/proc/uptime": "10 10",
        "/proc/sys/kernel/random/boot_id": "boot",
        "/sys/fs/cgroup/cgroup.controllers": "memory pids",
    }.items():
        target = path(name)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)
    path("/run/systemd/system").mkdir(parents=True)
    monkeypatch.setattr(module, "Path", path)
    evidence = tmp_path / "evidence"
    monkeypatch.setattr(module, "EVIDENCE", evidence)
    monkeypatch.setattr(module.os, "geteuid", lambda: 0)
    monkeypatch.setattr(module.socket, "gethostname", lambda: "sugarkube-lifecycle-proof-v1")
    monkeypatch.setattr(module.shutil, "which", lambda _: "/usr/bin/real")
    monkeypatch.setattr(
        module,
        "sys",
        SimpleNamespace(version_info=(3, 12), version="3.12", executable=sys.executable),
    )
    clock = [0]
    monkeypatch.setattr(module.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(module.time, "sleep", lambda seconds: clock.__setitem__(0, clock[0] + 1))
    state = {
        "fixtures": [],
        "mounts": {},
        "cgroups": {},
        "records": [],
        "baseline": {"dns": "unchanged"},
        "units": "LoadState=not-found\nMainPID=0\nActiveState=inactive",
        "timeout": False,
        "harness_passed": True,
        "returncode": 0,
        "signals": [],
        "commands": [],
    }
    monkeypatch.setattr(module, "fixtures", lambda: state["fixtures"])
    monkeypatch.setattr(module, "mount_evidence", lambda: state["mounts"])
    monkeypatch.setattr(module, "probe_cgroup_processes", lambda: state["cgroups"])
    monkeypatch.setattr(module, "processes", lambda: state["records"])
    monkeypatch.setattr(module, "baseline", lambda: state["baseline"])
    monkeypatch.setattr(
        module, "unit_evidence", lambda deadline: dict.fromkeys(module.UNITS, state["units"])
    )

    def command(*args, **kwargs):
        state["commands"].append(args)
        if args[0] == "ip":
            return json.dumps([{"ifname": "lo"}])
        if args[:2] == ("systemctl", "show"):
            return "LoadState=not-found"
        return "recorded"

    monkeypatch.setattr(module, "command", command)

    def terminate(pgid, sig):
        state["signals"].append((pgid, sig))
        assert pgid == 123 and sig == module.signal.SIGTERM
        state["records"] = []

    monkeypatch.setattr(module.os, "killpg", terminate)

    class Process:
        pid = 123
        returncode = state["returncode"]

        def __init__(self, args, **kwargs):
            assert kwargs["start_new_session"] is True
            assert kwargs["env"]["PYTHONPATH"].endswith("/deps")
            assert "PYTHONOPTIMIZE" not in kwargs["env"]
            assert all(kwargs["env"][key] == value for key, value in module.FLAGS.items())
            state["records"] = [{"pid": 123, "pgid": 123, "sid": 123, "start_ticks": 100}]
            (evidence / "result.json").write_text(json.dumps({"passed": state["harness_passed"]}))
            self.returncode = state["returncode"]

        def poll(self):
            if state["timeout"] and state["records"]:
                return None
            state["records"] = []
            return self.returncode

    monkeypatch.setattr(module.subprocess, "Popen", Process)
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    (bundle / "payload").write_text("verified")
    (bundle / "SHA256SUMS").write_text(hashlib.sha256(b"verified").hexdigest() + "  payload\n")
    return module, state, bundle, path, clock


def test_supervisor_records_cleanup_before_graceful_shutdown(supervisor):
    module, state, bundle, path, clock = supervisor
    assert module.main(bundle) == 0
    status = json.loads((module.EVIDENCE / "status.json").read_text())
    assert status["passed"] and status["cleanup_passed"]
    assert state["signals"] == []
    assert state["commands"][-1] == ("systemctl", "--no-block", "poweroff")
    hashes = json.loads((module.EVIDENCE / "evidence-hashes.json").read_text())
    assert "pre-shutdown-cleanup.json" in hashes
    for name, digest in hashes.items():
        assert hashlib.sha256((module.EVIDENCE / name).read_bytes()).hexdigest() == digest
    assert not list(module.EVIDENCE.glob("*.new"))


@pytest.mark.parametrize(
    "failure",
    ["timeout", "nonzero", "harness", "mount", "cgroup", "baseline", "journal", "shutdown"],
)
def test_supervisor_failure_outcomes_and_cleanup_ownership(supervisor, monkeypatch, failure):
    module, state, bundle, path, clock = supervisor
    original = module.subprocess.Popen

    def launch(*args, **kwargs):
        proc = original(*args, **kwargs)
        if failure == "mount":
            state["mounts"] = {"123": ["fixture mount"]}
        elif failure == "cgroup":
            state["cgroups"] = {"probe": [456]}
        elif failure == "baseline":
            state["baseline"] = {"dns": "drifted"}
        return proc

    monkeypatch.setattr(module.subprocess, "Popen", launch)
    state["timeout"] = failure == "timeout"
    state["returncode"] = 2 if failure == "nonzero" else 0
    state["harness_passed"] = failure != "harness"
    command = module.command

    def fail_command(*args, **kwargs):
        if (failure == "journal" and args[0] == "journalctl") or (
            failure == "shutdown" and args[-1] == "poweroff"
        ):
            raise subprocess.CalledProcessError(1, args)
        return command(*args, **kwargs)

    monkeypatch.setattr(module, "command", fail_command)
    assert module.main(bundle) == (0 if failure == "shutdown" else 1)
    status = json.loads((module.EVIDENCE / "status.json").read_text())
    if failure in ("mount", "cgroup", "baseline", "journal"):
        assert status["cleanup_errors"] and not status["cleanup_passed"]
        assert not (module.EVIDENCE / "shutdown-intent.json").exists()
    if failure == "timeout":
        assert status["test_timeout"] and state["signals"] == [(123, module.signal.SIGTERM)]
    if failure == "shutdown":
        assert "CalledProcessError" in (module.EVIDENCE / "shutdown-error.json").read_text()


@pytest.mark.parametrize(
    "failure", ["boot", "version", "cgroup", "tool", "fixture", "nic", "unit", "checksum"]
)
def test_supervisor_preflight_failures_never_launch_or_claim_cleanup(
    supervisor, monkeypatch, failure
):
    module, state, bundle, path, clock = supervisor
    if failure == "boot":
        path("/proc/uptime").write_text("301 0")
    elif failure == "version":
        module.sys.version_info = (3, 14)
    elif failure == "cgroup":
        path("/sys/fs/cgroup/cgroup.controllers").unlink()
    elif failure == "tool":
        monkeypatch.setattr(module.shutil, "which", lambda _: None)
    elif failure == "fixture":
        state["fixtures"] = [path("/run/existing")]
    elif failure == "checksum":
        (bundle / "payload").write_text("tamper")
    else:
        command = module.command

        def changed(*args, **kwargs):
            if failure == "nic" and args[0] == "ip":
                return '[{"ifname":"eth0"}]'
            if failure == "unit" and args[:2] == ("systemctl", "show"):
                return "LoadState=loaded"
            return command(*args, **kwargs)

        monkeypatch.setattr(module, "command", changed)
    monkeypatch.setattr(module.subprocess, "Popen", lambda *a, **k: pytest.fail("unsafe launch"))
    assert module.main(bundle) == 1
    status = json.loads((module.EVIDENCE / "status.json").read_text())
    assert not status["passed"] and not status["cleanup_passed"]
    assert "preflight incomplete" in status["cleanup_errors"][0]
    assert state["signals"] == []
    assert not (module.EVIDENCE / "shutdown-intent.json").exists()


@pytest.mark.parametrize("failure", ["hostname", "root", "replay"])
def test_supervisor_refuses_unowned_guest_without_evidence_mutation(
    supervisor, monkeypatch, failure
):
    module, state, bundle, path, clock = supervisor
    if failure == "hostname":
        monkeypatch.setattr(module.socket, "gethostname", lambda: "existing-member")
    elif failure == "root":
        monkeypatch.setattr(module.os, "geteuid", lambda: 1000)
    else:
        module.EVIDENCE.mkdir()
        (module.EVIDENCE / "keep").write_text("previous")
    with pytest.raises(SystemExit):
        module.main(bundle)
    assert state["commands"] == state["signals"] == []
    assert not (module.EVIDENCE / "status.json").exists()


def test_offline_extracts_verified_pure_wheel(tmp_path):
    module = load("resolver_offline_prepare")
    (tmp_path / "wheels").mkdir()
    wheel = tmp_path / "wheels/example.whl"
    wheel.write_bytes(wheel_bytes())
    (tmp_path / "python-dependencies.json").write_text(
        json.dumps(
            {
                "packages": [
                    {
                        "file": "wheels/example.whl",
                        "sha256": hashlib.sha256(wheel.read_bytes()).hexdigest(),
                    }
                ]
            }
        )
    )
    module.prepare(tmp_path, tmp_path / "deps")
    assert (tmp_path / "deps/example/__init__.py").read_text() == "VALUE = 42\n"


@pytest.mark.parametrize("relative", ["../outside", "/absolute"])
def test_bundle_manifest_refuses_escape(monkeypatch, tmp_path, relative):
    monkeypatch.syspath_prepend(str(DIRECTORY))
    module = load("resolver_oneshot")
    (tmp_path / "SHA256SUMS").write_text("0" * 64 + "  " + relative + "\n")
    with pytest.raises(ValueError, match="invalid bundle manifest path"):
        module.verify_bundle(tmp_path)


def test_command_budget_is_passed_and_expired_budget_never_launches(monkeypatch):
    monkeypatch.syspath_prepend(str(DIRECTORY))
    module = load("resolver_oneshot")
    monkeypatch.setattr(module.time, "monotonic", lambda: 100)
    calls = []

    def command(args, **kwargs):
        calls.append((args, kwargs))
        return " value\n"

    monkeypatch.setattr(module.subprocess, "check_output", command)
    assert module.command("probe", deadline=103) == "value"
    assert calls[0][1]["timeout"] == 3
    assert module.command("probe") == "value"
    assert calls[1][1]["timeout"] == 10
    with pytest.raises(TimeoutError):
        module.command("probe", deadline=100)
    assert len(calls) == 2


def test_proc_and_cgroup_evidence_handles_exit_races_and_comm_parentheses(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(DIRECTORY))
    module = load("resolver_oneshot")
    root = tmp_path / "fixture"
    root.mkdir()
    monkeypatch.setattr(module, "ROOT", root)
    proc = tmp_path / "proc"
    proc.mkdir()
    (proc / "nonnumeric").mkdir()
    for pid in (123, 124, 125):
        (proc / str(pid)).mkdir()
    # 124 and 125 intentionally vanish between directory enumeration and reads.
    fields = ["S", "1", "123", "123"] + ["0"] * 15 + ["500"]
    (proc / "123/stat").write_text("123 (name (with) spaces)) " + " ".join(fields))
    (proc / "123/mountinfo").write_text(f"unrelated\nowned {root}\n")
    temporary = tmp_path / "tmp"
    temporary.mkdir()
    extra = temporary / "sugarkube-view-proof-owned"
    extra.mkdir()
    groups = tmp_path / "groups"
    (groups / module.UNITS[0]).mkdir(parents=True)
    (groups / module.UNITS[0] / "cgroup.procs").write_text("123\n456\n")
    mapping = {"/proc": proc, "/tmp": temporary, "/sys/fs/cgroup/system.slice": groups}
    monkeypatch.setattr(module, "Path", lambda p: mapping[str(p)])
    assert module.processes() == [
        {"pid": 123, "state": "S", "pgid": 123, "sid": 123, "start_ticks": 500}
    ]
    assert module.mount_evidence() == {"123": [f"owned {root}"]}
    assert module.fixtures() == [root, extra]
    assert module.probe_cgroup_processes() == {module.UNITS[0]: [123, 456], module.UNITS[1]: []}
    records = module.processes()
    with pytest.raises(RuntimeError, match="leader identity changed"):
        module.owned(records, 123, 499)
    assert module.owned(records, 123, 500) == records
    assert module.owned(records, 999, 500) == []


@pytest.fixture
def lifecycle(monkeypatch, tmp_path):
    module = load("resolver_lifecycle")
    root = tmp_path / "fixture"
    monkeypatch.setattr(module, "ROOT", root)
    monkeypatch.setattr(
        module, "sys", SimpleNamespace(version_info=(3, 12), executable=sys.executable)
    )
    monkeypatch.setattr(module.os, "geteuid", lambda: 0)
    readlink = module.os.readlink
    monkeypatch.setattr(
        module.os,
        "readlink",
        lambda p: (
            "../run/systemd/resolve/stub-resolv.conf"
            if str(p) == "/etc/resolv.conf"
            else readlink(p)
        ),
    )
    monkeypatch.setattr(module.socket, "gethostname", lambda: "sugarkube-lifecycle-proof-v1")
    monkeypatch.setattr(module.shutil, "which", lambda _: "/usr/bin/real")
    for key, value in module.FLAGS.items():
        monkeypatch.setenv(key, value)
    monkeypatch.delenv("PYTHONPATH", raising=False)
    units = tmp_path / "units"
    units.mkdir()
    proc = tmp_path / "mountinfo"
    proc.write_text("")

    def path(value):
        if str(value) == "/run/systemd/system":
            return units
        if str(value) in ("/proc/self/mountinfo", "/proc/123/mountinfo"):
            return proc
        if str(value).startswith(("/var/lib/rancher", "/etc/rancher")):
            return tmp_path / "absent"
        raise AssertionError(f"unexpected host path: {value}")

    monkeypatch.setattr(module, "Path", path)
    state = {
        "commands": [],
        "ipc": "first",
        "baseline": {"links": [{"ifname": "lo"}]},
        "cleanup_error": None,
        "pytest_xml": "<testsuite><testcase/><testcase/></testsuite>",
    }
    monkeypatch.setattr(module, "baseline", lambda: state["baseline"])

    class Unavailable(ValueError):
        pass

    class DNS:
        STATE = root / "run/sugarkube-ethernet-dns"
        RESOLVED = root / "run/systemd/resolve"
        HOST_RESOLV = root / "etc/resolv.conf"
        SERVICE = "runtime"
        HOOK = "view"
        identity = None

        def resolved_layout(self):
            return {"fixture": True}

        def service_files(self, enrollment):
            return {
                "runtime": (
                    b"RuntimeDirectory=sugarkube-ethernet-dns\n"
                    b"RuntimeDirectoryMode=0755\nRuntimeDirectoryPreserve=yes\n"
                ),
                "view": b"BindReadOnlyPaths=original:alias\nBindReadOnlyPaths=generated:original\n",
            }

        def view_links(self):
            return {
                "io.systemd.Resolve": (
                    "../../sugarkube-ethernet-dns/host-resolved/io.systemd.Resolve"
                )
            }

        def atomic(self, path, text):
            temp = path.with_name(path.name + ".new")
            temp.write_text(text)
            temp.replace(path)

        def initialize_view(self, enrollment):
            if (self.RESOLVED / "unknown").exists():
                raise Unavailable("unsupported resolved directory entry")
            view = self.STATE / "resolved"
            marker = self.STATE / "view-identity.json"
            if view.exists() and not marker.exists():
                raise Unavailable(
                    "unfinished resolver view setup; explicit reconciliation required"
                )
            if not view.exists():
                view.mkdir()
                for name, target in self.view_links().items():
                    (view / name).symlink_to(target)
                self.identity = {"inode": self.STATE.stat().st_ino}
                marker.write_text(json.dumps(self.identity))
            self.check_view(enrollment)

        def check_view(self, enrollment):
            link = self.STATE / "resolved/io.systemd.Resolve"
            if readlink(link) != self.view_links()[link.name]:
                raise Unavailable("resolver compatibility link changed")
            if self.STATE.stat().st_ino != self.identity["inode"]:
                raise Unavailable(
                    "resolver directory identity changed; explicit migration required"
                )
            return self.identity

        def check_process_view(self, enrollment, pid, dns_pid, expected):
            assert pid == 123
            if "BindPaths=" in (units / module.UNITS[1]).read_text():
                raise Unavailable("K3s resolver directory mount drifted")

    dns = DNS()
    monkeypatch.setattr(module, "module", lambda: dns)

    def run(*args):
        state["commands"].append(args)
        if "--property=LoadState" in args:
            return "LoadState=not-found"
        if args[:2] == ("systemctl", "start"):
            if args[2] == module.UNITS[0]:
                dns.STATE.mkdir(exist_ok=True)
            else:
                (root / "ready").write_text("123")
        if "--property=MainPID" in args:
            return "123" if "--value" in args else "MainPID=0"
        if "--property=ActiveState" in args:
            return "ActiveState=inactive"
        if args[:2] == ("systemctl", "is-active"):
            return "active"
        return ""

    monkeypatch.setattr(module, "run", run)

    def pytest_run(*args, **kwargs):
        xml = next(x.split("=", 1)[1] for x in args[0] if x.startswith("--junitxml="))
        Path(xml).write_text(state["pytest_xml"])
        assert kwargs == {"check": True}
        assert "--noconftest" in args[0]

    monkeypatch.setattr(module.subprocess, "run", pytest_run)

    class IPC:
        def __init__(self, host, marker):
            assert host == dns.RESOLVED
            state["ipc"] = marker

        def close(self):
            if state["cleanup_error"] == "ipc" and state["ipc"] == "second":
                raise RuntimeError("fixture IPC cleanup failure")

    monkeypatch.setattr(module, "IPC", IPC)

    def observe(number):
        (root / "request").write_text(str(number))
        return {
            "stub": (dns.STATE / "resolved/stub-resolv.conf").read_text(),
            "mounts": ["stable"],
            "ipc": {"main": state["ipc"], "monitor": state["ipc"]},
            "uplink": (dns.RESOLVED / "resolv.conf").read_text(),
        }

    monkeypatch.setattr(module, "observe", observe)
    return module, state, dns, tmp_path / "result.json", units, proc


def test_lifecycle_orchestration_records_all_refusals_and_removes_owned_fixtures(lifecycle):
    module, state, dns, output, units, proc = lifecycle
    module.qualify(output)
    result = json.loads(output.read_text())
    assert result["passed"] and result["cleanup_passed"] and result["namespace_cases"] == 2
    assert len(result["refusals"]) == 5
    assert len(result["observations"]) == 4
    assert [r["stub"] for r in result["observations"][:3]] == [
        f"nameserver 127.0.0.55\nsearch {s}\n" for s in ("original", ".", "renewed")
    ]
    assert not module.ROOT.exists() and not list(units.iterdir())
    assert "RuntimeDirectoryPreserve=yes" in result["probe_units"][module.UNITS[0]]
    assert "BindPaths=" not in result["probe_units"][module.UNITS[1]]


@pytest.mark.parametrize(
    "report",
    [
        "<testsuite><testcase/></testsuite>",
        "<testsuite><testcase><skipped/></testcase><testcase/></testsuite>",
        "<testsuite><testcase><failure/></testcase><testcase/></testsuite>",
        "<testsuite><testcase><error/></testcase><testcase/></testsuite>",
    ],
)
def test_namespace_incomplete_report_never_starts_services(lifecycle, report):
    module, state, dns, output, units, proc = lifecycle
    state["pytest_xml"] = report
    with pytest.raises(AssertionError):
        module.qualify(output)
    result = json.loads(output.read_text())
    assert not result["passed"] and result["cleanup_passed"]
    assert not module.ROOT.exists() and not list(units.iterdir())
    assert all(args[1] == "show" for args in state["commands"])


@pytest.mark.parametrize("failure", ["stop", "reload", "ipc", "mount", "baseline"])
def test_lifecycle_cleanup_failure_is_persisted_and_preserves_uncertain_fixtures(
    lifecycle, monkeypatch, failure
):
    module, state, dns, output, units, proc = lifecycle
    original = module.run
    cleanup = [False]
    check = dns.check_view

    def checked(enrollment):
        try:
            return check(enrollment)
        except ValueError as error:
            if "identity changed" in str(error):
                cleanup[0] = True
                if failure == "mount":
                    proc.write_text(str(module.ROOT))
                elif failure == "baseline":
                    state["baseline"] = {"links": [{"ifname": "changed"}]}
            raise

    monkeypatch.setattr(dns, "check_view", checked)

    def run(*args):
        if cleanup[0] and (
            (failure == "stop" and args[1] == "stop")
            or (failure == "reload" and args[1] == "daemon-reload")
        ):
            raise RuntimeError("simulated cleanup uncertainty")
        return original(*args)

    monkeypatch.setattr(module, "run", run)
    state["cleanup_error"] = failure
    with pytest.raises(AssertionError):
        module.qualify(output)
    result = json.loads(output.read_text())
    assert not result["passed"] and not result["cleanup_passed"] and result["cleanup_errors"]
    if failure != "baseline":
        assert module.ROOT.exists()


def test_unit_evidence_uses_bounded_read_only_queries(monkeypatch):
    monkeypatch.syspath_prepend(str(DIRECTORY))
    module = load("resolver_oneshot")
    calls = []
    monkeypatch.setattr(module, "command", lambda *a, **k: calls.append((a, k)) or "state")
    assert module.unit_evidence(321) == dict.fromkeys(module.UNITS, "state")
    assert all(a[:2] == ("systemctl", "show") and k == {"deadline": 321} for a, k in calls)


@pytest.mark.parametrize(
    "failure", ["ownership", "stuck", "stop", "deadline", "fixture", "journal"]
)
def test_supervisor_cleanup_faults_never_authorize_shutdown(supervisor, monkeypatch, failure):
    module, state, bundle, path, clock = supervisor
    state["timeout"] = failure in ("ownership", "stuck")
    original_launch = module.subprocess.Popen
    fixture = bundle / "fixture"

    def launch(*args, **kwargs):
        process = original_launch(*args, **kwargs)
        if failure == "ownership":
            state["records"][0]["sid"] = 456
        if failure in ("stop", "deadline"):
            state["units"] = "LoadState=loaded\nMainPID=123\nActiveState=active"
        if failure == "fixture":
            fixture.symlink_to(bundle, target_is_directory=True)
            state["fixtures"] = [fixture]
        return process

    monkeypatch.setattr(module.subprocess, "Popen", launch)
    if failure == "stuck":
        monkeypatch.setattr(module.os, "killpg", lambda *args: state["signals"].append(args))
    original_command = module.command

    def command(*args, **kwargs):
        if failure == "stop" and args[:3] == ("systemctl", "--no-block", "stop"):
            state["units"] = "LoadState=loaded\nMainPID=0\nActiveState=failed"
            raise RuntimeError("stop result uncertain")
        return original_command(*args, **kwargs)

    monkeypatch.setattr(module, "command", command)
    if failure == "journal":

        def broken(deadline):
            raise RuntimeError("properties unavailable")

        monkeypatch.setattr(module, "unit_evidence", broken)
    assert module.main(bundle) == 1
    status = json.loads((module.EVIDENCE / "status.json").read_text())
    assert status["cleanup_errors"] and not status["cleanup_passed"]
    assert not (module.EVIDENCE / "shutdown-intent.json").exists()
    if failure == "ownership":
        assert state["signals"] == []
    if failure == "stuck":
        assert state["signals"] == [(123, module.signal.SIGTERM)]
    if failure == "fixture":
        assert fixture.is_symlink()


def test_lifecycle_run_is_bounded_and_baseline_tracks_file_identity(monkeypatch, tmp_path):
    module = load("resolver_lifecycle")
    calls = []

    def command(args, **kwargs):
        calls.append((args, kwargs))
        return ' [{"ifname":"lo"}] \n'

    monkeypatch.setattr(module.subprocess, "check_output", command)
    existing = tmp_path / "resolver"
    existing.write_text("nameserver 127.0.0.53\n")
    monkeypatch.setattr(
        module,
        "Path",
        lambda p: tmp_path / "absent" if str(p).endswith("stub-resolv.conf") else existing,
    )
    result = module.baseline()
    assert result["links"] == [{"ifname": "lo"}]
    assert result["dns"]["/run/systemd/resolve/stub-resolv.conf"] is None
    assert result["dns"]["/etc/resolv.conf"] == {
        "sha256": hashlib.sha256(existing.read_bytes()).hexdigest(),
        "inode": existing.stat().st_ino,
        "device": existing.stat().st_dev,
    }
    assert calls == [(("ip", "-j", "link", "show"), {"text": True, "timeout": 20})]


@pytest.mark.parametrize("failure", [None, "writable", "wrong_errno"])
def test_snapshot_requires_readonly_and_records_both_ipc_endpoints(monkeypatch, tmp_path, failure):
    import errno

    module = load("resolver_lifecycle")
    host = tmp_path / "resolved"
    host.mkdir()
    state = tmp_path / "state"
    (state / "host-resolved").mkdir(parents=True)
    stub = host / "stub"
    stub.write_text("nameserver 127.0.0.55\n")
    (host / "resolv.conf").write_text("nameserver 192.0.2.53\n")
    dns = SimpleNamespace(HOST_RESOLV=stub, RESOLVED=host, STATE=state)
    mountinfo = tmp_path / "mountinfo"
    mountinfo.write_text(f"unrelated\nview {tmp_path}\n")
    monkeypatch.setattr(module, "ROOT", tmp_path)
    monkeypatch.setattr(module, "module", lambda: dns)
    monkeypatch.setattr(module, "Path", lambda p: mountinfo)
    monkeypatch.setattr(module.os, "readlink", lambda p: "mnt:[fixture]")
    connections = []

    class Client:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def settimeout(self, seconds):
            assert seconds == 2

        def connect(self, path):
            connections.append(path)

        def recv(self, size):
            assert size == 8
            return b"marker"

    monkeypatch.setattr(module.socket, "socket", lambda *args: Client())
    write = Path.write_text

    def readonly(path, text, *args, **kwargs):
        if path.name == "write-must-fail" and failure != "writable":
            raise OSError(errno.EACCES if failure == "wrong_errno" else errno.EROFS, "simulated")
        return write(path, text, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", readonly)
    if failure:
        with pytest.raises(AssertionError):
            module.snapshot()
    else:
        result = module.snapshot()
        assert result["namespace"] == "mnt:[fixture]"
        assert result["mounts"] == [f"view {tmp_path}"]
        assert result["stub"] == stub.read_text()
        assert result["ipc"] == dict.fromkeys(
            ("io.systemd.Resolve", "io.systemd.Resolve.Monitor"), "marker"
        )
    assert connections == [
        str(host / n) for n in ("io.systemd.Resolve", "io.systemd.Resolve.Monitor")
    ]


@pytest.mark.parametrize("failure", [None, "mismatch", "timeout"])
def test_observe_waits_for_matching_request_and_identical_child(monkeypatch, tmp_path, failure):
    module = load("resolver_lifecycle")
    monkeypatch.setattr(module, "ROOT", tmp_path)
    clock = [0]
    monkeypatch.setattr(module.time, "monotonic", lambda: clock[0])

    def wait(seconds):
        clock[0] += 1
        if failure != "timeout":
            child = {"stub": "wrong" if failure == "mismatch" else "expected"}
            (tmp_path / "response").write_text(
                json.dumps({"request": "9", "stub": "expected", "child": child})
            )

    monkeypatch.setattr(module.time, "sleep", wait)
    (tmp_path / "response").write_text('{"request":"8"}')
    if failure:
        with pytest.raises(AssertionError):
            module.observe(9)
    else:
        assert module.observe(9) == {"request": "9", "stub": "expected", "child_matches": True}
    assert (tmp_path / "request").read_text() == "9"


def test_probe_atomically_publishes_once_per_request(monkeypatch, tmp_path):
    module = load("resolver_lifecycle")
    monkeypatch.setattr(module, "ROOT", tmp_path)
    calls = []
    monkeypatch.setattr(module, "snapshot", lambda: calls.append("sample") or {"stub": "fixture"})
    monkeypatch.setattr(module, "run", lambda *args: '{"stub":"fixture"}')
    (tmp_path / "request").write_text("1")
    waits = [0]

    def stop(seconds):
        waits[0] += 1
        if waits[0] == 2:
            raise InterruptedError("end simulated service loop")

    monkeypatch.setattr(module.time, "sleep", stop)
    with pytest.raises(InterruptedError):
        module.probe()
    assert calls == ["sample"]
    assert json.loads((tmp_path / "response").read_text()) == {
        "request": "1",
        "stub": "fixture",
        "child": {"stub": "fixture"},
    }
    assert not (tmp_path / "response.new").exists()
    assert (tmp_path / "ready").read_text().isdigit()


@pytest.mark.parametrize("failure", [None, "accept", "bind", "thread"])
def test_ipc_fixture_closes_all_resources_and_refuses_worker_errors(monkeypatch, tmp_path, failure):
    module = load("resolver_lifecycle")
    events = []
    servers = []

    class Event:
        value = False

        def is_set(self):
            return self.value

        def set(self):
            self.value = True

    event = Event()
    monkeypatch.setattr(module.threading, "Event", lambda: event)

    class Connection:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            events.append("connection closed")

        def sendall(self, data):
            assert data == b"first"
            event.set()

    class Server:
        calls = 0
        closed = False

        def bind(self, path):
            assert path.startswith(str(tmp_path))
            if failure == "bind":
                raise OSError("bind failed")

        def listen(self, count):
            assert count == 4

        def settimeout(self, timeout):
            assert timeout == 0.1

        def accept(self):
            self.calls += 1
            if failure == "accept":
                raise OSError("accept failed")
            if self.calls == 1:
                raise module.socket.timeout()
            return Connection(), None

        def close(self):
            self.closed = True

    def socket(*args):
        server = Server()
        servers.append(server)
        return server

    class Thread:
        def __init__(self, target):
            self.target = target

        def start(self):
            event.value = False
            self.target()

        def join(self, seconds):
            assert seconds == 3

        def is_alive(self):
            return failure == "thread"

    monkeypatch.setattr(module.socket, "socket", socket)
    monkeypatch.setattr(module.threading, "Thread", Thread)
    if failure == "bind":
        with pytest.raises(OSError):
            module.IPC(tmp_path, "first")
    else:
        ipc = module.IPC(tmp_path, "first")
        if failure:
            with pytest.raises(AssertionError):
                ipc.close()
        else:
            ipc.close()
            assert events == ["connection closed", "connection closed"]
    assert all(server.closed for server in servers)


def test_refused_requires_a_failure_not_silent_success():
    module = load("resolver_lifecycle")
    records = []
    with pytest.raises(AssertionError, match="unsafe acceptance"):
        module.refused(lambda: None, "expected guard", records)
    assert records == []


def test_lifecycle_loads_production_module_with_only_disposable_path_substitutions(
    monkeypatch, tmp_path
):
    module = load("resolver_lifecycle")
    monkeypatch.setattr(module, "ROOT", tmp_path)
    dns = module.module()
    assert dns.STATE == tmp_path / "run/sugarkube-ethernet-dns"
    assert dns.RESOLVED == tmp_path / "run/systemd/resolve"
    assert dns.HOST_RESOLV == tmp_path / "etc/resolv.conf"
    assert dns.SERVICE == Path("/etc/systemd/system/sugarkube-ethernet-dns.service")
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize(
    "name", ["resolver_lifecycle", "resolver_oneshot", "resolver_offline_prepare"]
)
def test_optimized_entrypoints_fail_before_argument_or_guest_handling(monkeypatch, name):
    import runpy

    monkeypatch.syspath_prepend(str(DIRECTORY))
    flags = {n: getattr(sys.flags, n) for n in dir(sys.flags) if not n.startswith("_")}
    flags["optimize"] = 1
    monkeypatch.setattr(sys, "flags", SimpleNamespace(**flags))
    monkeypatch.setattr(sys, "argv", [name, "--help"])
    with pytest.raises(SystemExit, match="requires assertions enabled"):
        runpy.run_path(str(DIRECTORY / f"{name}.py"), run_name="__main__")


def test_builder_cli_rejects_non_commit_before_git(monkeypatch, tmp_path):
    import runpy

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "build",
            "--repo",
            str(tmp_path),
            "--commit",
            "main",
            "--output",
            str(tmp_path / "output.tgz"),
        ],
    )
    monkeypatch.setattr(subprocess, "check_output", lambda *a, **k: pytest.fail("unexpected git"))
    with pytest.raises(ValueError, match="full commit SHA"):
        runpy.run_path(str(DIRECTORY / "build_resolver_bundle.py"), run_name="__main__")
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("valid_args", [False, True])
def test_offline_cli_never_installs_or_executes(monkeypatch, tmp_path, valid_args):
    import runpy

    bundle = tmp_path / "bundle"
    bundle.mkdir()
    (bundle / "python-dependencies.json").write_text('{"packages":[]}')
    destination = tmp_path / "deps"
    monkeypatch.setattr(
        sys, "argv", ["offline"] + ([str(bundle), str(destination)] if valid_args else [])
    )
    if valid_args:
        runpy.run_path(str(DIRECTORY / "resolver_offline_prepare.py"), run_name="__main__")
        assert destination.is_dir() and not list(destination.iterdir())
    else:
        with pytest.raises(SystemExit, match="Usage:"):
            runpy.run_path(str(DIRECTORY / "resolver_offline_prepare.py"), run_name="__main__")
        assert not destination.exists()


def test_supervisor_cli_refuses_wrong_guest_without_commands(monkeypatch, tmp_path):
    import runpy
    import socket

    monkeypatch.syspath_prepend(str(DIRECTORY))
    monkeypatch.setattr(sys, "argv", ["oneshot", "--run-approved", str(tmp_path)])
    monkeypatch.setattr(socket, "gethostname", lambda: "wrong-guest")
    monkeypatch.setattr(
        subprocess, "check_output", lambda *a, **k: pytest.fail("unexpected command")
    )
    with pytest.raises(SystemExit, match="wrong guest or missing root"):
        runpy.run_path(str(DIRECTORY / "resolver_oneshot.py"), run_name="__main__")
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("existing", [False, True])
def test_lifecycle_cli_preserves_early_error_without_overwriting_result(
    monkeypatch, tmp_path, existing
):
    import os
    import runpy
    import signal

    output = tmp_path / "result.json"
    if existing:
        output.write_text('{"previous":"evidence"}')
    monkeypatch.setattr(sys, "argv", ["lifecycle", "--run-approved", str(output)])

    def unreadable(path, *args, **kwargs):
        raise OSError("resolver unavailable")

    monkeypatch.setattr(os, "readlink", unreadable)
    handlers = []
    monkeypatch.setattr(signal, "signal", lambda sig, handler: handlers.append((sig, handler)))
    monkeypatch.setattr(
        subprocess, "check_output", lambda *a, **k: pytest.fail("unexpected command")
    )
    with pytest.raises((OSError, AssertionError)):
        runpy.run_path(str(DIRECTORY / "resolver_lifecycle.py"), run_name="__main__")
    result = json.loads(output.read_text())
    if existing:
        assert result == {"previous": "evidence"}
    else:
        assert result["passed"] is False and result["early_error"]
    assert handlers[0][0] == signal.SIGTERM
    with pytest.raises(InterruptedError, match="qualification interrupted"):
        handlers[0][1](signal.SIGTERM, None)


def test_supervisor_removes_only_owned_fixture_after_process_and_mount_checks(
    supervisor, monkeypatch
):
    module, state, bundle, path, clock = supervisor
    fixture = bundle / "owned-fixture"
    events = []

    class OwnedFixture:
        def __str__(self):
            return str(fixture)

        def __fspath__(self):
            return str(fixture)

        def is_symlink(self):
            return False

        def is_dir(self):
            return fixture.is_dir()

        def stat(self):
            return SimpleNamespace(st_uid=0)

    original_launch = module.subprocess.Popen

    def launch(*args, **kwargs):
        process = original_launch(*args, **kwargs)
        fixture.mkdir()
        return process

    monkeypatch.setattr(module.subprocess, "Popen", launch)
    monkeypatch.setattr(module, "fixtures", lambda: [OwnedFixture()] if fixture.exists() else [])
    remove = module.shutil.rmtree

    def checked_remove(target):
        assert not state["records"] and not state["mounts"] and not state["cgroups"]
        events.append(str(target))
        remove(target)

    monkeypatch.setattr(module.shutil, "rmtree", checked_remove)
    assert module.main(bundle) == 0
    assert events == [str(fixture)] and not fixture.exists()


def test_lifecycle_waits_for_new_probe_readiness_before_tamper_check(lifecycle, monkeypatch):
    module, state, dns, output, units, proc = lifecycle
    original = module.run
    delayed = [False]

    def run(*args):
        result = original(*args)
        if (
            args[:3] == ("systemctl", "start", module.UNITS[1])
            and "BindPaths=" in (units / module.UNITS[1]).read_text()
        ):
            (module.ROOT / "ready").unlink()
            delayed[0] = True
        return result

    monkeypatch.setattr(module, "run", run)
    waits = []

    def ready(seconds):
        assert delayed[0]
        waits.append(seconds)
        (module.ROOT / "ready").write_text("123")

    monkeypatch.setattr(module.time, "sleep", ready)
    module.qualify(output)
    assert waits == [0.05]
    assert json.loads(output.read_text())["passed"]
