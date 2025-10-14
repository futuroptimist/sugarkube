from __future__ import annotations

import os
import subprocess


def _run_script(env: dict[str, str]) -> dict[str, str]:
    result = subprocess.run(
        ["/bin/bash", "scripts/compute_pi_gen_cache_key.sh"],
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    outputs: dict[str, str] = {}
    for raw_line in result.stdout.strip().splitlines():
        if not raw_line:
            continue
        key, value = raw_line.split("=", 1)
        outputs[key] = value
    return outputs


def test_compute_cache_key_success(tmp_path):
    """Regression: when the pi-gen ref is available we should use it in the key."""

    remote = tmp_path / "pi-gen.git"
    subprocess.run(["git", "init", "--bare", str(remote)], check=True)

    work = tmp_path / "work"
    subprocess.run(["git", "init", str(work)], check=True)

    git_env = os.environ.copy()
    git_env.update(
        {
            "GIT_AUTHOR_NAME": "sugarkube",
            "GIT_AUTHOR_EMAIL": "ci@sugarkube.local",
            "GIT_COMMITTER_NAME": "sugarkube",
            "GIT_COMMITTER_EMAIL": "ci@sugarkube.local",
        }
    )

    subprocess.run(["git", "-C", str(work), "checkout", "-b", "bookworm"], env=git_env, check=True)
    (work / "README.md").write_text("hello\n")
    subprocess.run(["git", "-C", str(work), "add", "README.md"], env=git_env, check=True)
    subprocess.run(["git", "-C", str(work), "commit", "-m", "init"], env=git_env, check=True)
    subprocess.run(["git", "-C", str(work), "remote", "add", "origin", str(remote)], env=git_env, check=True)
    subprocess.run(["git", "-C", str(work), "push", "-u", "origin", "bookworm"], env=git_env, check=True)

    head = (
        subprocess.run(
            ["git", "-C", str(work), "rev-parse", "HEAD"],
            env=git_env,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    )

    env = os.environ.copy()
    env.update(
        {
            "RUNNER_OS": "Linux",
            "PI_GEN_BRANCH": "bookworm",
            "PI_GEN_REMOTE": str(remote),
            "PI_GEN_CACHE_MONTH": "2030-01",
        }
    )

    outputs = _run_script(env)

    assert outputs["fallback"] == "false"
    assert outputs["ref"] == head
    assert outputs["restore_prefix"] == "pigen-Linux-bookworm-"
    assert outputs["key"] == f"pigen-Linux-bookworm-{head}-2030-01"


def test_compute_cache_key_fallback(tmp_path):
    """E2E: tolerate git ls-remote failures by falling back to a static key."""

    missing_remote = tmp_path / "missing.git"
    env = os.environ.copy()
    env.update(
        {
            "RUNNER_OS": "Linux",
            "PI_GEN_BRANCH": "bookworm",
            "PI_GEN_REMOTE": str(missing_remote),
            "PI_GEN_CACHE_MONTH": "2030-01",
        }
    )

    outputs = _run_script(env)

    assert outputs["fallback"] == "true"
    assert outputs["ref"] == "fallback"
    assert outputs["restore_prefix"] == "pigen-Linux-bookworm-"
    assert outputs["key"] == "pigen-Linux-bookworm-fallback-2030-01"
