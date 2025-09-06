import importlib.util
import io
from pathlib import Path

import pytest


@pytest.fixture
def scan_secrets():
    spec = importlib.util.spec_from_file_location(
        "scan_secrets",
        Path(__file__).resolve().parents[1] / "scripts" / "scan-secrets.py",
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# Ensure regex scan catches common secret patterns.
@pytest.mark.parametrize(
    "line",
    ["+api" "_key=123", "+token" ": abc", "+aws_secret" "_key=xyz"],
)
def test_regex_scan_detects_patterns(scan_secrets, line):
    diff = ["+++ b/file.txt", line]
    assert scan_secrets.regex_scan(diff)


def test_regex_scan_ignores_self(scan_secrets):
    diff = ["+++ b/scripts/scan-secrets.py", "+api" "_key=123"]
    assert not scan_secrets.regex_scan(diff)


def test_regex_scan_ignores_removed_lines(scan_secrets):
    diff = ["+++ b/file.txt", "-pass" "word=abc"]
    assert not scan_secrets.regex_scan(diff)


def test_main_exit_codes(monkeypatch, scan_secrets):
    monkeypatch.setattr(scan_secrets, "run_ripsecrets", lambda diff_text: None)
    monkeypatch.setattr(
        scan_secrets.sys,
        "stdin",
        io.StringIO("+++ b/file\n+safe=1\n"),
    )
    assert scan_secrets.main() == 0
    monkeypatch.setattr(
        scan_secrets.sys,
        "stdin",
        io.StringIO("+++ b/file\n+pass" "word=abc\n"),
    )
    assert scan_secrets.main() == 1


def test_main_ripsecrets_detects_secret(monkeypatch, scan_secrets):
    monkeypatch.setattr(scan_secrets, "run_ripsecrets", lambda diff_text: True)
    monkeypatch.setattr(
        scan_secrets.sys,
        "stdin",
        io.StringIO("+++ b/file\n+safe=1\n"),
    )
    assert scan_secrets.main() == 1


def test_main_ripsecrets_clean(monkeypatch, scan_secrets):
    monkeypatch.setattr(
        scan_secrets,
        "run_ripsecrets",
        lambda diff_text: False,
    )
    monkeypatch.setattr(
        scan_secrets.sys,
        "stdin",
        io.StringIO("+++ b/file\n+safe=1\n"),
    )
    assert scan_secrets.main() == 0


def test_run_ripsecrets_returns_none_when_missing(monkeypatch, scan_secrets):
    monkeypatch.setattr(scan_secrets.shutil, "which", lambda _: None)
    assert scan_secrets.run_ripsecrets("diff") is None


def test_run_ripsecrets_detects_secret(monkeypatch, scan_secrets):
    monkeypatch.setattr(
        scan_secrets.shutil,
        "which",
        lambda _: "/bin/ripsecrets",
    )

    class Result:
        returncode = 1
        stdout = "found"
        stderr = ""

    monkeypatch.setattr(
        scan_secrets.subprocess,
        "run",
        lambda *a, **k: Result,
    )
    assert scan_secrets.run_ripsecrets("diff") is True


def test_run_ripsecrets_logs_to_stderr(monkeypatch, scan_secrets, capsys):
    monkeypatch.setattr(
        scan_secrets.shutil,
        "which",
        lambda _: "/bin/ripsecrets",
    )

    class Result:
        returncode = 1
        stdout = ""
        stderr = "leak"

    monkeypatch.setattr(
        scan_secrets.subprocess,
        "run",
        lambda *a, **k: Result,
    )
    assert scan_secrets.run_ripsecrets("diff") is True
    assert "leak" in capsys.readouterr().err


def test_run_ripsecrets_clean(monkeypatch, scan_secrets):
    monkeypatch.setattr(
        scan_secrets.shutil,
        "which",
        lambda _: "/bin/ripsecrets",
    )

    class Result:
        returncode = 0
        stdout = ""
        stderr = ""

    monkeypatch.setattr(
        scan_secrets.subprocess,
        "run",
        lambda *a, **k: Result,
    )
    assert scan_secrets.run_ripsecrets("diff") is False


def test_main_skips_when_no_diff(monkeypatch, scan_secrets, capsys):
    monkeypatch.setattr(scan_secrets.sys, "stdin", io.StringIO(""))
    assert scan_secrets.main() == 0
    assert "No diff provided" in capsys.readouterr().err
