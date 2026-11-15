"""Exercise the real rollout helper with stdout/stderr-separated kubectl responses."""

import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
PRIMARY = "app.kubernetes.io/instance=dspace"
FALLBACK = "release=dspace"
WARNING = "WARNING: Unable to read /etc/rancher/k3s/k3s.yaml: permission denied"
ERROR = "error: unable to connect to the server"


def run_discovery(tmp_path, selector, *, failed=False, empty_primary_warning=False):
    justfile = (REPO_ROOT / "justfile").read_text()
    start = justfile.index("    wait_for_rollouts() {")
    end = justfile.index("    ensure_upgrade_target_exists() {", start)
    helper = justfile[start:end]
    calls = tmp_path / "kubectl.calls"
    # A shell function keeps this test isolated from any installed kubectl or cluster.
    stub = r"""
kubectl() {
    printf '%s\n' "$*" >> "$calls"
    if [[ "$*" == *"get deploy,statefulset,daemonset"* ]]; then
        if [[ "$6" != "$selector" ]]; then
            if [[ "$empty_primary_warning" == True ]]; then
                printf '%s\n' "$warning" >&2
            fi
            return 0
        fi
        printf '%s\n' deployment.apps/dspace statefulset.apps/dspace-worker
        if [[ "$failed" == True ]]; then
            printf '%s\n' "$error" >&2
            return 7
        fi
        printf '%s\n' "$warning" >&2
        return 0
    fi
    [[ "$3 $4" == "rollout status" ]] || return 99
}
"""
    result = subprocess.run(
        [
            "bash",
            "-c",
            "set -euo pipefail\n"
            'calls="$1"; selector="$2"; failed="$3"; empty_primary_warning="$4"\n'
            'warning="$5"; error="$6"; namespace=dspace; release=dspace\n'
            + stub
            + helper
            + "wait_for_rollouts\n",
            "rollout-test",
            str(calls),
            selector,
            str(failed),
            str(empty_primary_warning),
            WARNING,
            ERROR,
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    return result, calls.read_text().splitlines()


@pytest.mark.parametrize("selector", [PRIMARY, FALLBACK])
def test_rollout_discovery_keeps_success_warning_on_stderr(tmp_path, selector):
    result, calls = run_discovery(tmp_path, selector)

    assert result.returncode == 0, result.stderr
    assert result.stderr == WARNING + "\n"
    assert WARNING not in result.stdout
    assert calls[-2:] == [
        "-n dspace rollout status deployment.apps/dspace --timeout=180s",
        "-n dspace rollout status statefulset.apps/dspace-worker --timeout=180s",
    ]
    assert len(calls) == (3 if selector == PRIMARY else 4)


@pytest.mark.parametrize("selector", [PRIMARY, FALLBACK])
def test_rollout_discovery_stops_on_query_error_even_with_partial_stdout(tmp_path, selector):
    result, calls = run_discovery(tmp_path, selector, failed=True)

    assert result.returncode != 0
    assert ERROR in result.stderr
    assert f"via label {selector}:" in result.stderr
    assert "rollout status" not in "\n".join(calls)
    assert len(calls) == (1 if selector == PRIMARY else 2)


def test_empty_primary_stdout_with_warning_still_uses_fallback(tmp_path):
    result, calls = run_discovery(tmp_path, FALLBACK, empty_primary_warning=True)

    assert result.returncode == 0, result.stderr
    assert result.stderr.count(WARNING) == 2
    assert len(calls) == 4
    assert f"-l {FALLBACK} -o name" in calls[1]
    assert all(WARNING not in call for call in calls)
