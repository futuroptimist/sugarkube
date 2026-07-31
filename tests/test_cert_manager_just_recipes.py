import json
import os
import pathlib
import shutil
import subprocess
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]

pytestmark = pytest.mark.skipif(
    shutil.which("just") is None, reason="just is required for this test"
)


def run_recipe(tmp_path, *arguments):
    capture = tmp_path / "capture.json"
    stub = tmp_path / "python3"
    stub.write_text(
        f"#!{sys.executable}\n"
        "import json, os, sys\n"
        "json.dump({'env': os.environ.get('SUGARKUBE_ENV'), 'argv': sys.argv[2:]}, "
        "open(os.environ['CAPTURE'], 'w'))\n"
    )
    stub.chmod(0o755)
    environment = {
        **os.environ,
        "PATH": os.pathsep.join((str(tmp_path), os.environ.get("PATH", os.defpath))),
        "CAPTURE": str(capture),
    }
    result = subprocess.run(
        ["just", "--justfile", str(ROOT / "justfile"), *arguments],
        cwd=ROOT,
        env=environment,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    payload = json.loads(capture.read_text()) if capture.exists() else None
    return result, payload


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
def test_documented_named_invocations_are_normalized(tmp_path, arguments, expected):
    result, payload = run_recipe(tmp_path, *arguments)
    assert result.returncode == 0, result.stderr
    assert payload == {"env": "staging", "argv": expected}


def test_positional_invocation_remains_supported(tmp_path):
    result, payload = run_recipe(
        tmp_path,
        "cert-manager-certificate-status",
        "danielsmith",
        "danielsmith-staging-tls",
        "staging",
    )
    assert result.returncode == 0, result.stderr
    assert payload == {
        "env": "staging",
        "argv": [
            "status",
            "--namespace",
            "danielsmith",
            "--certificate",
            "danielsmith-staging-tls",
        ],
    }


@pytest.mark.parametrize(
    "arguments",
    [
        ("cert-manager-certificate-status", "namespace=danielsmith", "certificate=site-tls"),
        (
            "cert-manager-certificate-status",
            "namespace=danielsmith",
            "certificate=site-tls",
            "env=",
        ),
        (
            "cert-manager-certificate-status",
            "wrong=danielsmith",
            "certificate=site-tls",
            "env=staging",
        ),
    ],
)
def test_missing_empty_or_mismatched_arguments_fail_before_python(tmp_path, arguments):
    result, payload = run_recipe(tmp_path, *arguments)
    assert result.returncode != 0
    assert payload is None
    assert "error" in result.stderr.lower()


@pytest.mark.parametrize("environment", ["prod", "unknown"])
def test_non_staging_status_fails_before_kubectl(tmp_path, environment):
    marker = tmp_path / "kubectl-invoked"
    kubectl = tmp_path / "kubectl"
    kubectl.write_text("#!/bin/sh\n" f"touch {str(marker)!r}\n" "exit 99\n")
    kubectl.chmod(0o755)
    command_environment = {
        **os.environ,
        "PATH": os.pathsep.join((str(tmp_path), os.environ.get("PATH", os.defpath))),
    }

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
        env=command_environment,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    assert result.returncode != 0
    assert "refusing operation: export SUGARKUBE_ENV=staging" in result.stderr
    assert "Traceback" not in result.stderr
    assert not marker.exists()
