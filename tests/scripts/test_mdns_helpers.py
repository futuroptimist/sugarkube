import subprocess
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[2] / "scripts"))

from mdns_helpers import _norm_host, _same_host, ensure_self_ad_is_visible  # noqa: E402


class FakeRunner:
    def __init__(self, responses):
        self._responses = responses
        self._calls = {}

    def __call__(self, command, capture_output, text, check):
        service = command[-1]
        idx = self._calls.get(service, 0)
        self._calls[service] = idx + 1
        stdout_values = self._responses.get(service, [])
        stdout = stdout_values[idx] if idx < len(stdout_values) else ""
        return subprocess.CompletedProcess(command, 0, stdout=stdout, stderr="")


def test_same_host_handles_case_and_suffix():
    assert _same_host("Host.Local.", "host.local")
    assert _same_host("HOST", "host.local")
    assert not _same_host("host-a", "host-b.local")


def test_ensure_self_ad_is_visible_requires_phase():
    bootstrap_record = (
        "=;eth0;IPv4;k3s-sugar-dev@host0 (bootstrap);_k3s-sugar-dev._tcp;local;host0.local;"
        "192.0.2.10;6443;txt=k3s=1;txt=cluster=sugar;txt=env=dev;txt=role=bootstrap;"
        "txt=leader=host0.local;txt=phase=bootstrap\n"
    )
    server_record = (
        "=;eth0;IPv4;k3s-sugar-dev@host0 (server);_k3s-sugar-dev._tcp;local;host0.local;"
        "192.0.2.10;6443;txt=k3s=1;txt=cluster=sugar;txt=env=dev;txt=role=server;"
        "txt=leader=host0.local;txt=phase=server\n"
    )
    responses = {
        "_k3s-sugar-dev._tcp": ["", bootstrap_record, "", server_record],
        "_https._tcp": ["", "", "", ""],
    }
    runner = FakeRunner(responses)

    result = ensure_self_ad_is_visible(
        expected_host="host0.local",
        cluster="sugar",
        env="dev",
        retries=4,
        delay=0.0,
        require_phase="server",
        runner=runner,
    )
    assert result is not None
    observed, attempt = result
    assert observed == "host0.local"
    assert attempt == 4


def test_ensure_self_ad_matches_leader_when_host_differs():
    server_record = (
        "=;eth0;IPv4;k3s-sugar-dev@host1 (server);_k3s-sugar-dev._tcp;local;host1.local;"
        "192.0.2.11;6443;txt=k3s=1;txt=cluster=sugar;txt=env=dev;txt=role=server;"
        "txt=leader=expected.local;txt=phase=server\n"
    )
    responses = {
        "_k3s-sugar-dev._tcp": [server_record],
        "_https._tcp": [""],
    }
    runner = FakeRunner(responses)

    result = ensure_self_ad_is_visible(
        expected_host="expected.local",
        cluster="sugar",
        env="dev",
        retries=1,
        delay=0.0,
        require_phase="server",
        runner=runner,
    )
    assert result is not None
    observed, attempt = result
    assert observed == "expected.local"
    assert attempt == 1


def test_norm_host_strips_trailing_dots():
    assert _norm_host("Host.LOCAL.") == "host.local"
    assert _norm_host("example.com...") == "example.com"
