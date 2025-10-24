import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
from mdns_helpers import _same_host, ensure_self_ad_is_visible  # noqa: E402


def _make_runner(stdout_by_service):
    def _runner(cmd, capture_output=True, text=True, check=False):
        service_type = cmd[-1]
        stdout = stdout_by_service.get(service_type, "")
        return subprocess.CompletedProcess(cmd, 0, stdout=stdout, stderr="")

    return _runner


def test_same_host_normalises_case_and_trailing_dots():
    assert _same_host("Host.LOCAL.", "host.local")
    assert _same_host("host.local", "HOST")
    assert not _same_host("host-a", "host-b")


def test_ensure_self_ad_is_visible_filters_by_phase():
    bootstrap_record = (
        "=;eth0;IPv4;k3s-sugar-dev@host0 (bootstrap);_k3s-sugar-dev._tcp;"
        "local;host0.local;192.0.2.10;6443;"
        "txt=k3s=1;txt=cluster=sugar;txt=env=dev;txt=role=bootstrap;"
        "txt=leader=host0.local;txt=phase=bootstrap\n"
    )
    server_record = (
        "=;eth0;IPv4;k3s-sugar-dev@host0 (server);_k3s-sugar-dev._tcp;"
        "local;host0.local;192.0.2.10;6443;"
        "txt=k3s=1;txt=cluster=sugar;txt=env=dev;txt=role=server;"
        "txt=leader=host0.local;txt=phase=server\n"
    )

    runner = _make_runner({
        "_k3s-sugar-dev._tcp": bootstrap_record + server_record,
        "_https._tcp": "",
    })

    observed_bootstrap = ensure_self_ad_is_visible(
        expected_host="HOST0.LOCAL.",
        cluster="sugar",
        env="dev",
        retries=1,
        delay=0,
        require_phase="bootstrap",
        runner=runner,
        sleep=lambda _: None,
    )
    assert observed_bootstrap == "host0.local"

    observed_server = ensure_self_ad_is_visible(
        expected_host="host0.local",
        cluster="sugar",
        env="dev",
        retries=1,
        delay=0,
        require_phase="server",
        runner=runner,
        sleep=lambda _: None,
    )
    assert observed_server == "host0.local"

    missing_server = ensure_self_ad_is_visible(
        expected_host="host0.local",
        cluster="sugar",
        env="dev",
        retries=1,
        delay=0,
        require_phase="server",
        runner=_make_runner({"_k3s-sugar-dev._tcp": bootstrap_record}),
        sleep=lambda _: None,
    )
    assert missing_server is None


def test_ensure_self_ad_is_visible_matches_expected_address():
    record = (
        "=;eth0;IPv4;k3s-sugar-dev@host0 (server);_k3s-sugar-dev._tcp;"
        "local;host0.local;192.0.2.10;6443;"
        "txt=k3s=1;txt=cluster=sugar;txt=env=dev;txt=role=server;"
        "txt=leader=host0.local;txt=phase=server\n"
    )

    runner = _make_runner({"_k3s-sugar-dev._tcp": record})

    observed = ensure_self_ad_is_visible(
        expected_host="host0.local",
        cluster="sugar",
        env="dev",
        retries=1,
        delay=0,
        require_phase="server",
        expect_addr="192.0.2.10",
        runner=runner,
        sleep=lambda _: None,
    )
    assert observed == "host0.local"

    missing = ensure_self_ad_is_visible(
        expected_host="host0.local",
        cluster="sugar",
        env="dev",
        retries=1,
        delay=0,
        require_phase="server",
        expect_addr="192.0.2.250",
        runner=runner,
        sleep=lambda _: None,
    )
    assert missing is None


def test_ensure_self_ad_is_visible_accepts_missing_address(capsys):
    record = (
        "=;eth0;IPv4;k3s-sugar-dev@host0 (bootstrap);_k3s-sugar-dev._tcp;"
        "local;host0.local;;6443;"
        "txt=k3s=1;txt=cluster=sugar;txt=env=dev;txt=role=bootstrap;"
        "txt=leader=host0.local;txt=phase=bootstrap\n"
    )

    runner = _make_runner({"_k3s-sugar-dev._tcp": record})

    observed = ensure_self_ad_is_visible(
        expected_host="host0.local",
        cluster="sugar",
        env="dev",
        retries=1,
        delay=0,
        require_phase="bootstrap",
        expect_addr="192.0.2.10",
        runner=runner,
        sleep=lambda _: None,
    )

    assert observed == "host0.local"
    warning = capsys.readouterr().err
    assert "advertisement omitted address" in warning


def test_ensure_self_ad_is_visible_accepts_matching_role_when_phase_missing():
    record = (
        "=;eth0;IPv4;k3s-sugar-dev@host0 (bootstrap);_k3s-sugar-dev._tcp;"
        "local;host0.local;192.0.2.10;6443;"
        "txt=k3s=1;txt=cluster=sugar;txt=env=dev;txt=role=bootstrap;"
        "txt=leader=host0.local\n"
    )

    runner = _make_runner({"_k3s-sugar-dev._tcp": record})

    observed = ensure_self_ad_is_visible(
        expected_host="host0.local",
        cluster="sugar",
        env="dev",
        retries=1,
        delay=0,
        require_phase="bootstrap",
        runner=runner,
        sleep=lambda _: None,
    )

    assert observed == "host0.local"

    mismatched_role = ensure_self_ad_is_visible(
        expected_host="host0.local",
        cluster="sugar",
        env="dev",
        retries=1,
        delay=0,
        require_phase="server",
        runner=runner,
        sleep=lambda _: None,
    )

    assert mismatched_role is None

    server_record = record.replace("role=bootstrap", "role=server")
    runner_server = _make_runner({"_k3s-sugar-dev._tcp": server_record})

    missing_bootstrap = ensure_self_ad_is_visible(
        expected_host="host0.local",
        cluster="sugar",
        env="dev",
        retries=1,
        delay=0,
        require_phase="bootstrap",
        runner=runner_server,
        sleep=lambda _: None,
    )

    assert missing_bootstrap is None
