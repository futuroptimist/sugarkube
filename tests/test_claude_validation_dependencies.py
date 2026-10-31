"""Keep Claude's credentialless promtool preparation aligned with CI."""

import os
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]


def workflow(name):
    return yaml.safe_load((ROOT / ".github" / "workflows" / name).read_text())


def promtool_step(steps):
    return next(step for step in steps if step.get("name") == "Install promtool")


def test_promtool_dependency_parity_and_stage():
    jobs = workflow("claude.yml")["jobs"]
    validation = jobs["claude-validation"]
    steps = validation["steps"]
    install = promtool_step(steps)
    for filename, job in [("tests.yml", "test"), ("ci.yml", "test")]:
        assert install["env"] == promtool_step(workflow(filename)["jobs"][job]["steps"])["env"]
    names = [step.get("name") for step in steps]
    assert names.index("Install promtool") < names.index("Checkout same-repository PR commit")
    assert names.index("Install promtool") < names.index("Test CI")
    assert validation["permissions"] == {"contents": "read"}
    assert not install.get("continue-on-error", False)
    assert not next(step for step in steps if step.get("name") == "Test CI").get(
        "continue-on-error", False
    )
    assert all(step.get("name") != "Install promtool" for step in jobs["claude"]["steps"])


@pytest.mark.parametrize("failure", ["", "curl", "sha256sum"])
def test_promtool_preparation_isolated_and_fail_closed(tmp_path, failure):
    """Execute the workflow shell with recording tools, without network or sudo."""
    step = promtool_step(workflow("claude.yml")["jobs"]["claude-validation"]["steps"])
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = tmp_path / "calls"
    workspace = tmp_path / "pr-workspace"
    workspace.mkdir()
    # A checkout-supplied archive symlink must never be touched.
    victim = tmp_path / "victim"
    victim.write_text("unchanged")
    archive = f"prometheus-{step['env']['PROMTOOL_VERSION']}.linux-amd64.tar.gz"
    (workspace / archive).symlink_to(victim)
    for tool in ["curl", "sha256sum", "tar", "sudo", "promtool"]:
        stub = bin_dir / tool
        stub.write_text(
            "#!/bin/bash\n"
            'tool="${0##*/}"\n'
            'printf "%s|%s|%s\\n" "$tool" "$PWD" "$*" >> "$CALL_LOG"\n'
            'if [[ "$tool" == sha256sum ]]; then cat >> "$CALL_LOG"; fi\n'
            'if [[ "$tool" == "$FAIL_TOOL" ]]; then exit 1; fi\n'
        )
        stub.chmod(0o755)
    result = subprocess.run(
        ["bash", "-c", step["run"]],
        cwd=workspace,
        env={
            **os.environ,
            **step["env"],
            "PATH": f"{bin_dir}:{os.environ['PATH']}",
            "CALL_LOG": str(log),
            "FAIL_TOOL": failure,
        },
        capture_output=True,
        text=True,
    )
    calls = [line.split("|") for line in log.read_text().splitlines() if "|" in line]
    expected = ["curl", "sha256sum", "tar", "sudo", "promtool"]
    if failure:
        expected = expected[: expected.index(failure) + 1]
    assert [call[0] for call in calls] == expected
    assert result.returncode == (1 if failure else 0), result.stderr
    download_dir = Path(calls[0][1])
    assert download_dir != workspace
    assert not download_dir.is_relative_to(workspace)
    assert not download_dir.exists(), "Temporary downloads must be cleaned up even on failure"
    assert victim.read_text() == "unchanged"
    assert calls[0][2] == (
        "-fsSLO https://github.com/prometheus/prometheus/releases/download/"
        f"v{step['env']['PROMTOOL_VERSION']}/{archive}"
    )
    if failure != "curl":
        assert f"{step['env']['PROMETHEUS_SHA256']}  {archive}" in log.read_text()
    if not failure:
        binary = f"prometheus-{step['env']['PROMTOOL_VERSION']}.linux-amd64/promtool"
        assert calls[2][2] == f"-xzf {archive} {binary}"
        assert calls[3][2] == f"install {binary} /usr/local/bin/promtool"
        assert calls[4][2] == "--version"
