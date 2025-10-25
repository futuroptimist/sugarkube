import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
from k3s_mdns_parser import parse_mdns_records  # noqa: E402
from mdns_helpers import (  # noqa: E402
    _same_host,
    ensure_self_ad_is_visible,
    normalize_hostname,
)


def _make_runner(stdout_by_service):
    def _runner(cmd, capture_output=True, text=True, check=False, **kwargs):
        service_type = cmd[-1]
        stdout = stdout_by_service.get(service_type, "")
        return subprocess.CompletedProcess(cmd, 0, stdout=stdout, stderr="")

    return _runner


def test_normalize_hostname_strips_trailing_dot_and_is_case_insensitive():
    assert normalize_hostname("Host0.LOCAL.") == "host0.local"
    assert normalize_hostname("HOST0") == "host0"


def test_same_host_normalises_case_and_trailing_dots():
    assert _same_host("Host.LOCAL.", "host.local")
    assert _same_host("host.local", "HOST")
    assert not _same_host("host-a", "host-b")


def test_same_host_accepts_repeated_local_suffix():
    assert _same_host("Host.LOCAL.local", "host.local")
    assert _same_host("host.local.local", "HOST")


def test_same_host_strips_control_characters():
    assert _same_host("host0.local\x00", "host0.local")
    assert _same_host("\x07host1.local", "host1")


def test_host_equality_uses_eq_not_identity():
    left = "".join(["host", "0", ".local"])
    right = "".join(["host", "0", ".local"])
    assert left is not right
    assert _same_host(left, right)


def test_txt_parsing_handles_multiple_trailing_args():
    line = (
        "=;eth0;IPv4;k3s-sugar-dev@host0 (bootstrap);_k3s-sugar-dev._tcp;"
        "local;host0.local;192.0.2.10;6443;"
        "txt=phase=bootstrap;txt=role=candidate;"
        "txt=leader=none;txt=host=host0.local"
    )
    records = parse_mdns_records([line], "sugar", "dev")
    assert len(records) == 1
    record = records[0]
    assert record.txt["phase"] == "bootstrap"
    assert record.txt["role"] == "candidate"
    assert record.txt["leader"] == "none"
    assert record.txt["host"] == "host0.local"


def test_txt_parsing_handles_single_concatenated_string():
    line = (
        "=;eth0;IPv4;k3s-sugar-dev@host0 (bootstrap);_k3s-sugar-dev._tcp;"
        "local;host0.local;192.0.2.10;6443;"
        "txt=phase=bootstrap,role=candidate,leader=none,host=host0.local"
    )
    records = parse_mdns_records([line], "sugar", "dev")
    assert len(records) == 1
    record = records[0]
    assert record.txt["phase"] == "bootstrap"
    assert record.txt["role"] == "candidate"
    assert record.txt["leader"] == "none"
    assert record.txt["host"] == "host0.local"


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


def test_ensure_self_ad_is_visible_accepts_hostname_address(capsys):
    record = (
        "=;eth0;IPv4;k3s-sugar-dev@host0 (server);_k3s-sugar-dev._tcp;"
        "local;host0.local;host0.local;6443;"
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
    warning = capsys.readouterr().err
    assert "advertisement reported non-IP" in warning


def test_ensure_self_ad_is_visible_uses_role_when_phase_missing():
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


def test_ensure_self_ad_is_visible_handles_uppercase_phase_and_leader_host_fallback():
    record = (
        "=;eth0;IPv4;k3s-sugar-dev@host0 (server);_k3s-sugar-dev._tcp;"
        "local;;192.0.2.10;6443;"
        "txt=k3s=1;txt=cluster=sugar;txt=env=dev;txt=role=SERVER ;"
        "txt=leader=HOST0.LOCAL.;txt=phase=Server \n"
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


def test_ensure_self_ad_is_visible_recovers_from_browse_timeout(capsys):
    record = (
        "=;eth0;IPv4;k3s-sugar-dev@host0 (server);_k3s-sugar-dev._tcp;"
        "local;host0.local;192.0.2.10;6443;"
        "txt=k3s=1;txt=cluster=sugar;txt=env=dev;txt=role=server;"
        "txt=leader=host0.local;txt=phase=server\n"
    )

    class TimeoutThenSuccess:
        def __init__(self):
            self.calls = 0

        def __call__(self, cmd, **kwargs):
            self.calls += 1
            if self.calls == 1:
                raise subprocess.TimeoutExpired(cmd, timeout=kwargs.get("timeout", 5))
            return subprocess.CompletedProcess(cmd, 0, stdout=record, stderr="")

    runner = TimeoutThenSuccess()

    observed = ensure_self_ad_is_visible(
        expected_host="host0.local",
        cluster="sugar",
        env="dev",
        retries=2,
        delay=0,
        require_phase="server",
        runner=runner,
        sleep=lambda _: None,
    )

    assert observed == "host0.local"
    warning = capsys.readouterr().err
    assert "avahi-browse timed out" in warning


def test_ensure_self_ad_is_visible_accepts_uppercase_cluster_and_env():
    record = (
        "=;eth0;IPv4;k3s-sugar-dev@host0 (server);_k3s-sugar-dev._tcp;"
        "local;host0.local;192.0.2.10;6443;"
        "txt=k3s=1;txt=cluster=SUGAR ;txt=ENV=DEV ;txt=role=server;"
        "txt=phase=server\n"
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


def test_ensure_self_ad_is_visible_falls_back_without_resolve():
    unresolved = "+;eth0;IPv4;k3s-sugar-dev@host0 (bootstrap);_k3s-sugar-dev._tcp;local\n"

    calls = []

    def runner(cmd, capture_output=True, text=True, check=False):
        assert capture_output and text and not check
        service = cmd[-1]
        flags = [arg for arg in cmd[1:] if arg.startswith("-")]
        primary_flag = flags[0] if flags else ""
        resolve = "r" in primary_flag
        calls.append((service, primary_flag))
        if service == "_k3s-sugar-dev._tcp" and not resolve:
            stdout = unresolved
        else:
            stdout = ""
        return subprocess.CompletedProcess(cmd, 0, stdout=stdout, stderr="")

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
    assert calls == [
        ("_k3s-sugar-dev._tcp", "-rptk"),
        ("_https._tcp", "-rptk"),
        ("_k3s-sugar-dev._tcp", "-ptk"),
    ]


def test_ensure_self_ad_is_visible_logs_phase_mismatch_details(capsys):
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
        require_phase="bootstrap",
        runner=runner,
        sleep=lambda _: None,
    )

    assert observed is None
    error_output = capsys.readouterr().err
    assert "skipped host host0.local" in error_output
    assert "require_phase=bootstrap" in error_output
    assert '"phase=server"' in error_output
    assert '"role=server"' in error_output


def test_ensure_self_ad_is_visible_logs_host_comparison_details(capsys):
    record = (
        "=;eth0;IPv4;k3s-sugar-dev@host1 (server);_k3s-sugar-dev._tcp;"
        "local;host1.local;192.0.2.20;6443;"
        "txt=k3s=1;txt=cluster=sugar;txt=env=dev;txt=role=server;"
        "txt=leader=host1.local;txt=phase=server\n"
    )

    runner = _make_runner({"_k3s-sugar-dev._tcp": record})

    observed = ensure_self_ad_is_visible(
        expected_host="host0.local",
        cluster="sugar",
        env="dev",
        retries=1,
        delay=0,
        require_phase="server",
        runner=runner,
        sleep=lambda _: None,
    )

    assert observed is None
    error_output = capsys.readouterr().err
    assert "host mismatch" in error_output
    assert "expected host0.local" in error_output
    assert "host=host1.local" in error_output
    assert "reason=host, leader" in error_output
