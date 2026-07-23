from __future__ import annotations

import os
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

JUSTFILE = Path(__file__).resolve().parent.parent / "justfile"


def _write_fake_python3(bin_dir: Path) -> Path:
    log_path = bin_dir / "cluster_identity_args.log"
    script = bin_dir / "python3"
    script.write_text(
        textwrap.dedent(f"""#!/usr/bin/python3
import os
import sys

args = sys.argv[1:]
is_cluster_identity_assert = (
    len(args) >= 2
    and args[0].endswith("scripts/cluster_identity.py")
    and args[1] == "assert"
)
if is_cluster_identity_assert:
    env_value = args[args.index("--env") + 1] if "--env" in args else ""
    with open({str(log_path)!r}, "a", encoding="utf-8") as handle:
        handle.write(env_value + "\\n")
    detected = os.environ.get("SUGARKUBE_STUB_NODE_ENV", env_value)
    if env_value not in {{"dev", "staging", "prod"}}:
        print(f"unsupported environment: {{env_value}}", file=sys.stderr)
        raise SystemExit(2)
    if detected != env_value:
        message = (
            f"refusing to continue: requested env={{env_value}} "
            f"but connected cluster reports env={{detected}}"
        )
        print(message, file=sys.stderr)
        raise SystemExit(1)
    print(detected)
    raise SystemExit(0)

os.execv("/usr/bin/python3", ["/usr/bin/python3", *sys.argv[1:]])
"""),
        encoding="utf-8",
    )
    script.chmod(0o755)
    return log_path


def _run_assert_cluster_env(
    tmp_path: Path, requested: str, detected: str | None = None
) -> subprocess.CompletedProcess[str]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    log_path = _write_fake_python3(bin_dir)
    kubeconfig = tmp_path / "config"
    kubeconfig.write_text("apiVersion: v1\n", encoding="utf-8")
    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}{os.pathsep}{env['PATH']}"
    if detected is not None:
        env["SUGARKUBE_STUB_NODE_ENV"] = detected
    env["SUGARKUBE_ARG_LOG"] = str(log_path)
    return subprocess.run(
        [
            "just",
            "--justfile",
            str(JUSTFILE),
            "assert-cluster-env",
            requested,
            str(kubeconfig),
        ],
        cwd=JUSTFILE.parent,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


@pytest.mark.skipif(shutil.which("just") is None, reason="just is required for this test")
@pytest.mark.parametrize(
    ("positional", "prefixed", "normalized"),
    [("prod", "env=prod", "prod"), ("staging", "env=staging", "staging")],
)
def test_assert_cluster_env_recipe_normalizes_positional_and_env_prefix(
    tmp_path: Path, positional: str, prefixed: str, normalized: str
) -> None:
    positional_result = _run_assert_cluster_env(tmp_path, positional, normalized)
    prefixed_result = _run_assert_cluster_env(tmp_path, prefixed, normalized)

    assert positional_result.returncode == 0, positional_result.stderr
    assert prefixed_result.returncode == 0, prefixed_result.stderr
    assert positional_result.stdout == prefixed_result.stdout == f"{normalized}\n"
    log_path = tmp_path / "bin" / "cluster_identity_args.log"
    assert log_path.read_text(encoding="utf-8").splitlines() == [normalized, normalized]


@pytest.mark.skipif(shutil.which("just") is None, reason="just is required for this test")
def test_assert_cluster_env_recipe_legacy_int_normalizes_to_staging(tmp_path: Path) -> None:
    result = _run_assert_cluster_env(tmp_path, "env=int", "staging")

    assert result.returncode == 0, result.stderr
    assert 'WARNING: env name "int" is deprecated; using env=staging.' in result.stderr
    assert (tmp_path / "bin" / "cluster_identity_args.log").read_text(
        encoding="utf-8"
    ) == "staging\n"


@pytest.mark.skipif(shutil.which("just") is None, reason="just is required for this test")
def test_assert_cluster_env_recipe_mismatch_still_fails_before_mutation(tmp_path: Path) -> None:
    sentinel = tmp_path / "sentinel"
    sentinel.write_text("unchanged\n", encoding="utf-8")

    result = _run_assert_cluster_env(tmp_path, "env=prod", "staging")

    assert result.returncode != 0
    assert "requested env=prod" in result.stderr
    assert "env=staging" in result.stderr
    assert sentinel.read_text(encoding="utf-8") == "unchanged\n"


@pytest.mark.skipif(shutil.which("just") is None, reason="just is required for this test")
def test_assert_cluster_env_recipe_invalid_values_remain_rejected(tmp_path: Path) -> None:
    result = _run_assert_cluster_env(tmp_path, "env=qa", "qa")

    assert result.returncode != 0
    assert "unsupported environment: qa" in result.stderr
