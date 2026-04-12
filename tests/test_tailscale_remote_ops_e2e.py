"""End-to-end coverage for tailscale just recipes using stubbed binaries."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.usefixtures("ensure_just_available")
def test_tailscale_recipes_e2e_with_stubs(tmp_path: Path) -> None:
    just_bin = shutil.which("just")
    assert just_bin, "just is required for this e2e test"

    fakebin = tmp_path / "bin"
    fakebin.mkdir()
    calls = tmp_path / "calls.log"

    def write_stub(name: str, body: str) -> None:
        path = fakebin / name
        path.write_text(body, encoding="utf-8")
        path.chmod(0o755)

    write_stub(
        "sudo",
        """#!/usr/bin/env bash
set -euo pipefail
exec "$@"
""",
    )
    write_stub(
        "curl",
        """#!/usr/bin/env bash
set -euo pipefail
if [ "$1" = "-fsSL" ] && [ "${2:-}" = "--output" ]; then
  cat > "$3" <<'SH'
#!/usr/bin/env bash
exit 0
SH
  exit 0
fi
exit 1
""",
    )
    write_stub(
        "sh",
        f"""#!/usr/bin/env bash
set -euo pipefail
printf 'install %s\n' "$*" >> "{calls}"
exit 0
""",
    )
    write_stub(
        "tailscale",
        f"""#!/usr/bin/env bash
set -euo pipefail
if [ "$1" = "status" ] && [ "${{2:-}}" = "--json" ]; then
  cat <<'JSON'
{{"BackendState":"Running","Self":{{"HostName":"sugarkube0","TailscaleIPs":["100.70.0.1"]}}}}
JSON
  exit 0
fi
printf 'tailscale %s\n' "$*" >> "{calls}"
""",
    )

    env = os.environ.copy()
    env["PATH"] = f"{fakebin}:{env.get('PATH', '')}"
    env["SUGARKUBE_TAILSCALE_AUTH_KEY"] = "tskey-test"
    env["SUGARKUBE_TAILSCALE_INSTALL_SHA256"] = (
        "fb99eae951f1adc14d1a4a9a186c21930db2786b3208c94c7d9af382bd1048e5"
    )

    install = subprocess.run(
        [just_bin, "tailscale-install"],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert install.returncode == 0, install.stderr

    up = subprocess.run(
        [just_bin, "tailscale-up"],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert up.returncode == 0, up.stderr

    status = subprocess.run(
        [just_bin, "tailscale-status"],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert status.returncode == 0, status.stderr
    assert "BackendState=Running" in status.stdout

    logged = calls.read_text(encoding="utf-8")
    assert "install -c" not in logged
    assert "install /" in logged
    assert "tailscale up --auth-key tskey-test" in logged
