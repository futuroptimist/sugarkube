"""Unit tests for network namespace TCP connectivity probes."""

from __future__ import annotations

from types import SimpleNamespace

from tests.helpers.netns_probe import probe_namespace_connectivity


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
