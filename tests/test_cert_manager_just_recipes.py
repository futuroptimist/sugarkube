import os
import pathlib
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]


@pytest.fixture
def stubbed_python(tmp_path):
    output = tmp_path / "invocation.txt"
    stub = tmp_path / "python3"
    stub.write_text(
        "#!/usr/bin/env bash\n"
        'printf \'SUGARKUBE_ENV=%s\\n\' "${SUGARKUBE_ENV-}" > "${CAPTURE}"\n'
        'printf \'%s\\n\' "$@" >> "${CAPTURE}"\n'
    )
    stub.chmod(0o755)
    environment = {**os.environ, "PATH": f"{tmp_path}:{os.environ['PATH']}", "CAPTURE": str(output)}
    return environment, output


def run_recipe(stubbed_python, *arguments):
    environment, output = stubbed_python
    result = subprocess.run(
        ["just", "--justfile", str(ROOT / "justfile"), *arguments],
        cwd=ROOT,
        env=environment,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    invocation = output.read_text().splitlines() if output.exists() else []
    return result, invocation


@pytest.mark.parametrize(
    "arguments,expected",
    [
        (("cert-manager-cloudflare-token-secret", "env=staging"), ["install-token"]),
        (
            (
                "cert-manager-certificate-status",
                "namespace=danielsmith",
                "certificate=danielsmith-staging-tls",
                "env=staging",
            ),
            ["status", "--namespace", "danielsmith", "--certificate", "danielsmith-staging-tls"],
        ),
        (
            (
                "cert-manager-certificate-verify-authorization",
                "namespace=danielsmith",
                "certificate=danielsmith-staging-tls",
                "env=staging",
            ),
            [
                "verify-authorization",
                "--namespace",
                "danielsmith",
                "--certificate",
                "danielsmith-staging-tls",
            ],
        ),
        (
            (
                "cert-manager-certificate-recover",
                "namespace=danielsmith",
                "certificate=danielsmith-staging-tls",
                "host=staging.danielsmith.io",
                "env=staging",
                "timeout=600",
            ),
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
def test_documented_named_arguments_are_normalized(stubbed_python, arguments, expected):
    result, invocation = run_recipe(stubbed_python, *arguments)

    assert result.returncode == 0, result.stderr
    assert invocation == [
        "SUGARKUBE_ENV=staging",
        str(ROOT / "scripts/staging_cert_manager.py"),
        *expected,
    ]


def test_status_retains_positional_compatibility(stubbed_python):
    result, invocation = run_recipe(
        stubbed_python,
        "cert-manager-certificate-status",
        "danielsmith",
        "danielsmith-staging-tls",
        "staging",
    )

    assert result.returncode == 0, result.stderr
    assert invocation[0] == "SUGARKUBE_ENV=staging"
    assert "namespace=" not in " ".join(invocation)


@pytest.mark.parametrize("environment", ["prod", "qa"])
def test_non_staging_environment_fails_closed_without_kubectl(tmp_path, environment):
    marker = tmp_path / "kubectl-called"
    kubectl = tmp_path / "kubectl"
    kubectl.write_text(f"#!/usr/bin/env bash\ntouch {marker}\n")
    kubectl.chmod(0o755)

    result = subprocess.run(
        [
            "just",
            "--justfile",
            str(ROOT / "justfile"),
            "cert-manager-certificate-status",
            "namespace=danielsmith",
            "certificate=danielsmith-staging-tls",
            f"env={environment}",
        ],
        cwd=ROOT,
        env={**os.environ, "PATH": f"{tmp_path}:{os.environ['PATH']}"},
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    assert result.returncode == 1
    assert "export SUGARKUBE_ENV=staging" in result.stderr
    assert not marker.exists()


@pytest.mark.parametrize(
    "arguments",
    [
        ("cert-manager-certificate-status", "namespace=ns", "certificate=cert"),
        ("cert-manager-certificate-status", "namespace=", "certificate=cert", "env=staging"),
        (
            "cert-manager-certificate-status",
            "host=wrong",
            "certificate=cert",
            "env=staging",
        ),
        ("cert-manager-cloudflare-token-secret", "env="),
    ],
)
def test_missing_empty_or_mismatched_arguments_fail_before_python(stubbed_python, arguments):
    result, invocation = run_recipe(stubbed_python, *arguments)

    assert result.returncode != 0
    assert invocation == []
    assert "ERROR" in result.stderr or "takes 3" in result.stderr
