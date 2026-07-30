import os
import pathlib
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]


@pytest.fixture
def python_stub(tmp_path):
    executable = tmp_path / "python3"
    executable.write_text(
        "#!/bin/sh\n"
        "printf 'SUGARKUBE_ENV=%s\\n' \"${SUGARKUBE_ENV-}\"\n"
        "printf '%s\\n' \"$@\"\n"
    )
    executable.chmod(0o755)
    return tmp_path


def run_just(arguments, *, path=None):
    environment = os.environ.copy()
    if path is not None:
        environment["PATH"] = f"{path}:{environment['PATH']}"
    return subprocess.run(
        ["just", "--justfile", str(ROOT / "justfile"), *arguments],
        cwd=ROOT,
        env=environment,
        input=b"",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


@pytest.mark.parametrize(
    "arguments,expected",
    [
        (
            ["cert-manager-cloudflare-token-secret", "env=staging"],
            ["install-token"],
        ),
        (
            [
                "cert-manager-certificate-status",
                "namespace=danielsmith",
                "certificate=danielsmith-staging-tls",
                "env=staging",
            ],
            ["status", "--namespace", "danielsmith", "--certificate", "danielsmith-staging-tls"],
        ),
        (
            [
                "cert-manager-certificate-verify-authorization",
                "namespace=danielsmith",
                "certificate=danielsmith-staging-tls",
                "env=staging",
            ],
            [
                "verify-authorization",
                "--namespace",
                "danielsmith",
                "--certificate",
                "danielsmith-staging-tls",
            ],
        ),
        (
            [
                "cert-manager-certificate-recover",
                "namespace=danielsmith",
                "certificate=danielsmith-staging-tls",
                "host=staging.danielsmith.io",
                "env=staging",
                "timeout=600",
            ],
            [
                "recover",
                "--namespace",
                "danielsmith",
                "--certificate",
                "danielsmith-staging-tls",
                "--host",
                "staging.danielsmith.io",
                "--timeout",
                "600",
            ],
        ),
    ],
)
def test_documented_named_arguments_are_normalized(python_stub, arguments, expected):
    result = run_just(arguments, path=python_stub)

    assert result.returncode == 0, result.stderr.decode()
    assert result.stdout.decode().splitlines() == [
        "SUGARKUBE_ENV=staging",
        str(ROOT / "scripts" / "staging_cert_manager.py"),
        *expected,
    ]


def test_positional_arguments_remain_supported(python_stub):
    result = run_just(
        ["cert-manager-certificate-status", "danielsmith", "site-tls", "staging"],
        path=python_stub,
    )

    assert result.returncode == 0
    assert result.stdout.decode().splitlines()[-5:] == [
        "status",
        "--namespace",
        "danielsmith",
        "--certificate",
        "site-tls",
    ]


@pytest.mark.parametrize("environment", ["prod", "development"])
def test_non_staging_environment_fails_closed(environment):
    result = run_just(
        [
            "cert-manager-certificate-status",
            "namespace=danielsmith",
            "certificate=site-tls",
            f"env={environment}",
        ]
    )

    assert result.returncode != 0
    assert b"refusing operation: export SUGARKUBE_ENV=staging" in result.stderr
    assert b"Traceback" not in result.stderr


def test_omitted_environment_is_rejected_by_just():
    result = run_just(["cert-manager-certificate-status", "danielsmith", "site-tls"])

    assert result.returncode != 0
    assert b"takes 3" in result.stderr


@pytest.mark.parametrize(
    "arguments,message",
    [
        (
            [
                "cert-manager-certificate-status",
                "namespace=",
                "certificate=site-tls",
                "env=staging",
            ],
            b"namespace must not be empty",
        ),
        (
            [
                "cert-manager-certificate-status",
                "certificate=site-tls",
                "namespace=danielsmith",
                "env=staging",
            ],
            b"unexpected value for namespace",
        ),
    ],
)
def test_empty_or_mismatched_named_arguments_fail_cleanly(python_stub, arguments, message):
    result = run_just(arguments, path=python_stub)

    assert result.returncode != 0
    assert message in result.stderr
    assert b"Traceback" not in result.stderr
    assert b"SUGARKUBE_ENV=" not in result.stdout
