from __future__ import annotations

import subprocess

from tests.mdns_namespace_utils import probe_namespace_connectivity


class DummyProc:
    def __init__(self, poll_result=None, wait_side_effect=None):
        self.poll_result = poll_result
        self.wait_side_effect = wait_side_effect
        self.wait_called = False
        self.terminated = False
        self.killed = False

    def poll(self):
        return self.poll_result

    def wait(self, timeout=None):
        self.wait_called = True
        if self.wait_side_effect:
            raise self.wait_side_effect
        self.poll_result = 0

    def terminate(self):
        self.terminated = True

    def kill(self):
        self.killed = True


def test_probe_namespace_connectivity_success(monkeypatch):
    proc = DummyProc(poll_result=None)
    calls = {}

    def fake_popen(cmd, **kwargs):
        calls["server"] = cmd
        return proc

    def fake_run(cmd, **kwargs):
        calls["client"] = cmd
        return subprocess.CompletedProcess(cmd, 0, stdout="ok", stderr="")

    assert probe_namespace_connectivity(
        "ns-one",
        "ns-two",
        "192.168.100.2",
        popen_factory=fake_popen,
        run_command=fake_run,
        timeout_secs=2,
    )

    assert calls["server"][:3] == ["ip", "netns", "exec"]
    assert "python" in calls["server"]
    assert calls["client"][:3] == ["ip", "netns", "exec"]
    assert proc.wait_called
    assert not proc.terminated


def test_probe_namespace_connectivity_terminates_on_failure(monkeypatch):
    proc = DummyProc(poll_result=None)
    calls = {}

    def fake_popen(cmd, **kwargs):
        calls["server"] = cmd
        return proc

    def fake_run(cmd, **kwargs):
        calls["client"] = cmd
        return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="boom")

    assert not probe_namespace_connectivity(
        "ns-one",
        "ns-two",
        "192.168.100.2",
        popen_factory=fake_popen,
        run_command=fake_run,
        timeout_secs=2,
    )

    assert calls["server"][:3] == ["ip", "netns", "exec"]
    assert calls["client"][:3] == ["ip", "netns", "exec"]
    assert proc.terminated
    assert proc.wait_called
