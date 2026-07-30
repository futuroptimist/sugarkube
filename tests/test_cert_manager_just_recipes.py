import json
import os
import pathlib
import subprocess
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]


def run_recipe(tmp_path, *arguments):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    stub = bin_dir / "python3"
    stub.write_text(
        f"#!{sys.executable}\n"
        "import json, os, sys\n"
        "print(json.dumps({'environment': os.environ.get('SUGARKUBE_ENV'), "
        "'argv': sys.argv[2:]}))\n"
    )
    stub.chmod(0o755)
    environment = {**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}"}
    return subprocess.run(
        ["just", "--justfile", str(ROOT / "justfile"), *arguments],
        cwd=ROOT,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )


@pytest.mark.parametrize(
    "arguments,expected",
    [
        (["cert-manager-cloudflare-token-secret", "env=staging"], ["install-token"]),
        (
            [
                "cert-manager-certificate-status",
                "namespace=danielsmith",
                "certificate=danielsmith-staging-tls",
                "env=staging",
            ],
            [
                "status",
                "--namespace",
                "danielsmith",
                "--certificate",
                "danielsmith-staging-tls",
            ],
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
def test_documented_named_arguments_are_normalized(tmp_path, arguments, expected):
    result = run_recipe(tmp_path, *arguments)
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload == {"environment": "staging", "argv": expected}


def test_positional_arguments_remain_compatible(tmp_path):
    result = run_recipe(
        tmp_path, "cert-manager-certificate-status", "danielsmith", "site-tls", "staging"
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {
        "environment": "staging",
        "argv": ["status", "--namespace", "danielsmith", "--certificate", "site-tls"],
    }


@pytest.mark.parametrize(
    "arguments",
    [
        ["cert-manager-certificate-status", "namespace=ns", "certificate=cert"],
        ["cert-manager-certificate-status", "namespace=ns", "certificate=cert", "env="],
        ["cert-manager-certificate-status", "host=wrong", "certificate=cert", "env=staging"],
    ],
)
def test_empty_or_mismatched_arguments_fail_before_python(tmp_path, arguments):
    result = run_recipe(tmp_path, *arguments)
    assert result.returncode != 0
    assert "ERROR:" in result.stderr
    assert result.stdout == ""
