"""Unit tests for network namespace TCP connectivity probes."""

from __future__ import annotations

import subprocess
from types import SimpleNamespace

from tests.helpers.netns_probe import NamespaceProbeResult, probe_namespace_connectivity


class _DummyProc:
    def __init__(self, cmd, **_: object) -> None:  # noqa: D401 - test helper
        self.cmd = cmd
        self.terminated = False
        self.returncode = 0

    def wait(self, timeout: float | None = None) -> int:  # noqa: D401 - test helper
        self.wait_timeout = timeout
        return self.returncode

    def terminate(self) -> None:  # noqa: D401 - test helper
        self.terminated = True


def test_probe_uses_python_tcp_handshake() -> None:
    """The connectivity probe should rely on python sockets instead of ping."""

    commands: list[list[str]] = []

    def runner(cmd, **_: object):  # noqa: ANN001 - signature matches subprocess.run
        commands.append(cmd)
        return SimpleNamespace(returncode=0)

    proc_holder: list[_DummyProc] = []

    def spawner(cmd, **kwargs: object) -> _DummyProc:  # noqa: ANN001 - subprocess signature
        proc = _DummyProc(cmd, **kwargs)
        proc_holder.append(proc)
        return proc

    result = probe_namespace_connectivity(
        "ns-client",
        "ns-server",
        "192.168.50.2",
        run_cmd=runner,
        popen_cmd=spawner,
        sleep_fn=lambda _: None,
    )

    assert result, "TCP connectivity probe should succeed when both commands return 0"
    assert isinstance(result, NamespaceProbeResult)
    assert result.attempts == 1
    assert proc_holder, "Server process should be spawned"
    server_cmd = proc_holder[0].cmd
    assert server_cmd[:4] == ["ip", "netns", "exec", "ns-server"]
    assert server_cmd[4] == "python3"

    assert commands, "Client command should be invoked"
    client_cmd = commands[0]
    assert client_cmd[:4] == ["ip", "netns", "exec", "ns-client"]
    assert client_cmd[4] == "python3"


def test_probe_terminates_server_on_client_failure() -> None:
    """Server processes should be cleaned up when the client cannot connect."""

    def failing_runner(cmd, **_: object):  # noqa: ANN001 - subprocess signature
        return SimpleNamespace(returncode=1)

    proc_holder: list[_DummyProc] = []

    def spawner(cmd, **kwargs: object) -> _DummyProc:  # noqa: ANN001
        proc = _DummyProc(cmd, **kwargs)
        proc.returncode = 1
        proc_holder.append(proc)
        return proc

    result = probe_namespace_connectivity(
        "ns-client",
        "ns-server",
        "192.168.50.2",
        run_cmd=failing_runner,
        popen_cmd=spawner,
        sleep_fn=lambda _: None,
    )

    assert not result, "Probe should fail when client cannot connect"
    assert proc_holder, "Server process should be spawned even when client fails"
    assert proc_holder[0].terminated, "Server process should be terminated on failure"


def test_probe_returns_false_when_server_spawn_fails() -> None:
    """Server startup errors should cause the probe to fail gracefully."""

    def spawner(*_: object, **__: object) -> None:  # noqa: ANN001 - subprocess signature
        raise RuntimeError("boom")

    result = probe_namespace_connectivity(
        "ns-client",
        "ns-server",
        "192.168.50.2",
        popen_cmd=spawner,
        sleep_fn=lambda _: None,
    )

    assert not result, "Probe should return False when the server process cannot start"


def test_probe_wait_timeout_triggers_cleanup() -> None:
    """Timeout while waiting for server should terminate the process and fail the probe."""

    commands: list[list[str]] = []

    def runner(cmd, **_: object):  # noqa: ANN001 - subprocess.run signature
        commands.append(cmd)
        return SimpleNamespace(returncode=0)

    class _TimeoutProc(_DummyProc):
        def wait(self, timeout: float | None = None) -> int:  # noqa: D401 - test helper
            self.wait_timeout = timeout
            raise subprocess.TimeoutExpired(cmd="server", timeout=timeout or 0)

    proc_holder: list[_TimeoutProc] = []

    def spawner(cmd, **kwargs: object) -> _TimeoutProc:  # noqa: ANN001 - subprocess signature
        proc = _TimeoutProc(cmd, **kwargs)
        proc_holder.append(proc)
        return proc

    result = probe_namespace_connectivity(
        "ns-client",
        "ns-server",
        "192.168.50.2",
        run_cmd=runner,
        popen_cmd=spawner,
        sleep_fn=lambda _: None,
    )

    assert not result, "Probe should return False when the server wait times out"
    assert proc_holder and proc_holder[0].terminated, "Server should be terminated on timeout"
    assert commands, "Client command should have been executed before timeout"


def test_probe_handles_server_wait_error() -> None:
    """Generic wait errors should fail the probe and trigger cleanup."""

    def runner(cmd, **_: object):  # noqa: ANN001 - subprocess.run signature
        return SimpleNamespace(returncode=0)

    class _ErrorProc(_DummyProc):
        def wait(self, timeout: float | None = None) -> int:  # noqa: D401 - test helper
            self.wait_timeout = timeout
            raise RuntimeError("boom")

    proc_holder: list[_ErrorProc] = []

    def spawner(cmd, **kwargs: object) -> _ErrorProc:  # noqa: ANN001 - subprocess signature
        proc = _ErrorProc(cmd, **kwargs)
        proc_holder.append(proc)
        return proc

    result = probe_namespace_connectivity(
        "ns-client",
        "ns-server",
        "192.168.50.2",
        run_cmd=runner,
        popen_cmd=spawner,
        sleep_fn=lambda _: None,
    )

    assert not result, "Probe should return False when wait raises an unexpected error"
    assert proc_holder and proc_holder[0].terminated, "Server should be terminated on error"


def test_probe_uses_configurable_start_delay() -> None:
    """Custom start delay should be passed to the sleep function."""

    def runner(cmd, **_: object):  # noqa: ANN001 - subprocess.run signature
        return SimpleNamespace(returncode=0)

    proc_holder: list[_DummyProc] = []

    def spawner(cmd, **kwargs: object) -> _DummyProc:  # noqa: ANN001 - subprocess signature
        proc = _DummyProc(cmd, **kwargs)
        proc_holder.append(proc)
        return proc

    sleep_calls: list[float] = []

    def sleeper(duration: float) -> None:
        sleep_calls.append(duration)

    result = probe_namespace_connectivity(
        "ns-client",
        "ns-server",
        "192.168.50.2",
        run_cmd=runner,
        popen_cmd=spawner,
        sleep_fn=sleeper,
        server_start_delay=1.5,
    )

    assert result, "Probe should still succeed with a custom delay"
    assert sleep_calls == [1.5], "Sleep should be invoked with the configured delay"


def test_probe_retries_before_succeeding() -> None:
    """Transient client failures should retry with diagnostic breadcrumbs."""

    commands: list[list[str]] = []

    def runner(cmd, **_: object):  # noqa: ANN001 - subprocess.run signature
        commands.append(cmd)
        code = 1 if len(commands) == 1 else 0
        return SimpleNamespace(returncode=code, stderr="probe failed" if code else "")

    proc_holder: list[_DummyProc] = []

    def spawner(cmd, **kwargs: object) -> _DummyProc:  # noqa: ANN001 - subprocess signature
        proc = _DummyProc(cmd, **kwargs)
        proc_holder.append(proc)
        return proc

    result = probe_namespace_connectivity(
        "ns-client",
        "ns-server",
        "192.168.50.2",
        run_cmd=runner,
        popen_cmd=spawner,
        sleep_fn=lambda _: None,
        retry_delay=0,
        attempts=2,
    )

    assert result, "Probe should retry and succeed on a subsequent attempt"
    assert result.attempts == 2
    assert proc_holder and proc_holder[0].terminated, "First server should be cleaned up"
    assert result.errors and "client attempt 1" in result.errors[0]


def test_probe_surfaces_reason_on_spawn_failure() -> None:
    """Spawn failures should include a human-readable reason for skips."""

    def spawner(*_: object, **__: object):  # noqa: ANN001 - subprocess signature
        raise RuntimeError("netns disabled")

    result = probe_namespace_connectivity(
        "ns-client",
        "ns-server",
        "192.168.50.2",
        popen_cmd=spawner,
        sleep_fn=lambda _: None,
        retry_delay=0,
        attempts=1,
    )

    assert not result, "Probe should fail when namespaces cannot be spawned"
    assert result.attempts == 1
    assert result.reason and "netns disabled" in result.reason
    assert result.errors == [result.reason]
