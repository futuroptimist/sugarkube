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
        effect = None
        if isinstance(self.wait_side_effect, list):
            if self.wait_side_effect:
                effect = self.wait_side_effect.pop(0)
        elif self.wait_side_effect:
            effect = self.wait_side_effect
            self.wait_side_effect = None

        if effect:
            raise effect

        self.poll_result = 0

    def terminate(self):
        self.terminated = True

    def kill(self):
        self.killed = True


def test_probe_namespace_connectivity_success():
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


def test_probe_namespace_connectivity_terminates_on_failure():
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


def test_probe_namespace_connectivity_client_timeout_returns_false():
    proc = DummyProc(poll_result=None)

    def fake_popen(cmd, **kwargs):
        return proc

    def fake_run(cmd, **kwargs):
        raise subprocess.TimeoutExpired(cmd, timeout=2)

    assert not probe_namespace_connectivity(
        "ns-one",
        "ns-two",
        "192.168.100.2",
        popen_factory=fake_popen,
        run_command=fake_run,
        timeout_secs=2,
    )

    assert proc.terminated


def test_probe_namespace_connectivity_server_wait_timeout_triggers_kill():
    timeout_error = subprocess.TimeoutExpired(cmd="wait", timeout=2)
    proc = DummyProc(poll_result=None, wait_side_effect=[timeout_error, timeout_error])

    def fake_popen(cmd, **kwargs):
        return proc

    def fake_run(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, 0, stdout="ok", stderr="")

    assert not probe_namespace_connectivity(
        "ns-one",
        "ns-two",
        "192.168.100.2",
        popen_factory=fake_popen,
        run_command=fake_run,
        timeout_secs=1,
    )

    assert proc.terminated
    assert proc.killed
    assert proc.wait_called
