"""Regression tests for the `just status` recipe."""

from __future__ import annotations

import os
import subprocess
import textwrap
from pathlib import Path

import pytest


JUSTFILE = Path(__file__).resolve().parent.parent / "justfile"


def _status_recipe_commands() -> list[str]:
    lines = JUSTFILE.read_text(encoding="utf-8").splitlines()
    capture = False
    body: list[str] = []
    for line in lines:
        if capture:
            if line.startswith("    "):
                body.append(line[4:])
                continue
            if line == "" or line.startswith("#"):
                break
            if not line.startswith(" "):
                break
        elif line.startswith("status:"):
            capture = True
    if not body:
        pytest.fail("status recipe missing from justfile")
    return body


def _write_status_script(tmp_path: Path) -> Path:
    commands = "\n".join(_status_recipe_commands())
    script = tmp_path / "status.sh"
    script.write_text(
        textwrap.dedent(
            f"""#!/usr/bin/env bash
            set -euo pipefail
            {commands}
            """
        ),
        encoding="utf-8",
    )
    script.chmod(0o755)
    return script


def test_status_recipe_handles_missing_k3s(tmp_path: Path) -> None:
    """The status recipe should exit cleanly with guidance when k3s is absent."""

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()

    sudo = bin_dir / "sudo"
    sudo.write_text(
        textwrap.dedent(
            """\
            #!/usr/bin/env bash
            echo "sudo should not run when k3s is missing" >&2
            exit 97
            """
        ),
        encoding="utf-8",
    )
    sudo.chmod(0o755)

    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}{os.pathsep}{env['PATH']}"

    script = _write_status_script(tmp_path)

    result = subprocess.run(
        [str(script)],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    stdout = result.stdout
    assert "k3s is not installed yet." in stdout
    assert "raspi_cluster_setup.md" in stdout
    assert "Follow the instructions" in stdout
    assert "sudo should not run" not in result.stderr


def test_status_recipe_invokes_k3s_when_available(tmp_path: Path) -> None:
    """Once k3s is on the PATH the recipe should call through to kubectl."""

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()

    sudo = bin_dir / "sudo"
    sudo.write_text(
        textwrap.dedent(
            """\
            #!/usr/bin/env bash
            exec "$@"
            """
        ),
        encoding="utf-8",
    )
    sudo.chmod(0o755)

    k3s_log = tmp_path / "k3s.log"
    k3s = bin_dir / "k3s"
    k3s.write_text(
        textwrap.dedent(
            """\
            #!/usr/bin/env python3
            import os
            import sys


            def main() -> None:
                log_path = os.environ["TEST_K3S_LOG"]
                with open(log_path, "w", encoding="utf-8") as handle:
                    handle.write(" ".join(sys.argv[1:]))
                print("fake k3s output")


            if __name__ == "__main__":
                main()
            """
        ),
        encoding="utf-8",
    )
    k3s.chmod(0o755)

    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}{os.pathsep}{env['PATH']}"
    env["TEST_K3S_LOG"] = str(k3s_log)

    script = _write_status_script(tmp_path)

    result = subprocess.run(
        [str(script)],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "fake k3s output" in result.stdout
    assert "raspi_cluster_setup.md" not in result.stdout
    assert k3s_log.read_text(encoding="utf-8") == "kubectl get nodes -o wide"
