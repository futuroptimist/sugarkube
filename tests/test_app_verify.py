"""Unit tests for scripts.app_verify."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from scripts import app_verify


def _set_main_env(monkeypatch: pytest.MonkeyPatch, *, paths: str = "/,/livez") -> None:
    monkeypatch.setenv("SUGARKUBE_APP", "demo")
    monkeypatch.setenv("SUGARKUBE_ENV", "staging")
    monkeypatch.setenv("SUGARKUBE_VERIFY_PATHS", paths)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, True),
        ("", True),
        ("0", False),
        ("false", False),
        ("no", False),
        ("off", False),
        ("1", True),
        ("true", True),
    ],
)
def test_env_flag_parses_common_boolean_values(
    monkeypatch: pytest.MonkeyPatch, value: str | None, expected: bool
) -> None:
    if value is None:
        monkeypatch.delenv("SUGARKUBE_TEST_FLAG", raising=False)
    else:
        monkeypatch.setenv("SUGARKUBE_TEST_FLAG", value)

    assert app_verify.env_flag("SUGARKUBE_TEST_FLAG", default=True) is expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("", "/"),
        ("livez", "/livez"),
        (" /healthz \n", "/healthz"),
        (" nested / path ", "/nested/path"),
    ],
)
def test_normalize_path_removes_whitespace_and_adds_leading_slash(raw: str, expected: str) -> None:
    assert app_verify.normalize_path(raw) == expected


@pytest.mark.parametrize(
    ("raw", "host_key", "expected"),
    [
        ('{"ingress":{"host":"example.test"}}', "ingress.host", "example.test"),
        ('{"status":{"url":"https://example.test"}}', "status.url", "https://example.test"),
        ('{"ingress":{}}', "ingress.host", ""),
        ('{"ingress":"not-a-dict"}', "ingress.host", ""),
        ("not json", "ingress.host", ""),
    ],
)
def test_host_from_values_follows_configured_key(raw: str, host_key: str, expected: str) -> None:
    assert app_verify.host_from_values(raw, host_key) == expected


@pytest.mark.parametrize(
    ("raw", "default", "expected"),
    [
        (None, 7, 7),
        ("12", 7, 12),
        ("-5", 7, 0),
        ("not-an-int", 7, 7),
    ],
)
def test_int_env_parses_nonnegative_integers(
    monkeypatch: pytest.MonkeyPatch, raw: str | None, default: int, expected: int
) -> None:
    if raw is None:
        monkeypatch.delenv("SUGARKUBE_TEST_INT", raising=False)
    else:
        monkeypatch.setenv("SUGARKUBE_TEST_INT", raw)

    assert app_verify.int_env("SUGARKUBE_TEST_INT", default) == expected


@pytest.mark.parametrize(
    ("body", "byte_limit", "line_limit", "expected_lines", "expected_truncated"),
    [
        (b"", 10, 2, [], False),
        (b"one\ntwo\nthree", 20, 2, ["one", "two"], True),
        (b"abcdef", 3, 5, ["abc"], True),
        ("caf\xe9".encode(), 10, 5, ["café"], False),
    ],
)
def test_preview_text_applies_byte_and_line_limits(
    body: bytes,
    byte_limit: int,
    line_limit: int,
    expected_lines: list[str],
    expected_truncated: bool,
) -> None:
    assert app_verify.preview_text(body, byte_limit, line_limit) == (
        expected_lines,
        expected_truncated,
    )


def test_discover_host_prefers_helm_values(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SUGARKUBE_RELEASE", "demo")
    monkeypatch.setenv("SUGARKUBE_NAMESPACE", "demo-ns")
    monkeypatch.setattr(app_verify, "shutil_which", lambda name: f"/bin/{name}")

    calls: list[list[str]] = []

    def fake_run_capture(args: list[str]) -> subprocess.CompletedProcess[str]:
        calls.append(args)
        return subprocess.CompletedProcess(args, 0, '{"ingress":{"host":"helm.example"}}', "")

    monkeypatch.setattr(app_verify, "run_capture", fake_run_capture)

    assert app_verify.discover_host("sugar-staging") == ("helm.example", [])
    assert calls == [
        [
            "helm",
            "--kube-context",
            "sugar-staging",
            "get",
            "values",
            "demo",
            "--namespace",
            "demo-ns",
            "--all",
            "--output",
            "json",
        ]
    ]


def test_discover_host_falls_back_to_kubectl_and_reports_helm_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SUGARKUBE_RELEASE", "demo")
    monkeypatch.setenv("SUGARKUBE_NAMESPACE", "demo-ns")
    monkeypatch.setattr(app_verify, "shutil_which", lambda name: f"/bin/{name}")

    def fake_run_capture(args: list[str]) -> subprocess.CompletedProcess[str]:
        if args[0] == "helm":
            return subprocess.CompletedProcess(args, 1, "", "helm boom\nwith newline")
        return subprocess.CompletedProcess(args, 0, "kubectl.example\n", "")

    monkeypatch.setattr(app_verify, "run_capture", fake_run_capture)

    host, errors = app_verify.discover_host("sugar-staging")

    assert host == "kubectl.example"
    assert errors == ["helm get values failed for context sugar-staging: helm boom with newline"]


def test_discover_host_returns_errors_when_tools_fail(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SUGARKUBE_RELEASE", "demo")
    monkeypatch.setenv("SUGARKUBE_NAMESPACE", "demo-ns")
    monkeypatch.setattr(app_verify, "shutil_which", lambda name: f"/bin/{name}")

    def fake_run_capture(args: list[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(args, 1, "", f"{args[0]} failed\n")

    monkeypatch.setattr(app_verify, "run_capture", fake_run_capture)

    host, errors = app_verify.discover_host("sugar-staging")

    assert host == ""
    assert errors == [
        "helm get values failed for context sugar-staging: helm failed",
        "kubectl ingress lookup failed for context sugar-staging: kubectl failed",
    ]


def test_discover_host_skips_missing_tools(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SUGARKUBE_RELEASE", "demo")
    monkeypatch.setenv("SUGARKUBE_NAMESPACE", "demo-ns")
    monkeypatch.setattr(app_verify, "shutil_which", lambda name: None)

    assert app_verify.discover_host("sugar-staging") == ("", [])


def test_run_curl_passes_timeouts_and_reads_body(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SUGARKUBE_APP_VERIFY_CURL_CONNECT_TIMEOUT", "2")
    monkeypatch.setenv("SUGARKUBE_APP_VERIFY_CURL_MAX_TIME", "5")
    calls: list[list[str]] = []

    def fake_run(
        args: list[str], *, capture_output: bool, text: bool, check: bool
    ) -> subprocess.CompletedProcess[str]:
        calls.append(args)
        body_path = Path(args[args.index("-o") + 1])
        body_path.write_bytes(b'{"status":"ok"}')
        return subprocess.CompletedProcess(args, 0, "200", "")

    monkeypatch.setattr(app_verify.subprocess, "run", fake_run)

    rc, status, body, stderr = app_verify.run_curl("https://example.test/livez")

    assert (rc, status, body, stderr) == (0, "200", b'{"status":"ok"}', "")
    assert calls == [
        [
            "curl",
            "-sS",
            "--connect-timeout",
            "2",
            "--max-time",
            "5",
            "-o",
            calls[0][7],
            "-w",
            "%{http_code}",
            "https://example.test/livez",
        ]
    ]
    assert not Path(calls[0][7]).exists()


def test_run_curl_defaults_blank_status_to_000(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(
        args: list[str], *, capture_output: bool, text: bool, check: bool
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(args, 7, "", "connect failed\n")

    monkeypatch.setattr(app_verify.subprocess, "run", fake_run)

    assert app_verify.run_curl("https://example.test/") == (7, "000", b"", "connect failed")


def test_print_placeholder_failure_lists_errors_and_commands(
    capsys: pytest.CaptureFixture[str],
) -> None:
    app_verify.print_placeholder_failure(
        "demo", "staging", "sugar-staging", ["/", "/livez"], ["helm failed"]
    )

    captured = capsys.readouterr()
    assert captured.out.splitlines() == [
        "  curl -fsS https://<host>/",
        "  curl -fsS https://<host>/livez",
    ]
    assert "Could not derive a host for demo using context sugar-staging." in captured.err
    assert "helm failed" in captured.err
    assert "Suggested next steps: just app-status app=demo env=staging" in captured.err


def test_main_print_only_uses_discovered_host_without_curl(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _set_main_env(monkeypatch, paths="/, livez")
    monkeypatch.setattr(app_verify, "discover_host", lambda kube_context: ("example.test", []))
    monkeypatch.setattr(app_verify, "run_curl", lambda url: pytest.fail("curl should not run"))

    assert app_verify.main(["--print-only"]) == 0

    captured = capsys.readouterr()
    assert captured.out.splitlines() == [
        "curl -fsS https://example.test/",
        "curl -fsS https://example.test/livez",
    ]
    assert captured.err == ""


def test_main_print_only_returns_zero_with_placeholder_host(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _set_main_env(monkeypatch)
    monkeypatch.setattr(app_verify, "discover_host", lambda kube_context: ("", ["lookup failed"]))

    assert app_verify.main(["--print-only"]) == 0

    captured = capsys.readouterr()
    assert "curl -fsS https://<host>/livez" in captured.out
    assert "lookup failed" in captured.err


def test_main_returns_one_when_host_discovery_fails_outside_print_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_main_env(monkeypatch)
    monkeypatch.setattr(app_verify, "discover_host", lambda kube_context: ("", []))

    assert app_verify.main([]) == 1


def test_main_runs_all_checks_and_reports_failures(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _set_main_env(monkeypatch, paths="/,/livez,/large")
    monkeypatch.setenv("SUGARKUBE_APP_VERIFY_BODY_PREVIEW_BYTES", "4")
    monkeypatch.setenv("SUGARKUBE_APP_VERIFY_BODY_PREVIEW_LINES", "1")
    monkeypatch.setattr(
        app_verify, "discover_host", lambda kube_context: ("https://example.test", [])
    )
    calls: list[str] = []

    def fake_run_curl(url: str) -> tuple[int, str, bytes, str]:
        calls.append(url)
        if url.endswith("/livez"):
            return 0, "503", b"down", ""
        if url.endswith("/large"):
            return 0, "200", b"line1\nline2", ""
        return 0, "200", b"ok", ""

    monkeypatch.setattr(app_verify, "run_curl", fake_run_curl)

    assert app_verify.main([]) == 1

    captured = capsys.readouterr()
    assert calls == [
        "https://example.test/",
        "https://example.test/livez",
        "https://example.test/large",
    ]
    assert "Status: OK (HTTP 200)" in captured.out
    assert "Status: FAILED (HTTP 503)" in captured.out
    assert "curl exit status: 22" in captured.out
    assert "Body preview:" in captured.out
    assert "Verification failed: 1/3 checks failed." in captured.err
    assert "/livez (https://example.test/livez)" in captured.err


def test_main_reports_curl_stderr_and_can_hide_bodies(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _set_main_env(monkeypatch, paths="/")
    monkeypatch.setenv("SUGARKUBE_APP_VERIFY_SHOW_BODY", "0")
    monkeypatch.setattr(app_verify, "discover_host", lambda kube_context: ("example.test", []))
    monkeypatch.setattr(
        app_verify,
        "run_curl",
        lambda url: (7, "000", b"secret body", "first stderr line\nsecond stderr line"),
    )

    assert app_verify.main([]) == 1

    captured = capsys.readouterr()
    assert "curl stderr:" in captured.out
    assert "first stderr line" in captured.out
    assert "second stderr line" in captured.out
    assert "Body:" not in captured.out


def test_main_success_reports_empty_body(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _set_main_env(monkeypatch, paths="/")
    monkeypatch.setattr(app_verify, "discover_host", lambda kube_context: ("example.test", []))
    monkeypatch.setattr(app_verify, "run_curl", lambda url: (0, "200", b"", ""))

    assert app_verify.main([]) == 0

    captured = capsys.readouterr()
    assert "Body: <empty>" in captured.out
    assert "Verification passed: 1/1 checks succeeded." in captured.out


@pytest.mark.parametrize(
    ("host", "expected"),
    [
        ("", ""),
        (" example.test/ ", "https://example.test"),
        ("http://example.test", "https://example.test"),
        ("https://example.test", "https://example.test"),
    ],
)
def test_base_url_from_host_preserves_https_contract(host: str, expected: str) -> None:
    assert app_verify.base_url_from_host(host) == expected


def test_run_capture_uses_text_capture_without_check(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(
        args: list[str], *, capture_output: bool, text: bool, check: bool
    ) -> subprocess.CompletedProcess[str]:
        assert capture_output is True
        assert text is True
        assert check is False
        return subprocess.CompletedProcess(args, 0, "out", "err")

    monkeypatch.setattr(app_verify.subprocess, "run", fake_run)

    assert app_verify.run_capture(["demo"]).stdout == "out"


def test_shutil_which_returns_matching_executable_path() -> None:
    assert app_verify.shutil_which("python3")
