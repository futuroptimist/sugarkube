import subprocess
import sys
from pathlib import Path

# Add scripts/ to import path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
from k3s_mdns_query import query_mdns  # noqa: E402


def _sample_server_stdout() -> str:
    return (
        "=;eth0;IPv4;k3s-sugar-dev@host0 (server);_k3s-sugar-dev._tcp;local;host0.local;"
        "192.168.1.10;6443;txt=k3s=1;txt=cluster=sugar;txt=env=dev;txt=role=server\n"
    )


def test_query_mdns_keeps_output_when_avahi_errors():
    messages = []

    calls = []

    def runner(command, capture_output, text, check, timeout=None):
        assert command[0] == "avahi-browse"
        assert capture_output and text and not check
        assert timeout is not None and timeout > 0
        calls.append(command[-1])
        if command[-1] == "_k3s-sugar-dev._tcp":
            return subprocess.CompletedProcess(
                command,
                returncode=255,
                stdout=_sample_server_stdout(),
                stderr="Failed to resolve",
            )
        return subprocess.CompletedProcess(
            command,
            returncode=0,
            stdout="",
            stderr="",
        )

    results = query_mdns(
        "server-first",
        "sugar",
        "dev",
        runner=runner,
        debug=messages.append,
    )

    assert results == ["host0.local"]
    assert any("255" in msg for msg in messages)
    assert calls == ["_k3s-sugar-dev._tcp", "_https._tcp"]


def test_query_mdns_handles_avahi_timeout():
    messages = []

    calls = []

    def runner(command, capture_output, text, check, timeout=None, env=None):
        calls.append(timeout)
        raise subprocess.TimeoutExpired(command, timeout, output=_sample_server_stdout())

    results = query_mdns(
        "server-first",
        "sugar",
        "dev",
        runner=runner,
        debug=messages.append,
    )

    assert results == ["host0.local"]
    # With retry logic: 2 attempts per service type (primary + legacy) = 4 calls
    assert len(calls) == 4
    assert all(call and call > 0 for call in calls)
    assert any("timed out" in msg for msg in messages)


def test_query_mdns_queries_legacy_service_type_when_needed():
    legacy_stdout = (
        "=;eth0;IPv4;k3s API sugar/dev [server] on host0;_https._tcp;local;host0.local;"
        "192.168.1.50;6443;txt=k3s=1;txt=cluster=sugar;txt=env=dev;txt=role=server\n"
    )

    calls = []

    def runner(command, capture_output, text, check, timeout=None):
        assert command[0] == "avahi-browse"
        assert capture_output and text and not check
        assert timeout is not None and timeout > 0
        calls.append(command[-1])
        if command[-1] == "_https._tcp":
            return subprocess.CompletedProcess(
                command,
                returncode=0,
                stdout=legacy_stdout,
                stderr="",
            )
        return subprocess.CompletedProcess(
            command,
            returncode=0,
            stdout="",
            stderr="",
        )

    results = query_mdns(
        "server-first",
        "sugar",
        "dev",
        runner=runner,
    )

    assert results == ["host0.local"]
    assert calls == ["_k3s-sugar-dev._tcp", "_https._tcp"]


def test_query_mdns_bootstrap_leaders_uses_txt_leader(tmp_path):
    fixture = tmp_path / "mdns.txt"
    fixture.write_text(
        (
            "=;eth0;IPv4;k3s-sugar-dev@host1 (bootstrap);_k3s-sugar-dev._tcp;local;host1.local;"
            "192.168.1.11;6443;txt=k3s=1;txt=cluster=sugar;txt=env=dev;"
            "txt=role=bootstrap;txt=phase=bootstrap;txt=leader=leader0.local\n"
            "=;eth0;IPv4;k3s-sugar-dev@host2 (bootstrap);_k3s-sugar-dev._tcp;local;host2.local;"
            "192.168.1.12;6443;txt=k3s=1;txt=cluster=sugar;txt=env=dev;"
            "txt=role=bootstrap;txt=phase=bootstrap\n"
        ),
        encoding="utf-8",
    )

    results = query_mdns(
        "bootstrap-leaders",
        "sugar",
        "dev",
        fixture_path=str(fixture),
    )

    assert results == ["leader0.local", "host2.local"]


def test_query_mdns_uses_service_name_when_unresolved(tmp_path):
    fixture = tmp_path / "mdns.txt"
    fixture.write_text(
        "+;eth0;IPv4;k3s-sugar-dev@host3 (bootstrap);_k3s-sugar-dev._tcp;local\n",
        encoding="utf-8",
    )

    results = query_mdns(
        "bootstrap-leaders",
        "sugar",
        "dev",
        fixture_path=str(fixture),
    )

    assert results == ["host3.local"]


def test_query_mdns_handles_missing_avahi():
    messages = []

    def runner(command, capture_output, text, check, timeout=None):
        raise FileNotFoundError("avahi-browse missing")

    results = query_mdns(
        "server-first",
        "sugar",
        "dev",
        runner=runner,
        debug=messages.append,
    )

    assert results == []
    assert any("not found" in message for message in messages)


def test_query_mdns_server_hosts_returns_unique_hosts(tmp_path):
    fixture = tmp_path / "servers.txt"
    fixture.write_text(
        (
            "=;eth0;IPv4;k3s-sugar-dev@host0 (server);_k3s-sugar-dev._tcp;local;host0.local;"
            "192.168.1.10;6443;txt=k3s=1;txt=cluster=sugar;txt=env=dev;txt=role=server\n"
            "=;eth0;IPv6;k3s-sugar-dev@host0 (server);_k3s-sugar-dev._tcp;local;host0.local;"
            "fe80::1;6443;txt=k3s=1;txt=cluster=sugar;txt=env=dev;txt=role=server\n"
            "=;eth0;IPv4;k3s-sugar-dev@host1 (server);_k3s-sugar-dev._tcp;local;host1.local;"
            "192.168.1.11;6443;txt=k3s=1;txt=cluster=sugar;txt=env=dev;txt=role=server\n"
            "=;eth0;IPv4;k3s-sugar-dev@host2 (bootstrap);_k3s-sugar-dev._tcp;local;host2.local;"
            "192.168.1.12;6443;txt=k3s=1;txt=cluster=sugar;txt=env=dev;txt=role=bootstrap\n"
        ),
        encoding="utf-8",
    )

    results = query_mdns(
        "server-hosts",
        "sugar",
        "dev",
        fixture_path=str(fixture),
    )

    assert results == ["host0.local", "host1.local"]


def test_query_mdns_falls_back_without_resolve():
    unresolved = "+;eth0;IPv4;k3s-sugar-dev@host0 (bootstrap);_k3s-sugar-dev._tcp;local\n"

    calls = []

    def runner(command, capture_output, text, check, timeout=None):
        assert command[0] == "avahi-browse"
        assert capture_output and text and not check
        resolve = "--resolve" in command
        service = command[-1]
        calls.append((service, resolve))
        if service == "_k3s-sugar-dev._tcp" and not resolve:
            stdout = unresolved
        else:
            stdout = ""
        return subprocess.CompletedProcess(command, 0, stdout=stdout, stderr="")

    results = query_mdns(
        "bootstrap-leaders",
        "sugar",
        "dev",
        runner=runner,
    )

    assert results == ["host0.local"]
    assert calls == [
        ("_k3s-sugar-dev._tcp", True),
        ("_https._tcp", True),
        ("_k3s-sugar-dev._tcp", False),
        ("_https._tcp", False),
    ]


def test_query_mdns_retries_on_failure():
    """Test that avahi-browse is retried once if it fails without output."""
    messages = []
    call_count = [0]

    def runner(command, capture_output, text, check, timeout=None, env=None):
        assert command[0] == "avahi-browse"
        call_count[0] += 1

        # First call fails, second succeeds
        if call_count[0] == 1:
            return subprocess.CompletedProcess(
                command,
                returncode=1,
                stdout="",
                stderr="Daemon not running",
            )
        else:
            return subprocess.CompletedProcess(
                command,
                returncode=0,
                stdout=_sample_server_stdout(),
                stderr="",
            )

    results = query_mdns(
        "server-first",
        "sugar",
        "dev",
        runner=runner,
        debug=messages.append,
    )

    # Should succeed on retry
    assert results == ["host0.local"]
    # Should have retried (2 attempts for primary service + 2 for legacy)
    assert call_count[0] >= 2
    assert any("retrying" in msg.lower() for msg in messages)


def test_query_mdns_logs_exit_codes_and_stderr():
    """Test that exit codes and stderr are logged."""
    messages = []

    def runner(command, capture_output, text, check, timeout=None, env=None):
        return subprocess.CompletedProcess(
            command,
            returncode=42,
            stdout=_sample_server_stdout(),
            stderr="Some error message",
        )

    results = query_mdns(
        "server-first",
        "sugar",
        "dev",
        runner=runner,
        debug=messages.append,
    )

    assert results == ["host0.local"]
    # Check that exit code is logged
    assert any("exit_code=42" in msg for msg in messages)
    # Check that stderr is logged
    assert any("Some error message" in msg for msg in messages)


def test_query_mdns_uses_allow_iface():
    """Test that ALLOW_IFACE env variable adds --interface option."""
    import os

    original_env = os.environ.get("ALLOW_IFACE")
    try:
        os.environ["ALLOW_IFACE"] = "eth0"
        commands_seen = []

        def runner(command, capture_output, text, check, timeout=None, env=None):
            commands_seen.append(command)
            return subprocess.CompletedProcess(
                command,
                returncode=0,
                stdout=_sample_server_stdout(),
                stderr="",
            )

        results = query_mdns(
            "server-first",
            "sugar",
            "dev",
            runner=runner,
        )

        assert results == ["host0.local"]
        # Check that --interface=eth0 was added
        assert any("--interface=eth0" in cmd for cmd in commands_seen)
    finally:
        if original_env is not None:
            os.environ["ALLOW_IFACE"] = original_env
        else:
            os.environ.pop("ALLOW_IFACE", None)
