"""Guard isolated CI suites, complete coverage transfer, and the required check."""

import os
import subprocess
from itertools import product
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"


def workflow():
    # BaseLoader retains GitHub's `on` key instead of YAML 1.1's boolean True.
    return yaml.load(WORKFLOW.read_text(), Loader=yaml.BaseLoader)


def step(job, name):
    return next(item for item in workflow()["jobs"][job]["steps"] if item.get("name") == name)


def test_ci_keeps_triggers_and_isolates_required_suites():
    config = workflow()
    assert config["name"] == "ci"
    assert config["on"] == {"pull_request": "", "push": {"branches": ["main"]}}
    assert "permissions" not in config  # Do not expand the existing token permissions.
    assert "env" not in config
    assert set(config["jobs"]) == {"bash", "python", "test"}
    for name, job in config["jobs"].items():
        assert job["runs-on"] == "ubuntu-latest"
        assert "continue-on-error" not in job
        assert "permissions" not in job
        assert "env" not in job
        assert "timeout-minutes" not in job
        assert "strategy" not in job
        if name != "test":
            assert "needs" not in job
            assert "if" not in job
        assert job["steps"][0] == {"uses": "actions/checkout@v4"}


def test_ci_retains_shared_dependency_and_service_setup():
    names = [
        "Set up Python",
        "Install Python test deps",
        "Install promtool",
        "Install bats and mDNS dependencies",
        "Verify helm-oci-install just recipe",
        "Ensure Avahi services are running",
    ]
    for name in names:
        bash_step = step("bash", name)
        assert bash_step == step("python", name)
        assert "continue-on-error" not in bash_step
        assert "if" not in bash_step
    for lane in ("bash", "python"):
        assert [item.get("name") for item in workflow()["jobs"][lane]["steps"]][1:7] == names
    assert step("python", "Set up Python")["with"] == {"python-version": "3.x"}
    assert step("python", "Install Python test deps")["run"].splitlines() == [
        "python -m pip install --upgrade pip",
        "pip install pytest pytest-cov pyyaml",
    ]
    packages = step("python", "Install bats and mDNS dependencies")["run"]
    assert packages.replace("\\\n", " ").split() == [
        "sudo",
        "apt-get",
        "update",
        "sudo",
        "apt-get",
        "install",
        "-y",
        "avahi-daemon",
        "avahi-utils",
        "bats",
        "build-essential",
        "cmake",
        "dbus",
        "libcurl4-openssl-dev",
        "libdw-dev",
        "libglib2.0-bin",
        "libnss-mdns",
        "just",
        "ncat",
        "zlib1g-dev",
        "binutils-dev",
        "libiberty-dev",
    ]
    assert step("python", "Ensure Avahi services are running")["run"].splitlines() == [
        "sudo systemctl start dbus",
        "sudo systemctl start avahi-daemon",
        "sudo systemctl status avahi-daemon --no-pager",
    ]
    assert step("python", "Verify helm-oci-install just recipe")["run"].strip() == (
        "./scripts/test-helm-oci-install.sh"
    )


def test_ci_keeps_full_test_inventories_and_coverage_arguments():
    bash = step("bash", "Run Bash tests under kcov")
    assert bash["env"] == {
        "KCOV_OUT": "${{ github.workspace }}/coverage/kcov",
        "BATS_LIB_PATH": "${{ github.workspace }}/tests/bats",
        "BATS_CWD": "${{ github.workspace }}",
    }
    assert "if" not in bash and "continue-on-error" not in bash
    command = "\n".join(
        line for line in bash["run"].splitlines() if not line.lstrip().startswith("#")
    )
    assert command.replace("\\\n", " ").split() == [
        "mkdir",
        "-p",
        '"$KCOV_OUT"',
        "kcov",
        '--include-path="${GITHUB_WORKSPACE}/scripts"',
        '--exclude-pattern="/usr,/opt,/lib,/bin,/sbin,${GITHUB_WORKSPACE}/tests"',
        "--bash-dont-parse-binary-dir",
        '"$KCOV_OUT"',
        "bats",
        "--recursive",
        "tests/bats",
    ]
    python = step("python", "Run Python tests with coverage")
    assert python == {
        "name": "Run Python tests with coverage",
        "id": "pytest",
        "continue-on-error": "true",
        "run": "pytest -vv --durations=25 --cov=scripts --cov=tests "
        "--cov-report=xml:coverage/python-coverage.xml\n",
    }
    fail = step("python", "Fail if Python tests failed")
    assert fail["if"] == "steps.pytest.outcome == 'failure'"
    assert "continue-on-error" not in fail
    assert subprocess.run(["bash", "-e", "-c", fail["run"]], capture_output=True).returncode == 1
    bash_names = [item.get("name") for item in workflow()["jobs"]["bash"]["steps"]]
    assert bash_names.index("Build and install kcov") < bash_names.index(bash["name"])
    assert not any(
        item.get("name") == "Build and install kcov"
        for item in workflow()["jobs"]["python"]["steps"]
    )


@pytest.mark.parametrize(
    "lane,label,upload_path,download_path",
    [
        ("bash", "Bash", "coverage/kcov", "coverage/kcov"),
        ("python", "Python", "coverage/python-coverage.xml", "coverage"),
    ],
)
def test_ci_preserves_disjoint_coverage_artifacts_even_after_failure(
    lane,
    label,
    upload_path,
    download_path,
):
    upload = step(lane, f"Preserve {label} coverage")
    download = step("test", f"Restore {label} coverage")
    assert upload["uses"] == "actions/upload-artifact@v4"
    assert download["uses"] == "actions/download-artifact@v4"
    assert upload["if"] == download["if"] == "always()"
    assert "continue-on-error" not in upload and "continue-on-error" not in download
    assert upload["with"] == {
        "name": f"ci-{lane}-coverage",
        "path": upload_path,
        "if-no-files-found": "error",
    }
    # Directory contents are rooted inside their uploaded directory; individual files
    # are rooted at the filename. Restore each to its original Codecov search path.
    assert download["with"] == {"name": f"ci-{lane}-coverage", "path": download_path}


def test_ci_keeps_combined_codecov_reporting_and_failure_semantics():
    upload = step("test", "Upload to Codecov")
    assert upload == {
        "name": "Upload to Codecov",
        "uses": "codecov/codecov-action@v4",
        "if": "always()",
        "with": {
            "directory": "coverage",
            "files": "coverage/python-coverage.xml,coverage/kcov/*/cobertura.xml",
            "fail_ci_if_error": "true",
            "verbose": "true",
            "flags": "python,shell",
        },
    }
    names = [item.get("name") for item in workflow()["jobs"]["test"]["steps"]]
    assert names.index("Restore Bash coverage") < names.index(upload["name"])
    assert names.index("Restore Python coverage") < names.index(upload["name"])


@pytest.mark.parametrize(
    "bash_result,python_result",
    list(product(["success", "failure", "cancelled", "skipped", ""], repeat=2)),
)
def test_ci_required_check_fails_closed_for_every_lane_result(bash_result, python_result):
    aggregate = workflow()["jobs"]["test"]
    assert aggregate["needs"] == ["bash", "python"]
    assert aggregate["if"] == "always()"
    assert "name" not in aggregate  # Preserve the original check identity: ci / test.
    gate = step("test", "Require both test suites to pass")
    assert gate["if"] == "always()"
    assert "continue-on-error" not in gate
    assert gate["env"] == {
        "BASH_RESULT": "${{ needs.bash.result }}",
        "PYTHON_RESULT": "${{ needs.python.result }}",
    }
    result = subprocess.run(
        ["bash", "-e", "-c", gate["run"]],
        env={**os.environ, "BASH_RESULT": bash_result, "PYTHON_RESULT": python_result},
        capture_output=True,
        text=True,
    )
    assert result.returncode == (0 if bash_result == python_result == "success" else 1)
